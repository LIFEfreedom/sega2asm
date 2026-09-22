#!/usr/bin/env python3
"""Текст Maui Mallard: сценки, концовка, титры.

    python tools/story.py            все найденные блоки
    python tools/story.py --raw      с кодами-разделителями
    python tools/story.py --extent   границы для coverage.py

Текст лежит **обычным ASCII** и не сжат. Строка кончается нулём, а перед
строкой стоит байт-код: `$03` у имён в титрах, `$04` у заголовков,
`$05` и `$06` встречаются на границах разделов. Перевод строки внутри
реплики — тоже нулевой байт, так что «строка» здесь это одна строка
экрана, а не реплика целиком.

Границы находятся перебором, а не списком: берётся протяжённый участок
печатных знаков, к нему прирастают нули и коды. Поэтому новый блок в
картридже нашёлся бы сам.
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

# Банк `$1E`: сценки, концовка и титры лежат там подряд.
SCAN = (0x1E9000, 0x1EB000)
CODES = (0x00, 0x03, 0x04, 0x05, 0x06)
LEAST = 24


def _wordy(a, b, need=4):
    """Есть ли в куске слово из `need` букв подряд.

    Без этого в выдачу лезут таблицы, у которых байты случайно
    попадают в печатный диапазон.
    """
    run = 0
    for k in range(a, b):
        if 0x41 <= ROM[k] <= 0x5A:
            run += 1
            if run >= need:
                return True
        else:
            run = 0
    return False


def runs(lo=SCAN[0], hi=SCAN[1], least=LEAST):
    """Участки печатного ASCII не короче `least` знаков."""
    out, i = [], lo
    while i < hi:
        if 0x20 <= ROM[i] < 0x60:
            j = i
            while j < hi and (0x20 <= ROM[j] < 0x60 or ROM[j] in CODES):
                j += 1
            if j - i >= least and _wordy(i, j):
                out.append((i, j))
            i = j
        else:
            i += 1
    return out


def lines(a, b):
    """Строки блока: нуль — конец строки, байт перед строкой — код."""
    out, cur, code = [], [], None
    for k in range(a, b):
        c = ROM[k]
        if c == 0:
            if cur:
                out.append((code, "".join(cur)))
            cur, code = [], None
        elif c in CODES:
            code = c
        else:
            cur.append(chr(c))
    if cur:
        out.append((code, "".join(cur)))
    return out



# Описатели меню. Разбор формата — docs/mauimallard/engine.md.
MENUS = [
    (0x1FD440, u"главное меню"),
    (0x1FD46E, u"оно же с отладкой ($FF2180)"),
    (0x1FD4AA, u"настройки"),
]
SETTINGS = 0xFFFD78          # блок настроек: $FFFFFD78 + индекс


def _string(a):
    """Строка с нулём на конце -> (текст, адрес за нулём)."""
    s = a
    while ROM[a]:
        a += 1
    return "".join(chr(c) for c in ROM[s:a]), a + 1


def menu(at):
    """Описатель -> список пунктов.

    Формат читается из `$297514`: байт-счётчик, на пункт столбец, строка,
    ASCII с нулём и байт кода. Длины операндов взяты у четырёх
    обработчиков из таблицы `bra.w` с `$297578`.
    """
    a = at
    n = ROM[a]
    a += 1
    out = []
    for _k in range(n):
        row, col = ROM[a], ROM[a + 1]      # сначала СТРОКА, потом столбец
        a += 2
        text, a = _string(a)
        act = ROM[a]
        a += 1
        arg = {}
        if act == 0:                       # запустить процедуру
            a += a & 1                     # выровнять
            arg["proc"] = int.from_bytes(ROM[a:a + 4], "big")
            a += 4
        elif act == 1:                     # выбор из списка
            arg["setting"] = ROM[a]
            cnt = ROM[a + 1]
            a += 2
            arg["choices"] = []
            for _j in range(cnt):
                s, a = _string(a)
                arg["choices"].append(s)
        elif act == 2:                     # показать число
            arg["setting"] = ROM[a]
            a += 2
        elif act == 3:                     # число плюс процедура
            arg["setting"] = ROM[a]
            arg["proc"] = int.from_bytes(ROM[a + 2:a + 6], "big")
            a += 6
        out.append((col, row, text, act, arg))
    return out, a


def do_menus():
    for at, name in MENUS:
        items, end = menu(at)
        print(u"=== $%06X  %s  пунктов %d, конец $%06X"
              % (at, name, len(items), end))
        for col, row, text, act, arg in items:
            where = (u"по центру" if col & 0x80 else u"столбец %2d" % col)
            line = u"  строка %-2d %-11s %-12s код %d" % (
                row, where, text.strip(), act)
            if "setting" in arg:
                line += u"  настройка $%06X" % (SETTINGS + arg["setting"])
            if "proc" in arg:
                line += u"  -> $%06X" % arg["proc"]
            if "choices" in arg:
                line += u"  [%s]" % u", ".join(c.strip()
                                               for c in arg["choices"])
            print(line)
        print()

def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    rs = runs()
    if arg == "--menus":
        do_menus()
        return
    if arg == "--extent":
        lo = min(a for a, _b in rs)
        hi = max(b for _a, b in rs)
        print(u"блоков %d, с $%06X по $%06X, всего %d байт"
              % (len(rs), lo, hi, sum(b - a for a, b in rs)))
        for a, b in rs:
            print(u"  $%06X-$%06X  %4d" % (a, b, b - a))
        return
    total = 0
    for a, b in rs:
        ls = lines(a, b)
        total += len(ls)
        print(u"--- $%06X-$%06X" % (a, b))
        for code, t in ls:
            if arg == "--raw":
                print(u"  %s  %s" % ("%02X" % code if code else "..", t))
            else:
                print(u"  %s" % t)
    print()
    print(u"блоков %d, строк %d, байт %d"
          % (len(rs), total, sum(b - a for a, b in rs)))


if __name__ == "__main__":
    main()
