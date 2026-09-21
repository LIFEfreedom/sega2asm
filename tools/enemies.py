#!/usr/bin/env python3
"""Каталог противников Maui Mallard: кто, где водится, чем описан.

    python tools/enemies.py              сводка
    python tools/enemies.py --list       каталог: строка на вид
    python tools/enemies.py --show 160   один вид подробно
    python tools/enemies.py --sheet      листы кадров по всем видам
    python tools/enemies.py --sheet 160  лист одного вида
    python tools/enemies.py --contact    общий лист: по кадру на вид
    python tools/enemies.py --gen        генераторы: клетка ставит выпускателя
    python tools/enemies.py --code       кого заводит код, а не клетка
    python tools/enemies.py --who        откуда «кодовые» берутся в уровне
    python tools/enemies.py --level 6    кто водится на уровне

Отдельного списка противников в картридже нет: противник — обычный объект
из клетки карты. Признак ровно один и он проверяемый: **процедура
обновления объекта дотягивается до ядра урона `loc_2A2C48`**, то есть
объект умеет принимать удар и терять жизни.

Как считается достижимость. Строится граф по КАЖДОЙ команде банка
`$28D000`-`$2AC000`: у `bsr`/`jsr` две дуги (цель и возврат), у `bra`/`jmp`
одна, у условного перехода две, `rts` обрывает. Отдельно добавлены дуги
через данные: `lea ($1Fxxxx).l,aN` — это срез состояний или цепочка
обработчиков, и все длинные слова оттуда, попадающие в банк кода, тоже
дуги. Конструктор связан со своей процедурой обновления дугой
«`move.l #adr,$1E(a0)`».

Почему поля берутся не по всему обходу. Конструктор часто сам кого-нибудь
порождает, и после `jsr loc_29974C` регистр `a0` указывает уже НА ЧУЖОЙ
объект — всё, что записано дальше, принадлежит порождённому, а не виду.
Поэтому обход несёт флаг «мы внутри чужого объекта»: он взводится вызовом
`loc_29974C` и снимается восстановлением `a0` (`movea.w a1,a0` или
`movem` со стека). Поля вида собираются только при снятом флаге.

Кадры берутся не по общему обходу, а по трём вещам, которые принадлежат
виду по построению: скрипт при рождении, лесенка его программы `+$48` и
скрипты обработчиков из его срезов состояний. Общий обход для этого не
годится — в него затекают чужие скрипты (одна только `$299D5E` ставит
всем подряд облачко на смерть). Рисует tools/sprites.py.

Палитра кадру не положена (см. tools/sprites.py): берётся палитра первого
уровня, где вид водится. Цвета поэтому — догадка, а формы — нет.
"""
import bisect
import os
import re
import struct
import sys
from collections import defaultdict, deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT as out_path                            # noqa: E402
from paths import asm_dir, rom_bytes                         # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM = rom_bytes()
U16 = lambda a: struct.unpack_from(">H", ROM, a)[0]           # noqa: E731
U32 = lambda a: struct.unpack_from(">I", ROM, a)[0]           # noqa: E731

CODE = (0x28D000, 0x2AC000)         # банк обработчиков порождения
CORE = 0x2A2C48                     # ядро урона
SPAWN = "loc_29974C"                # завести объект: a0 становится чужим
LEVELS = 23

# ---------------------------------------------------------------- разбор

A_C = re.compile(r"^; \$([0-9A-F]{6})\s*$")
A_L = re.compile(r"^\w+:\s*;\s*\$([0-9A-F]{6})")


def load_asm():
    d = asm_dir()
    by_addr = {}
    if not os.path.isdir(d):
        sys.exit("нет разобранного кода: %s (сделайте `make split`)" % d)
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".asm"):
            continue
        cur = None
        for ln in open(os.path.join(d, fn), encoding="utf-8",
                       errors="replace"):
            s = ln.rstrip()
            m = A_C.match(s.strip())
            if m:
                cur = int(m.group(1), 16)
                continue
            m = A_L.match(s)
            if m:
                cur = int(m.group(1), 16)
            t = s.strip()
            if (t and not t.startswith(";") and cur is not None
                    and not re.match(r"^\w+:", t)):
                by_addr.setdefault(cur, re.sub(r"\s+", " ", t))
    return by_addr


