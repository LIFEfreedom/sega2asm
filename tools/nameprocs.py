#!/usr/bin/env python3
"""Предложить имена безымянным процедурам по механическим признакам.

    python tools/nameprocs.py 010000 020000 >> game_symbols.user.txt
    make nameprocs FROM=010000 TO=020000

Зачем. Процедур в ROM полторы тысячи, разобрать каждую глазами
непозволительно дорого. Но у каждой видно, ЧЕМ она занимается: какие
трапы BIOS зовёт, в какую область VDP пишет, какие известные базы и
смещения записей задевает. Этого хватает, чтобы место вызова читалось:
`AiPickAction_0178F4` говорит больше, чем `loc_0178F4`.

Чего инструмент НЕ делает. Он не утверждает, ЗАЧЕМ процедура нужна.
Имя `MapPaint_020768` значит ровно «трогает карту местности и пишет в
неё», и ничего сверх. Где роль установлена чтением кода, имя заменяется
руками на осмысленное.

Как устроено. Сначала по телу считаются очки предметных областей
(поведение, юниты, бой, карта, игроки, вывод, звук, ввод, ядро). Область
с наибольшим счётом даёт ПРЕФИКС. Внутри области первое подошедшее
правило даёт УТОЧНЕНИЕ. Адрес в имени оставлен намеренно: имена
уникальны, и сразу видно, что имя машинное.
"""
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT as out_path
from paths import user_symbols

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ADDR = (re.compile(r"^; \$([0-9A-F]{6})$"),
        re.compile(r"^\S.*;\s*\$([0-9A-F]{6})$"),
        re.compile(r"^\torg\t\$([0-9A-F]{6})$"))

# Область -> признаки, каждый даёт очко за каждое вхождение.
DOMAINS = {
    "Ai": ["TestActionInSet", "SetAnimDuration", "PickRandomBranch",
           "BehaviourDispatch", "$15(a", "$24(a", "$14(a"],
    "Unit": ["UnitRecords", "UnitSlots", "UnitStatTable", "UnitTypeTable",
             "CreateUnit", "$0C(a", "$18(a"],
    "Combat": ["HpDamage", "HpHeal", "ResolveCombat", "ApplyCombatDamage",
               "IsDeadOrCarcass", "MakeCarcass", "$16(a", "$1C(a"],
    "Map": ["TerrainMap", "UnitMap", "PlacementMap", "TerrainCellFromXY",
            "PaintTerrainCell", "ClampMapCoords", "GetTerrainType",
            "SetTerrainType", "CellFromXY"],
    "Player": ["Player1State", "Player2State", "CurrentPlayerPtr",
               "CanAfford", "PayCost", "PopulationCounts", "MainStatePtr"],
    "Gfx": ["VDP_", "GfxWorkBuffer", "FlushSpriteTable", "SpriteList",
            "BuildVisibleUnitList", "UpdateUnitScreenPos"],
    "Sound": ["PlaySound", "PlaySfx", "BiosPlay", "PendingSfxId"],
    "Input": ["ReadDPadDirection", "ReadButtonState", "InputState"],
    "Core": ["GameState", "GameTick", "MainState", "FrameWait",
             "VDPWaitVBlank", "DelayTimer"],
    "Z80": ["Z80_BUSREQ", "Z80_RESET", "A01C04", "A00000"],
}

# Диапазон внутренностей BIOS: всё, что лежит между входом line-F и
# концом его функций, относится к ядру независимо от прочих признаков.
BIOS_LO, BIOS_HI = 0x000668, 0x001F00

# Уточнение внутри области: (метка, проверка).
REFINE = [
    ("Clear",    lambda j, tr, vd: tr.get("21", 0) and tr.get("22", 0)),
    ("Palette",  lambda j, tr, vd: "CRAM" in vd or tr.get("20", 0) or tr.get("32", 0)),
    ("Scroll",   lambda j, tr, vd: "VSRAM" in vd or tr.get("29", 0)),
    ("Load",     lambda j, tr, vd: tr.get("10", 0) and tr.get("04", 0)),
    ("Unpack",   lambda j, tr, vd: tr.get("10", 0)),
    ("Text",     lambda j, tr, vd: tr.get("25", 0) or tr.get("24", 0)),
    ("Draw",     lambda j, tr, vd: tr.get("04", 0) or tr.get("01", 0)
                                   or tr.get("2B", 0) or bool(vd) or "VDP_" in j),
    ("Sfx",      lambda j, tr, vd: tr.get("2F", 0) or tr.get("30", 0)),
    ("Rand",     lambda j, tr, vd: "Random" in j),
    ("Loop",     lambda j, tr, vd: "dbf\t" in j),
    ("Table",    lambda j, tr, vd: bool(re.search(r"lea\tdata_\d+", j))),
    ("Args",     lambda j, tr, vd: j.startswith("link")),
]


