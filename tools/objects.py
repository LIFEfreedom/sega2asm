#!/usr/bin/env python3
"""Поведение каждого объекта Maui Mallard, а не только противников.

    python tools/objects.py             сводка по видам поведения
    python tools/objects.py --list      все процедуры обновления по частоте
    python tools/objects.py --show 2A4A7A   одна процедура: кто её носит и тело
    python tools/objects.py --level 5   что водится на уровне

Объект на карте описывается двумя вещами: конструктором (он ставит поля) и
**процедурой обновления `+$1E`** — она и есть поведение. Конструкторов 182,
а процедур обновления меньше сотни: у большинства объектов поведение общее,
а различаются они скриптом анимации.

Отпечаток считается по СВОЕМУ телу процедуры (обход из `tools/enemies.py`,
который отделяет своё от порождённого), и каждая черта — это конкретное
обращение, а не догадка: «движение» — запись в `+$16`/`+$18`, «игрок» —
чтение `$FFFFE1CA`/`$FFFFE1DC`, «урон» — достижимость ядра `loc_2A2C48`,
и так далее.

Имена в `NAMES` прочитаны глазами по телу процедуры; всё остальное в выводе
вычисляется. Где имени нет, стоит отпечаток — он беднее, но не выдуман.
"""
import bisect
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import enemies as E                                          # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BY, ADDRS = E.BY, E.ADDRS

# Черты: каждая — проверяемое обращение в теле процедуры.
TRAITS = (
    ("движение", re.compile(r"\$1[68]\(a0\)")),
    ("шаг", re.compile(r"loc_29A982|loc_29A6C8|loc_29A6A6")),
    ("земля", re.compile(r"loc_2919A2|loc_2AB4FC|loc_2AB514")),
    ("игрок", re.compile(r"FFFFE1CA|FFFFE1DC|FFFFE1DE|FF220C")),
    ("камера", re.compile(r"FFFFE1BC|FFFFE1BE|FFFFE130|FFFFE132")),
    ("порождает", re.compile(r"loc_29974C")),
    ("звук", re.compile(r"SoundStart")),
    ("автомат", re.compile(r"lea\s+\(\$1F[0-9A-F]{4}\)\.l,a\d")),
    ("программа", re.compile(r"\$48\(a0\)")),
    ("скрипт", re.compile(r"\$22\(a0\)")),
    ("уборка", re.compile(r"loc_29192A|ObjectReleaseCell|loc_2997B2")),
    ("смерть", re.compile(r"loc_299CF8")),
    ("экран", re.compile(r"loc_29AA6A")),
    ("таймер", re.compile(r"\$6\(a0\)")),
    ("предмет", re.compile(r"FF21FA|FF21F8")),
    ("касание", re.compile(r"\$42\(a1\)|\$44\(a1\)|\$43\(a0\)")),
)

