#!/usr/bin/env python3
"""Находит списки правил по приоритету — и у динозавров, и у ИИ игрока.

    make chains

Вся поведенческая логика этой игры написана одним приёмом: цепочка
подпрограмм, каждая возвращает «сделал» или «не сделал», и вызывающий
останавливается на первой сделавшей. В листинге это выглядит так:

    bsr.w   ПравилоА
    bne.w   выход
    bsr.w   ПравилоБ
    bne.w   выход
    ...

Поиск механический: подряд идущие пары `bsr.w` + `bne.w` с ОДНИМ И ТЕМ ЖЕ
адресом выхода. Три пары подряд уже не совпадение.

Так находится не только то, что разобрано в game-ai-behaviours.md, но и
цепочка компьютерного противника, которая до этого в документах не
упоминалась вовсе.
"""
import collections
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MIN_RULES = 3


def scan(path):
    """Цепочки одного листинга: (адрес начала, метка выхода, список правил)."""
    lines = [l.rstrip("\n") for l in open(path, encoding="utf-8", errors="replace")]
    out = []
    cur, exit_to, start = [], None, None

    def flush():
        if len(cur) >= MIN_RULES:
            out.append((start, exit_to, list(cur)))
        cur.clear()

    i = 0
    while i < len(lines):
        m = re.match(r"\s*bsr\.w\s+(\S+)", lines[i])
        if m:
            j = i + 1
            while j < len(lines) and lines[j].startswith(";"):
                j += 1
            m2 = re.match(r"\s*bne\.w\s+(\S+)", lines[j]) if j < len(lines) else None
            if m2 and (exit_to is None or exit_to == m2.group(1)):
                if not cur:
                    at = re.match(r";\s*\$([0-9A-F]{6})", lines[i - 1] if i else "")
                    start = at.group(1) if at else "??????"
                exit_to = m2.group(1)
                cur.append(m.group(1))
                i = j + 1
                continue
            flush()
            exit_to = None
        elif cur and lines[i].strip() and not lines[i].startswith(";"):
            flush()
            exit_to = None
        i += 1
    flush()
    return out


def main():
    rows = []
    for p in sorted(glob.glob(os.path.join(HERE, "out", "asm", "m68k", "*.asm"))):
        for start, _exit, rules in scan(p):
            rows.append((os.path.basename(p), start, rules))
    rows.sort(key=lambda r: (-len(r[2]), r[1]))
    print("Цепочек правил найдено: %d\n" % len(rows))
    print("| где | адрес | правил | порядок |")
    print("|---|---|---|---|")
    for f, start, rules in rows:
        print("| `%s` | `$%s` | %d | %s |"
              % (f, start, len(rules), ", ".join(rules)))
    print()
    cnt = collections.Counter(f for f, _, _ in rows)
    for f, n in cnt.most_common():
        print("%-18s %d цепочек" % (f, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
