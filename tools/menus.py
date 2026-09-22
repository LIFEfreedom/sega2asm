#!/usr/bin/env python3
u"""Меню команд: картинки, пункты, переходы и доступность по миссиям.

    make menus                  # восемь меню в PNG плюс сводка
    make menus MNARGS=--plain   # без разметки пунктов
    make menus MNARGS=--hud     # подложка панели, три варианта

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
HUD_NAMES = 0x01170C       # три подложки панели по 732 байта
HUD_TILES = 0x0111AA       # тайлы панели, база — тайл $256
HUD_COLS, HUD_ROWS = 13, 28
HUD_STRIDE = 4 + HUD_COLS * HUD_ROWS * 2
HUD_BASE = 0x8256          # к слову имени прибавляется это
MREC = 0x5C
CHAPTERS = 0x060400
DIRS = (u"вверх", u"вверх-вправо", u"вправо", u"вниз-вправо",
        u"вниз", u"вниз-влево", u"влево", u"вверх-влево")

# Процедура доступности на команду: (имя, адрес, проверки по пунктам).
# Разобрано по data_177 $024B52; счёт проверок сверяется с числом пунктов.
AVAIL = {
    1: (u"SubmenuAvailAll", 0x024BAE, None),
    2: (u"SubmenuAvailWeather", 0x024D1A,
        (u"полив", u"ливень", u"буря", u"засуха", u"землетрясение",
         u"молния", u"метеорит")),
    3: (u"SubmenuAvailAll", 0x024BAE, None),
    4: (u"SubmenuAvailAll", 0x024BAE, None),
    5: (u"SubmenuAvailEggs", 0x024D78,
        (u"яйцо вида 1", u"вида 2", u"вида 5", u"вида 4", u"вида 6",
         u"вида 3")),
    6: (u"SubmenuAvailPlants", 0x024DCA,
        (u"растение 1", u"растение 2", u"растение 4", u"растение 3")),
    7: (u"SubmenuAvailRemodel", 0x024E04,
        (u"вид 1", u"вид 2", u"вид 5", u"вид 4", u"вид 6", u"вид 3",
         u"улучшить выбранного")),
    8: (u"SubmenuAvailMark", 0x024BC4,
        (u"выбранный юнит", u"свой вид 4", u"вражеский вид 4",
         u"безусловно", u"всего своих", u"свой вид 6",
         u"вражеский вид 6")),
}


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


def hud(vi, path, toff=0, scale=3):
    u"""Подложка панели: 13 столбцов на 28 строк.

    Слово имени из `$01170C` маскируется `$18FF` и к нему прибавляется
    `$8256`, то есть номер тайла задаётся младшим байтом, а база — начало
    блока `$0111AA`. Прямоугольник вверху пуст не по ошибке: там место
    миникарты, её наполняет `BuildTerrainMapTiles` тайлами с `$290`.
    """
    import maptex
    names = bytes(unpack(ROM, HUD_NAMES)[2])
    src = bytes(unpack(ROM, HUD_TILES)[2])
    pal = maptex.array_palette(0)
    w, h = HUD_COLS * 8, HUD_ROWS * 8
    px = [[(0, 0, 0)] * w for _ in range(h)]
    base = vi * HUD_STRIDE + 4
    for r in range(HUD_ROWS):
        for c in range(HUD_COLS):
            o = base + (r * HUD_COLS + c) * 2
            if o + 2 > len(names):
                continue
            n = ((struct.unpack_from(">H", names, o)[0] & 0x18FF)
                 + HUD_BASE) & 0xFFFF
            t = (n & 0x7FF) - 0x256
            g = src[toff + t * 32:toff + (t + 1) * 32]
            if len(g) < 32:
                continue
            hf, vf = (n >> 11) & 1, (n >> 12) & 1
            for y in range(8):
                sy = 7 - y if vf else y
                row = px[r * 8 + y]
                for x in range(8):
                    sx = 7 - x if hf else x
                    b = g[sy * 4 + (sx >> 1)]
                    v = (b >> 4) if sx % 2 == 0 else (b & 15)
                    row[c * 8 + x] = pal[v]
    W, H = w * scale, h * scale
    img = [[(0, 0, 0)] * W for _ in range(H)]
    for y in range(h):
        for x in range(w):
            col = px[y][x]
            for ky in range(scale):
                row = img[y * scale + ky]
                for kx in range(scale):
                    row[x * scale + kx] = col
    png(path, W, H, img)


def do_hud():
    d = out_path("menus")
    os.makedirs(d, exist_ok=True)
    names = bytes(unpack(ROM, HUD_NAMES)[2])
    n = len(names) // HUD_STRIDE
    for vi in range(n):
        toff = 0 if vi == 0 else 0x740
        p = os.path.join(d, "hud_%d.png" % vi)
        hud(vi, p, toff)
        print(u"подложка %d (тайлы со смещения $%03X) -> %s"
              % (vi, toff, os.path.relpath(p, HERE)))
    print(u"панелей в $%06X: %d по %d байт" % (HUD_NAMES, n, HUD_STRIDE))
    return 0


def main():
    args = sys.argv[1:]
    if "--hud" in args:
        return do_hud()
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

    p(u"\n## Процедуры доступности\n\n")
    p(u"`data_177` `$024B52`, индекс — номер команды. Ставит единицу, "
      u"когда условие выполнено; маска миссии кладёт `$FF` поверх.\n\n")
    p(u"| команда | процедура | пунктов | по пунктам |\n"
      u"|---|---|---:|---|\n")
    for k in range(1, 9):
        name, a, checks = AVAIL[k]
        n = menu(k - 1)[0]
        p(u"| %d | `%s` `$%06X` | %d | %s |\n"
          % (k, name, a, n,
             u", ".join(checks) if checks else u"все, безусловно"))
    bad = [k for k in range(1, 9)
           if AVAIL[k][2] and len(AVAIL[k][2]) != menu(k - 1)[0]]
    p(u"\nЧисло проверок сходится с числом пунктов у %d из 8.\n"
      % (8 - len(bad)))

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
