#!/usr/bin/env python3
"""Надписи на арене уровня 9 «MD MAYHEM - 3».

    python tools/captions.py           двенадцать надписей: текст и картинка
    python tools/captions.py --text    только расшифровка
    python tools/captions.py --steps   таблица из 252 шагов
    python tools/captions.py --font    все начертания, какие встретились
    python tools/captions.py --dead    надпись, до которой таблица не доходит

Надписи не хранятся буквами. Буква — это **список клеток карты имён**, а
ставит их та же процедура `$295812`, которой объекты пишут одиночную
клетку. Поэтому в картридже нет ни шрифта 3x5, ни строки «OH, BABY»:
есть только координаты закрашенных клеток.

Читает это `$29ECA8`:

    move.w  $4C(a0),d3          номер шага, 0..251
    lea     ($1FD95E).l,a6      шесть номеров плиток
    lea     ($1FD96A).l,a1      таблица шагов
    add.w   d3,d3 / add.w d3,d3
    movea.l ($0,a1,d3.w),a1     запись шага, 8 байт
    move.w  (a1)+,$6(a0)        сколько кадров держать
    move.w  (a1)+,d2            какой плиткой писать -> a6
    movea.l (a1)+,a1            список клеток
    move.w  (a1)+,d7            сколько клеток
    moveq   #5,d0 / add.b (a1)+,d0      столбец
    moveq   #3,d1 / add.b (a1)+,d1      строка

Отсюда «+5, +3»: клетки лежат байтами от левого верхнего угла полосы, а
полоса стоит со столбца 5, строки 3. Ширина полосы 28 клеток, высота 5.

Шаги идут четвёрками. Буква проступает плиткой 1, мигает плиткой 2 — и
так слева направо, последняя держится 90 кадров. Потом тем же порядком
буквы гаснут: плитка 1, потом плитка 0 (пустая), последняя 60 кадров.
У надписи из k букв ровно 4k шагов, и 252 шага делятся на двенадцать
надписей без остатка.

Соответствие «начертание -> буква» прочитано глазами и лежит в `FONT`;
всё остальное в выводе вычисляется, включая разбивку на надписи и
разбивку надписи на буквы.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import rom_bytes                                  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM = rom_bytes()

TILES = 0x1FD95E          # шесть номеров плиток, использованы три
STEPS = 0x1FD96A          # 252 указателя на записи шага
COUNT = 252               # `cmpi.w #$00FC,d4` в $29ECB6
RECS = 0x1FDD5A           # записи шага, по 8 байт
LISTS = 0x1FE3A2          # списки клеток
COL0, ROW0 = 5, 3         # `moveq #5,d0` и `moveq #3,d1`

# Записи, до которых таблица шагов не доходит: двенадцать штук перед
# первой достижимой. Их четыре списка клеток лежат тоже отдельно, перед
# первым достижимым списком.
DEAD_RECS = (RECS, 0x1FDDBA)
DEAD_LISTS = (0x1FE3A2, 0x1FE3B6, 0x1FE3CC, 0x1FE3E2)


def U16(a):
    return int.from_bytes(ROM[a:a + 2], "big")


def U32(a):
    return int.from_bytes(ROM[a:a + 4], "big")


def cells(at):
    """Список клеток -> [(столбец, строка)]."""
    n = U16(at)
    a = at + 2
    out = []
    for _k in range(n):
        out.append(((COL0 + ROM[a]) & 0xFF, (ROW0 + ROM[a + 1]) & 0xFF))
        a += 2
    return out


def steps():
    """252 шага: (длительность, номер плитки, адрес списка)."""
    out = []
    for i in range(COUNT):
        r = U32(STEPS + 4 * i)
        out.append((U16(r), U16(r + 2), U32(r + 4)))
    return out


def letters(cl):
    """Группа клеток -> отдельные буквы.

    Буквы разделены пустым столбцом, так что резать можно по разрывам в
    наборе столбцов. Это не догадка о ширине: у запятой она 2, у `G` и
    `M` — 4 и 5.
    """
    cols = sorted({c for c, _r in cl})
    runs, cur = [], [cols[0]]
    for c in cols[1:]:
        if c == cur[-1] + 1:
            cur.append(c)
        else:
            runs.append(cur)
            cur = [c]
    runs.append(cur)
    return [[(c, r) for c, r in cl if c in run] for run in runs]


def shape(g):
    """Начертание буквы строками, без привязки к месту на полосе."""
    c0 = min(c for c, _r in g)
    w = max(c for c, _r in g) - c0 + 1
    m = [[" "] * w for _ in range(5)]
    for c, r in g:
        m[r - ROW0][c - c0] = "#"
    return "/".join("".join(x) for x in m)


# Прочитано глазами. Живые надписи и мёртвая нарисованы РАЗНЫМИ руками:
# у `A`, `R` и `Y` там по два начертания, и это единственный внутренний
# признак, что мёртвый кусок остался от другого захода.
FONT = {
    "###/# #/# #/# #/###": "O",
    "# #/# #/###/# #/# #": "H",
    "  /  /  /##/ #": ",",
    "## /# #/## /# #/## ": "B",
    " # /###/# #/###/# #": "A",
    "#   #/ # # /  #  /  #  /  #  ": "Y",
    "###/#  /###/  #/###": "S",
    "#   #/# # #/# # #/ ### / # # ": "W",
    "###/#  /## /#  /###": "E",
    "#  /#  /#  /#  /###": "L",
    "#/#/#/ /#": "!",
    "### /#   /# ##/#  #/####": "G",
    "###/ # / # / # / # ": "T",
    "#   #/## ##/# # #/#   #/#   #": "M",
    "#/#/#/#/#": "I",
    "#/#/ / / ": "'",
    "# #/# #/# #/# #/###": "U",
    "## /# #/###/## /# #": "R",
    "###/#  /#  /#  /###": "C",
    " # /# #/###/# #/# #": "A",      # только в мёртвой надписи
    "## /# #/## /# #/# #": "R",      # только в мёртвой надписи
    "# #/# #/ # / # / # ": "Y",      # только в мёртвой надписи
}


def read(cl):
    """Группа клеток -> строка."""
    return "".join(FONT.get(shape(g), "?") for g in letters(cl))


def captions():
    """Разбивка 252 шагов на надписи: [(первый шаг, последний, на, с)].

    Граница вычисляется, а не задана. Шаги идут парами, и различает пары
    **второй** шаг: при появлении буквы там плитка 2, при гашении — 0.
    Значит появление кончается на первой паре с нулём, а гашение длится
    ровно столько же пар, сколько было букв.
    """
    st = steps()
    out = []
    i = 0
    while i + 1 < COUNT:
        first = i
        on = []
        while i + 1 < COUNT and st[i + 1][1] != 0:
            on.append(st[i][2])
            i += 2
        off = []
        while i + 1 < COUNT and len(off) < len(on):
            off.append(st[i][2])
            i += 2
        out.append((first, i - 1, on, off))
    return out


def art(sel, width=28):
    """Полоса 28x5 с закрашенными клетками."""
    g = [[" "] * width for _ in range(5)]
    for c, r in sel:
        g[r - ROW0][c - COL0] = "#"
    return ["|" + "".join(x) + "|" for x in g]


def whole(on):
    out = set()
    for lst in on:
        out |= set(cells(lst))
    return out


def do_text():
    for k, (a, b, on, _off) in enumerate(captions(), 1):
        print(u"%2d  шаги %3d..%3d  букв %d  «%s»"
              % (k, a, b, len(on), read(whole(on))))


def do_show():
    caps = captions()
    ok = sum(1 for _a, _b, on, off in caps if on == off)
    for k, (a, b, on, _off) in enumerate(caps, 1):
        print(u"=== %d, шаги %3d..%3d, букв %d: «%s»"
              % (k, a, b, len(on), read(whole(on))))
        for line in art(whole(on)):
            print(u"  " + line)
        print()
    print(u"надписей %d, шагов %d"
          % (len(caps), sum(b - a + 1 for a, b, _o, _f in caps)))
    print(u"гашение повторяет появление буква в букву: %d из %d"
          % (ok, len(caps)))


def do_steps():
    tiles = [U16(TILES + 2 * i) for i in range(6)]
    print(u"плитки $%06X: %s" % (TILES, " ".join("$%04X" % t for t in tiles)))
    print(u"  использованы 0, 1 и 2; три последние не берёт никто")
    print()
    lo = hi = None
    for i, (dur, idx, lst) in enumerate(steps()):
        r = U32(STEPS + 4 * i)
        lo = r if lo is None else min(lo, r)
        hi = r if hi is None else max(hi, r)
        print(u"%3d  запись $%06X  кадров %3d  плитка %d  список $%06X (%d)"
              % (i, r, dur, idx, lst, U16(lst)))
    print()
    print(u"записи $%06X..$%06X, списки $%06X..$%06X"
          % (lo, hi + 8, LISTS, extent()[1]))


def extent():
    """Границы всего хозяйства: от таблицы плиток до конца списков."""
    end = 0
    for _d, _i, lst in steps():
        end = max(end, lst + 2 + 2 * U16(lst))
    return TILES, end


def do_font():
    got = {}
    for _d, _i, lst in steps():
        for g in letters(cells(lst)):
            got.setdefault(shape(g), 0)
            got[shape(g)] += 1
    for lst in DEAD_LISTS:
        for g in letters(cells(lst)):
            got.setdefault(shape(g), 0)
    print(u"начертаний %d" % len(got))
    keys = sorted(got, key=lambda k: (FONT.get(k, "?"), -got[k]))
    for k in keys:
        rows = k.split("/")
        print(u"  %-2s  встреч %2d" % (FONT.get(k, "?"), got[k]))
        for r in rows:
            print(u"        %s" % r)


def do_dead():
    lo, hi = DEAD_RECS
    print(u"записи $%06X..$%06X (%d байт), списки $%06X..$%06X (%d байт)"
          % (lo, hi, hi - lo, DEAD_LISTS[0], LISTS + 0x50,
             LISTS + 0x50 - DEAD_LISTS[0]))
    print(u"на них не указывает ни одно длинное слово картриджа, а")
    print(u"единственный читатель берёт таблицу $%06X с номерами 0..%d"
          % (STEPS, COUNT - 1))
    whole = set()
    for lst in DEAD_LISTS:
        whole |= set(cells(lst))
    print()
    print(u"«%s»" % read(whole))
    for line in art(whole):
        print(u"  " + line)


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--text":
        do_text()
    elif arg == "--steps":
        do_steps()
    elif arg == "--font":
        do_font()
    elif arg == "--dead":
        do_dead()
    elif arg == "--extent":
        a, b = extent()
        print(u"$%06X-$%06X, %d байт" % (a, b, b - a))
    else:
        do_show()


if __name__ == "__main__":
    main()
