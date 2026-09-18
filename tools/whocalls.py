#!/usr/bin/env python3
"""Кто ведёт на адрес: все формы перехода, а не только абсолютные.

    python tools/whocalls.py 008392 [ещё адреса]
    python tools/whocalls.py 008370-008430        # диапазон

Нужен там, где анализатор не считает окрестность кодом: метки в
дизассемблере нет, и `grep` бессилен. Ищет по сырым байтам ROM:

* все `Bcc` — не только `bra` и `bsr`. На этом разбор уже спотыкался:
  скан без условных переходов признал живую процедуру мёртвой;
* `jsr`/`jmp` с `d16(pc)` и с `abs.l`;
* любую `d16(pc)`-адресацию (`lea`, `pea`, `move`) — так находятся
  таблицы, на которые ссылаются, а не переходят.

Приём того же рода, но с другой стороны: искать не переход, а ЧТЕНИЕ
ячейки. Абсолютная адресация кодирует `$FF0553` длинным словом
`00FF0553`, и скан на эти четыре байта находит ссылку независимо от
того, что анализатор думает об окрестности.
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CC = ["bra", "bsr", "bhi", "bls", "bcc", "bcs", "bne", "beq",
      "bvc", "bvs", "bpl", "bmi", "bge", "blt", "bgt", "ble"]


def scan(rom, lo, hi):
    """Все ссылки внутрь [lo, hi) -> {цель: [(адрес, вид)]}."""
    n = len(rom)
    out = {}

    def add(t, a, kind):
        if lo <= t < hi:
            out.setdefault(t, []).append((a, kind))

    def s16(a):
        v = (rom[a] << 8) | rom[a + 1]
        return v - 0x10000 if v & 0x8000 else v

    for a in range(2, n - 5, 2):
        b0, b1 = rom[a], rom[a + 1]
        if 0x60 <= b0 <= 0x6F:
            if b1 == 0x00:
                add(a + 2 + s16(a + 2), a, CC[b0 - 0x60] + ".w")
            elif b1 != 0xFF:
                d = b1 - 0x100 if b1 & 0x80 else b1
                add(a + 2 + d, a, CC[b0 - 0x60] + ".s")
        op = (b0 << 8) | b1
        if op in (0x4EBA, 0x4EFA):
            add(a + 2 + s16(a + 2), a,
                "jsr d16(pc)" if op == 0x4EBA else "jmp d16(pc)")
        if op in (0x4EB9, 0x4EF9):
            v = ((rom[a + 2] << 24) | (rom[a + 3] << 16)
                 | (rom[a + 4] << 8) | rom[a + 5])
            add(v, a, "jsr abs.l" if op == 0x4EB9 else "jmp abs.l")
        # любая d16(pc)-адресация: слово режима кончается на $FA
        if rom[a - 1] == 0xFA:
            add(a + s16(a), a - 2, "d16(pc) $%04X" % ((rom[a - 2] << 8) | 0xFA))
    return out


def longword_refs(rom, value):
    """Ссылки-данные: длинное слово с этим значением."""
    pat = bytes([(value >> 24) & 0xFF, (value >> 16) & 0xFF,
                 (value >> 8) & 0xFF, value & 0xFF])
    out, i = [], rom.find(pat)
    while i >= 0:
        out.append(i)
        i = rom.find(pat, i + 1)
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    rom = open(os.path.join(HERE, "game.gen"), "rb").read()
    for arg in sys.argv[1:]:
        if "-" in arg:
            a, b = arg.split("-")
            lo, hi = int(a, 16), int(b, 16)
        else:
            lo = int(arg, 16)
            hi = lo + 2
        print("== ссылки внутрь $%06X..$%06X ==" % (lo, hi))
        found = scan(rom, lo, hi)
        for t in sorted(found):
            print("  -> $%06X : %s"
                  % (t, ", ".join("$%06X %s" % x for x in found[t][:6])))
        if not found:
            print("  переходов нет")
        if hi - lo > 16:      # на широком диапазоне это один шум из графики
            print()
            continue
        for t in range(lo, hi, 2):
            lw = longword_refs(rom, t)
            if lw:
                print("  длинное слово $%08X лежит в: %s"
                      % (t, ", ".join("$%06X" % x for x in lw[:8])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
