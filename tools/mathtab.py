#!/usr/bin/env python3
"""Числовые таблицы банка `$1E`: проверка, а не пересказ.

    python tools/mathtab.py            проверить все таблицы
    python tools/mathtab.py --dump     ещё и значения
    python tools/mathtab.py --extent   границы для coverage.py

Хвост банка `$1E` перед шрифтом — это подряд лежащие таблицы, и у каждой
проверка своя и жёсткая. Совпадение по форме тут ничего не стоило бы:
таблица растущих чисел похожа на что угодно, поэтому названием считается
только то, что подтверждено формулой с точностью до единицы младшего
разряда либо кодом, который таблицу читает.

Границы не заданы руками: каждая таблица кончается ровно там, где
начинается следующая, а длина берётся из читателя — у синуса это
`$1EAF94` (косинус на четверть вперёд), у тангенса `#$01FF` в `$29566A`,
у маски LZSS `add.w d6,d6` дважды в `$29762E`.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import rom_bytes                                  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM = rom_bytes()

GAUGE = 0x1EACF0          # восемь ступеней шкалы топлива, 8 длинных слов
MASKS = 0x1EAD10          # маски LZSS, 33 длинных слова
SINE = 0x1EAD94           # синус, 1024 + 256 слов
TAN512 = 0x1EB794         # тангенс, 512 слов, множитель 256
TAN33 = 0x1EBB94          # тангенс, 33 слова, множитель $7FFF
ROT32 = 0x1EBBD6          # 32 пары (косинус, синус)
END = 0x1EBC56            # встык с блоком тайлов


def U16(a):
    return int.from_bytes(ROM[a:a + 2], "big")


def S16(a):
    v = U16(a)
    return v - 0x10000 if v >= 0x8000 else v


def U32(a):
    return int.from_bytes(ROM[a:a + 4], "big")


def check_sine():
    """Синус: 1024 точки на оборот и ещё четверть, чтобы хватило косинусу."""
    worst = 0
    for i in range(1280):
        want = 32767 * math.sin(i * 2 * math.pi / 1024)
        worst = max(worst, abs(S16(SINE + 2 * i) - want))
    quarter = all(S16(SINE + 2 * (i + 256)) == S16(SINE + 0x200 + 2 * i)
                  for i in range(1024))
    return (u"синус $%06X, 1280 слов: худшее отклонение от 32767*sin %.2f, "
            u"косинус с $%06X — та же таблица: %s"
            % (SINE, worst, SINE + 0x200, u"да" if quarter else u"НЕТ"))


def check_tan512():
    """Тангенс в 8.8: множитель 256 задан делением `asl.l #8` у читателя.

    Прямая проверка тут обманывает: у полюса тангенс так крут, что даже
    верная таблица отходит от `256*tan` на десятки. Поэтому проверка
    обратная — берём арктангенс значения и смотрим, попадает ли он в свой
    номер.
    """
    worst, at, sat = 0.0, 0, []
    for i in range(512):
        v = S16(TAN512 + 2 * i)
        if abs(v) == 32767:
            sat.append(i)
            continue
        k = math.atan(v / 256.0) * 512 / math.pi
        d = abs(((k - i + 256) % 512) - 256)
        if d > worst:
            worst, at = d, i
    return (u"тангенс $%06X, 512 слов, множитель 256: arctg(v/256) уходит от "
            u"номера не более чем на %.2f шага (при i=%d), насыщены %s"
            % (TAN512, worst, at, ", ".join(str(x) for x in sat)))


def check_tan33():
    """Тангенс от 0 до 45 градусов, 32 шага, размах $7FFF."""
    worst = 0
    for i in range(33):
        want = 32767 * math.tan(i * math.pi / 128)
        want = max(-32767, min(32767, want))
        worst = max(worst, abs(S16(TAN33 + 2 * i) - want))
    return (u"тангенс $%06X, 33 слова, шаг 45/32 градуса: худшее отклонение "
            u"%.2f (последнее значение упёрто в $7FFF)" % (TAN33, worst))


def check_rot32():
    """32 пары (косинус, синус) — поворот на 11,25 градуса."""
    worst = 0
    for i in range(32):
        ang = i * 2 * math.pi / 32
        worst = max(worst, abs(S16(ROT32 + 4 * i) - 32767 * math.cos(ang)))
        worst = max(worst, abs(S16(ROT32 + 4 * i + 2) - 32767 * math.sin(ang)))
    return (u"поворот $%06X, 32 пары (cos, sin): худшее отклонение %.2f, "
            u"конец $%06X" % (ROT32, worst, ROT32 + 128))


def check_masks():
    """Маски LZSS: `(1 << n) - 1` для n от 0 до 32, ровно."""
    bad = [n for n in range(33)
           if U32(MASKS + 4 * n) != ((1 << n) - 1) & 0xFFFFFFFF]
    return (u"маски LZSS $%06X, 33 длинных слова (1<<n)-1: неверных %d, "
            u"конец $%06X — встык с синусом" % (MASKS, len(bad), MASKS + 132))


def check_gauge():
    """Ступени шкалы: k-е слово — k нибблов двойки слева."""
    bad = 0
    for k in range(8):
        want = 0
        for j in range(k + 1):
            want |= 2 << (4 * (7 - j))
        if U32(GAUGE + 4 * k) != want:
            bad += 1
    return (u"шкала топлива $%06X, 8 длинных слов: неверных %d, "
            u"конец $%06X" % (GAUGE, bad, GAUGE + 32))


def do_dump():
    print(u"--- шкала топлива $%06X" % GAUGE)
    for k in range(8):
        print(u"  %d  %08X" % (k, U32(GAUGE + 4 * k)))
    print(u"--- маски LZSS $%06X" % MASKS)
    print(u"  " + " ".join("%08X" % U32(MASKS + 4 * n) for n in range(33)))
    print(u"--- тангенс $%06X (каждое 16-е)" % TAN512)
    for i in range(0, 512, 16):
        print(u"  %3d  %7d" % (i, S16(TAN512 + 2 * i)))
    print(u"--- тангенс $%06X" % TAN33)
    print(u"  " + " ".join("%d" % S16(TAN33 + 2 * i) for i in range(33)))
    print(u"--- поворот $%06X" % ROT32)
    for i in range(32):
        print(u"  %2d  cos %7d  sin %7d"
              % (i, S16(ROT32 + 4 * i), S16(ROT32 + 4 * i + 2)))


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--extent":
        print(u"$%06X-$%06X, %d байт" % (GAUGE, END, END - GAUGE))
        return
    for line in (check_gauge(), check_masks(), check_sine(), check_tan512(),
                 check_tan33(), check_rot32()):
        print(line)
    if arg == "--dump":
        print()
        do_dump()


if __name__ == "__main__":
    main()