def vdpkind(v):
    hi, lo = (v >> 16) & 0xFFFF, v & 0xFFFF
    cd = ((hi >> 14) & 3) | (((lo >> 4) & 0xF) << 2)
    return {1: "VRAM", 3: "CRAM", 5: "VSRAM"}.get(cd, "?")


def load():
    asm = out_path("asm", "m68k")
    rows = []
    for fn in sorted(os.listdir(asm)):
        addr = None
        for raw in open(os.path.join(asm, fn), encoding="utf-8",
                        errors="replace"):
            line = raw.rstrip("\n")
            hit = False
            for pat in ADDR:
                m = pat.match(line)
                if m:
                    addr = int(m.group(1), 16)
                    hit = True
                    break
            if not hit and line.startswith("\t") and addr is not None:
                rows.append((addr, line.strip()))
                addr = None
    rows.sort()
    return rows


def main():
    lo = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0
    hi = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x200000
    if not os.path.isdir(out_path("asm", "m68k")):
        print("[--] нет out/<имя>/asm/m68k — сначала `make split`")
        return 1

    rows = load()
    order = [a for a, _ in rows]
    code = dict(rows)

    named = set()
    for line in open(user_symbols(),
                     encoding="utf-8"):
        m = re.match(r"^\s*\w+\s*=\s*\$([0-9A-F]+)", line)
        if m:
            named.add(int(m.group(1), 16))

    refs = collections.Counter()
    for a, t in rows:
        for m in re.finditer(r"loc_([0-9A-F]{6})", t):
            refs[int(m.group(1), 16)] += 1

    starts = []
    prev = True
    for a in order:
        t = code[a]
        if (("movem.l" in t and "-(a7)" in t) or t.startswith("link\t")) \
                and prev:
            starts.append(a)
        prev = t.startswith(("rts", "rte", "bra", "jmp"))
    sel = [s for s in starts if lo <= s < hi]

    out = []
    for i, s in enumerate(sel):
        if s in named:
            continue
        e = sel[i + 1] if i + 1 < len(sel) else hi
        body = [code[a] for a in order if s <= a < e]
        if not body:
            continue
        j = "\n".join(body)
        tr = collections.Counter(
            m.group(1) for t in body
            for m in [re.match(r"^dc\.w\t\$FF([0-9A-F]{2})$", t)] if m)
        vd = collections.Counter()
        for t in body:
            m = re.search(r"#\$([0-9A-F]{8}),\(VDP_CTRL\)", t)
            if m:
                vd[vdpkind(int(m.group(1), 16))] += 1

        score = {d: sum(j.count(k) for k in keys)
                 for d, keys in DOMAINS.items()}
        best = max(score, key=lambda d: (score[d], d))
        if BIOS_LO <= s < BIOS_HI:
            best = "Bios"
        elif score[best] == 0:
            best = ""
        note = ""
        for label, test in REFINE:
            if test(j, tr, vd):
                note = label
                break
        out.append([s, best, note, len(body), refs.get(s, 0), e])

    # Наследование области от вызывающих: процедура без собственных
    # признаков получает область того, кто её зовёт. Двух проходов
    # хватает — дальше картина перестаёт меняться.
    callers = collections.defaultdict(list)
    for a, t in rows:
        for m in re.finditer(r"loc_([0-9A-F]{6})", t):
            callers[int(m.group(1), 16)].append(a)

    def owner(addr):
        """Чья это процедура — вернуть её область, если та известна."""
        for o2 in out:
            if o2[0] <= addr < o2[5]:
                return o2[1]
        return ""

    for _ in range(2):
        for o in out:
            if o[1]:
                continue
            votes = collections.Counter(
                d for d in (owner(c) for c in callers.get(o[0], ())) if d)
            if votes:
                o[1] = votes.most_common(1)[0][0]

    out = [(o[0], (o[1] or "Sub") + o[2], o[3], o[4]) for o in out]

    cnt = collections.Counter(c for _, c, _, _ in out)
    print("; Имена ниже выведены по механическим признакам тела: вызванные")
    print("; трапы BIOS, адреса VDP, задетые известные базы и смещения.")
    print("; Префикс — предметная область с наибольшим счётом, суффикс —")
    print("; уточнение по первому подошедшему правилу. Имя говорит, ЧЕМ")
    print("; процедура занимается, и НИЧЕГО не утверждает о том, ЗАЧЕМ.")
    print("; Адрес в имени намеренный: имена уникальны и видно, что они")
    print("; машинные. Сгенерировано tools/nameprocs.py.")
    print(";")
    print("; По категориям: " + ", ".join("%s %d" % kv
                                          for kv in cnt.most_common()))
    print()
    for s, cat, n, r in out:
        print("%-30s = $%06X   ; %d инстр, %d ссылок"
              % ("%s_%06X" % (cat, s), s, n, r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
