#!/usr/bin/env python3
"""Память видеочипа Mega Drive и кадр из неё — для эталонных картинок `romtrace.py`.

Модель без тактов: порты `$C00000` (данные) и `$C00004` (управление), 24 регистра,
VRAM 64 КБ, CRAM (64 слова), VSRAM (40 слов), автоинкремент (регистр 15), DMA
68000 → VDP (источник — ROM или ОЗУ через `read_word`), заливка и копирование VRAM.
Чтения портов остаются за `romtrace.py` (от них зависит логика игры).

`picture()` рисует кадр H40 320×224 по правилам VDP: фон (регистр 7), плоскости B и A
(размер — регистр 16; прокрутка по горизонтали целиком, по полосам 8 строк или по
строкам — регистр 11 и таблица регистра 13; по вертикали целиком или по столбцам 16
точек — VSRAM), окно вместо A (регистры 17, 18), спрайты по связям от записи 0
(регистр 5): не больше 80, 20 на строку и 320 точек на строку, первая непрозрачная
точка выигрывает. Слой пикселя: B, A, спрайты; высокий приоритет над низким.
Цвет CRAM — канал × 36, как у ремейка и `sprites.py`.

Не смоделировано и отвергается: режим тени и подсветки (регистр 12 бит 3), чересстрочный
режим, H32, маска спрайта с X = 0.
"""
import struct

VRAM, CRAM, VSRAM = 1, 3, 5
WIDTH, HEIGHT = 320, 224


