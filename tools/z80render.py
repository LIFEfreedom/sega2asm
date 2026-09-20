#!/usr/bin/env python3
"""Прогоняет звуковой драйвер Maui Mallard на эмуляторе и пишет WAV.

    make z80render                  все мелодии (многодорожечные звуки)
    make z80render RENDERARGS=--all      все 169 звуков
    make z80render RENDERARGS="12 34"    только эти номера
    make z80render RENDERARGS="--seconds 90 --all"

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
"""
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


def render(exe, img, out_wav, sound, frames, gain, init, stop):
    args = [exe, rom_path(), img, out_wav, "0", str(frames), "-1", "-1",
            "1" if stop else "0", str(gain),
            "--ring", "%X,%X" % (RING, RING_IX),
            "--init", init,
            "--play", "FF10%02X" % sound,
            "--busy", "%X,%X,%X,%X,%X" % SLOTS]
    r = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        raise SystemExit("render.exe: %s" % (r.stderr or r.stdout).strip())
    m = re.search(r"пик (\d+)", r.stdout)
    return int(m.group(1)) if m else 0


def main():
    args = sys.argv[1:]
    seconds = 45
    if "--seconds" in args:
        i = args.index("--seconds")
        seconds = int(args[i + 1])
        del args[i:i + 2]
    every = "--all" in args
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

    out = out_path("sound", "music")
    os.makedirs(out, exist_ok=True)
    frames = int(seconds * FPS)
    print("к выгрузке %d звуков, по %d с (%d кадров)\n"
          % (len(want), seconds, frames))

    # Проход первый: узнать, кто громче всех.
    peaks = {}
    for n in want:
        tmp = os.path.join(out, "_probe.wav")
        cnt = z80seq.tracks(n)[1]
        peaks[n] = render(exe, img, tmp, n, frames, 256, init, cnt == 1)
        print("  звук %3d: дорожек %2d, пик %5d" % (n, cnt, peaks[n]))
    if os.path.exists(os.path.join(out, "_probe.wav")):
        os.remove(os.path.join(out, "_probe.wav"))

    top = max(peaks.values()) or 1
    # Потолок высокий нарочно: у этого драйвера канал даёт около 768, и
    # даже полный микс редко выходит за тысячу — без множителя в
    # десятки раз файл получился бы тихим.
    gain = max(1, min(65536, int(256 * 29500 / top)))
    print("\nобщий множитель %d/256 (самый громкий пик %d)\n" % (gain, top))

    # Проход второй: с общим уровнем и в постоянные файлы.
    for n in want:
        cnt = z80seq.tracks(n)[1]
        wav = os.path.join(out, "sound_%03d.wav" % n)
        p = render(exe, img, wav, n, frames, gain, init, cnt == 1)
        size = os.path.getsize(wav)
        print("  %s: дорожек %2d, пик %5d, %.1f с"
              % (os.path.basename(wav), cnt, p, (size - 44) / 4 / 53267.0))
    print("\nготово: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
