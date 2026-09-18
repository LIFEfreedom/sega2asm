#!/usr/bin/env python3
"""Достаёт графику: распаковывает блоки и рисует их в PNG.

    make gfx                           сводка по обоим хранилищам
    python tools/gfx.py --assets       30 наборов тайлов местности
    python tools/gfx.py --sprites      сводка по 48 наборам спрайтов
    python tools/gfx.py --sprites 0    все кадры набора 0 лентой
    python tools/gfx.py 062BDA         произвольный блок по адресу
    python tools/gfx.py --findpal      где в ROM лежат палитры

К любому режиму добавляется `--pal 031D1C` — палитра из ROM; без неё
рисуется серым по номеру цвета, чего хватает, чтобы опознать содержимое.

Два независимых хранилища:

* `table_assets` `$061800` — 30 записей, наборы тайлов местности.
  Идут четвёрками: описание метатайлов, затем наборы по 96, 256 и 128
  тайлов. Описание узнаётся по началу `FF 15 16 17` и тайлами не является.
* `table_gfx_a` `$078818` — 48 записей, и каждая ведёт на СВОЮ таблицу
  указателей: три уровня, а не два. На третьем лежат кадры ровно по
  512 байт, то есть по 16 тайлов — спрайт 4x4. Всего 5464 кадра.

Тайл: 8x8 точек по 4 бита, 32 байта, строки сверху вниз, в байте сначала
левая точка. **У спрайтов тайлы идут по столбцам**, поэтому кадр 4x4
перед выводом переставляется — иначе картинка рассыпается на полосы.

Палитра — 16 слов CRAM вида `0BGR`: по три значащих бита на составляющую,
остальные нули. Это же и признак, по которому палитры находятся в ROM.
"""
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from unpack import unpack  # noqa: E402

rom = open(os.path.join(HERE, "game.gen"), "rb").read()
ASSETS = 0x061800
SPRITES = 0x078818
GREY = [(0, 0, 0)] + [(17 * i,) * 3 for i in range(1, 16)]

L = lambda a: struct.unpack(">I", rom[a:a + 4])[0]


def read_palette(a):
    out = []
    for i in range(16):
        v = (rom[a + 2 * i] << 8) | rom[a + 2 * i + 1]
        if v & 0xF111:
            raise ValueError("$%06X не палитра: слово %d = $%04X" % (a, i, v))
        out.append((((v >> 1) & 7) * 36, ((v >> 5) & 7) * 36,
                    ((v >> 9) & 7) * 36))
    return out


def find_palettes(lo=0, hi=None, variety=6):
    """Все 32-байтные участки, проходящие правило `0BGR`."""
    hi = hi if hi is not None else len(rom) - 32
    out, a = [], lo
    while a < hi:
        ws = [(rom[a + 2 * j] << 8) | rom[a + 2 * j + 1] for j in range(16)]
        if not any(v & 0xF111 for v in ws) and len(set(ws)) >= variety:
            out.append(a)
            a += 32
        else:
            a += 2
    return out