# Прочитано глазами. Адрес -> (короткое имя, чем именно доказано).
NAMES = {
    0x2A4A7A: ("украшение: один `rts`",
               "тело — ровно одна команда, логики нет вообще"),
    0x2A4A8E: ("самоснятие по таймеру",
               "`tst.w $6(a0)` и, если взведён, `loc_2997B2` — снять объект"),
    0x2A4A9C: ("вернуть клетку по таймеру",
               "то же, но зовёт `ObjectReleaseCell`"),
    0x2A4862: ("проявиться по ходу уровня",
               "ждёт `$FF133E` в пределах `$0100`, потом ставит себе "
               "скрипт `$1D8A10` и становится украшением"),
    0x29A4D8: ("дождаться связи и исчезнуть",
               "ждёт `+$40`, потом отсчитывает `+$6` и уходит в `$2A4A9C`"),
    0x29EFBA: ("состояние из флага уровня",
               "копирует байт `$FF213E` в своё `+$4` и перезапускает кадр"),
    0x2A2746: ("ловушка на область",
               "сверяет игрока с прямоугольником `+$4C`/`+$4E`/`+$50`/`+$52` "
               "в клетках и при попадании уходит в `$2A278A`"),
    0x2A1804: ("метка высоты",
               "когда камера подойдёт, кладёт свой `+$14` в `$FF1390` "
               "и снимается"),
    0x2AAD52: ("такт бонусной игры",
               "считает `+$4C`, перезаряжает из `+$8`, меняет скрипт "
               "на `$1D97EE`"),
    0x2A44CE: ("источник со случайным шагом",
               "пауза `$30..$AF` от `loc_296B0C`, потом порождает "
               "на (x+8, y-8)"),
    0x29BABE: ("сам уходит от камеры",
               "окно `$30 x $18` клеток вокруг `$FFFFE130`/`$FFFFE132`, "
               "вне его — освободить VRAM и клетку"),
    0x2A20D6: ("качается и падает от удара",
               "ведёт `+$14` по `$1EAF94` с фазой в `+$8`; по `+$42` "
               "роняет себя и уходит в `$2A2150`"),
    0x29A58E: ("отметить слот порождения",
               "по `+$40` пишет 1 в `$FF1104[+$4C]` и становится украшением"),
    0x2A08DC: ("летает по коробке",
               "отражает `+$16`/`+$18` от границ `+$4C`/`+$4E` и "
               "`+$50`/`+$52`"),
    0x29C686: ("переключатель",
               "по состоянию пишет 1 в `$FFFFE1F2` и гасит `$FFFFE1D0`"),
    0x29F202: ("падает, когда толкнут",
               "по подсостоянию уходит в `loc_29A6A6`"),
    0x29A1C0: ("проседающая платформа",
               "сверяет себя с `$FFFFE20A` — тем, на чём стоит игрок, — "
               "и пружинит к `+$4C`"),
    0x29B6AC: ("генератор со счётом до трёх",
               "считает в `$FF1104` и на третьем выпускает бойца"),
    0x2A166A: ("генератор по таймеру",
               "крутит `+$6`, потом `loc_2A14E6`"),
    0x2A32AA: ("ходит по кругу",
               "фаза `+$4C` шагом 6 с заворотом на `$400`, из неё синус и "
               "косинус, оба на `+$50`/`+$52` — и в `+$12`, и в `+$14`"),
    0x29C6C2: ("выход с уровня",
               "по состоянию пишет 1 в `$FF1A6C` — сигнал выхода из кольца "
               "занятий"),
    0x29CD5A: ("показывает, жив ли другой",
               "смотрит `$FF1104[+$4C]` и переключает свой кадр по тому, "
               "занят слот порождения или нет"),
    0x29D672: ("рычаг, срабатывающий раз",
               "по `+$4C` даёт звук `$38`, перезапускает кадр и уходит "
               "в состояние 1"),
    0x29BDF8: ("вешает свой обработчик",
               "`lea (loc_29BE08).l,a6`, приоритет `$2000`, "
               "и `loc_296444`"),
    0x2A00F4: ("бонусный предмет, который дозревает",
               "считает `+$4C`, меняет скрипт `$1D9360` на `$1D9382`, "
               "потом по `+$6` выдаёт себя под звук `$9C`"),
    0x29F790: ("платформа, проседающая под весом",
               "если игрок стоит на ней (`$FFFFE20A` равно `a0`), состояние "
               "растёт, иначе падает; на пятом уходит в `loc_29A6A6`"),
    0x29FDC2: ("гаситель разбега",
               "ловит игрока в `$60` впереди по взгляду, обнуляет его "
               "`+$16` и делит `$FF04E4` пополам"),
    0x29D7A4: ("привязан к памяти порождения",
               "индексируется `$FF1104[+$29 * 2]` и включается по тому, "
               "занят слот или нет"),
    0x29DBBC: ("пускатель справа налево",
               "раз в 20 кадров шлёт объект со скриптом `$1DA23A` от "
               "(x+$A0, y+случайное), скорость `$0300`, цель в `+$4C`"),
    0x29F0F8: ("ловушка, взводящаяся на подходе",
               "игрок ближе `$80` по вертикали и правее на `$20` — "
               "переключить состояние и поднять бит 7 в `+$31`"),
    0x29EE70: ("источник по условию",
               "ждёт `loc_29EE4A`, потом 120 кадров паузы и порождает"),
    0x29E78A: ("генератор по расстоянию",
               "ждёт, пока игрок подойдёт ближе `$FFD0`, и выпускает "
               "объект с программой `$1FF2E2`"),
}


def fingerprint(upd):
    body = [a for a, al in E.walk(upd, 0) if not al]
    txt = " ".join(BY.get(a, "") for a in body)
    got = ["урон"] if upd in E.HITS else []
    got += [n for n, rx in TRAITS if rx.search(txt)]
    return got, len(body)


def kind(upds, fp):
    if upds == (0x2A4A7A,):
        return "украшение"
    if "урон" in fp:
        return "противник или разрушаемое"
    if set(upds) & gen_updates():
        return "генератор"
    if not fp:
        return "почти ничего не делает"
    if set(fp) <= {"таймер", "уборка", "скрипт", "экран", "камера"}:
        return "исчезает само"
    if "игрок" in fp and "движение" not in fp:
        return "триггер"
    if "движение" in fp or "шаг" in fp:
        return "движется"
    return "прочее"


def groups():
    cells, where = E.census()
    by = defaultdict(lambda: {"h": set(), "cells": 0, "codes": set(),
                              "levels": set()})
    none = {"h": set(), "cells": 0, "codes": set(), "levels": set()}
    for (c, h), n in cells.items():
        us = E.own_updates(h)
        g = by[tuple(sorted(us))] if us else none
        g["h"].add(h)
        g["cells"] += n
        g["codes"].add(c)
        g["levels"] |= where[(c, h)]
    rows = []
    for us, g in by.items():
        fp = sorted(set(sum((fingerprint(u)[0] for u in us), [])))
        rows.append({"upd": us, "fp": fp, "kind": kind(us, fp), **g})
    rows.sort(key=lambda r: -r["cells"])
    return rows, none, sum(cells.values())


