#!/usr/bin/env python3
"""Распаковщик Maui Mallard: LZSS на битовом потоке (`$29766A`).

    python tools/lzss.py 20B670          распаковать и показать сводку
    python tools/lzss.py 20B670 --save   положить в out/<проект>/gfx/

**Поправка к graphics.md.** Раньше здесь было сказано, что распаковщика в
игре нет. Для кадров спрайтов это так: их тайлы уходят в VRAM прямой
передачей из ROM. Но **графика уровней сжата**, и распаковщик есть —
`$29766A`, его зовёт загрузчик уровня `$291012`.

Формат потока (вычитан из `$297612`, `$297622`, `$29766A`):

* поток читается **длинными словами**, биты идут от старшего;
* `1` — дальше восемь бит литерала;
* `0` — дальше десять бит расстояния назад и четыре бита длины;
  расстояние 0 означает конец, длина = четыре бита плюс два,
  то есть копируются от 2 до 17 байт;
* копирование побайтовое и **перекрытие разрешено**: расстояние 1
  размножает последний байт.

Таблица масок `(1 << n) - 1` лежит в ROM по `$1EAD10` — она нужна только
ассемблерной версии, здесь маски считаются.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT as out_path
from paths import rom_bytes

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM = rom_bytes()
MASKS = 0x1EAD10


class Stream(object):
    """Битовый поток, как его читает `$297612` / `$297622`."""

    def __init__(self, rom, at):
        self.rom = rom
        self.at = at
        self.buf = 0
        self.left = 0

    def _fill(self):
        self.buf = struct.unpack_from(">I", self.rom, self.at)[0]
        self.at += 4

    def bit(self):
        self.left -= 1
        if self.left < 0:
            self._fill()
            self.left = 31
        b = (self.buf >> 31) & 1
        self.buf = (self.buf << 1) & 0xFFFFFFFF
        return b

    def take(self, n):
        """n бит. Слово может кончиться посередине — тогда склейка."""
        if self.left == 0:
            self._fill()
            self.left = 32
        if self.left >= n:
            self.left -= n
            v = (self.buf >> (32 - n)) & ((1 << n) - 1)
            self.buf = (self.buf << n) & 0xFFFFFFFF
            return v
        k = self.left
        hi = (self.buf >> (32 - k)) & ((1 << k) - 1)
        self._fill()
        rest = n - k
        self.left = 32 - rest
        lo = (self.buf >> (32 - rest)) & ((1 << rest) - 1)
        self.buf = (self.buf << rest) & 0xFFFFFFFF
        return (hi << rest) | lo


def unpack(at, rom=None, limit=1 << 22):
    """-> (распакованное, сколько байт съедено в ROM)."""
    rom = ROM if rom is None else rom
    s = Stream(rom, at)
    out = bytearray()
    while len(out) < limit:
        if s.bit():
            out.append(s.take(8))
            continue
        dist = s.take(10)
        if dist == 0:
            return bytes(out), s.at - at
        n = s.take(4) + 2
        if dist > len(out):
            raise ValueError("$%06X: ссылка назад за начало (%d > %d)"
                             % (at, dist, len(out)))
        for _ in range(n):
            out.append(out[-dist])
    raise ValueError("$%06X: конца потока нет за %d байт" % (at, limit))


def looks_packed(at):
    """Грубая проверка: распаковывается ли и во что-то осмысленное."""
    try:
        data, used = unpack(at)
    except Exception:
        return None
    return (len(data), used) if used > 8 and len(data) > used else None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__)
        return 2
    at = int(args[0], 16)
    data, used = unpack(at)
    print("$%06X: %d байт сжатого -> %d байт (x%.2f)"
          % (at, used, len(data), len(data) / used))
    print("  начало: %s" % " ".join("%02X" % b for b in data[:32]))
    same = sum(1 for b in data if (b >> 4) == (b & 15))
    print("  байт с одинаковыми ниблами: %.0f%% (у тайлов 4bpp обычно много)"
          % (100.0 * same / len(data)))
    if "--save" in sys.argv:
        d = out_path("gfx")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "unpacked_%06X.bin" % at)
        with open(p, "wb") as f:
            f.write(data)
        print("  -> %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
