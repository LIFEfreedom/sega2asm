#!/usr/bin/env python3
"""Печатает таблицу исключений 68000 с нашими именами.

    make vectors

Шестьдесят четыре длинных слова в самом начале картриджа. Половина из них
на Mega Drive не используется и указывает на общую заглушку, зато
остальные — это точки входа, до которых по ссылкам не добраться: их
вызывает процессор, а не код.

Уровни прерываний на Mega Drive расставлены так, что их легко перепутать:
**кадровое прерывание — уровень 6 (вектор 30), строчное — уровень 4
(вектор 28)**, а уровень 2 отдан внешнему входу с порта джойстика.
Наоборот не бывает, хотя интуиция подсказывает обратное.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NAMES = {
    0: "начальный SP", 1: "сброс", 2: "ошибка шины", 3: "ошибка адреса",
    4: "недопустимая команда", 5: "деление на ноль", 6: "CHK",
    7: "TRAPV", 8: "нарушение привилегий", 9: "трассировка",
    10: "line-A", 11: "line-F", 15: "необслуженное прерывание",
    24: "ложное прерывание", 25: "уровень 1", 26: "уровень 2, порт ввода",
    27: "уровень 3", 28: "уровень 4, СТРОЧНОЕ", 29: "уровень 5",
    30: "уровень 6, КАДРОВОЕ", 31: "уровень 7, NMI",
}
for i in range(16):
    NAMES[32 + i] = "TRAP #%d" % i


def symbols():
    out = {}
    path = os.path.join(HERE, "game_symbols.user.txt")
    for ln in open(path, encoding="utf-8"):
        m = re.match(r"(\S+)\s*=\s*\$([0-9A-F]{6})", ln)
        if m:
            out.setdefault(int(m.group(2), 16), m.group(1))
    return out


def main():
    rom = open(os.path.join(HERE, "game.gen"), "rb").read()
    sym = symbols()
    seen = {}
    for v in range(64):
        a = int.from_bytes(rom[v * 4:v * 4 + 4], "big")
        seen.setdefault(a, []).append(v)
    # Заглушка — тот адрес, на который смотрит больше всего векторов.
    stub = max(seen, key=lambda a: len(seen[a]))
    print("| адрес | имя | вектор |")
    print("|---|---|---|")
    for a in sorted(seen):
        vs = seen[a]
        if a == stub and len(vs) > 4:
            what = "заглушка неиспользуемых, %d векторов" % len(vs)
        else:
            what = ", ".join(NAMES.get(v, "вектор %d" % v) for v in vs)
        print("| `$%06X` | %s | %s |" % (a, sym.get(a, "—"), what))
    named = sum(1 for a in seen if a in sym)
    print()
    print("Различных обработчиков %d, из них названо %d."
          % (len(seen), named))
    return 0


if __name__ == "__main__":
    sys.exit(main())
