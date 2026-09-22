#!/usr/bin/env python3
u"""Меню команд: картинки, пункты, переходы и доступность по миссиям.

    make menus                  # восемь меню в PNG плюс сводка
    make menus MNARGS=--plain   # без разметки пунктов

## Восемь меню

`OpenCommandMenu` `$0058D8` берёт номер команды (с единицы), кладёт его в
`$FF9C72` и идёт в `MenuPictures` `$0058C8` — восемь СЛОВ, смещения
относительно самой таблицы. По смещению лежит сжатый блок, и он
раскладывается без остатка:

| что | сколько |
|---|---|
| слово | сколько пунктов |
| по 10 байт на пункт | геометрия и переходы |
| 70 тайлов | картинка меню, 10 на 7 |

Проверка простая и жёсткая: `2 + пунктов * 10 + 70 * 32` равно длине
блока у всех восьми, байт в байт.

Тайлы уходят в VRAM `$F6E0` (то есть номера с `$7B7`), а имена ставятся
подряд блоком 10 на 7 начиная с `$0982` плюс `$24EC(a5)` — это строка 7,
столбец 1 от начала плоскости.

## Десять байт пункта

Первые восемь — **куда перейти по каждому из восьми направлений**, по
байту на сторону, начиная с «вверх» и дальше по часовой стрелке. Свой же
номер значит «отсюда туда хода нет». Последние два — X и Y пункта в
точках внутри картинки 80 на 56.

Разбор проверен на сетке 3x3 команды 1: у верхнего левого пункта вверх и
влево стоит он сам, вправо сосед справа, вниз сосед снизу, и так у всех
девяти.

Так что подсветка и ходьба по меню не считаются из координат, а прописаны
таблицей; поэтому меню и бывают неправильными сетками — у команды 6
четыре пункта стоят ромбом.

## Доступность

`BuildSubmenuForCommand` `$024B1E` обнуляет девять байт с `$FF9C73`,
зовёт свою процедуру команды из `data_177` и добавляет
`ApplyMissionCommandMask` `$024E62`. Вот она и интересна:

```asm
	move.b	($FF9C72).l,d0     ; номер команды
	subq.b	#1,d0
	add.b	d0,d0
	movea.l	(MainStatePtr).l,a0
	move.w	($3C,a0,d0.w),d1   ; СЛОВО ИЗ ОПИСАНИЯ МИССИИ
	lea	($FF9C7B).l,a0
	moveq	#8,d2
	... btst d2,d1 ; сброшенный бит -> st (a0), то есть «нельзя»
```

То есть у каждой миссии в записи с `+$3C` лежат **восемь слов, по одному
на команду, и в каждом девять значащих бит — по биту на пункт меню**.
Сброшенный бит закрывает пункт. Отсюда и берётся, что в начале игры
доступны не все команды.

Байт `$FF9C73` отвечает пункту 0, `$FF9C7B` — пункту 8.

## Чего здесь нет

Своя процедура команды из `data_177` `$024B1E` не разобрана: она может
закрыть пункт и помимо маски миссии (например когда не хватает еды).
Здесь показана только маска — то, что задано данными миссии, а не
состоянием партии.
"""
import collections
import io
import os
import struct
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from unpack import unpack                                    # noqa: E402
from gfx import png                                          # noqa: E402
from paths import OUT as out_path, rom_bytes                 # noqa: E402

ROM = rom_bytes()

MENU_PICTURES = 0x0058C8   # восемь слов, смещения относительно себя
MENU_NAMES = 0x0496F0      # CommandMenuNames
COLS, ROWS = 10, 7         # картинка меню в тайлах
ITEM = 10                  # байт на пункт
MASK_FIELD = 0x3C          # слово на команду в описании миссии
MREC = 0x5C
CHAPTERS = 0x060400
DIRS = (u"вверх", u"вверх-вправо", u"вправо", u"вниз-вправо",
        u"вниз", u"вниз-влево", u"влево", u"вверх-влево")


def menu(k):
    u"""Меню команды k+1: (пунктов, [запись], тайлы)."""
    o = struct.unpack_from(">H", ROM, MENU_PICTURES + 2 * k)[0]
    d = bytes(unpack(ROM, MENU_PICTURES + o)[2])
    n = struct.unpack_from(">H", d, 0)[0]
    items = [d[2 + i * ITEM:2 + (i + 1) * ITEM] for i in range(n)]
    return n, items, d[2 + n * ITEM:]


def fits(k):
    u"""Сходится ли длина блока: 2 + пунктов * 10 + 70 * 32."""
    o = struct.unpack_from(">H", ROM, MENU_PICTURES + 2 * k)[0]
    d = bytes(unpack(ROM, MENU_PICTURES + o)[2])
    n = struct.unpack_from(">H", d, 0)[0]
    return len(d), 2 + n * ITEM + COLS * ROWS * 32


def chapters():
    out = []
    for c in range(16):
        p = struct.unpack_from(">I", ROM, CHAPTERS + c * 4)[0]
        if not (0 < p < 0x280000):
            continue
        try:
            out.append((c, bytes(unpack(ROM, p)[2])))
        except Exception:
            continue
    return out