BY = load_asm()
ADDRS = sorted(BY)
NEXT = dict(zip(ADDRS, ADDRS[1:]))

TARGET = re.compile(r"(?:loc_|\$00|\$)([0-9A-F]{6})")
BSR = re.compile(r"^(?:bsr|jsr)\b")
BRA = re.compile(r"^(?:bra|jmp)\b")
BCC = re.compile(r"^(?:b(?:hi|ls|cc|cs|ne|eq|vc|vs|pl|mi|ge|lt|gt|le)\b|db)")
END = re.compile(r"^(?:rts|rte|rtr)\b")
TBL = re.compile(r"lea\s+\(\$(1[EF][0-9A-F]{4})\)\.l,a\d")
UPD = re.compile(r"move\.l\s+#\$00([0-9A-F]{6}),\$1E\(a0\)")
RESTORE = re.compile(r"movea\.w\s+a\d,a0|movem\.[wl]\s+\(a7\)\+,.*\ba0\b")


def table_longs(base, cap=32):
    """Срез состояний или цепочка: длинные слова, пока они в банке кода.

    Цепочка начинается словом-счётчиком, срез — сразу указателем, поэтому
    пробуются оба начала и берётся то, что длиннее.
    """
    best = []
    for start in (base, base + 2):
        got = []
        for s in range(cap):
            v = U32(start + s * 4)
            if not (CODE[0] <= v < CODE[1]):
                break
            got.append(v)
        if len(got) > len(best):
            best = got
    return best


def build_graph():
    fwd = defaultdict(set)
    for a in ADDRS:
        t = BY[a]
        n = NEXT.get(a)
        if BSR.match(t):
            m = TARGET.search(t)
            if m:
                fwd[a].add(int(m.group(1), 16))
            if n:
                fwd[a].add(n)
        elif BRA.match(t):
            m = TARGET.search(t)
            if m:
                fwd[a].add(int(m.group(1), 16))
        elif BCC.match(t):
            m = TARGET.search(t)
            if m:
                fwd[a].add(int(m.group(1), 16))
            if n:
                fwd[a].add(n)
        elif END.match(t):
            pass
        elif n:
            fwd[a].add(n)
        m = TBL.search(t)
        if m:
            for v in table_longs(int(m.group(1), 16)):
                fwd[a].add(v)
    return fwd


FWD = build_graph()


def walk(at, thr, cap=60000):
    """Обход, считающий порождения вдоль пути. Отдаёт (адрес, чужой?).

    `thr` — сколько вызовов `loc_29974C` ещё «свои». У конструктора это 1:
    первым вызовом он заводит СЕБЯ, и `a0` после него — наш объект. У
    процедуры обновления это 0: объект уже существует, и любое порождение
    подменяет `a0` чужим.
    """
    seen, q = set(), deque([(at, 0)])
    out = set()
    while q and len(seen) < cap:
        cur, k = q.popleft()
        if (cur, k) in seen or not (CODE[0] <= cur < CODE[1]):
            continue
        seen.add((cur, k))
        out.add((cur, k > thr))
        t = BY.get(cur, "")
        after = k
        if SPAWN in t and BSR.match(t):
            after = min(k + 1, thr + 1)
        elif RESTORE.search(t) and k:
            after = k - 1
        for b in FWD.get(cur, ()):
            # подмена `a0` живёт только в продолжении, не в теле вызова
            q.append((b, after if b == NEXT.get(cur) else k))
    return out


UPD_REG = re.compile(r"move\.l\s+d(\d),\$1E\(a0\)")
IMM_REG = re.compile(r"move\.l\s+#\$00([0-9A-F]{6}),d(\d)")


