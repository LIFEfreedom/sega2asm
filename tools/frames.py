#!/usr/bin/env python3
"""Таблица кадров в начале картриджа (Maui Mallard).

    python tools/frames.py            сводка
    python tools/frames.py 0 1 2      разбор этих кадров
    python tools/frames.py --pieces   вторая половина: раскладки спрайта
    python tools/frames.py --pieces 131
    make frames FRAME=0

С `$000200` идут длинные слова-указатели. Каждый ведёт на **список
передач**: как затащить тайлы этого кадра в VRAM. Формат списка вычитан из
`$2960DE` — процедуры, которая его исполняет:

```
+0   слово: сколько передач минус одна
+2   шесть байт заголовка (в разборе не участвуют)
+8   на каждую передачу по десять байт:
       слово  — адрес описателя (там +$6 шаг в VRAM, +$8 длина)
       4 байта
       длинное слово — источник, СЛОВНЫЙ адрес (умножать на два)
```

Читает таблицу `$2A0306`: берёт указатель по номеру от базы `$001080`,
сверяет с тем, что уже стоит у объекта в `+$C`, и если кадр сменился —
выделяет место в VRAM (`$290D9A`) и ставит передачи в очередь.
"""
import collections
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import rom_bytes

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM = rom_bytes()
BASE = int(os.environ.get("MM_FRAME_TABLE", "000200"), 16)
# С этого места таблица меняет смысл: дальше не списки передач, а
# раскладки — из каких кусков сложить спрайт на экране.
PIECES = 0x002F00
TAB_END = 0x003898
U16 = lambda o: struct.unpack_from(">H", ROM, o)[0]
U32 = lambda o: struct.unpack_from(">I", ROM, o)[0]


def parse(v):
    """-> [(описатель, источник в байтах)] либо None, если это не список."""
    n = U16(v) + 1
    if not (1 <= n <= 64):
        return None
    out, a = [], v + 8
    for _ in range(n):
        d, s = U16(a), U32(a + 6)
        if not (0x3898 <= d < 0x4000) or not (0x1C00 <= s < len(ROM) // 2):
            return None
        out.append((d, s * 2))
        a += 10
    return out


def extent():
    """Сколько подряд идущих указателей разбираются как списки передач."""
    i = 0
    while parse(U32(BASE + i * 4)) is not None:
        i += 1
    return i


def show(i):
    v = U32(BASE + i * 4)
    items = parse(v)
    print("кадр %d: указатель в $%06X -> $%06X" % (i, BASE + i * 4, v))
    if items is None:
        print("  на список передач не похоже: %s"
              % " ".join("%02X" % b for b in ROM[v:v + 16]))
        return
    print("  заголовок: %s" % " ".join("%02X" % b for b in ROM[v + 2:v + 8]))
    for d, s in items:
        print("    источник $%06X, длина %d слов, шаг в VRAM $%04X (описатель $%04X)"
              % (s, U16(d + 8), U16(d + 6), d))


def summary():
    n = extent()
    print("таблица кадров $%06X, подряд разбирается %d записей "
          "(до $%06X)\n" % (BASE, n, BASE + n * 4))
    cnt = collections.Counter()
    src = []
    for i in range(n):
        items = parse(U32(BASE + i * 4))
        cnt[len(items)] += 1
        src += [s for _d, s in items]
    print("передач всего %d, в кадре их: %s"
          % (len(src), ", ".join("%d→%d" % kv for kv in sorted(cnt.items())[:8])))
    print("источники: от $%06X до $%06X" % (min(src), max(src)))
    nxt = U32(BASE + n * 4)
    print("\nследом (запись %d) идёт уже другое — $%06X: %s"
          % (n, nxt, " ".join("%02X" % b for b in ROM[nxt:nxt + 16])))
    print("похоже на список адресов внутри самой таблицы кадров")


def pieces(v):
    """Раскладка: слово «сколько кусков», слово-ссылка, дальше по 4 байта."""
    n = U16(v)
    if not (1 <= n <= 64):
        return None
    out = []
    for k in range(n):
        o = v + 4 + k * 4
        y = struct.unpack_from(">b", ROM, o)[0]
        x = struct.unpack_from(">b", ROM, o + 1)[0]
        out.append((y, x, U16(o + 2)))
    return out


def show_pieces(i):
    at = PIECES + i * 4
    v = U32(at)
    items = pieces(v)
    print("раскладка %d: указатель в $%06X -> $%06X, ссылка $%04X"
          % (i, at, v, U16(v + 2)))
    if items is None:
        print("  на раскладку не похоже: %s"
              % " ".join("%02X" % b for b in ROM[v:v + 16]))
        return
    for y, x, w in items:
        print("    y %+4d  x %+4d  тайл $%03X, ряд палитры %d%s%s"
              % (y, x, w & 0x7FF, (w >> 13) & 3,
                 ", отражён по горизонтали" if w & 0x0800 else "",
                 ", по вертикали" if w & 0x1000 else ""))


def pieces_summary():
    n = (TAB_END - PIECES) // 4
    cnt = collections.Counter()
    bad = 0
    names = []
    for i in range(n):
        items = pieces(U32(PIECES + i * 4))
        if items is None:
            bad += 1
            continue
        cnt[len(items)] += 1
        names += [w for _y, _x, w in items]
    print("раскладок %d (с $%06X по $%06X), не разобралось %d"
          % (n, PIECES, TAB_END, bad))
    print("кусков всего %d; в раскладке их от %d до %d"
          % (len(names), min(cnt), max(cnt)))
    print("ни одного слова с битом 15 и ни одного номера тайла >= $800: %s"
          % ("да" if not any(w & 0x8000 or (w & 0x7FF) >= 0x800 for w in names)
             else "НЕТ"))
    rows = collections.Counter((w >> 13) & 3 for w in names)
    print("ряды палитры: %s" % dict(sorted(rows.items())))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--pieces" in sys.argv:
        if args:
            for a in args:
                show_pieces(int(a, 0))
                print()
        else:
            pieces_summary()
        return 0
    if not args:
        summary()
        return 0
    for a in args:
        show(int(a, 0))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
