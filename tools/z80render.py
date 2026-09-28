#!/usr/bin/env python3
"""Прогоняет звуковой драйвер Maui Mallard на эмуляторе и пишет WAV.

    make z80render                  все мелодии (многодорожечные звуки)
    make z80render RENDERARGS=--all      все 169 звуков
    make z80render RENDERARGS="12 34"    только эти номера
    make z80render RENDERARGS="--seconds 90 --all"
    make z80render RENDERARGS="--seconds 120 --gain 5900 7 9 22"
    make z80render RENDERARGS=--reference   эталон для ремейка (export/sound)

Разбор данных сказал, ЧТО драйвер сыграет ([z80.md]). Здесь он играет:
код Z80 исполняется как есть, звук берётся из того, что этот код пишет в
YM2612 и PSG, а сэмплы драйвер сам достаёт из картриджа через банковый
регистр. Считает `build/tools/render.exe` (`tools/render/render.c`),
которому нужны два чужих ядра — `make deps`.

Ничего не зашито: адрес образа драйвера и четыре таблицы, которые 68000
отдаёт ему при старте, вычитываются из самого кода 68000 — из загрузчика
`$2F8C6C` и из четвёрки `pea` перед вызовом `$2F8D7C`.

Уровень выставляется в два прохода: сперва всё считается с единичным
усилением, потом берётся ОДИН общий множитель на всю выгрузку, чтобы
самая громкая мелодия не доходила до предела, а тихие не стали громкими.

`--reference` пишет эталон, по которому ремейк (mauimallard #33) сверяет
свою эмуляцию: все 169 номеров в двух режимах — `$FF $10 n`, как здесь, и
«остановить всё» `$296D16` (десять `$FF $1B i 0` и `$FF $16`) перед ним; на
каждый кадр от включения два CRC-32 из `render.c --log` (записи драйвера в
YM2612, PSG и банк; смесь до фильтра). Длина — как у выгрузки: однодорожечные
до тишины, остальные `--seconds`. Файлы — `export/sound/reference.bin` и
`reference.json` (где чей кусок и как он снят).
"""
import io
import json
import os
import re
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ccbuild import build as cc_build
from paths import OUT as out_path
from paths import build_dir, rom_bytes, rom_path, toolbin
import z80seq

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROM = rom_bytes()

RING = 0x1B40          # кольцо команд в ОЗУ Z80
RING_IX = 0x0036       # индекс записи, его ведёт 68000
SLOTS = (0x1B80, 16, 0x20, 6, 0x21)   # где смотреть, занят ли слот
FPS = 59.9227          # кадр NTSC, как в render.c


def find_driver_image():
    """Границы образа драйвера — из загрузчика: `lea A,a0; lea B,a1`."""
    for i in range(0x280000, len(ROM) - 16, 2):
        if (ROM[i] == 0x41 and ROM[i + 1] == 0xF9
                and ROM[i + 6] == 0x43 and ROM[i + 7] == 0xF9
                and ROM[i + 12] == 0x20 and ROM[i + 13] == 0x09):
            a = struct.unpack_from(">I", ROM, i + 2)[0]
            b = struct.unpack_from(">I", ROM, i + 8)[0]
            if 0 < a < b < len(ROM) and b - a < 0x4000:
                return a, b
    raise SystemExit("не нашёл загрузчик драйвера в коде 68000")


def find_tables():
    """Четыре адреса из `pea` перед `jsr $2F8D7C`.

    В коде они лежат в обратном порядке: первым кладут последний аргумент.
    Драйвер получает их в том порядке, в каком их снимает `$2F8D7C` — от
    `$8(a6)` к `$14(a6)`, — поэтому список переворачивается.
    """
    pat = bytes.fromhex("4EB9002F8D7C")
    at = ROM.find(pat, 0x280000)
    if at < 0:
        raise SystemExit("не нашёл вызов инициализации звука")
    out = []
    for k in range(4):
        o = at - 24 + k * 6
        if ROM[o] != 0x48 or ROM[o + 1] != 0x79:
            raise SystemExit("перед вызовом ожидались четыре pea")
        out.append(struct.unpack_from(">I", ROM, o + 2)[0])
    return out[::-1]


def image_path():
    """Образ ОЗУ Z80: кусок картриджа как есть, дополненный нулями."""
    lo, hi = find_driver_image()
    d = build_dir()
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "z80.img")
    img = bytearray(0x2000)
    img[0:hi - lo] = ROM[lo:hi]
    with open(path, "wb") as f:
        f.write(img)
    return path, lo, hi