GENS = None


def gen_updates():
    """Процедуры обновления генераторов — из `enemies.py --gen`."""
    global GENS
    if GENS is None:
        GENS = set()
        for r in E.generators():
            GENS |= E.own_updates(r["h"])
    return GENS


FOES = None


def foe_updates():
    """Процедуры видов из каталога противников: они описаны там."""
    global FOES
    if FOES is None:
        FOES = set()
        for row in E.collect()[0]:
            FOES |= row["p"]["upd"]
    return FOES


def name_of(r):
    for u in r["upd"]:
        if u in NAMES:
            return NAMES[u][0]
    if set(r["upd"]) & foe_updates():
        return "вид из каталога противников (enemy-catalog.md)"
    return None


def do_summary():
    rows, none, tot = groups()
    named = sum(r["cells"] for r in rows if name_of(r))
    print("объектов из клеток %d, конструкторов %d, процедур обновления %d"
          % (tot, sum(len(r["h"]) for r in rows) + len(none["h"]), len(rows)))
    print("прочитано глазами: %d объектов (%.0f %%)"
          % (named, 100.0 * named / tot))
    print()
    tally = defaultdict(lambda: [0, 0])
    for r in rows:
        t = tally[r["kind"]]
        t[0] += 1
        t[1] += r["cells"]
    for k, (n, c) in sorted(tally.items(), key=lambda kv: -kv[1][1]):
        print("   %-28s процедур %3d, объектов %5d (%.0f %%)"
              % (k, n, c, 100.0 * c / tot))
    if none["cells"]:
        print("   %-28s процедур   -, объектов %5d"
              % ("без своего обновления", none["cells"]))


def do_list():
    rows, none, tot = groups()
    acc = 0
    for r in rows:
        acc += r["cells"]
        nm = name_of(r)
        print("%5d %5.1f%%  %-22s к%-3d ур.%-13s %s"
              % (r["cells"], 100.0 * acc / tot,
                 ",".join("$%06X" % u for u in r["upd"])[:22], len(r["h"]),
                 ",".join(str(x) for x in sorted(r["levels"]))[:13],
                 nm or ("[%s] %s" % (r["kind"], ", ".join(r["fp"])))))


def do_show(at):
    rows, none, tot = groups()
    for r in rows:
        if at not in r["upd"]:
            continue
        print("процедура %s" % ",".join("$%06X" % u for u in r["upd"]))
        print("  объектов %d, конструкторов %d" % (r["cells"], len(r["h"])))
        print("  коды     %s" % E.fmt(sorted(r["codes"])))
        print("  уровни   %s" % E.fmt(sorted(r["levels"])))
        print("  вид      %s" % r["kind"])
        print("  черты    %s" % (", ".join(r["fp"]) or "—"))
        if at in NAMES:
            print("  прочитано: %s" % NAMES[at][0])
            print("     чем доказано: %s" % NAMES[at][1])
        print("  конструкторы: %s"
              % ", ".join("$%06X" % x for x in sorted(r["h"])))
        print()
        i = bisect.bisect_left(ADDRS, at)
        for k, a in enumerate(ADDRS[i:]):
            print("     $%06X  %s" % (a, BY[a]))
            if BY[a].startswith("rts") or k > 30:
                break
        return
    print("процедуры $%06X среди клеточных объектов нет" % at)


def do_level(n):
    import levels as L
    import struct
    rows, none, tot = groups()
    g = L.gfx(n)
    d, pr = g["map_data"], L.props(g)
    jump = E.U32(E.record(n) + 0x20)
    mw, mh = struct.unpack_from(">HH", d, 0)
    here = defaultdict(int)
    for cy in range(mh):
        for cx in range(mw):
            off = struct.unpack_from(">H", d, 4 + (cy * mw + cx) * 2)[0]
            c = pr[off // 8][2]
            if c:
                here[E.U32(jump + c * 4)] += 1
    mine = defaultdict(int)
    for r in rows:
        for h in r["h"]:
            if h in here:
                mine[tuple(r["upd"])] += here[h]
    print("уровень %d: объектов %d, поведений %d"
          % (n, sum(here.values()), len(mine)))
    lut = {tuple(r["upd"]): r for r in rows}
    for us, k in sorted(mine.items(), key=lambda kv: -kv[1]):
        r = lut[us]
        print("   %4d  %-22s %s"
              % (k, ",".join("$%06X" % u for u in us)[:22],
                 name_of(r) or ("[%s] %s" % (r["kind"], ", ".join(r["fp"])))))


def main():
    a = sys.argv[1:]
    if not a:
        do_summary()
    elif a[0] == "--list":
        do_list()
    elif a[0] == "--show" and len(a) > 1:
        do_show(int(a[1], 16))
    elif a[0] == "--level" and len(a) > 1:
        do_level(int(a[1]))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
