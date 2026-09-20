#!/usr/bin/env python3
"""Карта мира целиком: таблица имён собирается из блоков и метатайлов.

    make worldmap

Это первый экран, который в проекте собирается **целиком**, а не по
тайлам. Схему даёт `DrawWorldMapWindow`, которому `ShowTitleScreen`
`$057A86` передаёт три указателя подряд:

```asm
	pea	(WorldMetatiles).l   ; $185226
	pea	(WorldBlocks).l      ; $185566
	pea	(WorldMap).l         ; $185966
	move.w	#$0080,-(a7)
	move.w	#$0038,-(a7)
	move.w	#$6000,-(a7)         ; атрибуты имени: палитра 3
	move.w	#$C000,-(a7)         ; таблица имён плана A
	bsr.w	DrawWorldMapWindow
```

Цепочка трёхступенчатая, и читается она в `GfxState_05A1D0`:

```asm
	move.b	(a1)+,d0          ; байт карты — номер блока, считая с единицы
	subq.w	#1,d0
	lsl.w	#2,d0
	move.b	($0,a2,d0.w),d3   ; блок -> номер метатайла
	lsl.w	#3,d3
	move.w	($0,a3,d3.w),d4   ; метатайл -> четыре слова имени
```

| ступень | адрес | размер | что |
|---|---|---|---|
| карта | `$185966` | 1600 | 40x40 байт, номер блока с единицы |
| блоки | `$185566` | 1024 | 256 записей по 4 байта, номера метатайлов |
| метатайлы | `$185226` | 832 | 104 записи по 4 слова, номера тайлов |

Каждая ступень удваивает сторону: метатайл 2x2 тайла, блок 2x2 метатайла,
то есть 4x4 тайла или 32x32 точки. Вся карта — 40x40 блоков, 1280x1280.

Что тайлы лежат шестнадцатью в ряд, видно прямо в данных: первый метатайл
это `0000 0001 0010 0011`, то есть пара по горизонтали и такая же пара
через шестнадцать номеров.

Графика — `$183CB6`, ровно 8192 байта, 256 тайлов: столько же, сколько
различных номеров в метатайлах. Палитра — `WorldMapPalette` `$185FA6`.
Слово имени — обычное имя VDP: биты 0…10 номер тайла, бит 11 отражение по
горизонтали, бит 12 по вертикали, биты 13…14 палитра. В карте мира
встречается только бит 11, и без него береговая линия рассыпается: она
собрана зеркальными парами. Палитру задаёт не имя, а аргумент `$6000`
отрисовки — строка CRAM 3, куда `ShowTitleScreen` кладёт `WorldMapPalette`
трапом `$FF20`.
"""
import io
import os
import struct
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from unpack import unpack                                    # noqa: E402
from gfx import png, read_palette                            # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT as out_path

ROM = open(os.path.join(HERE, "game.gen"), "rb").read()
U16 = lambda o: struct.unpack_from(">H", ROM, o)[0]

TILES = 0x183CB6
METAS = 0x185226
BLOCKS = 0x185566
MAP = 0x185966
PAL = 0x185FA6
W = H = 40                     # блоков
GREY = [(v, v, v) for v in (0, 17, 34, 51, 68, 85, 102, 119,
                            136, 153, 170, 187, 204, 221, 238, 255)]


def tile_pixels(data, n):
    """8x8 индексов цвета тайла n."""
    o = n * 32
    if o + 32 > len(data):
        return [[0] * 8 for _ in range(8)]
    rows = []
    for y in range(8):
        line = []
        for x in range(4):
            b = data[o + y * 4 + x]
            line.append(b >> 4)
            line.append(b & 15)
        rows.append(line)
    return rows


def main():
    src = int(sys.argv[1], 16) if len(sys.argv) > 1 else TILES
    _m, size, tiles, _e = unpack(ROM, src)
    pal = read_palette(PAL)
    print("тайлы $%06X: %d байт, %d тайлов" % (src, size, size // 32))

    px = W * 32
    canvas = [[(0, 0, 0)] * px for _ in range(px)]
    used = set()
    for by in range(H):
        for bx in range(W):
            blk = ROM[MAP + by * W + bx]
            if blk == 0:
                continue
            used.add(blk)
            bo = BLOCKS + (blk - 1) * 4
            for my in range(2):
                for mx in range(2):
                    meta = ROM[bo + my * 2 + mx]
                    mo = METAS + meta * 8
                    for ty in range(2):
                        for tx in range(2):
                            name = U16(mo + (ty * 2 + tx) * 2)
                            t = tile_pixels(tiles, name & 0x07FF)
                            if name & 0x0800:        # бит 11 — отражение
                                t = [r[::-1] for r in t]
                            if name & 0x1000:        # бит 12 — по вертикали
                                t = t[::-1]
                            ox = (bx * 4 + mx * 2 + tx) * 8
                            oy = (by * 4 + my * 2 + ty) * 8
                            for y in range(8):
                                row = canvas[oy + y]
                                for x in range(8):
                                    row[ox + x] = pal[t[y][x]]
    d = out_path("gfx")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "worldmap_%06X.png" % src)
    png(path, px, px, canvas)
    print("блоков в карте: %d различных из 256" % len(used))
    print("собрано: %s (%dx%d)" % (os.path.relpath(path, HERE), px, px))
    return 0


if __name__ == "__main__":
    sys.exit(main())