def own_updates(h):
    """Процедуры обновления, которые конструктор ставит СВОЕМУ объекту.

    Половина конструкторов пишет `+$1E` непосредственным операндом, другая
    половина кладёт адрес в регистр (`move.l #adr,d7`) и ставит уже оттуда:
    так сделаны семейства, где несколько кодов порождения делят один
    хвост. Оба случая собираются по одному обходу.
    """
    out, regs, via = set(), defaultdict(set), set()
    for a, alien in walk(h, 1):
        if alien:
            continue
        t = BY.get(a, "")
        m = UPD.search(t)
        if m:
            v = int(m.group(1), 16)
            if CODE[0] <= v < CODE[1]:
                out.add(v)
        m = IMM_REG.search(t)
        if m:
            v = int(m.group(1), 16)
            if CODE[0] <= v < CODE[1]:
                regs[m.group(2)].add(v)
        m = UPD_REG.search(t)
        if m:
            via.add(m.group(1))
    for r in via:
        out |= regs.get(r, set())
    return out


def species_body(h):
    """Всё поведение вида: конструктор плюс его процедуры обновления."""
    got = set(walk(h, 1))
    for u in own_updates(h):
        got |= walk(u, 0)
    return got


# ---------------------------------------------------------------- признак

def damage_takers():
    """Команды, из которых достижимо ядро урона (обратный обход)."""
    rev = defaultdict(set)
    for a, s in FWD.items():
        for b in s:
            rev[b].add(a)
    hit, q = set(), deque([CORE])
    while q:
        cur = q.popleft()
        for p in rev.get(cur, ()):
            if p not in hit:
                hit.add(p)
                q.append(p)
    return hit


HITS = damage_takers()

# ---------------------------------------------------------------- перепись

HP = re.compile(r"move\.w\s+#\$([0-9A-F]+),\$1C\(a0\)")
DMG = re.compile(r"move\.b\s+#\$([0-9A-F]+),\$43\(a0\)")
SCR = re.compile(r"move\.l\s+#\$00([0-9A-F]{6}),\$22\(a0\)")
PROG = re.compile(r"move\.l\s+#\$00([0-9A-F]{6}),\$48\(a0\)")
SND = re.compile(r"pea\s+\(\$0000([0-9A-F]{2})\)\.w")
D12 = re.compile(r"(?:moveq\s+#(-?\d+)|move\.w\s+#\$([0-9A-F]+)),d([12])$")


def record(n):
    import levels as L
    return L.record(n)


