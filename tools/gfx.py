#!/usr/bin/env python3
"""Достаёт графику: распаковывает блоки и рисует их в PNG.

    make gfx                                    сводка по всему
    make gfx GFXARGS="--stages 1 0"             набор тайлов этапа 1 палитрой 0
    make gfx GFXARGS="--sprites 43"             кадры набора 43
    make gfx GFXARGS=062BDA                     блок по адресу
    make gfx GFXARGS=--findpal                  палитры в ROM

Три хранилища и две палитры по умолчанию.

* `table_assets` `$061800` — 30 записей, наборы тайлов местности.
  Идут четвёрками: описание метатайлов, затем наборы по 96, 256 и 128
  тайлов. Описание узнаётся по началу `FF 15 16 17` и тайлами не является.
* `table_gfx_a` `$078818` — 48 записей, каждая ведёт на СВОЮ таблицу
  указателей: три уровня, а не два. На третьем — кадры ровно по 512 байт,
  то есть по 16 тайлов, спрайт 4x4. Всего 5464 кадра.
* `$01318C` — одиннадцать записей по `$1CC` байт: **14 палитр и номера
  трёх наборов тайлов**. Это и есть пара «графика — цвет» для поля боя.

Палитры поля боя раскладываются по слотам CRAM в `$005384`:
слот 0 — `data_99[0]`, слоты 1 и 2 — `data_99` по номерам из байтов
`+$28` и `+$29` описания миссии (на деле всегда 1 и 3), слот 3 — палитра
из записи этапа по байту `+$4C`. Поэтому спрайты по умолчанию рисуются
палитрой `data_99[3]`, а тайлы — палитрой записи.

Тайл: 8x8 точек по 4 бита, 32 байта, строки сверху вниз, в байте сначала
левая точка. **У спрайтов тайлы идут по столбцам**, поэтому кадр 4x4
перед выводом переставляется — иначе картинка рассыпается на полосы.

Палитра — 16 слов CRAM вида `0BGR`, по три значащих бита на составляющую.
Это же правило служит признаком поиска (`--findpal`). В ОЗУ у палитры
другой вид: шесть байт на цвет, «текущий» и «целевой» по три нибблa, —
так устроено затухание (`$00C5B0`), и по этому виду искать бесполезно.
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
PAL_ARRAY = 0x00F784      # data_99: девять палитр по 32 байта подряд
STAGE_GFX = 0x01318C      # одиннадцать записей по $1CC
STAGE_REC = 0x01CC
UNIT_PAL = PAL_ARRAY + 32 * 3   # слот 2 поля боя: им нарисованы юниты
METATILE_MARK = bytes([0xFF, 0x15, 0x16, 0x17])
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


def stage_records():
    """Записи графики этапа: 14 палитр и номера трёх наборов тайлов."""
    _m, size, d, _e = unpack(rom, STAGE_GFX)
    out = []
    for k in range(size // STAGE_REC):
        r = bytes(d[k * STAGE_REC:(k + 1) * STAGE_REC])
        pals = [[(((v >> 1) & 7) * 36, ((v >> 5) & 7) * 36, ((v >> 9) & 7) * 36)
                 for v in [(r[i * 32 + 2 * j] << 8) | r[i * 32 + 2 * j + 1]
                           for j in range(16)]] for i in range(14)]
        assets = [((r[0x1C2 + 2 * i] << 8) | r[0x1C3 + 2 * i]) // 4
                  for i in range(3)]
        out.append((pals, assets))
    return out


def do_stages(d, only=None, pal_no=0):
    recs = stage_records()
    print("== %d записей графики этапа, $%06X ==" % (len(recs), STAGE_GFX))
    for k, (pals, assets) in enumerate(recs):
        if only is not None and k != only:
            continue
        print("  %2d  наборы тайлов %s, палитр 14" % (k, assets))
        if only is None:
            continue
        for a in assets:
            p = L(ASSETS + 4 * a)
            _m, size, data, _e = unpack(rom, p)
            if bytes(data[:4]) == METATILE_MARK:
                print("      набор %2d — описание метатайлов, пропущен" % a)
                continue
            path = os.path.join(d, "stage%02d_pal%d_asset%02d.png"
                                % (k, pal_no, a))
            t = render(data, path, pal=pals[pal_no])
            print("      набор %2d  %4d тайлов -> %s"
                  % (a, t, os.path.relpath(path, HERE)))


def do_sprites(d, pal, only=None):
    pal = pal or read_palette(UNIT_PAL)
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
        print()
        do_stages(d)
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

    if args[0] == "--stages":
        only = int(args[1]) if len(args) > 1 else None
        pal_no = int(args[2]) if len(args) > 2 else 0
        do_stages(d, only, pal_no)
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
