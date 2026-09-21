#!/usr/bin/env python3
"""Уровни Maui Mallard: таблица, графика, карты.

    python tools/levels.py             сводка по 23 уровням
    python tools/levels.py --tiles 0   лист тайлов уровня
    python tools/levels.py --meta 0    лист метатайлов 16x16
    python tools/levels.py --map 0     карта уровня целиком
    python tools/levels.py --bg 0      фоновый слой (64x32)
    make levels LEVEL="--map 0"

Три таблицы по 23 записи идут подряд и держат всё об уровне:

| адрес | что |
|---|---|
| `$1FCB50` | запись уровня, `$42` байта |
| `$1FCBAC` | список объектов |
| `$1FCC08` | процедура уровня (все 23 ведут в код) |

Читает их `$2984BC` по номеру из `$FF1B14`. Из записи нам нужны два поля:
`+$00` — палитра (128 байт, все четыре ряда CRAM) и `+$08` — запись
графики, которую разбирает загрузчик `$291012`:

```
+$00 слово  флаг: карта (+$04) упакована
+$02 слово  флаг: таблица метатайлов (+$08) упакована
+$04 long   карта: слово ширины, слово высоты, дальше по слову на клетку —
            СМЕЩЕНИЕ в таблице метатайлов (всегда кратно восьми)
+$08 long   таблица метатайлов -> $FFFFE11C: по 8 байт, четыре имени VDP
            в порядке «слева сверху, справа сверху, слева снизу, справа снизу»
+$0C long   тайлы уровня, упакованы всегда -> VRAM
+$10 long   ещё один упакованный блок -> $FFFFE140 (что в нём — не разобрано)
+$14 long   карта имён фона: ширина, высота, дальше имена -> VRAM $E000
+$18 слово  флаг: блок (+$1A) упакован
+$1A long   -> $FFFFE120
```

Почти всё это **сжато** — см. [tools/lzss.py](lzss.py).

Что метатайлы лежат именно в `+$08`, видно в отрисовщике столбца
`$29135E`: он берёт слово карты в `d2` и пишет в VDP `($0,a2,d2.l)` и
`($4,a2,d2.l)`, где `a2` — `$FFFFE11C`. Автоинкремент VDP там `$8F80`,
то есть 64 слова, ровно ряд плоскости: запись идёт СТОЛБЦОМ, и пара
`+0`/`+4` — левая половина метатайла, `+2`/`+6` — правая.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT as out_path
from paths import rom_bytes

import lzss
import sprites as S

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM = rom_bytes()
TABLE, COUNT, REC = 0x1FCB50, 23, 0x42
OBJLISTS, PROCS = 0x1FCBAC, 0x1FCC08
U16 = lambda o: struct.unpack_from(">H", ROM, o)[0]
U32 = lambda o: struct.unpack_from(">I", ROM, o)[0]


def record(n):
    return U32(TABLE + n * 4)


def gfx(n):
    """Запись графики уровня -> словарь распакованных кусков."""
    g = U32(record(n) + 8)
    out = {"at": g, "map": U32(g + 4), "meta": U32(g + 8),
           "tiles": U32(g + 0xC), "blk10": U32(g + 0x10), "bg": U32(g + 0x14)}
    out["tiles_data"] = lzss.unpack(out["tiles"])[0]
    out["bg_data"] = lzss.unpack(out["bg"])[0]
    out["blk10_data"] = lzss.unpack(out["blk10"])[0]
    # Два флага в +$0: старшее слово — сжата ли карта, младшее — сжата ли
    # таблица метатайлов. Несжатое лежит в ROM как есть.
    if U16(g):
        out["map_data"] = lzss.unpack(out["map"])[0]
    else:
        w, h = struct.unpack_from(">HH", ROM, out["map"])
        out["map_data"] = ROM[out["map"]:out["map"] + 4 + w * h * 2]
    # Несжатую таблицу метатайлов обрезаем по самому дальнему смещению,
    # которое встретилось в карте: длины она нигде не хранит.
    if U16(g + 2):
        out["meta_data"] = lzss.unpack(out["meta"])[0]
    else:
        d = out["map_data"]
        far = max(struct.unpack_from(">H", d, 4 + i * 2)[0]
                  for i in range((len(d) - 4) // 2))
        out["meta_data"] = ROM[out["meta"]:out["meta"] + far + 8]
    return out


def pal(n):
    return S.cram(U32(record(n)))


def blit(dst, w, h, tiles, name, ox, oy, pals):
    """Одно имя VDP: тайл 8x8 с отражениями и рядом палитры."""
    t = name & 0x7FF
    if (t + 1) * 32 > len(tiles):
        return
    row = pals[(name >> 13) & 3]
    hf, vf = name & 0x800, name & 0x1000
    for y in range(8):
        py = oy + (7 - y if vf else y)
        if not (0 <= py < h):
            continue
        for xb in range(4):
            b = tiles[t * 32 + y * 4 + xb]
            for half, c in ((0, b >> 4), (1, b & 15)):
                x = xb * 2 + half
                px = ox + (7 - x if hf else x)
                if 0 <= px < w:
                    dst[py * w + px] = row[c] + (255,)


def out_dir():
    d = out_path("gfx")
    os.makedirs(d, exist_ok=True)
    return d


def save(name, w, h, buf, scale=1):
    p = os.path.join(out_dir(), name)
    S.png(p, w, h, buf, scale)
    print("  %dx%d -> %s" % (w * scale, h * scale, p))


def do_tiles(n, cols=32):
    g, p = gfx(n), pal(n)
    t = g["tiles_data"]
    cnt = len(t) // 32
    rows = (cnt + cols - 1) // cols
    w, h = cols * 8, rows * 8
    buf = [None] * (w * h)
    for i in range(cnt):
        blit(buf, w, h, t, i, (i % cols) * 8, (i // cols) * 8, p)
    print("уровень %d: тайлов %d" % (n, cnt))
    save("level%02d_tiles.png" % n, w, h, buf)


def metatiles(g):
    """-> список из четырёх имён на метатайл 2x2."""
    m = g["meta_data"]
    return [struct.unpack_from(">4H", m, i * 8) for i in range(len(m) // 8)]


def do_meta(n, cols=24):
    g, p = gfx(n), pal(n)
    mt, t = metatiles(g), g["tiles_data"]
    rows = (len(mt) + cols - 1) // cols
    w, h = cols * 16, rows * 16
    buf = [None] * (w * h)
    for i, q in enumerate(mt):
        ox, oy = (i % cols) * 16, (i // cols) * 16
        for k, name in enumerate(q):
            blit(buf, w, h, t, name, ox + (k % 2) * 8, oy + (k // 2) * 8, p)
    print("уровень %d: метатайлов %d" % (n, len(mt)))
    save("level%02d_meta.png" % n, w, h, buf)


def do_map(n, scale=1):
    g, p = gfx(n), pal(n)
    d = g["map_data"]
    mw, mh = struct.unpack_from(">HH", d, 0)
    mt, t = metatiles(g), g["tiles_data"]
    w, h = mw * 16, mh * 16
    buf = [None] * (w * h)
    bad = 0
    for cy in range(mh):
        for cx in range(mw):
            off = struct.unpack_from(">H", d, 4 + (cy * mw + cx) * 2)[0]
            if off % 8 or off // 8 >= len(mt):
                bad += 1
                continue
            for k, name in enumerate(mt[off // 8]):
                blit(buf, w, h, t, name, cx * 16 + (k % 2) * 8,
                     cy * 16 + (k // 2) * 8, p)
    print("уровень %d: карта %dx%d клеток (%dx%d точек), негодных клеток %d"
          % (n, mw, mh, w, h, bad))
    save("level%02d_map.png" % n, w, h, buf, scale)


def do_bg(n, scale=1):
    g, p = gfx(n), pal(n)
    d = g["bg_data"]
    bw, bh = struct.unpack_from(">HH", d, 0)
    t = g["tiles_data"]
    w, h = bw * 8, bh * 8
    buf = [None] * (w * h)
    for y in range(bh):
        for x in range(bw):
            name = struct.unpack_from(">H", d, 4 + (y * bw + x) * 2)[0]
            blit(buf, w, h, t, name, x * 8, y * 8, p)
    print("уровень %d: фон %dx%d имён" % (n, bw, bh))
    save("level%02d_bg.png" % n, w, h, buf, scale)


def summary():
    print("уровней %d, запись $%02X байт, таблицы $%06X / $%06X / $%06X\n"
          % (COUNT, REC, TABLE, OBJLISTS, PROCS))
    print(" №  запись   палитра  карта клеток   тайлов  метатайлов  фон"
          "    сжато -> распаковано")
    tot_in = tot_out = 0
    for n in range(COUNT):
        try:
            g = gfx(n)
        except Exception as e:
            print(" %2d  $%06X  не разбирается: %s" % (n, record(n), e))
            continue
        mw, mh = struct.unpack_from(">HH", g["map_data"], 0)
        bw, bh = struct.unpack_from(">HH", g["bg_data"], 0)
        raw = sum(lzss.unpack(g[k])[1] for k in ("tiles", "blk10", "bg"))
        big = sum(len(g[k + "_data"]) for k in ("tiles", "blk10", "bg"))
        tot_in += raw
        tot_out += big
        print(" %2d  $%06X  $%06X  %4dx%-4d    %5d   %9d  %2dx%-2d  "
              "%7d -> %7d" % (n, record(n), U32(record(n)), mw, mh,
                              len(g["tiles_data"]) // 32,
                              len(g["meta_data"]) // 8, bw, bh, raw, big))
    print("\nвсего %d байт сжатого дают %d (x%.2f)"
          % (tot_in, tot_out, float(tot_out) / tot_in))


def main():
    argv = sys.argv[1:]
    mode, scale, args = None, 1, []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--scale":
            i += 1
            scale = int(argv[i])
        elif a.startswith("--"):
            mode = a
        else:
            args.append(int(a, 0))
        i += 1
    if mode is None:
        summary()
        return 0
    fn = {"--tiles": do_tiles, "--meta": do_meta}.get(mode)
    if fn:
        for n in args or [0]:
            fn(n)
        return 0
    if mode == "--map":
        for n in args or [0]:
            do_map(n, scale)
        return 0
    if mode == "--bg":
        for n in args or [0]:
            do_bg(n, scale)
        return 0
    print("неизвестный ключ %s" % mode)
    return 2


if __name__ == "__main__":
    sys.exit(main())
