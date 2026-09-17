#!/usr/bin/env python3
"""Найти bin-сегменты, которые на самом деле содержат код.

    python tools/findcode.py

Зачем. Анализатор идёт по потоку управления от точек входа. Код, до
которого добираются только через указатель на функцию (`lea data_137(pc),a6`
и потом `jsr (a6)`) или в который входят с середины, он не находит и
размечает как данные. Такой код выпадает из дизассемблера целиком.

Как ищем. Считаем на чётных адресах плотность опкодов, которые почти не
встречаются в графике и таблицах: `rts`, `nop`, `jsr`/`jmp` с абсолютным
длинным адресом, `movem` в обе стороны, `link`/`unlk` и `lea (xxx).l,aN`.
Высокая плотность — повод посмотреть сегмент глазами.

Что делать с находкой. Поменять в game.yaml `type: bin` на `type: m68k`,
убрать строку `subdir`, пересобрать и СВЕРИТЬ ПОБАЙТОВО. Побайтовая
сверка здесь и есть проверка: если кусок на самом деле данные, ассемблер
не воспроизведёт их из декодированных инструкций. Часто сегмент оказывается
смесью — тогда его надо разрезать по адресу, с которого начинается
таблица, и хвост оставить данными.

Осторожно: таблицы переходов дают ложную тревогу. Например data_136 —
настоящая таблица самоотносительных слов (разбор в docs/game-ai.md), и
кодом она не является, хотя плотность у неё высокая.
"""
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

STRONG = {0x4E75, 0x4E71, 0x4EB9, 0x4EF9, 0x48E7, 0x4CDF, 0x4E5E, 0x4E56,
          0x41F9, 0x43F9, 0x45F9, 0x47F9, 0x49F9, 0x4BF9, 0x4DF9, 0x4FF9}
BRANCH = {0x6000, 0x6600, 0x6700, 0x6100}
LIMIT = 0x060000       # выше начинается графика, там искать бессмысленно
MIN_BYTES = 32
MIN_HITS = 3


def segments(path):
    cur = {}
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\s*-?\s*name:\s*(\S+)", line)
        if m:
            cur = {"name": m.group(1)}
        m = re.match(r"\s*type:\s*(\S+)", line)
        if m and cur:
            cur["type"] = m.group(1)
        m = re.match(r"\s*start:\s*0x([0-9A-Fa-f]+)", line)
        if m and cur:
            cur["start"] = int(m.group(1), 16)
        m = re.match(r"\s*end:\s*0x([0-9A-Fa-f]+)", line)
        if m and cur:
            cur["end"] = int(m.group(1), 16)
            yield cur
            cur = {}


def main():
    rom_path = os.path.join(HERE, "game.gen")
    if not os.path.exists(rom_path):
        print("[--] нет game.gen")
        return 1
    rom = open(rom_path, "rb").read()

    found = []
    for sg in segments(os.path.join(HERE, "game.yaml")):
        if sg.get("type") != "bin":
            continue
        s, e = sg["start"], sg["end"]
        if s >= LIMIT or e - s < MIN_BYTES:
            continue
        words = (e - s) // 2
        strong = branch = 0
        for a in range(s, e - 1, 2):
            w = struct.unpack_from(">H", rom, a)[0]
            if w in STRONG:
                strong += 1
            elif w in BRANCH:
                branch += 1
        if strong >= MIN_HITS:
            found.append((strong * 1000 // max(words, 1), strong, branch,
                          words, sg))

    found.sort(key=lambda r: (r[0], r[1]), reverse=True)
    if not found:
        print("подозрительных сегментов нет")
        return 0

    print("Сегменты с высокой плотностью опкодов — кандидаты в код.")
    print("Проверять глазами и обязательно сверять сборку побайтово.\n")
    print("  промилле  опкоды  ветвл.  слов   сегмент")
    for perm, strong, branch, words, sg in found:
        print("   %5d     %4d    %4d  %5d   %-14s $%06X-$%06X" % (
            perm, strong, branch, words, sg["name"], sg["start"], sg["end"]))
    print("\nвсего кандидатов: %d" % len(found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
