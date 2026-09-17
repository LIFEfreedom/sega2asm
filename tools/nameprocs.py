#!/usr/bin/env python3
"""Предложить имена безымянным процедурам по механическим признакам.

    python tools/nameprocs.py 050000 060000 >> game_symbols.user.txt

Зачем. В банках вывода процедур сотни, и разбирать каждую глазами
непозволительно дорого. Но у каждой видно, ЧЕМ она занимается: какие
трапы BIOS зовёт, в какую область VDP пишет, какие известные базы
задевает. Этого хватает, чтобы место вызова читалось: `GfxPalette_053140`
говорит больше, чем `loc_053140`.

Чего инструмент НЕ делает. Он не утверждает, ЗАЧЕМ процедура нужна.
Имя вида `GfxLoadGfx_050290` значит ровно «распаковывает и копирует в
VDP», и ничего сверх этого. Если роль установлена чтением кода, имя надо
заменить руками на осмысленное — так сделано для полутора десятков
процедур банка $05.

Адрес в имени оставлен намеренно: имена гарантированно уникальны, и
сразу видно, что имя машинное, а не выстраданное.
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

ADDR = (re.compile(r"^; \$([0-9A-F]{6})$"),
        re.compile(r"^\S.*;\s*\$([0-9A-F]{6})$"),
        re.compile(r"^\torg\t\$([0-9A-F]{6})$"))

# Порядок важен: от узкого признака к широкому, побеждает первый.
RULES = [
    ("ObjRecords", lambda j, tr, vd: "$86(a5)" in j or "#$005A" in j),
    ("SpriteList", lambda j, tr, vd: "FF2748" in j or "SpriteList" in j),
    ("Palette",    lambda j, tr, vd: "CRAM" in vd or tr.get("20", 0) >= 2
                                     or tr.get("32", 0)),
    ("ClearPlanes", lambda j, tr, vd: tr.get("21", 0) and tr.get("22", 0)),
    ("Scroll",     lambda j, tr, vd: "VSRAM" in vd or tr.get("29", 0)),
    ("LoadGfx",    lambda j, tr, vd: tr.get("10", 0) and tr.get("04", 0)),
    ("Decompress", lambda j, tr, vd: tr.get("10", 0)),
    ("VdpWrite",   lambda j, tr, vd: tr.get("04", 0) or tr.get("01", 0)
                                     or bool(vd) or "VDP_" in j),
    ("Sound",      lambda j, tr, vd: tr.get("2F", 0) or tr.get("30", 0)),
    ("Text",       lambda j, tr, vd: tr.get("25", 0) or tr.get("24", 0)),
    ("Input",      lambda j, tr, vd: "ReadDPad" in j or "ReadButton" in j),
    ("FrameWait",  lambda j, tr, vd: "WaitVBlank" in j or "FrameWait" in j),
    ("Units",      lambda j, tr, vd: "UnitRecords" in j or "UnitSlots" in j),
    ("Buffer",     lambda j, tr, vd: "GfxWorkBuffer" in j),
    ("Random",     lambda j, tr, vd: "Random" in j),
    ("Timer",      lambda j, tr, vd: "DelayTimer" in j or "GameTick" in j),
    ("State",      lambda j, tr, vd: "GameState" in j or "MainState" in j),
    ("Table",      lambda j, tr, vd: bool(re.search(r"lea\tdata_\d+", j))),
    ("Args",       lambda j, tr, vd: j.startswith("link")),
]


def vdpkind(v):
    hi, lo = (v >> 16) & 0xFFFF, v & 0xFFFF
    cd = ((hi >> 14) & 3) | (((lo >> 4) & 0xF) << 2)
    return {1: "VRAM", 3: "CRAM", 5: "VSRAM"}.get(cd, "?")


def main():
    lo = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0
    hi = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x200000
    asm = os.path.join(HERE, "out", "asm", "m68k")
    if not os.path.isdir(asm):
        print("[--] нет out/asm/m68k — сначала `make split`")
        return 1

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
    order = [a for a, _ in rows]
    code = dict(rows)

    named = set()
    for line in open(os.path.join(HERE, "game_symbols.user.txt"),
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
        cat = "Helper"
        for name, test in RULES:
            if test(j, tr, vd):
                cat = name
                break
        out.append((s, cat, len(body), refs.get(s, 0)))

    cnt = collections.Counter(c for _, c, _, _ in out)
    print("; Имена ниже выведены по механическим признакам тела: вызванные")
    print("; трапы BIOS, адреса VDP, задетые известные базы. Они говорят,")
    print("; ЧЕМ процедура занимается, и ничего не утверждают о том, ЗАЧЕМ.")
    print("; Адрес в имени намеренный: имена уникальны и видно, что они")
    print("; машинные. Сгенерировано tools/nameprocs.py.")
    print(";")
    print("; По категориям: " + ", ".join("%s %d" % kv for kv in cnt.most_common()))
    print()
    for s, cat, n, r in out:
        print("%-28s = $%06X   ; %d инстр, %d ссылок"
              % ("Gfx%s_%06X" % (cat, s), s, n, r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
