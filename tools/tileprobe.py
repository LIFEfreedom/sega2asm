#!/usr/bin/env python3
"""Показать кусок ROM как тайлы 4bpp — серой шкалой, без палитры.

    python tools/tileprobe.py 020000 [тайлов]
    make tileprobe ADDR=020000

Зачем отдельный инструмент, когда есть `gfx.py`. Тот знает таблицы и
распаковщики конкретной игры; здесь же вопрос более грубый: **лежат ли по
этому адресу готовые тайлы вообще**. Палитра на такой вопрос только мешает
— тёмные цвета съедают структуру, и несжатые тайлы выглядят как шум. В
шестнадцати оттенках серого рисунок 8x8 либо складывается, либо нет.

Так у Maui Mallard была опровергнута гипотеза «низкие банки — несжатые
тайлы»: энтропия и доля нулей говорили за неё, а картинка показала
вертикальные полосы с периодом в байтовый ряд тайла (docs/mauimallard/rom-map.md).

Пишет PNG в `out/<имя проекта>/gfx/grey_XXXXXX.png`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT as out_path
from paths import rom_bytes

try:
    from PIL import Image
except ImportError:
    print("[--] нужен Pillow:  pip install pillow")
    sys.exit(1)

ROM = rom_bytes()
GREY = [(i * 17, i * 17, i * 17) for i in range(16)]


def sheet(addr, ntiles=256, cols=16):
    """Лист тайлов: 32 байта на тайл, 4 байта на строку, старший нибл слева."""
    rows = (ntiles + cols - 1) // cols
    img = Image.new("RGB", (cols * 8, rows * 8))
    px = img.load()
    for t in range(ntiles):
        base = addr + t * 32
        if base + 32 > len(ROM):
            break
        tx, ty = (t % cols) * 8, (t // cols) * 8
        for y in range(8):
            for xb in range(4):
                b = ROM[base + y * 4 + xb]
                px[tx + xb * 2, ty + y] = GREY[b >> 4]
                px[tx + xb * 2 + 1, ty + y] = GREY[b & 15]
    return img


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__)
        return 2
    addr = int(args[0], 16)
    n = int(args[1]) if len(args) > 1 else 256
    d = out_path("gfx")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "grey_%06X.png" % addr)
    # Увеличиваем вдвое: на экране 8x8 разглядеть трудно, а NEAREST ничего
    # не додумывает — видно ровно то, что в ROM.
    img = sheet(addr, n)
    img.resize((img.width * 2, img.height * 2), Image.NEAREST).save(path)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