def census():
    """Клетки всех 23 уровней: (код, конструктор) -> сколько и где."""
    import levels as L
    cells, where = defaultdict(int), defaultdict(set)
    for n in range(LEVELS):
        g = L.gfx(n)
        d, pr = g["map_data"], L.props(g)
        jump = U32(record(n) + 0x20)
        mw, mh = struct.unpack_from(">HH", d, 0)
        for cy in range(mh):
            for cx in range(mw):
                off = struct.unpack_from(">H", d, 4 + (cy * mw + cx) * 2)[0]
                c = pr[off // 8][2]
                if not c:
                    continue
                h = U32(jump + c * 4)
                cells[(c, h)] += 1
                where[(c, h)].add(n)
    return cells, where


def describe(h):
    """Параметры вида: только своё, без порождённых."""
    body = species_body(h)
    mine = sorted(a for a, alien in body if not alien)
    hp, dmg, scr, prog, tbl, snd = set(), set(), set(), set(), set(), set()
    inv, mask = set(), set()
    prev = {}
    for a in mine:
        t = BY.get(a, "")
        for rx, bag, base in ((HP, hp, 16), (DMG, dmg, 16), (SCR, scr, 16),
                              (PROG, prog, 16), (SND, snd, 16)):
            m = rx.search(t)
            if m:
                bag.add(int(m.group(1), base))
        m = TBL.search(t)
        if m:
            tbl.add(int(m.group(1), 16))
        mm = D12.search(t)
        if mm:
            v = (int(mm.group(1)) & 0xFFFF if mm.group(1)
                 else int(mm.group(2), 16))
            prev[mm.group(3)] = (a, v)
        if "loc_2A2C48" in t and BSR.match(t):
            for k, bag in (("1", inv), ("2", mask)):
                if k in prev and 0 < a - prev[k][0] < 48:
                    bag.add(prev[k][1])
    return {"upd": own_updates(h), "hp": hp, "dmg": dmg, "scr": scr,
            "prog": prog, "tbl": tbl, "snd": snd, "inv": inv, "mask": mask,
            "n": len(mine)}


PROG_LEN = {0x80: 4, 0x81: 4, 0x82: 6, 0x83: 4, 0x84: 6, 0x85: 4, 0x86: 4,
            0x87: 4, 0x88: 4, 0x89: 4, 0x8A: 4, 0x8B: 4, 0x8C: 4, 0x8D: 6}
SCRIPTS = (0x1D6000, 0x1DC000)


def prog_starts():
    """Начала программ `+$48`: граница, дальше которой разбор не идёт."""
    got, rx = set(), re.compile(r"move\.l\s+#\$00([0-9A-F]{6}),\$48\(a")
    for a in ADDRS:
        m = rx.search(BY[a])
        if m:
            got.add(int(m.group(1), 16))
    return sorted(got)


def prog_scripts(base, limit=400):
    """Скрипты, которые раздаёт программа поведения `+$48` (команда `$84`).

    Разбор языка — в docs/mauimallard/engine.md: команда `$84 $00` несёт
    длинное слово со скриптом, голое слово меньше `$80` кончает шаг.
    """
    i = bisect.bisect_right(PSTARTS, base) if PSTARTS else 0
    end = PSTARTS[i] if i < len(PSTARTS) else base + 0x400
    out, at, seen = [], base, set()
    while limit and at not in seen and at < end and at + 6 < len(ROM):
        limit -= 1
        seen.add(at)
        op = ROM[at]
        if op < 0x80:
            at += 2
            continue
        if op not in PROG_LEN:
            break
        if op == 0x84:
            v = U32(at + 2)
            if SCRIPTS[0] <= v < SCRIPTS[1] and v not in out:
                out.append(v)
        at += PROG_LEN[op]
    return out


PSTARTS = prog_starts()


def script_starts():
    """Начала всех скриптов: нужны, чтобы обход не убежал в соседний."""
    got = set()
    rx = re.compile(r"move\.l\s+#\$00([0-9A-F]{6}),\$22\(a")
    for a in ADDRS:
        m = rx.search(BY[a])
        if m:
            v = int(m.group(1), 16)
            if SCRIPTS[0] <= v < SCRIPTS[1]:
                got.add(v)
    rx = re.compile(r"move\.l\s+#\$00([0-9A-F]{6}),\$48\(a")
    for a in ADDRS:
        m = rx.search(BY[a])
        if m:
            got |= set(prog_scripts(int(m.group(1), 16)))
    return sorted(got)


STARTS = script_starts()


def script_frames(s):
    """Кадры одного скрипта, с жёсткой границей по следующему скрипту."""
    import anim as A
    i = bisect.bisect_right(STARTS, s)
    end = STARTS[i] if i < len(STARTS) else s + 0x200
    out = []
    for at, _raw, _txt, fr in A.walk(s, 200):
        if at >= end:
            break
        if fr is not None and fr not in out:
            out.append(fr)
    return out


SCR_ANY = re.compile(r"move\.l\s+#\$00([0-9A-F]{6}),\$22\(a")
PROG_ANY = re.compile(r"move\.l\s+#\$00([0-9A-F]{6}),\$48\(a")


def all_scripts(h, species):
    """Скрипты вида, и только его.

    Общего обхода тут мало: в него затекают чужие скрипты — та же
    `$299D5E` ставит всем подряд `$1D8BCE`, облачко на смерть. Поэтому
    берётся ровно то, что принадлежит виду по построению:

    1. скрипт, с которым объект рождается (`anim.script_of_any`);
    2. лесенка его программы поведения `+$48`, тоже взятой при рождении;
    3. скрипты обработчиков из его срезов состояний — эти таблицы
       принадлежат виду целиком.
    """
    import anim as A
    got = []

    def add(s):
        if s and SCRIPTS[0] <= s < SCRIPTS[1] and s not in got:
            got.append(s)

    add(A.script_of_any(h))
    pr = A.field_imm(h, 0x0048)
    if pr:
        for s in prog_scripts(pr):
            add(s)
    for tb in sorted(species["tbl"]):
        for hh in table_longs(tb):
            for a, alien in walk(hh, 0):
                if alien:
                    continue
                t = BY.get(a, "")
                m = SCR_ANY.search(t)
                if m:
                    add(int(m.group(1), 16))
                m = PROG_ANY.search(t)
                if m:
                    for s in prog_scripts(int(m.group(1), 16)):
                        add(s)
    return got


def frames_of(h, species):
    """Номера кадров: из каждого скрипта вида — все, что встретились."""
    got = []
    for s in all_scripts(h, species):
        for fr in script_frames(s):
            if fr not in got:
                got.append(fr)
    return got


# ---------------------------------------------------------------- вывод

def collect():
    cells, where = census()
    hs = sorted(set(h for _c, h in cells))
    rows = []
    for h in hs:
        if h not in HITS and not (own_updates(h) & HITS):
            continue
        n = sum(v for (c, k), v in cells.items() if k == h)
        codes = sorted(c for (c, k) in cells if k == h)
        lv = set()
        for (c, k), s in where.items():
            if k == h:
                lv |= s
        rows.append({"h": h, "cells": n, "codes": codes,
                     "levels": sorted(lv), "p": describe(h)})
    rows.sort(key=lambda r: (-r["cells"], r["h"]))
    return rows, cells, hs


def fmt(vals, f="%d"):
    return ",".join(f % v for v in sorted(vals)) if vals else "—"


def do_summary():
    rows, cells, hs = collect()
    foe = sum(r["cells"] for r in rows)
    print("объектов на 23 уровнях: %d, конструкторов %d"
          % (sum(cells.values()), len(hs)))
    print("из них ПРОТИВНИКОВ: конструкторов %d, клеток %d (%.0f%%)"
          % (len(rows), foe, 100.0 * foe / sum(cells.values())))
    print()
    for key, name in (("hp", "жизни"), ("mask", "маска"),
                      ("inv", "неуязвимость")):
        tally = defaultdict(int)
        for r in rows:
            v = r["p"][key]
            tally[fmt(v, "$%X" if key == "mask" else "%d")] += 1
        print("%s:" % name)
        for v, k in sorted(tally.items(), key=lambda kv: -kv[1]):
            print("   %-22s видов %d" % (v, k))
        print()


def do_list():
    rows, _cells, _hs = collect()
    print("клеток  коды       уровни          конструктор  обновление   "
          "жизни  неуяз  маска   скриптов  срез состояний")
    for r in rows:
        p = r["p"]
        print("%6d  %-10s %-15s $%06X      %-12s %-6s %-6s %-7s %-9d %s"
              % (r["cells"], fmt(r["codes"])[:10],
                 fmt(r["levels"])[:15], r["h"],
                 fmt(p["upd"], "$%06X")[:12], fmt(p["hp"]),
                 fmt(p["inv"]), fmt(p["mask"], "$%04X")[:7],
                 len(p["scr"]),
                 fmt(p["tbl"], "$%06X")[:30]))
    print()
    print("видов %d, клеток %d"
          % (len(rows), sum(r["cells"] for r in rows)))


def do_show(code):
    rows, _cells, _hs = collect()
    hit = [r for r in rows if code in r["codes"] or r["h"] == code]
    if not hit:
        print("код %s среди противников не найден" % code)
        return
    for r in hit:
        p = r["p"]
        print("=" * 62)
        print("конструктор $%06X, код порождения %s" % (r["h"], fmt(r["codes"])))
        print("  клеток %d на уровнях %s" % (r["cells"], fmt(r["levels"])))
        print("  обновление      %s" % fmt(p["upd"], "$%06X"))
        print("  жизни           %s" % fmt(p["hp"]))
        print("  неуязвимость    %s кадров" % fmt(p["inv"]))
        print("  маска урона     %s" % fmt(p["mask"], "$%04X"))
        print("  урон игроку     %s" % fmt(p["dmg"]))
        print("  скрипты         %s" % fmt(p["scr"], "$%06X"))
        print("  программы +$48  %s" % fmt(p["prog"], "$%06X"))
        print("  срезы состояний %s" % fmt(p["tbl"], "$%06X"))
        print("  звуки           %s" % fmt(p["snd"], "$%02X"))
        print("  своих команд    %d" % p["n"])
        fr = frames_of(r["h"], p)
        print("  кадров          %d: %s"
              % (len(fr), ", ".join(str(x) for x in fr[:20])))


def do_level(n):
    import levels as L
    rows, _cells, _hs = collect()
    g = L.gfx(n)
    d, pr = g["map_data"], L.props(g)
    jump = U32(record(n) + 0x20)
    mw, mh = struct.unpack_from(">HH", d, 0)
    here = defaultdict(int)
    for cy in range(mh):
        for cx in range(mw):
            off = struct.unpack_from(">H", d, 4 + (cy * mw + cx) * 2)[0]
            c = pr[off // 8][2]
            if c:
                here[U32(jump + c * 4)] += 1
    mine = [(here[r["h"]], r) for r in rows if r["h"] in here]
    mine.sort(key=lambda t: -t[0])
    print("уровень %d: противников %d видов, %d клеток"
          % (n, len(mine), sum(k for k, _r in mine)))
    for k, r in mine:
        print("   %4d  $%06X  коды %-8s жизни %-5s маска %s"
              % (k, r["h"], fmt(r["codes"]), fmt(r["p"]["hp"]),
                 fmt(r["p"]["mask"], "$%04X")))


def do_sheet(only=None, scale=2, per_row=8):
    import frames as F
    import sprites as SP
    import levels as L
    rows, _cells, _hs = collect()
    d = out_path("gfx")
    os.makedirs(d, exist_ok=True)
    made = 0
    for r in rows:
        if only is not None and only not in r["codes"] and only != r["h"]:
            continue
        fr = frames_of(r["h"], r["p"])
        if not fr:
            print("$%06X: кадров не нашлось" % r["h"])
            continue
        SP.PALS = L.pal(r["levels"][0])
        got = []
        for i in fr[:32]:
            pieces = F.parse(F.U32(F.BASE + i * 4))
            got.append((i, pieces, SP.bounds(pieces)) if pieces
                       else (i, None, None))
        vis = [g for g in got if g[1]]
        if not vis:
            print("$%06X: кадры не разбираются" % r["h"])
            continue
        cw = max(b[2] - b[0] for _i, _p, b in vis) + 2
        ch = max(b[3] - b[1] for _i, _p, b in vis) + 2
        nrow = (len(got) + per_row - 1) // per_row
        w, h = cw * per_row, ch * nrow
        buf = [None] * (w * h)
        for k, (_i, pieces, b) in enumerate(got):
            if not pieces:
                continue
            ox = (k % per_row) * cw + 1 - b[0]
            oy = (k // per_row) * ch + 1 - b[1]
            for p in pieces:
                SP.draw(buf, w, h, ox, oy, p)
        path = os.path.join(d, "enemy_%03d_%06X.png" % (r["codes"][0], r["h"]))
        SP.png(path, w, h, buf, scale)
        made += 1
        print("код %3d $%06X: кадров %d, клетка %dx%d -> %s"
              % (r["codes"][0], r["h"], len(got), cw, ch, path))
    print("листов: %d" % made)


def emits(h, depth=4):
    """Кого вид ВЫПУСКАЕТ: чужой `+$1E`, потом чужой `+$1E` у того, и так далее.

    Клетка не всегда ставит противника сама. Коды 124-135 на уровнях 3 и 4,
    коды 200-202 на уровне 9 — это ГЕНЕРАТОРЫ: объект стоит на месте,
    считает и выпускает бойца. По ним уровень 9 и выглядел пустым.
    """
    got, cur = set(), [(h, 1)] + [(u, 0) for u in own_updates(h)]
    for _ in range(depth):
        nxt = set()
        for at, thr in cur:
            for a, alien in walk(at, thr):
                if not alien:
                    continue
                m = UPD.search(BY.get(a, ""))
                if m:
                    v = int(m.group(1), 16)
                    if CODE[0] <= v < CODE[1] and v not in got:
                        nxt.add(v)
        if not nxt:
            break
        got |= nxt
        cur = [(v, 0) for v in nxt]
    return got


def generators():
    """Клетки, которые ставят не противника, а того, кто его выпускает."""
    cells, where = census()
    hs = sorted(set(h for _c, h in cells))
    foe = set(h for h in hs if h in HITS or (own_updates(h) & HITS))
    out = []
    for h in hs:
        if h in foe:
            continue
        hurt = emits(h) & HITS
        if not hurt:
            continue
        n = sum(v for (c, k), v in cells.items() if k == h)
        lv = sorted(set().union(*[s for (c, k), s in where.items() if k == h]))
        cs = sorted(c for (c, k) in cells if k == h)
        out.append({"h": h, "cells": n, "codes": cs, "levels": lv,
                    "emits": sorted(hurt)})
    out.sort(key=lambda r: (-r["cells"], r["h"]))
    return out


def do_gen():
    rows = generators()
    lv = sorted(set().union(*[set(r["levels"]) for r in rows])) if rows else []
    print("генераторов %d, клеток под ними %d, уровни %s"
          % (len(rows), sum(r["cells"] for r in rows), fmt(lv)))
    print()
    print("клеток  коды        уровни     конструктор  выпускает")
    for r in rows:
        print("%6d  %-11s %-10s $%06X      %s"
              % (r["cells"], fmt(r["codes"])[:11], fmt(r["levels"])[:10],
                 r["h"], fmt(r["emits"], "$%06X")))


UPD_ANY = re.compile(r"move\.l\s+#\$00([0-9A-F]{6}),\$1E\(a\d\)")


def code_spawned():
    """Те, кого клетки не зовут: боссы и их части, заводимые кодом.

    Перепись идёт не по таблицам порождения, а по всему банку: берутся ВСЕ
    процедуры обновления, какие вообще кому-нибудь ставятся, и из них те,
    что дотягиваются до ядра урона. Что не попало в клеточный каталог —
    и есть порождаемое кодом.
    """
    ups = defaultdict(list)
    for a in ADDRS:
        m = UPD_ANY.search(BY[a])
        if m:
            v = int(m.group(1), 16)
            if CODE[0] <= v < CODE[1]:
                ups[v].append(a)
    rows, _cells, _hs = collect()
    known = set()
    for r in rows:
        known |= r["p"]["upd"]
    out = []
    for v in sorted(ups):
        if v in HITS and v not in known:
            out.append((v, ups[v]))
    return out


def do_code():
    rows = code_spawned()
    print("процедур обновления с уроном, которых нет в клеточном каталоге: %d"
          % len(rows))
    print()
    print("обновление  ставится из          жизни  неуяз  маска    срезы")
    for v, froms in rows:
        p = describe(froms[0])
        print("$%06X    %-20s %-6s %-6s %-8s %s"
              % (v, ",".join("$%06X" % x for x in froms[:2]),
                 fmt(p["hp"]), fmt(p["inv"]), fmt(p["mask"], "$%04X"),
                 fmt(p["tbl"], "$%06X")[:34]))


CARRY = re.compile(r"move\.l\s+#\$00([0-9A-F]{6})\s*,")


def closure(at, thr, depth=10):
    """Кого корень в итоге приводит в уровень, через любое сохранённое поле.

    Тут обход намеренно широкий: вопрос не «чьи это поля», а «кто вообще
    вносит эту процедуру в уровень». Поэтому за дугу считается ЛЮБОЕ
    `move.l #adr,...` с адресом из банка кода — и `+$1E`, и `+$50`, и
    просто в регистр. Части многочастного босса иначе теряются: им `+$1E`
    ставят через `a1`/`a2`.
    """
    got, frontier = set(), [(at, thr)]
    for _ in range(depth):
        nxt = set()
        for x, th in frontier:
            for a, _al in walk(x, th):
                for m in CARRY.finditer(BY.get(a, "")):
                    v = int(m.group(1), 16)
                    if CODE[0] <= v < CODE[1] and v not in got:
                        nxt.add(v)
        if not nxt:
            break
        got |= nxt
        frontier = [(v, 0) for v in nxt]
    return got


def roots():
    """Всё, чем уровень вообще может что-то завести."""
    cells, where = census()
    out = []
    for h in sorted(set(k for _c, k in cells)):
        cs = sorted(c for (c, k) in cells if k == h)
        lv = sorted(set().union(*[s for (c, k), s in where.items() if k == h]))
        out.append(("клетка $%06X, коды %s, ур. %s"
                    % (h, fmt(cs), fmt(lv)), h, 1))
    seen, tbl = set(), set()
    for n in range(LEVELS):
        t20 = U32(record(n) + 0x20)
        if t20 in seen:
            continue
        seen.add(t20)
        for k in range(256):
            tbl.add(U32(t20 + k * 4))
    tbl -= {0x2A526C} | set(k for _c, k in cells)
    for h in sorted(tbl):
        if CODE[0] <= h < CODE[1]:
            out.append(("таблица, клетки не зовут: $%06X" % h, h, 1))
    procs = {}
    for n in range(LEVELS):
        for f in (0x0C, 0x10, 0x14, 0x28, 0x2C, 0x30):
            v = U32(record(n) + f)
            if CODE[0] <= v < CODE[1]:
                procs.setdefault(v, []).append((n, f))
    for p, lst in sorted(procs.items()):
        out.append(("уровень %s, поле +$%02X ($%06X)"
                    % (fmt(sorted(set(n for n, _f in lst))), lst[0][1], p),
                    p, 0))
    return out


def do_who():
    """Откуда в уровне берётся каждый «кодовый» противник."""
    targets = [v for v, _f in code_spawned()]
    owner = defaultdict(list)
    for name, h, thr in roots():
        got = closure(h, thr)
        for t in targets:
            if t in got:
                owner[t].append(name)
    print("происхождение %d процедур обновления с уроном, которых нет"
          " в клеточном каталоге" % len(targets))
    print()
    lost = 0
    for t in targets:
        who = owner.get(t) or []
        if not who:
            lost += 1
        print("$%06X  %s" % (t, "; ".join(who[:3]) if who else "— НЕ ПРИВЯЗАЛОСЬ"))
    print()
    print("не привязалось: %d" % lost)


def do_contact(scale=2, per_row=6):
    """Общий лист: по одному кадру на вид, в порядке каталога."""
    import frames as F
    import sprites as SP
    import levels as L
    rows, _cells, _hs = collect()
    got = []
    for r in rows:
        fr = frames_of(r["h"], r["p"])
        pieces = None
        for i in fr:
            pieces = F.parse(F.U32(F.BASE + i * 4))
            if pieces:
                break
        got.append((r, pieces, SP.bounds(pieces) if pieces else None))
    vis = [g for g in got if g[1]]
    cw = max(b[2] - b[0] for _r, _p, b in vis) + 4
    ch = max(b[3] - b[1] for _r, _p, b in vis) + 4
    nrow = (len(got) + per_row - 1) // per_row
    w, h = cw * per_row, ch * nrow
    buf = [None] * (w * h)
    for k, (r, pieces, b) in enumerate(got):
        if not pieces:
            continue
        SP.PALS = L.pal(r["levels"][0])
        ox = (k % per_row) * cw + 2 - b[0]
        oy = (k // per_row) * ch + 2 - b[1]
        for p in pieces:
            SP.draw(buf, w, h, ox, oy, p)
    d = out_path("gfx")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "enemies_contact.png")
    SP.png(path, w, h, buf, scale)
    print("общий лист: %d видов, клетка %dx%d, %dx%d -> %s"
          % (len(got), cw, ch, w, h, path))
    for k, (r, _p, _b) in enumerate(got):
        print("   %2d (ряд %d, место %d)  код %3d  $%06X  клеток %4d"
              % (k + 1, k // per_row + 1, k % per_row + 1,
                 r["codes"][0], r["h"], r["cells"]))


def main():
    a = sys.argv[1:]
    if not a:
        do_summary()
    elif a[0] == "--list":
        do_list()
    elif a[0] == "--show" and len(a) > 1:
        do_show(int(a[1], 16) if len(a[1]) > 4 else int(a[1]))
    elif a[0] == "--level" and len(a) > 1:
        do_level(int(a[1]))
    elif a[0] == "--who":
        do_who()
    elif a[0] == "--gen":
        do_gen()
    elif a[0] == "--code":
        do_code()
    elif a[0] == "--contact":
        do_contact()
    elif a[0] == "--sheet":
        do_sheet(None if len(a) < 2
                 else (int(a[1], 16) if len(a[1]) > 4 else int(a[1])))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
