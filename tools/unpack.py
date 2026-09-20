#!/usr/bin/env python3
"""Распаковщик трапа `$FF10` — все пять методов.

    python tools/unpack.py 060424          # распаковать блок по адресу
    python tools/unpack.py 060424 --hex    # и напечатать дамп

Заголовок блока: слово — длина результата, байт — номер метода.
Диспетчер `$000D42` вычитает из номера единицу и прыгает по таблице
`data_12` = `$000D5A`; методы 4 и 5 в ней указывают на саму таблицу,
то есть не существуют.

| метод | адрес | схема |
|---|---|---|
| 1 | `$000D68` | LZ77, расстояние байтом |
| 2 | `$000DF8` | словарь плюс унарный код, без ссылок |
| 3 | `$000E98` | LZ77, расстояние байтом или словом |
| 6 | `$0011B0` | адаптивный Хаффман плюс ссылки, блоками |
| 7 | `$000F3A` | словарь плюс унарный код плюс ссылки, блоками |

Ниже — построчное повторение кода BIOS, а не вольный пересказ: проверка
в том, что распакованное совпадает по длине с заголовком и разбирается
как ожидаемая структура.
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

# Классы унарного кода, `data_13` = $000E7C: (сколько бит дочитать, база).
CLASSES = [(0, 0), (3, 1), (4, 9), (5, 25), (6, 64), (7, 128), (3, 57)]


class Bits:
    """Чтение бит от старшего к младшему, как в BIOS."""

    def __init__(self, buf, pos):
        self.b = buf
        self.p = pos
        self.cur = buf[self.p]
        self.p += 1
        self.n = 7                      # индекс следующего бита в cur
        self.last = self.p - 1          # последний использованный байт

    def bit(self):
        self.last = self.p - 1
        v = (self.cur >> self.n) & 1
        self.n -= 1
        if self.n < 0:
            self.n = 7
            self.cur = self.b[self.p]
            self.p += 1
        return v

    def bits(self, k):
        v = 0
        for _ in range(k):
            v = (v << 1) | self.bit()
        return v

    def byte(self):
        """Восемь бит подряд — `loc_0012FA` и `loc_00104E`."""
        return self.bits(8)

    def unary(self):
        """Считать единицы до нуля."""
        n = 0
        while self.bit():
            n += 1
        return n


def copy_match(out, dist, count):
    src = len(out) - dist
    for _ in range(count):
        out.append(out[src])
        src += 1


def m1(rom, a, size):
    out = bytearray()
    p = a + 3
    while len(out) < size:
        t = rom[p]
        p += 1
        if t < 0x80:
            out += rom[p:p + t + 1]
            p += t + 1
        else:
            n = (t & 0x7F) + 1
            copy_match(out, rom[p] + 1, n)
            p += 1
    return out, p


def m3(rom, a, size):
    out = bytearray()
    p = a + 3
    while len(out) < size:
        t = rom[p]
        p += 1
        if t < 0x80:
            out += rom[p:p + t + 1]
            p += t + 1
        else:
            n = (t & 0x3F) + 1
            if t & 0x40:
                d = (rom[p] << 8) | rom[p + 1]
                p += 2
            else:
                d = rom[p]
                p += 1
            copy_match(out, d + 1, n)
    return out, p


def m2(rom, a, size):
    dsize = rom[a + 3]
    dic = a + 4
    bs = Bits(rom, dic + dsize)
    out = bytearray()
    while len(out) < size:
        k = bs.unary()
        extra, base = CLASSES[k]
        out.append(rom[dic + base + bs.bits(extra)])
    return out, bs.last + 1


def m7(rom, a, size):
    blocks = rom[a + 3]
    dsize = rom[a + 4] or 0x100
    dic = a + 5
    p = dic + dsize
    out = bytearray()
    for _ in range(blocks):
        left = (rom[p] << 8) | rom[p + 1]
        bs = Bits(rom, p + 2)
        while left:
            t = bs.byte()
            if t < 0x80:
                for _ in range(t + 1):
                    k = bs.unary()
                    extra, base = CLASSES[k]
                    out.append(rom[dic + base + bs.bits(extra)])
                left -= t + 1
            else:
                n = (t & 0x7F) + 1
                d = bs.bits(8)
                if t & 0x40:
                    n -= 0x40
                    d = (d << 2) | bs.bits(2)
                copy_match(out, d + 1, n)
                left -= n
        p = bs.last + 1
    return out, p


# ── Метод 6: адаптивный Хаффман ──────────────────────────────────────────
# Узел 10 байт: +0 левый, +2 правый, +4 родитель, +6 чей ребёнок (0 или 2),
# +8 вес. Листья 0..255 лежат по смещениям 0, 10, ..., 2550; корень $13EC.
LEAF = 0xFFFF
ROOT = 0x13EC


class Tree:
    def __init__(self):
        self.L = {}
        self.R = {}
        self.P = {}
        self.S = {}
        self.W = {}
        # листья
        d2 = 0
        for i in range(256):
            o = i * 10
            self.L[o] = LEAF
            self.R[o] = LEAF
            self.P[o] = ((i >> 1) + 0x100) * 10
            self.W[o] = 1
            self.S[o] = d2
            d2 ^= 2
        # внутренние узлы: восемь уровней сверху вниз по 2^d7 штук
        child = 0
        weight = 2
        side = 0
        idx = 0x100
        off = 0x0A00
        for d7 in range(7, -1, -1):
            for _ in range(1 << d7):
                self.L[off] = child
                child += 10
                self.R[off] = child
                child += 10
                self.W[off] = weight
                self.S[off] = side
                self.P[off] = ((idx >> 1) + 0x100) * 10
                side ^= 2
                idx += 1
                off += 10
            weight += weight
        self.P[ROOT] = LEAF

    def depth(self, o):
        d = 0
        while self.P[o] != LEAF:
            o = self.P[o]
            d += 1
        return d

    def bump(self, o):
        while o != LEAF:
            self.W[o] += 1
            o = self.P[o]

    def find(self, node, want, avoid, budget):
        """`Bios_00114E`: обход сверху, первый узел нужного веса."""
        if budget == 0:
            return -1
        if self.W[node] == want:
            return node
        for ch in (self.L[node], self.R[node]):
            if ch == avoid or ch == LEAF:
                continue
            r = self.find(ch, want, avoid, budget - 1)
            if r >= 0:
                return r
        return -1

    def swap(self, a, b):
        """`loc_00111C`: поменять узлы местами вместе со связями."""
        pa, pb = self.P[a], self.P[b]
        self.P[a], self.P[b] = pb, pa
        sa, sb = self.S[a], self.S[b]
        self.S[a], self.S[b] = sb, sa
        # у нового родителя a записать b по старому месту a, и наоборот
        (self.L if sa == 0 else self.R)[pa] = b
        (self.L if sb == 0 else self.R)[pb] = a


def m6(rom, a, size):
    t = Tree()
    p = a + 3
    blocks = rom[p]
    p += 1
    out = bytearray()
    for _ in range(blocks):
        left = (rom[p] << 8) | rom[p + 1]
        bs = Bits(rom, p + 2)
        while left:
            tok = bs.byte()
            if tok < 0x80:
                for _ in range(tok + 1):
                    node = ROOT
                    while True:
                        ch = t.R[node] if bs.peek() else t.L[node]
                        if ch == LEAF:
                            break
                        node = ch
                        bs.bit()
                    out.append(node // 10)
                    t.bump(node)
                    d = t.depth(node)
                    found = t.find(ROOT, t.W[node], t.P[node], d)
                    if found >= 0 and found != node:
                        t.swap(found, node)
                left -= tok + 1
            else:
                n = (tok & 0x7F) + 1
                d = bs.bits(8)
                if tok & 0x40:
                    n -= 0x40
                    d = (d << 2) | bs.bits(2)
                copy_match(out, d + 1, n)
                left -= n
        p = bs.last + 1
    return out, p


def peek(self):
    return (self.cur >> self.n) & 1


Bits.peek = peek

METHODS = {1: m1, 2: m2, 3: m3, 6: m6, 7: m7}


def unpack(rom, a):
    size = (rom[a] << 8) | rom[a + 1]
    method = rom[a + 2]
    if method not in METHODS:
        raise ValueError("метод %d не существует" % method)
    out, end = METHODS[method](rom, a, size)
    return method, size, bytes(out[:size]), end


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    rom = rom_bytes()
    a = int(sys.argv[1], 16)
    method, size, data, end = unpack(rom, a)
    print("$%06X: метод %d, длина %d, распаковано %d, сжатых байт %d"
          % (a, method, size, len(data), end - a))
    if "--hex" in sys.argv:
        for i in range(0, len(data), 16):
            print("  %04X  %s" % (i, " ".join("%02X" % b
                                              for b in data[i:i + 16])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
