#!/usr/bin/env python3
"""Построить карту кода: что в каком банке ROM лежит.

    python tools/codemap.py [--out docs/code-map-table.md]

Классификация механическая, а не «на глаз»: для каждой инструкции
проверяется, упоминает ли она известную базу данных (массив юнитов, карты
местности, состояния игроков, буферы графики, меню), обращается ли к VDP
и является ли вызовом BIOS через line-F. Признаки суммируются по банкам
по 64 КБ.

Смысл в воспроизводимости: после правки game.yaml или добавления имён
цифры можно пересчитать и увидеть, где разбор продвинулся, а где нет.
Считаются и сырые адреса, и уже присвоенные имена, поэтому переименование
структуры не роняет её счётчик.
"""
import collections
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Подсистема -> по каким строкам её узнавать. Имена и сырые адреса вместе:
# в дизассемблере может стоять и то, и другое.
KEYS = {
    "юниты": ["FF5F4E", "FF60CE", "FF738E", "FF7B0E", "FF8DCE", "FF5F7E",
              "UnitRecords", "UnitSlots"],
    "карта": ["FF8FA0", "FFACEA", "FFD200", "UnitMap", "TerrainMap",
              "PlacementMap"],
    "игроки": ["Player1State", "Player2State", "CurrentPlayerPtr"],
    "состояние": ["GameState", "MainState"],
    "графбуфер": ["FFE45C", "FF1D64", "FF0D64", "FFF05C", "FFEE5C",
                  "GfxWorkBuffer"],
    "меню": ["FF4304", "FF4414", "FF432A", "FF434A", "FF436A", "FF4418"],
    "ввод": ["InputState", "FF0046"],
    "перепись": ["FFE086", "FFE042", "FFE043", "FFE044", "FFE045", "FFE046",
                 "PopulationCounts"],
    "параметры": ["UnitStatTable", "01FC5A", "UnitTypeTable", "01FAEE"],
}
TRAP = re.compile(r"^dc\.w\t\$FF[0-9A-F]{2}$")
ADDR = (re.compile(r"^; \$([0-9A-F]{6})$"),
        re.compile(r"^\S.*;\s*\$([0-9A-F]{6})$"),
        re.compile(r"^\torg\t\$([0-9A-F]{6})$"))


def instructions(asm_dir):
    """Выдать (адрес, текст) по всем файлам дизассемблера."""
    for fn in sorted(os.listdir(asm_dir)):
        addr = None
        path = os.path.join(asm_dir, fn)
        for raw in open(path, encoding="utf-8", errors="replace"):
            line = raw.rstrip("\n")
            for pat in ADDR:
                m = pat.match(line)
                if m:
                    addr = int(m.group(1), 16)
                    break
            else:
                if line.startswith("\t") and addr is not None:
                    yield addr, line.strip()
                    addr = None


def main():
    asm_dir = os.path.join(HERE, "out", "asm", "m68k")
    if not os.path.isdir(asm_dir):
        print("[--] нет out/asm/m68k — сначала `make split`")
        return 1

    bank = collections.defaultdict(collections.Counter)
    total = collections.Counter()
    for addr, text in instructions(asm_dir):
        b = addr >> 16
        total[b] += 1
        for name, keys in KEYS.items():
            if any(k in text for k in keys):
                bank[b][name] += 1
        if "VDP_" in text:
            bank[b]["VDP"] += 1
        if TRAP.match(text):
            bank[b]["трапы"] += 1

    cols = list(KEYS) + ["VDP", "трапы"]
    lines = ["| банк | инстр. | " + " | ".join(cols) + " |",
             "|" + "---|" * (len(cols) + 2)]
    for b in sorted(total):
        cells = " | ".join(str(bank[b].get(c, 0)) for c in cols)
        lines.append("| `$%02X0000` | %d | %s |" % (b, total[b], cells))
    table = "\n".join(lines)

    print("инструкций: %d в %d банках\n" % (sum(total.values()), len(total)))
    print(table)

    if "--out" in sys.argv:
        out = os.path.join(HERE, sys.argv[sys.argv.index("--out") + 1])
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write("# Карта кода: таблица признаков\n\n")
            f.write("Сгенерировано `tools/codemap.py`. Пояснения — в\n")
            f.write("[code-map.md](code-map.md).\n\n")
            f.write(table + "\n")
        print("\nзаписано: %s" % os.path.relpath(out, HERE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
