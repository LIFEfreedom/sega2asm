#!/usr/bin/env python3
"""Дизассемблер Z80 для звукового драйвера Dyna Brothers 2.

    python tools/z80dis.py            # весь драйвер
    python tools/z80dis.py 0BB 200    # $200 байт с адреса $00BB

Драйвер лежит в ROM по `$00207E` сжатым (метод 3, $1AC0 байт) и при
старте ($00093C) раскладывается в ОЗУ Z80 двумя кусками:
`$0000..$0FD1` и `$1100..$1BED`. Ещё тринадцать байт почтового ящика
копируются из `$000AA8` в `$1C00`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import rom_bytes

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

R8 = ["b", "c", "d", "e", "h", "l", "(hl)", "a"]
R16SP = ["bc", "de", "hl", "sp"]
R16AF = ["bc", "de", "hl", "af"]
CC = ["nz", "z", "nc", "c", "po", "pe", "p", "m"]
ALU = ["add a,", "adc a,", "sub ", "sbc a,", "and ", "xor ", "or ", "cp "]
ROT = ["rlc", "rrc", "rl", "rr", "sla", "sra", "sll", "srl"]
AF_ALT = "ex af,af" + chr(39)


def hx(v, n=2):
    return "$%0*X" % (n, v)


class Dis:
    def __init__(self, mem):
        self.m = mem

    def b(self, a):
        return self.m[a & 0xFFFF]

    def w(self, a):
        return self.b(a) | (self.b(a + 1) << 8)

    def one(self, a):
        """Возвращает (длина, текст, цель-перехода-или-None, конец-потока)."""
        op = self.b(a)
        if op == 0xCB:
            return self._cb(a)
        if op in (0xDD, 0xFD):
            return self._idx(a, "ix" if op == 0xDD else "iy")
        if op == 0xED:
            return self._ed(a)
        return self._main(a)

    # ── основная таблица ──────────────────────────────────────────────
    def _main(self, a):
        op = self.b(a)
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        p, q = y >> 1, y & 1
        n = self.b(a + 1)
        nn = self.w(a + 1)
        d = (a + 2 + ((self.b(a + 1) ^ 0x80) - 0x80)) & 0xFFFF

        if x == 0:
            if z == 0:
                if y == 0:
                    return 1, "nop", None, False
                if y == 1:
                    return 1, AF_ALT, None, False
                if y == 2:
                    return 2, "djnz %s" % hx(d, 4), d, False
                if y == 3:
                    return 2, "jr %s" % hx(d, 4), d, True
                return 2, "jr %s,%s" % (CC[y - 4], hx(d, 4)), d, False
            if z == 1:
                if q == 0:
                    return 3, "ld %s,%s" % (R16SP[p], hx(nn, 4)), None, False
                return 1, "add hl,%s" % R16SP[p], None, False
            if z == 2:
                if y < 4:
                    pair = [("(bc)", "a"), ("a", "(bc)"),
                            ("(de)", "a"), ("a", "(de)")][y]
                    return 1, "ld %s,%s" % pair, None, False
                s = hx(nn, 4)
                pair = [("(%s)" % s, "hl"), ("hl", "(%s)" % s),
                        ("(%s)" % s, "a"), ("a", "(%s)" % s)][y - 4]
                return 3, "ld %s,%s" % pair, None, False
            if z == 3:
                kw = "inc" if q == 0 else "dec"
                return 1, "%s %s" % (kw, R16SP[p]), None, False
            if z == 4:
                return 1, "inc %s" % R8[y], None, False
            if z == 5:
                return 1, "dec %s" % R8[y], None, False
            if z == 6:
                return 2, "ld %s,%s" % (R8[y], hx(n)), None, False
            return 1, ["rlca", "rrca", "rla", "rra",
                       "daa", "cpl", "scf", "ccf"][y], None, False

        if x == 1:
            if op == 0x76:
                return 1, "halt", None, True
            return 1, "ld %s,%s" % (R8[y], R8[z]), None, False

        if x == 2:
            return 1, "%s%s" % (ALU[y], R8[z]), None, False

        # x == 3
        if z == 0:
            return 1, "ret %s" % CC[y], None, False
        if z == 1:
            if q == 0:
                return 1, "pop %s" % R16AF[p], None, False
            return 1, ["ret", "exx", "jp (hl)", "ld sp,hl"][p], None, p in (0, 2)
        if z == 2:
            return 3, "jp %s,%s" % (CC[y], hx(nn, 4)), nn, False
        if z == 3:
            if y == 0:
                return 3, "jp %s" % hx(nn, 4), nn, True
            if y == 2:
                return 2, "out (%s),a" % hx(n), None, False
            if y == 3:
                return 2, "in a,(%s)" % hx(n), None, False
            return 1, ["", "", "", "", "ex (sp),hl",
                       "ex de,hl", "di", "ei"][y], None, False
        if z == 4:
            return 3, "call %s,%s" % (CC[y], hx(nn, 4)), nn, False
        if z == 5:
            if q == 0:
                return 1, "push %s" % R16AF[p], None, False
            return 3, "call %s" % hx(nn, 4), nn, False
        if z == 6:
            return 2, "%s%s" % (ALU[y], hx(n)), None, False
        return 1, "rst %s" % hx(y * 8), y * 8, False

    def _cb(self, a):
        op = self.b(a + 1)
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        if x == 0:
            return 2, "%s %s" % (ROT[y], R8[z]), None, False
        return 2, "%s %d,%s" % (["", "bit", "res", "set"][x], y, R8[z]), None, False

    def _ed(self, a):
        op = self.b(a + 1)
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        p, q = y >> 1, y & 1
        if x == 1:
            if z == 0:
                return 2, "in %s,(c)" % ("f" if y == 6 else R8[y]), None, False
            if z == 1:
                return 2, "out (c),%s" % ("0" if y == 6 else R8[y]), None, False
            if z == 2:
                kw = "sbc" if q == 0 else "adc"
                return 2, "%s hl,%s" % (kw, R16SP[p]), None, False
            if z == 3:
                s = hx(self.w(a + 2), 4)
                if q == 0:
                    return 4, "ld (%s),%s" % (s, R16SP[p]), None, False
                return 4, "ld %s,(%s)" % (R16SP[p], s), None, False
            if z == 4:
                return 2, "neg", None, False
            if z == 5:
                return 2, ("reti" if y == 1 else "retn"), None, True
            if z == 6:
                return 2, "im %d" % [0, 0, 1, 2, 0, 0, 1, 2][y], None, False
            return 2, ["ld i,a", "ld r,a", "ld a,i", "ld a,r",
                       "rrd", "rld", "nop", "nop"][y], None, False
        if x == 2 and z < 4 and y >= 4:
            name = [["ldi", "cpi", "ini", "outi"],
                    ["ldd", "cpd", "ind", "outd"],
                    ["ldir", "cpir", "inir", "otir"],
                    ["lddr", "cpdr", "indr", "otdr"]]
            return 2, name[y - 4][z], None, False
        return 2, "db $ED,%s" % hx(op), None, False

    def _idx(self, a, ix):
        op = self.b(a + 1)
        if op == 0xCB:
            dd = (self.b(a + 2) ^ 0x80) - 0x80
            o2 = self.b(a + 3)
            x, y, z = o2 >> 6, (o2 >> 3) & 7, o2 & 7
            tgt = "(%s%+d)" % (ix, dd)
            if x == 0:
                s = "%s %s" % (ROT[y], tgt)
            else:
                s = "%s %d,%s" % (["", "bit", "res", "set"][x], y, tgt)
            if x != 1 and z != 6:
                s += ",%s" % R8[z]
            return 4, s, None, False
        sub = self.one_plain(a + 1)
        if sub is None:
            return 1, "db %s" % hx(self.b(a)), None, False
        ln, txt, tgt, end = sub
        if "(hl)" in txt:
            dd = (self.b(a + 2) ^ 0x80) - 0x80
            txt = txt.replace("(hl)", "(%s%+d)" % (ix, dd))
            ln += 1
        else:
            txt = txt.replace("hl", ix)
            txt = txt.replace(",h", "," + ix + "h").replace(",l", "," + ix + "l")
        return ln + 1, txt, tgt, end

    def one_plain(self, a):
        op = self.b(a)
        if op in (0xCB, 0xDD, 0xED, 0xFD):
            return None
        return self._main(a)


def load():
    sys.path.insert(0, os.path.join(HERE, "tools"))
    from unpack import unpack
    rom = rom_bytes()
    _m, _size, d, _e = unpack(rom, 0x207E)
    img = bytearray(0x2000)
    img[0x0000:0x0FD2] = d[0:0x0FD2]
    img[0x1100:0x1100 + 0x0AEE] = d[0x0FD2:0x0FD2 + 0x0AEE]
    img[0x1C00:0x1C0D] = rom[0xAA8:0xAA8 + 13]
    return img


def main():
    img = load()
    dis = Dis(img)
    a = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0
    n = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x1AC0
    end = a + n
    while a < end:
        ln, txt, _t, _e = dis.one(a)
        raw = " ".join("%02X" % img[a + i] for i in range(ln))
        print("%04X  %-12s %s" % (a, raw, txt))
        a += ln
    return 0


if __name__ == "__main__":
    sys.exit(main())