def init_hex(tables):
    """Что 68000 кладёт в ящик при старте: `$FF`, команда $0B и четыре
    адреса по три байта, младшим вперёд."""
    b = bytearray([0xFF, 0x0B])
    for t in tables:
        b += bytes([t & 0xFF, (t >> 8) & 0xFF, (t >> 16) & 0xFF])
    return b.hex().upper()


# «Остановить всё» $296D16: $296CFA кладёт `$FF $1B i 0` для i = 0-9, потом
# $2F8E30 — `$FF $16` (sound.md; числа — sounds.json driver.stop_all).
STOP_ALL = "".join("FF1B%02X00" % i for i in range(10)) + "FF16"


def render(exe, img, out_wav, sound, frames, gain, init, stop, play=None,
           log=None):
    args = [exe, rom_path(), img, out_wav, "0", str(frames), "-1", "-1",
            "1" if stop else "0", str(gain),
            "--ring", "%X,%X" % (RING, RING_IX),
            "--init", init,
            "--play", play or "FF10%02X" % sound,
            "--busy", "%X,%X,%X,%X,%X" % SLOTS]
    if log:
        args += ["--log", log]
    r = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        raise SystemExit("render.exe: %s" % (r.stderr or r.stdout).strip())
    m = re.search(r"пик (\d+)", r.stdout)
    return int(m.group(1)) if m else 0


