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


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    rs = runs()
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
