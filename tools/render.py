#!/usr/bin/env python3
"""Прогоняет звуковой драйвер на эмуляторе и пишет WAV.

    make render                 50 эффектов в out/<имя>/sound/render/
    make render RENDERARGS=--music   плюс 45 песен по 30 секунд

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
from paths import OUT as out_path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

rom = open(os.path.join(HERE, "game.gen"), "rb").read()

EXE = os.path.join(HERE, "build", "render.exe")
IMG = os.path.join(HERE, "build", "z80.img")
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
    args = [EXE, os.path.join(HERE, "game.gen"), IMG, job["path"],
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


def main():
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
