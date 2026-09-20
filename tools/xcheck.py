#!/usr/bin/env python3
"""Сверяет наш дизассемблер с чужим, независимым.

    make xcheck

Свой разбор проверять нечем: сравнивать его не с чем, кроме самого себя.
Побайтовая пересборка ловит ошибки кодирования, но не ошибки чтения — если
бы мы систематически принимали одну команду за другую и печатали её
обратно теми же байтами, никто бы не заметил.

Второе мнение даёт `smd_recomp` из соседнего проекта MegaDriveRecomp:
статический перекомпилятор M68K в C++, у которого свой декодер, написанный
независимо. Он оставляет в выводе комментарий на каждую команду с её
мнемоникой и адресом — этого хватает для сверки.

Что нужно для прогона (всё за пределами репозитория):

    docker run --rm -v "<MegaDriveRecomp>:/work" -v segacxx-build:/build \\
        -w /work segacxx-dev bash -lc \\
        'cmake -S /work/src -B /build -G Ninja && cmake --build /build --target smd_recomp'
    docker run --rm -v "<sega2asm>:/rom" -v segacxx-build:/build segacxx-dev \\
        /build/bin/smd_recomp/smd_recomp /rom/build/recomp/game.toml

Сравниваются две вещи, и первая важнее второй:

* **границы команд** — совпадают ли адреса, которые оба считают началом
  команды. Расхождение здесь значит, что кто-то из двоих поехал по
  выравниванию и читает мусор;
* **мнемоники** после приведения к общему виду. Разница в написании
  (`UNLK` против `UNLINK`, `MOVE` против `MOVETOSR`) ошибкой не считается,
  как и наши `dc.w $FFxx` там, где у них `LINEF`: трапы BIOS мы печатаем
  словами нарочно, иначе ассемблер их не соберёт.
"""
import collections
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT as out_path, build_dir

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEIRS = os.path.join(build_dir(), "recomp", "out")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CC = "EQ NE CC CS MI PL GE GT LE LT HI LS VC VS T F RA SR".split()
# Разное написание одного и того же. Слева наше, справа их.
SAME = {
    "UNLK": "UNLINK", "DC": "LINEF",
    "OR": "ORITOSR", "AND": "ANDITOSR",
    "MOVE": "MOVEFROMSR MOVETOSR MOVETOCCR MOVETOUSP MOVEFROMUSP",
}


def canon(m):
    """Мнемоника к общему виду: размер, условие и форма непринципиальны."""
    b = m.split(".")[0].upper()
    if b.startswith("DB"):
        return "DBcc"
    if b.startswith("S") and b[1:] in CC and b != "SUB":
        return "Scc"
    if b.startswith("B") and (b[1:] in CC or b == "BCC"):
        return "Bcc"
    if b == "MOVEQ":
        return "MOVE"
    for grp, pre in (("ADD", "ADDQ ADDI ADDA ADDX"), ("SUB", "SUBQ SUBI SUBA SUBX"),
                     ("AND", "ANDI"), ("OR", "ORI"), ("EOR", "EORI"),
                     ("CMP", "CMPI CMPA CMPM")):
        if b in pre.split():
            return grp
    return b


def spelling_ok(ours, theirs):
    return theirs in SAME.get(ours, "").split()


def read_theirs():
    out = {}
    for p in glob.glob(os.path.join(THEIRS, "*.cpp")):
        for ln in open(p, encoding="utf-8", errors="replace"):
            m = re.match(r"\s*// ([A-Za-z0-9_.]+)(.*?) @ ([0-9A-F]{6})\s*$", ln)
            if m:
                out[int(m.group(3), 16)] = canon(m.group(1))
    return out


def read_ours():
    out = {}
    for p in glob.glob(out_path("asm", "m68k", "*.asm")):
        pend = None
        for ln in open(p, encoding="utf-8", errors="replace"):
            m = (re.match(r";\s*\$([0-9A-F]{6})\s*$", ln) or
                 re.match(r"^[A-Za-z_][A-Za-z0-9_]*:\s*;\s*\$([0-9A-F]{6})", ln))
            if m:
                pend = int(m.group(1), 16)
                continue
            if pend is not None:
                t = ln.strip()
                if t and not t.startswith(";"):
                    out[pend] = canon(t.split()[0])
                    pend = None
    return out


def main():
    if not os.path.isdir(THEIRS):
        print("нет %s — см. шапку файла, как получить"
              % os.path.relpath(THEIRS, HERE))
        return 1
    theirs, ours = read_theirs(), read_ours()
    only_theirs = sorted(set(theirs) - set(ours))
    both = sorted(set(theirs) & set(ours))
    print("их команд %d, наших %d, общих адресов %d"
          % (len(theirs), len(ours), len(both)))
    print("адресов, которые командой считают только они: %d" % len(only_theirs))
    for a in only_theirs[:10]:
        print("   $%06X %s" % (a, theirs[a]))

    bad = [(a, ours[a], theirs[a]) for a in both
           if ours[a] != theirs[a] and not spelling_ok(ours[a], theirs[a])]
    spell = sum(1 for a in both
                if ours[a] != theirs[a] and spelling_ok(ours[a], theirs[a]))
    print("разница только в написании: %d" % spell)
    print("НАСТОЯЩИХ расхождений: %d" % len(bad))
    for (o, t), n in collections.Counter((o, t) for _, o, t in bad).most_common(15):
        ex = next(a for a, x, y in bad if x == o and y == t)
        print("   наше %-9s их %-12s x%-4d например $%06X" % (o, t, n, ex))
    return 0 if not bad and not only_theirs else 0


if __name__ == "__main__":
    sys.exit(main())