def _commit(path):
    r = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def reference(exe, img, lo, hi, tables, init, seconds):
    """Эталон для ремейка: 169 номеров x 2 режима, CRC по кадрам."""
    frames = int(seconds * FPS)
    out = out_path("export", "sound")
    os.makedirs(out, exist_ok=True)
    tmp_wav = os.path.join(build_dir(), "_reference.wav")
    tmp_log = os.path.join(build_dir(), "_reference.log")
    blob = bytearray()
    runs = []
    for n in range(z80seq.sound_count()):
        cnt = z80seq.tracks(n)[1]
        for mode, play in (("start", "FF10%02X" % n),
                           ("stop_all", STOP_ALL + "FF10%02X" % n)):
            render(exe, img, tmp_wav, n, frames, 256, init, cnt == 1,
                   play=play, log=tmp_log)
            with open(tmp_log, "rb") as f:
                data = f.read()
            runs.append({"sound": n, "mode": mode, "tracks": cnt,
                         "play": play, "offset": len(blob),
                         "frames": len(data) // 8})
            blob += data
        print("  %3d: дорожек %2d, кадров %d" % (n, cnt, runs[-1]["frames"]))
    for p in (tmp_wav, tmp_log):
        if os.path.exists(p):
            os.remove(p)
    with open(os.path.join(out, "reference.bin"), "wb") as f:
        f.write(blob)
    doc = {
        "meta": {
            "generator": "tools/z80render.py --reference "
                         "(tools/render/render.c --log)",
            "spec": "docs/mauimallard/z80.md",
            "cores": {
                "clownz80": _commit(os.path.join(HERE, "third_party",
                                                 "clownz80")),
                "nuked_opn2": _commit(os.path.join(HERE, "third_party",
                                                   "Nuked-OPN2")),
                "nuked_mode": "ym3438_mode_ym2612",
            },
            "clock": {"master": 53693175, "z80": 15, "opn2_step": 42,
                      "psg_tick": 240, "sample": 1008,
                      "frame_z80_cycles": 3420 * 262 // 15},
            "image": {"base": "$%06X" % lo, "end": "$%06X" % hi,
                      "ram": 0x2000},
            "tables": ["$%06X" % t for t in tables],
            "ring": {"base": RING, "index": RING_IX, "mask": 0x3F},
            "run": u"ОЗУ Z80: образ, остальное нули; сброс; кадр: команды "
                   u"ящика в кольцо (init на кадре 2, play на кадре 4), "
                   u"прерывание (защёлка, снимается приёмом), команды Z80 "
                   u"до frame_z80_cycles тактов (перебор не переносится), "
                   u"после каждой — её такты в YM и PSG; однодорожечные — "
                   u"до тишины, остальные — %d с" % seconds,
            "frame": u"reference.bin: на кадр 8 байт — CRC-32 записей "
                     u"(вид 0-3 порт YM a&3, 4 PSG $7F11, 5 банк $6000; "
                     u"значение; такт Z80 команды от начала кадра, 16 бит "
                     u"LE) и CRC-32 смеси (отсчёт: левый, правый int32 LE, "
                     u"FM за 24 шага + средний PSG, до фильтра), оба LE",
        },
        "init": init,
        "runs": runs,
    }
    with io.open(os.path.join(out, "reference.json"), "w", encoding="utf-8",
                 newline="\n") as f:
        f.write(json.dumps(doc, ensure_ascii=False, indent=1))
        f.write(u"\n")
    print("эталон: %d прогонов, %d байт" % (len(runs), len(blob)))


def main():
    args = sys.argv[1:]
    seconds = 45
    if "--seconds" in args:
        i = args.index("--seconds")
        seconds = int(args[i + 1])
        del args[i:i + 2]
    fixed_gain = 0
    if "--gain" in args:
        i = args.index("--gain")
        fixed_gain = int(args[i + 1])
        del args[i:i + 2]
    every = "--all" in args
    ref = "--reference" in args
    args = [a for a in args if not a.startswith("--")]

    if args:
        want = [int(a, 0) for a in args]
    else:
        want = [n for n in range(z80seq.sound_count())
                if every or z80seq.tracks(n)[1] > 1]

    exe = cc_build(toolbin("render.exe"),
                   [os.path.join(HERE, "tools", "render", "render.c"),
                    os.path.join(HERE, "third_party", "clownz80", "unity.c"),
                    os.path.join(HERE, "third_party", "Nuked-OPN2", "ym3438.c")])
    img, lo, hi = image_path()
    tables = find_tables()
    init = init_hex(tables)
    print("драйвер $%06X-$%06X, таблицы %s"
          % (lo, hi, " ".join("$%06X" % t for t in tables)))
    if ref:
        reference(exe, img, lo, hi, tables, init, seconds)
        return 0

    frames = int(seconds * FPS)
    groups = {"music": [n for n in want if z80seq.tracks(n)[1] > 1],
              "sfx": [n for n in want if z80seq.tracks(n)[1] == 1]}
    # В таблице есть записи с нулём дорожек — играть в них нечего. Молчать
    # об этом нельзя: иначе в выгрузке просто не окажется пары номеров, и
    # поди пойми, инструмент их потерял или их там нет.
    empty = [n for n in want if z80seq.tracks(n)[1] == 0]
    print("к выгрузке %d звуков: мелодий %d, эффектов %d; предел %d с (%d кадров)"
          % (len(want) - len(empty), len(groups["music"]), len(groups["sfx"]),
             seconds, frames))
    if empty:
        print("пустых записей в таблице (дорожек ноль): %s"
              % " ".join(str(n) for n in empty))

    for kind in ("music", "sfx"):
        nums = groups[kind]
        if not nums:
            continue
        out = out_path("sound", kind)
        os.makedirs(out, exist_ok=True)
        print("\n── %s: %d звуков ──" % (out, len(nums)))

        if fixed_gain:
            gain = fixed_gain
            print("множитель %d/256 (задан)" % gain)
        else:
            # Проход первый: узнать, кто в ГРУППЕ громче всех. Считать общий
            # множитель на музыку и эффекты сразу нельзя: громкий эффект
            # утянул бы за собой все мелодии.
            tmp = os.path.join(out, "_probe.wav")
            peaks = {}
            for n in nums:
                cnt = z80seq.tracks(n)[1]
                peaks[n] = render(exe, img, tmp, n, frames, 256, init, cnt == 1)
            if os.path.exists(tmp):
                os.remove(tmp)

            top = max(peaks.values()) or 1
            # Потолок высокий нарочно: у этого драйвера канал даёт около
            # 768, и даже полный микс редко выходит за тысячу — без
            # множителя в десятки раз файл получился бы тихим.
            gain = max(1, min(65536, int(256 * 29500 / top)))
            print("множитель %d/256 (самый громкий пик %d)" % (gain, top))

        # Проход второй: с общим уровнем и в постоянные файлы.
        quiet = []
        for n in nums:
            cnt = z80seq.tracks(n)[1]
            wav = os.path.join(out, "sound_%03d.wav" % n)
            pk = render(exe, img, wav, n, frames, gain, init, cnt == 1)
            size = os.path.getsize(wav)
            secs = (size - 44) / 4 / 53267.0
            if pk < 64:
                quiet.append(n)
            if pk >= 32767:
                print("    ВНИМАНИЕ: упёрлось в предел, множитель великоват")
            print("  %s: дорожек %2d, пик %5d, %.1f с"
                  % (os.path.basename(wav), cnt, pk, secs))
        if quiet:
            print("  почти тихие (%d): %s"
                  % (len(quiet), " ".join(str(n) for n in quiet)))
    print("\nготово")
    return 0


if __name__ == "__main__":
    sys.exit(main())