class Vdp:
    def __init__(self, read_word, registers=None):
        self.read_word = read_word
        self.reg = list(registers) if registers else [0] * 24
        self.vram = bytearray(0x10000)
        self.cram = [0] * 64
        self.vsram = [0] * 40
        self.code = 0
        self.addr = 0
        self.pending = False
        self.fill = False
        self.writes = 0

    # --- порты ---

    def write(self, offset, size, value):
        """Запись в `$C00000 + offset` размером 1, 2 или 4 байта."""
        if size == 4:
            self.write(offset, 2, (value >> 16) & 0xFFFF)
            self.write(offset + 2, 2, value & 0xFFFF)
            return
        if size == 1:
            value = (value & 0xFF) * 0x101
        port = offset & 0x1F
        if port < 4:
            self._data(value & 0xFFFF)
        elif port < 8:
            self._control(value & 0xFFFF)

    def _control(self, w):
        if not self.pending:
            if w & 0xC000 == 0x8000:
                r = (w >> 8) & 0x1F
                if r < 24:
                    self.reg[r] = w & 0xFF
                return
            self.code = (self.code & 0x3C) | (w >> 14)
            self.addr = (self.addr & 0xC000) | (w & 0x3FFF)
            self.pending = True
            return
        self.pending = False
        self.code = (self.code & 0x03) | ((w >> 2) & 0x3C)
        self.addr = (self.addr & 0x3FFF) | ((w & 3) << 14)
        if self.code & 0x20 and self.reg[1] & 0x10:
            mode = self.reg[23] >> 6
            if mode < 2:
                self._dma_68k()
            elif mode == 2:
                self.fill = True
            else:
                self._dma_copy()

    def _length(self):
        n = self.reg[19] | self.reg[20] << 8
        return n or 0x10000

    def _dma_68k(self):
        high = (self.reg[23] & 0x7F) << 17
        low = self.reg[21] | self.reg[22] << 8          # слово адреса, крутится в 64К слов
        for _ in range(self._length()):
            self._store(self.read_word(high | low << 1))
            low = (low + 1) & 0xFFFF
        self.reg[21], self.reg[22] = low & 0xFF, low >> 8
        self.code &= 0x1F

    def _dma_copy(self):
        src = self.reg[21] | self.reg[22] << 8
        for _ in range(self._length()):
            self.vram[self.addr ^ 1] = self.vram[src ^ 1]
            src = (src + 1) & 0xFFFF
            self.addr = (self.addr + self.reg[15]) & 0xFFFF
        self.code &= 0x1F

    def _data(self, w):
        self.pending = False
        if self.fill:
            self.fill = False
            self._store(w)
            for _ in range(self._length()):
                self.vram[self.addr ^ 1] = w >> 8
                self.addr = (self.addr + self.reg[15]) & 0xFFFF
            self.code &= 0x1F
            return
        self._store(w)

    def _store(self, w):
        target = self.code & 0x0F
        a = self.addr
        if target == VRAM:
            base = a & 0xFFFE
            hi, lo = (w & 0xFF, w >> 8) if a & 1 else (w >> 8, w & 0xFF)
            self.vram[base], self.vram[base + 1] = hi, lo
        elif target == CRAM:
            self.cram[(a >> 1) & 63] = w & 0x0EEE
        elif target == VSRAM:
            if (a >> 1) < 40:
                self.vsram[a >> 1] = w & 0x07FF
        self.writes += 1
        self.addr = (a + self.reg[15]) & 0xFFFF

    # --- кадр ---

    def word(self, a):
        a &= 0xFFFF
        return self.vram[a] << 8 | self.vram[(a + 1) & 0xFFFF]

    def _tile_pixel(self, name, x, y):
        if name & 0x0800:
            x = 7 - x
        if name & 0x1000:
            y = 7 - y
        b = self.vram[((name & 0x7FF) * 32 + y * 4 + (x >> 1)) & 0xFFFF]
        return b & 15 if x & 1 else b >> 4

    def check(self):
        """Почему кадр нельзя нарисовать этой моделью, или None."""
        r = self.reg
        if r[12] & 0x08:
            return "режим тени и подсветки (регистр 12 = $%02X)" % r[12]
        if r[12] & 0x06:
            return "чересстрочный режим (регистр 12 = $%02X)" % r[12]
        if r[12] & 0x81 != 0x81:
            return "не H40 (регистр 12 = $%02X)" % r[12]
        if r[11] & 3 == 1:
            return "недопустимый режим прокрутки (регистр 11 = $%02X)" % r[11]
        return None

    def picture(self, sprites=True, skip_tiles=None):
        """-> список (r, g, b) по строкам, 320 × 224. skip_tiles — range номеров тайлов:
        спрайты с таким тайлом не рисуются и в пределах строки не считаются."""
        why = self.check()
        if why:
            raise ValueError(why)
        r = self.reg
        pal = [(((c >> 1) & 7) * 36, ((c >> 5) & 7) * 36, ((c >> 9) & 7) * 36) for c in self.cram]
        sizes = {0: 32, 1: 64, 3: 128}
        pw, ph = sizes.get(r[16] & 3, 32), sizes.get((r[16] >> 4) & 3, 32)
        base_a, base_b = (r[2] & 0x38) << 10, (r[4] & 7) << 13
        base_w, base_h = (r[3] & 0x3C) << 10, (r[13] & 0x3F) << 10
        hmode, vcol = r[11] & 3, r[11] & 4
        whp, right = (r[17] & 0x1F) * 16, r[17] & 0x80
        wvp, down = (r[18] & 0x1F) * 8, r[18] & 0x80

        def plane(base, x, y, hs, vs):
            px, py = (x - hs) & (pw * 8 - 1), (y + vs) & (ph * 8 - 1)
            name = self.word(base + ((py >> 3) * pw + (px >> 3)) * 2)
            c = self._tile_pixel(name, px & 7, py & 7)
            return (name >> 15, (name >> 13 & 3) * 16 + c) if c else None

        lines = self._sprite_lines(skip_tiles) if sprites else [[None] * WIDTH for _ in range(HEIGHT)]
        out = []
        for y in range(HEIGHT):
            line = y if hmode == 3 else (y & ~7 if hmode == 2 else 0)
            hs_a = self.word(base_h + line * 4) & 0x3FF
            hs_b = self.word(base_h + line * 4 + 2) & 0x3FF
            in_rows = (y >= wvp) if down else (y < wvp)
            sprite_line = lines[y]
            for x in range(WIDTH):
                col = (x >> 4) * 2 if vcol else 0
                best, rank = None, -1
                b = plane(base_b, x, y, hs_b, self.vsram[col + 1] & 0x3FF)
                if b:
                    best, rank = b[1], b[0] * 3
                in_cols = (x >= whp) if right else (x < whp)
                if in_rows or in_cols:
                    name = self.word(base_w + ((y >> 3) * 64 + (x >> 3)) * 2)
                    c = self._tile_pixel(name, x & 7, y & 7)
                    a = (name >> 15, (name >> 13 & 3) * 16 + c) if c else None
                else:
                    a = plane(base_a, x, y, hs_a, self.vsram[col] & 0x3FF)
                if a and a[0] * 3 + 1 > rank:
                    best, rank = a[1], a[0] * 3 + 1
                s = sprite_line[x]
                if s and s[0] * 3 + 2 > rank:
                    best, rank = s[1], s[0] * 3 + 2
                out.append(pal[best] if best is not None else pal[r[7] & 0x3F])
        return out

    def _sprite_lines(self, skip):
        sat = (self.reg[5] & 0x7E) << 9
        order, e = [], 0
        while len(order) < 80:
            y, size, link, name, x = struct.unpack(">HBBHH", bytes(self.vram[sat + e * 8:sat + e * 8 + 8]))
            order.append((y & 0x1FF, size, name, x & 0x1FF))
            link &= 0x7F
            if link == 0 or link >= 80:
                break
            e = link
        lines = []
        for yy in range(HEIGHT):
            line = [None] * WIDTH
            vy, count, dots = yy + 0x80, 0, 0
            for top, size, name, left in order:
                if dots >= 320:
                    break
                if skip is not None and (name & 0x7FF) in skip:
                    continue
                rows, cols = ((size & 3) + 1) * 8, (((size >> 2) & 3) + 1) * 8
                row = (vy - top) & 0x1FF
                if row >= rows:
                    continue
                count += 1
                if count > 20:
                    break
                if left == 0:
                    raise ValueError("спрайт с X = 0 (маска) не смоделирован")
                drawn = min(cols, 320 - dots)
                dots += cols
                if name & 0x1000:
                    row = rows - 1 - row
                for c in range(drawn):
                    sx = left - 0x80 + c
                    if not 0 <= sx < WIDTH or line[sx]:
                        continue
                    col = cols - 1 - c if name & 0x0800 else c
                    tile = (name & 0x7FF) + (col >> 3) * (rows >> 3) + (row >> 3)
                    b = self.vram[(tile * 32 + (row & 7) * 4 + ((col & 7) >> 1)) & 0xFFFF]
                    v = b & 15 if col & 1 else b >> 4
                    if v:
                        line[sx] = (name >> 15, (name >> 13 & 3) * 16 + v)
            lines.append(line)
        return lines
