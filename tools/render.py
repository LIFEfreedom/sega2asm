#!/usr/bin/env python3
"""Прогоняет звуковой драйвер на эмуляторе и пишет WAV.

    make render                 50 эффектов в out/<имя>/sound/render/
    make render RENDERARGS=--music   плюс 45 песен по 30 секунд
    make render RENDERARGS=--reference        эталон для ремейка (dyna #231)
    make render RENDERARGS="--reference --check"   прогнать ещё раз и сверить

Разбор данных, сделанный раньше, описывал ЧТО драйвер сыграет. Здесь он
играет: код Z80 исполняется как есть, а звук берётся из того, что этот
код пишет в YM2612 и PSG. Собирает и гоняет `build/render.exe`
(`tools/render/render.c`), которому нужны два чужих ядра — см. `make
deps`.

Как заводится звук — так же, как в игре: в почтовый ящик Z80 кладутся
банки (трапы `$FF2D`, `$FF35`) и номер команды (`$1C0A`, куда его
переносит VBlank), дальше драйвер разбирается сам.

Уровень выставляется в два прохода: сперва всё считается с единичным
усилением, потом берётся один общий множитель, чтобы самый громкий
номер не доходил до предела. Множитель ОДИН на всю выгрузку — иначе
тихие звуки стали бы громкими наравне с музыкой.
"""
import io
import json
import os
import subprocess
import sys
import wave

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

import dumptext  # noqa: E402
import pcm  # noqa: E402
import sfx as sfxmod  # noqa: E402
import z80dis  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT as out_path, build_dir, toolbin, rom_bytes, rom_path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

rom = rom_bytes()

EXE = toolbin("render.exe")          # общий: от ROM не зависит
IMG = os.path.join(build_dir(), "z80.img")   # свой: снят с этой ROM
OUT = out_path("sound", "render")
SFX_TABLE = 0x00201C
MUSIC_TABLE = 0x001F36
SONG_SECONDS = 30
HEADROOM = 30000          # пик самого громкого номера после усиления


