#!/usr/bin/env python3
"""Достаёт чужие эмуляторы, нужные для `make render`.

    make deps

Оба ядра в репозиторий НЕ кладутся: clownz80 под AGPLv3, Nuked-OPN2 под
LGPL 2.1, и втягивать их лицензии в этот проект незачем. Здесь только
команда загрузки; сами исходники живут в `third_party/`, который в
.gitignore, а собранный `build/render.exe` никуда не раздаётся — это
локальный инструмент разбора.

Почему именно эти два:

* **clownz80** — интерпретатор Z80 от Clownacy. Из него же сделан
  Z80-дизассемблер самого sega2asm, так что ядро проекту не чужое. Умеет
  ровно то, что нужно: считает такты каждой команды и реализует режим
  прерываний 1, а других драйвер и не использует.
* **Nuked-OPN2** — модель YM2612, снятая с кристалла. Писать свой FM
  синтезатор значило бы подменить железо своими допущениями; здесь
  считается тот же чип, что стоит в приставке.

SN76489 не качается: он прост настолько, что точная реализация короче
загрузки, и лежит прямо в `tools/render/render.c`. Но именно в нём и
нашлись обе ошибки цепочки — шум на октаву выше и уровень на 16 дБ выше
нужного, — так что «прост» не значит «сам собой верен». Обе поймались
сверкой с `psg.c` из Gens (github.com/lutris/gens); качать его для сборки
не нужно, сверка уже сделана.

Про лицензии стоит помнить вот что: AGPLv3 у clownz80 строже, чем LGPL, и
собранный `build/render.exe` — производная работа. Пока это локальный
инструмент разбора, вопроса нет; если однажды его понадобится кому-то
раздавать, ядро Z80 придётся либо заменить на разрешительное, либо
раздавать вместе с исходниками на условиях AGPL.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THIRD = os.path.join(HERE, "third_party")

REPOS = [
    ("clownz80", "https://github.com/Clownacy/clownz80", "AGPLv3"),
    ("clownz80/libraries/clowncommon",
     "https://github.com/Clownacy/clowncommon", "AGPLv3"),
    ("Nuked-OPN2", "https://github.com/nukeykt/Nuked-OPN2", "LGPL 2.1"),
]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main():
    os.makedirs(THIRD, exist_ok=True)
    for path, url, lic in REPOS:
        dest = os.path.join(THIRD, path.replace("/", os.sep))
        if os.path.isdir(dest) and os.listdir(dest):
            print("уже есть: third_party/%s" % path)
            continue
        print("загрузка %s (%s)" % (url, lic))
        r = subprocess.run(["git", "clone", "--depth", "1", url, dest])
        if r.returncode:
            return 1
    print()
    print("Готово. Дальше нужен компилятор C; на этой машине он ставился так:")
    print("    winget install BrechtSanders.WinLibs.POSIX.UCRT")
    print("и путь до его bin добавляется в PATH либо задаётся make render CC=...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
