#!/usr/bin/env python3
"""Что в картридже Maui Mallard уже разобрано, а что нет.

    python tools/coverage.py            сводка и непокрытые куски
    python tools/coverage.py --min 4096 только куски от 4 КБ
    python tools/coverage.py --raw      сырые тайлы в неразобранном
    python tools/coverage.py --raw 1    и нарисовать их в PNG
    make coverage

Каждый байт ROM помечается тем разбором, который его объясняет: запись
кадра, тайлы спрайта, сжатый блок уровня, код, звук. Что осталось без
метки — список того, до чего разбор ещё не дошёл. Это честный ответ на
вопрос «вся ли графика вытащена», а не впечатление.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import rom_bytes

import frames as F
import levels as L
import lzss

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM = rom_bytes()

# Банк кода: им ограничена последняя таблица обработчиков порождения.
CODE_START, CODE_END = 0x28D000, 0x2AC000


def build():
    """-> (карта меток, названия меток)."""
    mark = bytearray(len(ROM))
    names = {}

    def claim(a, b, tag):
        names[tag] = names.get(tag, tag)
        for i in range(max(0, a), min(len(ROM), b)):
            if not mark[i]:
                mark[i] = list(names).index(tag) + 1

    order = ["заголовок", "таблица кадров", "записи кадров", "тайлы спрайтов",
             "сборные объекты", "скрипты анимации", "таблицы уровней",
             "заставки уровней", "графика уровней", "код", "звук",
             "сырые тайлы", "палитры", "хвост $FF"]
    idx = {n: i + 1 for i, n in enumerate(order)}

    def put(a, b, n):
        t = idx[n]
        for i in range(max(0, a), min(len(ROM), b)):
            if not mark[i]:
                mark[i] = t

    put(0, 0x200, "заголовок")
    put(0x200, 0x3938, "таблица кадров")
    n = F.extent()
    for i in range(n):
        v = F.U32(F.BASE + i * 4)
        it = F.parse(v)
        put(v, v + 8 + len(it) * 10 + F.U16(v + 2) * 10, "записи кадров")
        for d, _w, _x, _y, s in it:
            put(s, s + F.U16(d + 8) * 2, "тайлы спрайтов")
    for i in range(F.SETS):
        v = F.U32(F.PARTS + i * 4)
        put(v, v + 2 + 2 * F.U16(v), "сборные объекты")
    for i in range(F.SETS, (F.TAB_END - F.PARTS) // 4):
        v = F.U32(F.PARTS + i * 4)
        put(v, v + 4 + 4 * F.U16(v), "сборные объекты")
    put(0x1D6D74, 0x1DD7BE, "скрипты анимации")
    put(0x1FBC50, 0x1FD8B0, "таблицы уровней")
    put(0x1FCF14, 0x1FD014, "таблицы уровней")   # свойства местности
    seen = set()
    for k in range(L.COUNT):
        g = L.gfx(k)
        for key in ("map", "meta", "tiles", "blk10", "bg"):
            a = g[key]
            if a in seen:
                continue
            seen.add(a)
            # Сжат блок или нет, говорят флаги в записи графики, а не
            # попытка распаковать: у несжатой таблицы первый бит потока
            # часто оказывается нулём с нулевым расстоянием, и распаковщик
            # «успешно» возвращает четыре байта.
            gr0 = L.U32(L.record(k) + 8)
            packed = {"map": L.U16(gr0) != 0, "meta": L.U16(gr0 + 2) != 0}
            if packed.get(key, True):
                u = lzss.unpack(a)[1]
            elif key == "meta":
                # четыре байта свойств на метатайл, восемь байт в таблице
                u = len(g["blk10_data"]) // 4 * 8
            else:
                u = len(g[key + "_data"])
            put(a, a + u, "графика уровней")
        # Таблиц обработчиков на мир ДВЕ, и лежат они встык: `+$20` и
        # `+$24`, причём вторая начинается ровно на 1020 байт позже первой.
        # Обе адресуются БАЙТОМ (`move.b d4,d0`, затем `*4`), то есть по 256
        # длинных слов. Раньше учитывалась только первая, и 1020 байт на мир
        # оставались без метки. Зажим по банку кода нужен последней паре:
        # без него она перелетает за `$28D000` на 146 байт.
        for off in (0x20, 0x24):
            sp = L.U32(L.record(k) + off)
            put(sp, min(sp + 256 * 4, CODE_START), "таблицы уровней")
        # профили земли: длину берём по самому дальнему смещению в свойствах
        prof = L.U32(L.record(k) + 4)
        far = max(w for w, _c, _s in L.props(g))
        put(prof, prof + far + 16, "таблицы уровней")
        gr = L.U32(L.record(k) + 8)
        extra = L.U32(gr + 0x1A)
        if extra:
            try:
                _d, u = lzss.unpack(extra)
                put(extra, extra + u, "графика уровней")
            except Exception:
                pass
    # списки заставок: по два на мир, скрипт и актёры
    for k in range(L.COUNT):
        at = L.U32(0x1FCC08 + k * 4)
        for a in range(at, at + 0x40, 2):
            w = L.U16(a)
            if w in (0x43F9, 0x45F9):
                v = L.U32(a + 2)
                put(v, v + 2 + L.U16(v) * (12 if w == 0x45F9 else 6),
                    "заставки уровней")
            if w == 0x4E75:
                break
    for a, b in raw_runs(mark):
        put(a, b, "сырые тайлы")
    import sprites as SP
    for a in SP.find_pals(8):
        if not mark[a]:
            put(a, a + 128, "палитры")
    put(CODE_START, CODE_END, "код")
    put(0x2F8000, 0x2F9000, "код")
    put(0x2ABADA, 0x2ABADA + 0x1862, "звук")
    put(0x2AD33C, 0x2F8BF2, "звук")
    put(0x2F9000, 0x300000, "хвост $FF")
    return mark, order


def raw_runs(mark, blk=0x200, least=0x400):
    """Непомеченные куски, похожие на сырые тайлы 4bpp.

    Признак грубый и честно назван «по виду»: доля байт с одинаковыми
    ниблами от 40% (две точки одного цвета подряд — обычное дело в
    пиксельной графике) при доле нулей меньше 85%, иначе в сеть попадает
    пустая набивка.
    """
    runs, s = [], None
    for a in range(0, len(ROM) - blk, blk):
        d = ROM[a:a + blk]
        same = sum(1 for x in d if (x >> 4) == (x & 15)) / float(len(d))
        zero = sum(1 for x in d if x == 0) / float(len(d))
        ok = mark[a] == 0 and same >= 0.40 and zero < 0.85
        if ok and s is None:
            s = a
        elif not ok and s is not None:
            if a - s >= least:
                runs.append((s, a))
            s = None
    return runs


def main():
    if "--raw" in sys.argv:
        mark, _ = build()
        draw = len(sys.argv) > sys.argv.index("--raw") + 1
        # метки уже проставлены, поэтому ищем по «чистой» карте
        m2 = bytearray(len(ROM))
        for i, v in enumerate(mark):
            m2[i] = 0 if v == list(range(1))[0] else v
        runs = [(a, b) for a, b in raw_runs(bytearray(len(ROM)))
                if all(mark[i] in (0, 12) for i in range(a, b, 0x200))]
        print("сырые тайлы в неразобранном: %d кусков" % len(runs))
        for a, b in runs:
            print("  $%06X-$%06X  %6d байт, %4d тайлов" % (a, b, b - a, (b - a) // 32))
            if draw:
                os.system('%s "%s" %06X %d' % (sys.executable,
                          os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "tileprobe.py"), a, (b - a) // 32))
        return 0
    mn = 0x800
    if "--min" in sys.argv:
        mn = int(sys.argv[sys.argv.index("--min") + 1], 0)
    mark, order = build()
    c = collections.Counter(mark)
    print("картридж %d байт, разбор покрывает:\n" % len(ROM))
    for i, name in enumerate(order):
        k = c.get(i + 1, 0)
        if k:
            print("  %-18s %8d  %5.1f%%" % (name, k, 100.0 * k / len(ROM)))
    left = c.get(0, 0)
    print("  %-18s %8d  %5.1f%%" % ("НЕ РАЗОБРАНО", left, 100.0 * left / len(ROM)))
    runs, s = [], None
    for i in range(len(ROM) + 1):
        m = mark[i] if i < len(ROM) else 1
        if m == 0 and s is None:
            s = i
        elif m and s is not None:
            if i - s >= mn:
                runs.append((s, i))
            s = None
    print("\nкуски без разбора от %d байт: %d" % (mn, len(runs)))
    for a, b in runs:
        print("  $%06X-$%06X  %7d" % (a, b, b - a))
    return 0


if __name__ == "__main__":
    sys.exit(main())