def banks_for_sfx():
    """Команда -> номер банка главного цикла, каким его застаёт вызов.

    У `$FF38` банк лежит в самой записи `table_sfx`. У `$FF2F` его нет:
    остаётся выбранный раньше, и он ищется назад по ближайшему `$FF36`
    (всегда 5) или `$FF2D` с константой. Где не нашлось — банк 5, он же
    стоит при старте.
    """
    out = {}
    for i in range((0x207E - SFX_TABLE) // 2):
        b, c = rom[SFX_TABLE + 2 * i], rom[SFX_TABLE + 2 * i + 1]
        if b <= 0x7F:
            out[c] = b
    for i in range(0, len(rom) - 6, 2):
        if (rom[i], rom[i + 1], rom[i + 4], rom[i + 5]) != (0x3F, 0x3C, 0xFF, 0x2F):
            continue
        cmd = rom[i + 2] << 8 | rom[i + 3]
        if cmd in out:
            continue
        for j in range(i + 4, max(0, i - 0x600), -2):
            if rom[j] == 0xFF and rom[j + 1] == 0x36:
                out[cmd] = 5
                break
            if (rom[j], rom[j + 1], rom[j - 4], rom[j - 3]) == (0xFF, 0x2D, 0x3F, 0x3C):
                out[cmd] = rom[j - 1]
                break
    return out


def song_titles():
    """(банк, песня) -> название с экрана музыки."""
    NT = 0x4BF5E
    w16 = lambda a: (rom[a] << 8) | rom[a + 1]
    out = {}
    for i in range(w16(NT) // 2):
        a = NT + w16(NT + 2 * i)
        e = a + 4
        while rom[e]:
            e += 1
        mid = w16(0x4B314 + 2 * rom[a])
        b, c = rom[MUSIC_TABLE + 2 * mid], rom[MUSIC_TABLE + 2 * mid + 1]
        if b <= 0x7F:
            out[(b, c)] = dumptext.dec(rom[a + 4:e])
    return out


def run(job, gain):
    """Один запуск эмулятора; возвращает пик отсчёта и частоту DAC.

    Частоту меряет сам эмулятор — по промежуткам между записями в
    регистр `$2A`. Расчётная формула `3.58 МГц / (13*шаг + 117)` её
    завышает: кадровое прерывание ворует такты у цикла воспроизведения,
    и настоящая частота ниже на несколько процентов.
    """
    args = [EXE, rom_path(), IMG, job["path"],
            "%02X" % job["cmd"], str(job["frames"]), str(job["main"]),
            str(job["music"]), "1" if job["stop"] else "0", str(gain)]
    r = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        raise SystemExit("render.exe: %s" % (r.stderr or r.stdout).strip())
    rate = start = None
    for line in (r.stderr or "").splitlines():
        if line.startswith("DAC:"):
            part = line.split(",")
            rate = int(float(part[1].split()[0]))
            start = int(part[2].split()[-1])
    return int(r.stdout.rsplit(" ", 1)[1]), rate, start


def envelope(path, rate, skip=0, step=0.01):
    """Средний квадрат по окнам в 10 мс — форма звука без учёта фазы.

    Окно короткое нарочно: у самых коротких сэмплов всего десятые
    доли секунды, и на полусекундных окнах сравнивать было бы
    нечего."""
    with wave.open(path) as w:
        n, sr, sw, ch = (w.getnframes(), w.getframerate(),
                         w.getsampwidth(), w.getnchannels())
        raw = w.readframes(n)
    if rate:
        sr = rate
    out = []
    k = int(sr * step) * ch * sw
    if k <= 0:
        return out
    off = skip * ch * sw
    for i in range(off, len(raw) - k + 1, k):
        acc = 0
        for j in range(i, i + k, sw * ch):
            if sw == 1:
                v = raw[j] - 128
            else:
                v = raw[j] | (raw[j + 1] << 8)
                if v >= 0x8000:
                    v -= 0x10000
            acc += v * v
        out.append((acc / (k // (sw * ch))) ** 0.5)
    return out


def pearson(a, b):
    n = min(len(a), len(b))
    if n < 6:
        return None
    a, b = a[:n], b[:n]
    ma, mb = sum(a) / n, sum(b) / n
    sa = sum((x - ma) ** 2 for x in a) ** 0.5
    sb = sum((x - mb) ** 2 for x in b) ** 0.5
    if sa == 0 or sb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb)


def sample_check(job, img):
    """Совпадает ли форма с сэмплом, выгруженным разбором данных.

    Две дороги независимы: `pcm.py` раскодировал дельты по описанию
    формата, эмулятор проиграл сэмпл сам. Сравнивать отсчёт с отсчётом
    бессмысленно — накапливается расхождение фазы, — а огибающая
    показывает то же самое без этой беды.
    """
    if not job.get("rate"):
        return None
    n = pcm.dac_sample(img, job["cmd"])
    if n is None:
        return None
    ref = out_path("sound",
                       "bank%d_sample%d.wav" % (job["main"], n))
    if not os.path.exists(ref):
        return None
    with wave.open(ref) as w:
        secs = w.getnframes() / float(job["rate"])
    # Окно подбирается под длину: около сотни окон на сэмпл. Слишком
    # мелкое ловит расхождение фазы на длинных, слишком крупное не
    # оставляет точек на коротких.
    step = min(0.05, max(0.005, secs / 120.0))
    return pearson(envelope(job["path"], None, job.get("start") or 0, step),
                   envelope(ref, job["rate"], 0, step))


# ─────────────────────────── эталон для ремейка ──────────────────────────
# Ремейк исполняет тот же образ драйвера на своей эмуляции (dyna #232) и
# обязан совпасть с render.c кадр в кадр. Эталон — CRC по кадрам (`--log`)
# для каждого звука в двух запусках, как у Maui (`z80render.py`).
FPS = 59.9227                # кадр драйвера: 59 736 тактов Z80
REF_SECONDS = 45             # песни; эффекты — до тишины
SFX_MAX_FRAMES = 600


def set_bank(n):
    """Пара байт ящика для банка n: x = n*8 + $1C0, (x >> 4, x << 4)."""
    x = n * 8 + 0x1C0
    return (x >> 4) & 0xFF, (x << 4) & 0xFF


def banks_script(main, music):
    a, b = set_bank(main)
    c, d = set_bank(music)
    return "1C04=%02X,1C05=%02X,1C06=%02X,1C07=%02X" % (a, b, c, d)


def reference_jobs():
    """39 песен (пары банк/команда из table_music) и 50 эффектов.

    Песня играет на своём банке прерывания при банке главного цикла 5 (как
    после старта), эффект — на банке, который застаёт его в игре по
    переписи мест (`soundsites.bank_by_command`), а где перепись банка не
    знает — по `banks_for_sfx`; банк прерывания 2."""
    import soundsites
    songs = sorted({(rom[MUSIC_TABLE + 2 * i], rom[MUSIC_TABLE + 2 * i + 1])
                    for i in range((SFX_TABLE - MUSIC_TABLE) // 2)
                    if rom[MUSIC_TABLE + 2 * i] <= 0x7F})
    banks = banks_for_sfx()
    banks.update(soundsites.bank_by_command(rom))
    if soundsites.ERRORS:
        raise SystemExit("перепись звука с ошибками — сначала make soundsites")
    jobs = [dict(kind="song", cmd=c, main=5, music=b,
                 frames=int(REF_SECONDS * FPS), stop=False) for b, c in songs]
    jobs += [dict(kind="sfx", cmd=c, main=banks.get(c, 5), music=2,
                  frames=SFX_MAX_FRAMES, stop=True) for c in range(0x90, 0xC2)]
    return jobs


# Режимы: «номер» — банки на кадре 2, команда на кадре 3 (как позиционный
# запуск render.c); «стоп + номер» — после банков трап $FF37: $1F в $1C14 и
# команда $E1, ожидание нуля в $1C14, затем номер (так начинается миссия,
# $003B0C: стоп, банк, трек).
def mail_for(job, mode):
    banks = banks_script(job["main"], job["music"])
    if mode == "start":
        return "%s/1C0A=%02X" % (banks, job["cmd"])
    return "%s/1C14=1F,1C0A=E1/?1C14/1C0A=%02X" % (banks, job["cmd"])


def _commit(path):
    r = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def reference_run(img, job, mode, log):
    args = [EXE, rom_path(), img, os.path.join(build_dir(), "_reference.wav"),
            "00", str(job["frames"]), "0", "0", "1" if job["stop"] else "0",
            "256", "--mail", mail_for(job, mode), "--log", log]
    r = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        raise SystemExit("render.exe: %s" % (r.stderr or r.stdout).strip())
    with open(log, "rb") as f:
        return f.read()


def reference(check):
    out = out_path("export", "sound")
    img = os.path.join(out, "z80.bin")
    if not os.path.exists(img):
        raise SystemExit("нет %s — сначала make soundsites"
                         % os.path.relpath(img, HERE))
    if bytes(z80dis.load()) != open(img, "rb").read():
        raise SystemExit("z80.bin расходится с z80dis.load()")
    os.makedirs(build_dir(), exist_ok=True)
    log = os.path.join(build_dir(), "_reference.log")
    blob, runs = bytearray(), []
    for job in reference_jobs():
        for mode in ("start", "stop"):
            data = reference_run(img, job, mode, log)
            runs.append({"kind": job["kind"], "command": job["cmd"],
                         "bank_main": job["main"], "bank_music": job["music"],
                         "mode": mode, "mail": mail_for(job, mode),
                         "until_silence": job["stop"],
                         "offset": len(blob), "frames": len(data) // 8})
            blob += data
        print("  %-4s $%02X: кадров %d / %d" % (job["kind"], job["cmd"],
                                               runs[-2]["frames"], runs[-1]["frames"]))
    for p in (log, os.path.join(build_dir(), "_reference.wav")):
        if os.path.exists(p):
            os.remove(p)
    ref_bin = os.path.join(out, "reference.bin")
    if check:
        old = open(ref_bin, "rb").read() if os.path.exists(ref_bin) else b""
        if old != bytes(blob):
            print("РАСХОЖДЕНИЕ: второй прогон дал другой reference.bin")
            return 1
        print("повтор совпал: %d прогонов, %d байт" % (len(runs), len(blob)))
        return 0
    with open(ref_bin, "wb") as f:
        f.write(blob)
    doc = {
        "meta": {
            "game": "Dyna Brothers 2",
            "generator": "tools/render.py --reference "
                         "(tools/render/render.c --mail --log)",
            "spec": "docs/game-sound.md",
            "cores": {
                "clownz80": _commit(os.path.join(HERE, "third_party", "clownz80")),
                "nuked_opn2": _commit(os.path.join(HERE, "third_party", "Nuked-OPN2")),
                "nuked_mode": "ym3438_mode_ym2612",
            },
            "clock": {"master": 53693175, "z80": 15, "opn2_step": 42,
                      "psg_tick": 240, "sample": 1008,
                      "frame_z80_cycles": 3420 * 262 // 15},
            "image": {"file": "sound/z80.bin", "ram": 0x2000},
            "banks": {"file": "sound/banks.bin", "rom": 0x1C0000,
                      "size": 0x8000},
            "run": u"ОЗУ Z80: образ, остальное нули; регистры нули; сброс; "
                   u"кадр: шаги сценария ящика (mail, с кадра 2), "
                   u"прерывание, команды Z80 до frame_z80_cycles тактов, "
                   u"после каждой — её такты в YM и PSG; эффекты — до "
                   u"тишины (слоты $1E20 + i*$30 свободны, $1C3C = 0, "
                   u"затем уровень покоя 3 кадра, не дольше 60), песни — "
                   u"%d кадров" % int(REF_SECONDS * FPS),
            "mail": u"шаги через запятую в начале кадра: АДР=ЗН — байт в "
                    u"ОЗУ Z80, / — конец кадра, ?АДР — ждать кадр за "
                    u"кадром, пока байт не станет нулём (hex)",
            "frame": u"reference.bin: на кадр 8 байт — CRC-32 записей "
                     u"(вид 0-3 порт YM a&3, 4 PSG $7F11, 5 банк $6000; "
                     u"значение; такт Z80 команды от начала кадра, 16 бит "
                     u"LE) и CRC-32 смеси (отсчёт: левый, правый int32 LE, "
                     u"FM за 24 шага + средний PSG, до фильтра), оба LE",
        },
        "runs": runs,
    }
    with io.open(os.path.join(out, "reference.json"), "w", encoding="utf-8",
                 newline="\n") as f:
        f.write(json.dumps(doc, ensure_ascii=False, indent=1))
        f.write(u"\n")
    print("эталон: %d прогонов, %d байт" % (len(runs), len(blob)))
    return 0


def main():
    if "--reference" in sys.argv:
        if not os.path.exists(EXE):
            raise SystemExit("нет %s — соберите: make deps && make render"
                             % os.path.relpath(EXE, HERE))
        return reference("--check" in sys.argv)
    want_music = "--music" in sys.argv
    if not os.path.exists(EXE):
        raise SystemExit("нет %s — соберите: make deps && make render"
                         % os.path.relpath(EXE, HERE))
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.dirname(IMG), exist_ok=True)
    open(IMG, "wb").write(bytes(z80dis.load()))

    img = z80dis.load()
    names = sfxmod.names()
    banks = banks_for_sfx()
    jobs = []
    for cmd in range(0x90, 0xC2):
        jobs.append(dict(kind="sfx", cmd=cmd, main=banks.get(cmd, 5), music=2,
                         frames=600, stop=True,
                         name=", ".join(names.get(cmd, []))
                              or sfxmod.NOTE.get(cmd, ""),
                         path=os.path.join(OUT, "sfx_%02X.wav" % cmd)))
    if want_music:
        titles = song_titles()
        for bank in (2, 3, 4):
            for n in range(15):
                cmd = 0x81 + n
                jobs.append(dict(kind="song", cmd=cmd, main=5, music=bank,
                                 frames=SONG_SECONDS * 60, stop=False,
                                 name=titles.get((bank, cmd), ""),
                                 path=os.path.join(
                                     OUT, "bank%d_song%02X.wav" % (bank, cmd))))

    print("проход 1 из 2: замер уровня, %d номеров" % len(jobs))
    peak = {}
    for j in jobs:
        j["peak"], j["rate"], j["start"] = run(j, 256)
        peak[j["kind"]] = max(peak.get(j["kind"], 1), j["peak"])
    gain = dict((k, max(1, min(4096, 256 * HEADROOM // v)))
                for k, v in peak.items())
    for k in sorted(gain):
        print("%-4s: пик %5d -> усиление %.2f" % (k, peak[k], gain[k] / 256.0))

    print("проход 2 из 2: запись")
    rows = []
    for j in jobs:
        j["peak"], j["rate"], j["start"] = run(j, gain[j["kind"]])
        with wave.open(j["path"]) as w:
            j["secs"] = w.getnframes() / float(w.getframerate())
        j["match"] = sample_check(j, img)
        rows.append(j)

    doc = os.path.join(OUT, "index.md")
    with open(doc, "w", encoding="utf-8", newline="\n") as f:
        f.write("# Звук, снятый с эмулятора\n\n")
        f.write("СГЕНЕРИРОВАНО `tools/render.py` (`make render`).\n\n")
        f.write("Драйвер исполняется как есть на эмуляторе Z80, звук — то, "
                "что\nэтот код пишет в YM2612 и PSG. Частота 53 267 Гц — "
                "родная частота\nмикросхемы, пересэмплирования нет.\n\n")
        f.write("Усиление одно на весь свой род, иначе тихие номера "
                "сравнялись бы\nс громкими: %s.\n\n"
                % ", ".join("%s %.2f" % (k, v / 256.0)
                            for k, v in sorted(gain.items())))
        f.write("Столбец «DAC» — ИЗМЕРЕННАЯ частота воспроизведения "
                "сэмпла, по\nпромежуткам между записями в регистр `$2A`. Расчётная\n"
                "формула её завышает: кадровое прерывание ворует такты у цикла\n"
                "воспроизведения.\n\n")
        f.write("Столбец «сверка» — совпадение огибающей с тем же сэмплом,\n"
                "выгруженным `make pcm` из данных. Единица значит, что разбор\n"
                "формата и живой прогон драйвера сошлись, хотя шли разными\n"
                "путями.\n\n")
        f.write("Где значение заметно ниже — это сэмплы банка 6 без огибающей\n"
                "вовсе: разбор отметил их ещё в `make pcm` — уровень гуляет во\n"
                "весь размах, формы нет. Сравнивать там нечего, и низкое число\n"
                "говорит о самом сэмпле, а не о расхождении.\n\n")
        f.write("| номер | название | банк | секунд | DAC | сверка | пик | файл |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        for j in rows:
            f.write("| `$%02X` | %s | %d | %.2f | %s | %s | %d | `%s` |\n"
                    % (j["cmd"], j["name"] or "—",
                       j["main"] if j["kind"] == "sfx" else j["music"],
                       j["secs"],
                       "%d Гц" % j["rate"] if j.get("rate") else "—",
                       "%.3f" % j["match"] if j.get("match") else "—",
                       j["peak"], os.path.basename(j["path"])))
    print("записано %d файлов и index.md в %s"
          % (len(rows), os.path.relpath(OUT, HERE)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