def png(path, w, h, rows):
    raw = b"".join(b"\0" + bytes(c for p in r for c in p) for r in rows)

    def chunk(tag, data):
        c = tag + data
        return (struct.pack(">I", len(data)) + c
                + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        f.write(chunk(b"IEND", b""))


def render(data, path, cols=16, pal=None, scale=2):
    pal = pal or GREY
    n = len(data) // 32
    rows = (n + cols - 1) // cols
    w, h = cols * 8, rows * 8
    img = [[(40, 40, 60)] * w for _ in range(h)]
    for t in range(n):
        tx, ty = (t % cols) * 8, (t // cols) * 8
        for y in range(8):
            b = data[t * 32 + y * 4: t * 32 + y * 4 + 4]
            for x in range(8):
                v = (b[x >> 1] >> 4) if x % 2 == 0 else (b[x >> 1] & 15)
                img[ty + y][tx + x] = pal[v]
    if scale > 1:
        big = []
        for r in img:
            rr = [p for p in r for _ in range(scale)]
            big.extend([rr] * scale)
        img, w, h = big, w * scale, h * scale
    png(path, w, h, img)
    return n


def columnwise(frame, side=4):
    """Кадр спрайта: тайлы по столбцам -> построчно."""
    t = [frame[k * 32:(k + 1) * 32] for k in range(side * side)]
    return b"".join(t[x * side + y] for y in range(side) for x in range(side))


def render_frames(frames, path, per_row=8, side=4, pal=None, scale=2):
    """Кадры 4x4 сеткой: рядом их видно, а лентой в 4 тайла — нет."""
    blank = bytes(32 * side)
    tiles = []
    rows = (len(frames) + per_row - 1) // per_row
    for r in range(rows):
        band = frames[r * per_row:(r + 1) * per_row]
        for y in range(side):
            for fr in band:
                tiles.append(fr[y * side * 32:(y * side + side) * 32])
            tiles.extend([blank] * (per_row - len(band)))
    return render(b"".join(tiles), path, cols=per_row * side,
                  pal=pal, scale=scale)


def out_dir():
    d = os.path.join(HERE, "out", "gfx")
    os.makedirs(d, exist_ok=True)
    return d


def table_len(base):
    n = (L(base) - base) // 4
    return n if 0 < n < 4096 else 0


def do_assets(d, pal):
    n = table_len(ASSETS)
    print("== %d наборов тайлов местности, таблица $%06X ==" % (n, ASSETS))
    for i in range(n):
        p = L(ASSETS + 4 * i)
        m, size, data, _e = unpack(rom, p)
        if bytes(data[:4]) == b"\xFF\x15\x16\x17":
            print("  %2d  $%06X  %6d байт  — описание метатайлов, не тайлы"
                  % (i, p, size))
            continue
        path = os.path.join(d, "asset_%02d.png" % i)
        t = render(data, path, pal=pal)
        print("  %2d  $%06X  %6d байт  %4d тайлов  -> %s"
              % (i, p, size, t, os.path.relpath(path, HERE)))


# Корень $078800 держит два указателя в ОДИН массив: $078810 -> $078818
# (записи 0..47) и $078814 -> $0788D8 (записи 48..115). Первая половина —
# подтаблицы кадров длинными словами, вторая устроена иначе: её читают
# самоотносительными СЛОВАМИ ($0018AA), и сюда она не входит.
SPRITE_SETS = 48


def do_sprites(d, pal, only=None):
    n = SPRITE_SETS
    total = empty = 0
    print("== %d наборов спрайтов, таблица $%06X ==" % (n, SPRITES))
    for i in range(n):
        if only is not None and i != only:
            continue
        sub = L(SPRITES + 4 * i)
        k = table_len(sub)
        if not k:
            print("  %2d  $%06X  подтаблица не разбирается" % (i, sub))
            continue
        frames = []
        for j in range(k):
            p = L(sub + 4 * j)
            if not (0 < p < 0x200000):
                empty += 1
                continue
            _m, _size, data, _e = unpack(rom, p)
            frames.append(columnwise(bytes(data)))
        total += len(frames)
        if only is None:
            print("  %2d  $%06X  записей %4d, кадров %4d" % (i, sub, k, len(frames)))
            continue
        path = os.path.join(d, "sprites_%02d.png" % i)
        render_frames(frames, path, pal=pal)
        print("  %2d  $%06X  кадров %d -> %s"
              % (i, sub, len(frames), os.path.relpath(path, HERE)))
    if only is None:
        print("  итого кадров %d, пустых записей %d" % (total, empty))


def main():
    args = sys.argv[1:]
    d = out_dir()
    pal = None
    if "--pal" in args:
        i = args.index("--pal")
        pal = read_palette(int(args[i + 1], 16))
        del args[i:i + 2]

    if not args:
        do_assets(d, pal)
        print()
        do_sprites(d, pal)
        return 0

    if args[0] == "--findpal":
        hits = find_palettes()
        print("палитр в ROM: %d" % len(hits))
        for h in hits:
            print("  $%06X" % h)
        return 0

    if args[0] == "--assets":
        do_assets(d, pal)
        return 0

    if args[0] == "--sprites":
        do_sprites(d, pal, int(args[1]) if len(args) > 1 else None)
        return 0

    a = int(args[0], 16)
    m, size, data, _e = unpack(rom, a)
    path = os.path.join(d, "block_%06X.png" % a)
    t = render(data, path, pal=pal)
    print("$%06X: метод %d, %d байт, %d тайлов -> %s"
          % (a, m, size, t, os.path.relpath(path, HERE)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