def missions():
    u"""[(глава, миссия, запись)]."""
    out = []
    for c, body in chapters():
        for i in range(len(body) // MREC):
            r = body[i * MREC:(i + 1) * MREC]
            if r[3]:
                out.append((c, i + 1, r))
    return out


def masks(rec):
    u"""Восемь слов доступности из описания миссии, по одному на команду."""
    return [struct.unpack_from(">H", rec, MASK_FIELD + 2 * k)[0]
            for k in range(8)]


def draw(k, path, scale=4, plain=False):
    u"""Картинка меню; без --plain пункты обводятся и нумеруются."""
    import maptex
    n, items, tiles = menu(k)
    pal = maptex.array_palette(0)
    w, h = COLS * 8, ROWS * 8
    px = [[(0, 0, 0)] * w for _ in range(h)]
    for t in range(COLS * ROWS):
        g = tiles[t * 32:(t + 1) * 32]
        cx, cy = (t % COLS) * 8, (t // COLS) * 8
        for y in range(8):
            row = px[cy + y]
            for x in range(8):
                b = g[y * 4 + (x >> 1)]
                v = (b >> 4) if x % 2 == 0 else (b & 15)
                row[cx + x] = pal[v]
    W, H = w * scale, h * scale
    img = [[(0, 0, 0)] * W for _ in range(H)]
    for y in range(h):
        for x in range(w):
            c = px[y][x]
            for ky in range(scale):
                row = img[y * scale + ky]
                for kx in range(scale):
                    row[x * scale + kx] = c
    if not plain:
        mark = (255, 64, 64)
        for i, r in enumerate(items):
            bx, by = r[8] * scale, r[9] * scale
            for d in range(6 * scale):
                for t in range(max(1, scale // 2)):
                    if by + t < H and bx + d < W:
                        img[by + t][bx + d] = mark
                    if by + d < H and bx + t < W:
                        img[by + d][bx + t] = mark
    png(path, W, H, img)
    return n


def main():
    args = sys.argv[1:]
    plain = "--plain" in args
    d = out_path("menus")
    os.makedirs(d, exist_ok=True)

    bad = []
    for k in range(8):
        got, want = fits(k)
        if got != want:
            bad.append((k + 1, got, want))
        p = os.path.join(d, "command_%d.png" % (k + 1))
        n = draw(k, p, plain=plain)
        print(u"команда %d: пунктов %d -> %s"
              % (k + 1, n, os.path.relpath(p, HERE)))
    print(u"длина блока сходится у %d из 8" % (8 - len(bad)))
    for k, got, want in bad:
        print(u"   команда %d: %d байт вместо %d" % (k, got, want))

    doc = os.path.join(HERE, "docs", "game-menus.md")
    f = io.open(doc, "w", encoding="utf-8", newline="\n")
    p = f.write
    p(u"# Меню команд\n\n")
    p(u"Собрано `tools/menus.py` (`make menus`). Картинки — в "
      u"`out/<имя>/menus/`.\n\n")
    p(u"СГЕНЕРИРОВАНО — правки затираются, меняйте инструмент.\n"
      u"Вывод, который надо сохранить, пишите в соседний, ручной файл.\n\n")
    p(u"Формат разобран в шапке `tools/menus.py`.\n\n")
    p(u"## Восемь меню\n\n")
    p(u"| команда | пунктов | блок | байт |\n|---|---:|---|---:|\n")
    for k in range(8):
        o = struct.unpack_from(">H", ROM, MENU_PICTURES + 2 * k)[0]
        n, _items, _t = menu(k)
        p(u"| %d | %d | `$%06X` | %d |\n"
          % (k + 1, n, MENU_PICTURES + o, fits(k)[0]))

    for k in range(8):
        n, items, _t = menu(k)
        p(u"\n## Команда %d — %d пунктов\n\n" % (k + 1, n))
        p(u"| пункт | X | Y | " + u" | ".join(DIRS) + u" |\n")
        p(u"|---|---:|---:|" + u"---|" * 8 + u"\n")
        for i, r in enumerate(items):
            p(u"| %d | %d | %d | %s |\n"
              % (i, r[8], r[9],
                 u" | ".join(u"—" if r[j] == i else str(r[j])
                             for j in range(8))))

    p(u"\n## Доступность по миссиям\n\n")
    p(u"Слово на команду в описании миссии с `+$%02X`; единица в бите i "
      u"открывает пункт i. Здесь показаны только миссии, где маска "
      u"закрывает хоть что-то.\n\n" % MASK_FIELD)
    p(u"| глава, миссия | " + u" | ".join(u"к%d" % (k + 1)
                                          for k in range(8)) + u" |\n")
    p(u"|---|" + u"---|" * 8 + u"\n")
    counts = collections.Counter()
    shown = 0
    for c, m, rec in missions():
        ms = masks(rec)
        full = [(1 << menu(k)[0]) - 1 for k in range(8)]
        if all(ms[k] & full[k] == full[k] for k in range(8)):
            counts["все открыты"] += 1
            continue
        shown += 1
        if shown <= 40:
            p(u"| гл.%d м.%d | %s |\n"
              % (c, m, u" | ".join(u"%d/%d" % (bin(ms[k] & full[k]).count("1"),
                                               menu(k)[0])
                                   for k in range(8))))
    p(u"\nМиссий, где открыто всё: **%d**; где что-то закрыто: **%d**"
      u"%s.\n" % (counts["все открыты"], shown,
                  u" (в таблице первые 40)" if shown > 40 else u""))
    f.close()
    print(u"сводка: %s" % os.path.relpath(doc, HERE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
