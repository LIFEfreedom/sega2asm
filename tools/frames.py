#!/usr/bin/env python3
"""Таблица кадров в начале картриджа (Maui Mallard).

    python tools/frames.py            сводка
    python tools/frames.py 0 1 2      разбор этих кадров
    python tools/frames.py --parts    вторая половина: сборные объекты
    python tools/frames.py --parts 20
    python tools/frames.py --sets     шесть наборов графики
    python tools/frames.py --descs    таблица описателей спрайта
    make frames FRAME=0

С `$000200` идут длинные слова-указатели. Каждый ведёт на **кадр**: и
список передач в VRAM, и раскладку спрайта разом — это одни и те же
десятибайтные записи, просто читают их две разные процедуры.

```
+0   слово: сколько кусков минус один
+2   слово: сколько коробок идёт следом за кусками
+4   четыре байта (кто читает — не найдено)
+8   на каждый кусок по десять байт:
       слово  — адрес описателя, короткий абсолютный ($3898-$3938)
       слово  — имя спрайта: палитра и приоритет (номер тайла всегда 0,
                база кадра прибавляется отдельно)
       байт   — смещение по горизонтали, со знаком
       байт   — смещение по вертикали, со знаком
       длинное слово — источник тайлов, СЛОВНЫЙ адрес (умножать на два)
     следом — коробки по десять байт: x0, x1, y0, y1, слово-номер, 4 байта
```

Кто читает:

* `$2960DE` — ставит передачи в очередь DMA (берёт +0 описателя, +8 длину);
* `$296208` — собирает таблицу спрайтов в `$FF050C` и шлёт её в VRAM
  `$F400` (берёт из описателя слово размера и ширину с высотой для
  отражений);
* `$2A028A` — достаёт коробку по номеру: две пары координат, уже
  сдвинутых на положение объекта и отражённых по его флагам;
* `$2A0306` — выбирает кадр по номеру от базы `$001080`, сверяет с `$C(a1)`
  и, если сменился, выделяет место в VRAM (`$290D9A`).

С `$002F00` таблица меняет смысл: там **сборные объекты** (`--parts`), а
первые шесть её записей — **наборы графики** (`--sets`), списки адресов
слотов таблицы кадров.
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
# С этого места таблица меняет смысл: сначала шесть наборов графики,
# дальше — сборные объекты.
PARTS = 0x002F00
TAB_END = 0x003898
# Описатели спрайта: шестнадцать записей по десять байт.
DESCS, DESCS_END = 0x003898, 0x003938
SETS = 6
U16 = lambda o: struct.unpack_from(">H", ROM, o)[0]
U32 = lambda o: struct.unpack_from(">I", ROM, o)[0]
S8 = lambda o: struct.unpack_from(">b", ROM, o)[0]
S16 = lambda o: struct.unpack_from(">h", ROM, o)[0]


def sext(v, bits):
    """Знаковое значение из `bits` младших бит."""
    top = 1 << (bits - 1)
    return v - (top << 1) if v & top else v


def parse(v):
    """-> [(описатель, имя, x, y, источник)] либо None, если это не кадр."""
    n = U16(v) + 1
    if not (1 <= n <= 64):
        return None
    out, a = [], v + 8
    for _ in range(n):
        d, s = U16(a), U32(a + 6)
        if not (DESCS <= d < DESCS_END) or not (0x1C00 <= s < len(ROM) // 2):
            return None
        out.append((d, U16(a + 2), S8(a + 4), S8(a + 5), s * 2))
        a += 10
    return out


def boxes(v, n):
    """Коробки идут сразу за кусками: по десять байт, номер в слове +4.

    Порядок полей взят из `$2A028A`: первые два байта правит бит 11 флагов
    объекта (отражение по горизонтали) и к ним прибавляется `$12(a0)` —
    значит это горизонталь; вторые два правит бит 12 и `$14(a0)`.
    """
    a = v + 8 + n * 10
    return [(S8(a + k * 10), S8(a + k * 10 + 1), S8(a + k * 10 + 2),
             S8(a + k * 10 + 3), U16(a + k * 10 + 4)) for k in range(U16(v + 2))]


def extent():
    """Сколько подряд идущих указателей разбираются как кадры."""
    i = 0
    while parse(U32(BASE + i * 4)) is not None:
        i += 1
    return i


def show(i):
    v = U32(BASE + i * 4)
    items = parse(v)
    print("кадр %d: указатель в $%06X -> $%06X" % (i, BASE + i * 4, v))
    if items is None:
        print("  на кадр не похоже: %s"
              % " ".join("%02X" % b for b in ROM[v:v + 16]))
        return
    print("  коробок %d, четыре нечитаемых байта: %s"
          % (U16(v + 2), " ".join("%02X" % b for b in ROM[v + 4:v + 8])))
    for d, w, x, y, s in items:
        print("    x %+4d  y %+4d  тайл +$%03X, палитра %d%s%s;"
              " размер %dx%d ($%04X), источник $%06X, %d слов"
              % (x, y, w & 0x7FF, (w >> 13) & 3,
                 ", отражён по горизонтали" if w & 0x0800 else "",
                 ", по вертикали" if w & 0x1000 else "",
                 U16(d + 2), U16(d + 4), d, s, U16(d + 8)))
    for x0, x1, y0, y1, num in boxes(v, len(items)):
        print("    коробка $%04X: x %+d..%+d, y %+d..%+d"
              % (num, x0, x1, y0, y1))


def summary():
    n = extent()
    print("таблица кадров $%06X, подряд разбирается %d записей "
          "(до $%06X)\n" % (BASE, n, BASE + n * 4))
    cnt = collections.Counter()
    src, box = [], 0
    for i in range(n):
        items = parse(U32(BASE + i * 4))
        cnt[len(items)] += 1
        box += U16(U32(BASE + i * 4) + 2)
        src += [s for _d, _w, _x, _y, s in items]
    print("кусков всего %d, в кадре их: %s"
          % (len(src), ", ".join("%d→%d" % kv for kv in sorted(cnt.items())[:8])))
    print("коробок всего %d" % box)
    print("источники: от $%06X до $%06X" % (min(src), max(src)))
    print("\nследом (запись %d) идут наборы графики и сборные объекты:"
          " --sets, --parts" % n)


def show_descs():
    print("описатели спрайта $%06X-$%06X, по десять байт:\n" % (DESCS, DESCS_END))
    print("  адрес  размер  ширина  высота  шаг VRAM  длина")
    for d in range(DESCS, DESCS_END, 10):
        print("  $%04X   $%04X   %5d   %5d     $%04X   %4d слов"
              % (d, U16(d), U16(d + 2), U16(d + 4), U16(d + 6), U16(d + 8)))


def show_sets():
    print("наборы графики: первые %d записей второй половины.\n"
          "Каждый — список адресов СЛОТОВ таблицы кадров; часть объекта\n"
          "выбирает из него по индексу. Кэшируются в ОЗУ с $FF0CE4,\n"
          "четыре набора по $C8 байт (`$296BA0`, `$296BEA`, `$296CB0`).\n"
          % SETS)
    for i in range(SETS):
        at = PARTS + i * 4
        v = U32(at)
        n = U16(v)
        print("  набор $%04X -> $%06X: %d кадров — %s"
              % (at, v, n, ", ".join("%d" % ((U16(v + 2 + k * 2) - BASE) // 4)
                                     for k in range(n))))


def parts(v):
    """Сборный объект: счётчик, набор графики, дальше по 4 байта на часть.

    Разбор вычитан из `$296D88`:

        слово A: биты 4-0   — номер кадра в наборе
                 биты 15-5  — смещение по горизонтали (арифметический сдвиг)
        слово B: биты 10-0  — смещение по вертикали, знаковое
                 бит 11     — отражение по горизонтали
                 бит 12     — отражение по вертикали
                 биты 14-13 — два флага, уходят в `$30` части
                 бит 15     — в данных не встречается

    Счётчик 0 — законная запись: частей нет, вся она занимает четыре байта.
    """
    n = U16(v)
    if n == 0:
        return []
    if not (1 <= n <= 64):
        return None
    out = []
    for k in range(n):
        a, b = U16(v + 4 + k * 4), U16(v + 6 + k * 4)
        out.append((a & 31, S16(v + 4 + k * 4) >> 5, sext(b & 0x7FF, 11), b >> 11))
    return out


def show_parts(i):
    at = PARTS + i * 4
    v = U32(at)
    items = parts(v)
    lk = U16(v + 2)
    print("сборный объект %d: указатель в $%06X -> $%06X, набор графики $%04X"
          % (i, at, v, lk))
    if items is None:
        print("  на сборный объект не похоже: %s"
              % " ".join("%02X" % b for b in ROM[v:v + 16]))
        return
    if not items:
        print("  частей нет, запись занимает четыре байта")
        return
    for idx, x, y, fl in items:
        print("    часть: кадр %2d набора,  x %+4d  y %+4d%s%s%s%s"
              % (idx, x, y,
                 ", отражена по горизонтали" if fl & 1 else "",
                 ", по вертикали" if fl & 2 else "",
                 ", флаг 13" if fl & 4 else "",
                 ", флаг 14" if fl & 8 else ""))


def parts_summary():
    n = (TAB_END - PARTS) // 4
    ptr = [U32(PARTS + i * 4) for i in range(n)]
    size = {PARTS + i * 4: U16(ptr[i]) for i in range(SETS)}
    cnt, links, bad, empty = collections.Counter(), collections.Counter(), 0, 0
    xs, ys, over = [], [], 0
    for i in range(SETS, n):
        items = parts(ptr[i])
        if items is None:
            bad += 1
            continue
        links[U16(ptr[i] + 2)] += 1
        if not items:
            empty += 1
            continue
        cnt[len(items)] += 1
        for idx, x, y, _fl in items:
            xs.append(x)
            ys.append(y)
            if idx >= size.get(U16(ptr[i] + 2), 32):
                over += 1
    print("вторая половина таблицы $%06X-$%06X: %d записей,\n"
          "из них %d наборов графики (--sets) и %d сборных объектов.\n"
          % (PARTS, TAB_END, n, SETS, n - SETS))
    print("сборные объекты: пустых %d, не разобралось %d" % (empty, bad))
    print("частей всего %d; в объекте их от %d до %d"
          % (len(xs), min(cnt), max(cnt)))
    print("ни один номер кадра не выходит за свой набор: %s"
          % ("да" if over == 0 else "НЕТ, %d раз" % over))
    print("смещения: x от %+d до %+d, y от %+d до %+d"
          % (min(xs), max(xs), min(ys), max(ys)))
    print("наборы: %s"
          % ", ".join("$%04X — %d раз (%d кадров)"
                      % (k, v, size[k]) for k, v in links.most_common()))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--descs" in sys.argv:
        show_descs()
        return 0
    if "--sets" in sys.argv:
        show_sets()
        return 0
    if "--parts" in sys.argv:
        if args:
            for a in args:
                show_parts(int(a, 0))
                print()
        else:
            parts_summary()
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
