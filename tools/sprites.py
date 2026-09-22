#!/usr/bin/env python3
"""Кадры спрайтов Maui Mallard в PNG.

    python tools/sprites.py 0 1 2            эти кадры
    python tools/sprites.py --sheet 900 64   лист: 64 кадра подряд с 900-го
    python tools/sprites.py --parts 150      сборный объект целиком
    python tools/sprites.py --pals           палитры, найденные в ROM
    make sprites SPRITE="--sheet 900 64"

Ключи: `--level 6` — взять палитру уровня (см. tools/levels.py),
`--pal 1FB158` — палитрой по адресу, `--scale 3` — увеличение,
`--row 2` — взять ряд палитры принудительно. Без них — серая шкала.

Всё, что нужно для рисования, лежит в самом кадре (см. tools/frames.py):
кусок называет описатель (форма и длина), источник тайлов и своё место.
Тайлы спрайта Mega Drive идут **по столбцам**: сверху вниз, потом
следующий столбец. Цвет 0 прозрачен.

Палитру кадр не хранит: в имени куска только ряд CRAM (0-3), а сами
цвета игра грузит отдельно — 128 байт (все четыре ряда) из ROM в
`$FFFFDC40` процедурой `$2A58B6`, оттуда в CRAM `$2A58C4`. Палитры уровней
лежат в поле `+$00` записи уровня (`--level`), а вне уровня блок грузит
сам экран перед отрисовкой — см. `--pals`, где каждый блок сведён
с тем местом кода, которое его грузит.

Для объектов НА УРОВНЕ связь полная: блок один на уровень (выбора у объекта
нет), ряд — биты 13-14 имени куска, значит пара «уровень + кадр» задаёт
цвет однозначно. Проверка и разбор — docs/mauimallard/enemy-catalog.md.
Руками блок задаётся только для кадров вне уровня.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT as out_path
from paths import rom_bytes

import frames as F

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM = rom_bytes()
GREY = [(17 * i, 17 * i, 17 * i) for i in range(16)]
LEVELS = 0x1FCB50   # таблица уровней, 23 записи; поле +$00 — палитра


def cram(a):
    """128 байт ROM -> четыре ряда по 16 цветов."""
    out = []
    for i in range(64):
        v = struct.unpack_from(">H", ROM, a + 2 * i)[0]
        out.append((((v >> 1) & 7) * 36, ((v >> 5) & 7) * 36,
                    ((v >> 9) & 7) * 36))
    return [out[r * 16:(r + 1) * 16] for r in range(4)]


def find_pals(least=12):
    """128-байтные участки, проходящие правило `0BGR`."""
    out, a = [], 0
    while a < len(ROM) - 128:
        ws = [struct.unpack_from(">H", ROM, a + 2 * j)[0] for j in range(64)]
        if not any(v & 0xF111 for v in ws) and len(set(ws)) >= least:
            out.append(a)
            a += 128
        else:
            a += 2
    return out



def loaders(window=8):
    """Где палитру ГРУЗЯТ: `lea $ADDR,a0`, а следом вызов загрузчика.

    Ищется по разобранному коду, а не по данным, поэтому список
    самоподдерживающийся: появится новый вызов — появится и строка.
    """
    import bisect
    import re as _re
    import enemies as _E
    lea = _re.compile(r"^(?:lea|movea\.l)\s+[(#]?\$([0-9A-F]{6,8})\)?\.?l?,a0")
    call = _re.compile(r"(?:bsr\.w|jsr)\s+\(?(PaletteFadeTo|PaletteLoad)")
    addrs = sorted(_E.BY)
    out = {}
    for i, a in enumerate(addrs):
        m = lea.match(_E.BY[a])
        if not m:
            continue
        for b in addrs[i + 1:i + 1 + window]:
            t = _E.BY[b]
            c = call.search(t)
            if c:
                out.setdefault(int(m.group(1), 16) & 0xFFFFFF,
                               []).append((a, c.group(1)))
                break
            if ",a0" in t or "(a0)" in t:
                break          # a0 переписали — эта пара не считается
    return out


def level_pals():
    """Блоки, на которые ссылается поле `+$00` записи уровня."""
    out = {}
    for i in range(23):
        r = struct.unpack_from(">I", ROM, 0x1FCB50 + 4 * i)[0]
        out.setdefault(struct.unpack_from(">I", ROM, r)[0], []).append(i)
    return out


def map_pals():
    """128 байт перед картой уровня: его собственная палитра.

    Запись графики (`+$08` записи уровня) держит в `+$04` адрес
    карты, а ровно за 128 байт до неё лежит блок цветов.
    """
    out = {}
    for i in range(23):
        r = struct.unpack_from(">I", ROM, 0x1FCB50 + 4 * i)[0]
        g = struct.unpack_from(">I", ROM, r + 8)[0]
        out.setdefault(struct.unpack_from(">I", ROM, g + 4)[0] - 0x80,
                       []).append(i)
    return out


def check_block(base, n=64):
    """Три числа: негодных слов, разных значений и ДЛИННЕЙШИЙ повтор.

    Повтор важен: правило `0BGR` дёшево проходится на рядах `$0000`
    и `$0EEE`, которых в картридже много, так что блок с длинным
    повтором — скорее графика или набивка, чем палитра.
    """
    ws = [struct.unpack_from(">H", ROM, base + 2 * j)[0] for j in range(n)]
    run = best = 1
    for j in range(1, n):
        run = run + 1 if ws[j] == ws[j - 1] else 1
        best = max(best, run)
    return sum(1 for v in ws if v & 0xF111), len(set(ws)), best


def tile(dst, src, ox, oy, pal, w, h):
    """Тайл 8x8, 4bpp, старший нибл слева. Цвет 0 прозрачен."""
    for y in range(8):
        py = oy + y
        if not (0 <= py < h):
            continue
        for xb in range(4):
            b = ROM[src + y * 4 + xb]
            for half, c in ((0, b >> 4), (1, b & 15)):
                px = ox + xb * 2 + half
                if c and 0 <= px < w:
                    dst[py * w + px] = pal[c] + (255,)


def draw(buf, w, h, x0, y0, piece, row=None):
    """Один кусок кадра: тайлы по столбцам от (x, y)."""
    d, name, x, y, src = piece
    tw, th = F.U16(d + 2) // 8, F.U16(d + 4) // 8
    pal = piece_pal(name, row)
    for k in range(tw * th):
        tile(buf, src + k * 32, x0 + x + (k // th) * 8,
             y0 + y + (k % th) * 8, pal, w, h)


PALS = None


def piece_pal(name, row):
    r = row if row is not None else (name >> 13) & 3
    return GREY if PALS is None else PALS[r]


def bounds(pieces):
    xs = [(x, x + F.U16(d + 2)) for d, _n, x, _y, _s in pieces]
    ys = [(y, y + F.U16(d + 4)) for d, _n, _x, y, _s in pieces]
    return (min(a for a, _b in xs), min(a for a, _b in ys),
            max(b for _a, b in xs), max(b for _a, b in ys))


def png(path, w, h, buf, scale=1):
    import zlib
    if scale > 1:
        big = [None] * (w * scale * h * scale)
        for y in range(h * scale):
            base = (y // scale) * w
            for x in range(w * scale):
                big[y * w * scale + x] = buf[base + x // scale]
        buf, w, h = big, w * scale, h * scale
    nul = bytes([0])
    raw = b"".join(nul + bytes(c for p in buf[r * w:(r + 1) * w]
                               for c in (p or (0, 0, 0, 0)))
                   for r in range(h))

    def chunk(tag, data):
        c = tag + data
        return (struct.pack(">I", len(data)) + c
                + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF))

    with open(path, "wb") as f:
        f.write(bytes([137, 80, 78, 71, 13, 10, 26, 10]))
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        f.write(chunk(b"IEND", b""))


def out_dir():
    d = out_path("gfx")
    os.makedirs(d, exist_ok=True)
    return d


def render_frame(i, scale=2, row=None):
    pieces = F.parse(F.U32(F.BASE + i * 4))
    if not pieces:
        print("кадр %d не разбирается" % i)
        return None
    x0, y0, x1, y1 = bounds(pieces)
    w, h = x1 - x0, y1 - y0
    buf = [None] * (w * h)
    for p in pieces:
        draw(buf, w, h, -x0, -y0, p, row)
    path = os.path.join(out_dir(), "frame_%04d.png" % i)
    png(path, w, h, buf, scale)
    print("кадр %d: %d кусков, %dx%d -> %s" % (i, len(pieces), w, h, path))
    return path


def render_parts(i, scale=2, row=None):
    """Сборный объект: части ставятся по своим смещениям."""
    at = F.PARTS + i * 4
    v = F.U32(at)
    items = F.parts(v)
    if not items:
        print("сборный объект %d пуст" % i)
        return None
    lk = F.U16(v + 2)
    fset = F.U32(lk)
    frame = lambda k: (F.U16(fset + 2 + k * 2) - F.BASE) // 4
    placed = []
    for idx, px, py, _fl in items:
        for d, name, x, y, src in F.parse(F.U32(F.BASE + frame(idx) * 4)):
            placed.append((d, name, x + px, y + py, src))
    x0, y0, x1, y1 = bounds(placed)
    w, h = x1 - x0, y1 - y0
    buf = [None] * (w * h)
    for p in placed:
        draw(buf, w, h, -x0, -y0, p, row)
    path = os.path.join(out_dir(), "parts_%03d.png" % i)
    png(path, w, h, buf, scale)
    print("сборный объект %d: %d частей, набор $%04X, %dx%d -> %s"
          % (i, len(items), lk, w, h, path))
    return path


def render_sheet(first, n, scale=1, row=None, per_row=8):
    """Лист: кадры сеткой, каждый в своей клетке."""
    got = []
    for i in range(first, first + n):
        pieces = F.parse(F.U32(F.BASE + i * 4))
        got.append((i, pieces, bounds(pieces)) if pieces else (i, None, None))
    cw = max((b[2] - b[0]) for _i, p, b in got if p) + 2
    ch = max((b[3] - b[1]) for _i, p, b in got if p) + 2
    rows = (len(got) + per_row - 1) // per_row
    w, h = cw * per_row, ch * rows
    buf = [None] * (w * h)
    for k, (_i, pieces, b) in enumerate(got):
        if not pieces:
            continue
        ox = (k % per_row) * cw + 1 - b[0]
        oy = (k // per_row) * ch + 1 - b[1]
        for p in pieces:
            draw(buf, w, h, ox, oy, p, row)
    path = os.path.join(out_dir(), "sheet_%04d_%d.png" % (first, n))
    png(path, w, h, buf, scale)
    print("лист: кадры %d-%d, клетка %dx%d, %dx%d -> %s"
          % (first, first + n - 1, cw, ch, w, h, path))
    return path


def main():
    global PALS
    argv = sys.argv[1:]
    scale, row, mode = 2, None, None
    args = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--pal":
            i += 1
            PALS = cram(int(argv[i], 16))
        elif a == "--level":
            i += 1
            n = int(argv[i], 0)
            PALS = cram(struct.unpack_from(
                ">I", ROM, struct.unpack_from(
                    ">I", ROM, LEVELS + n * 4)[0])[0])
        elif a == "--scale":
            i += 1
            scale = int(argv[i])
        elif a == "--row":
            i += 1
            row = int(argv[i])
        elif a in ("--sheet", "--parts", "--pals"):
            mode = a
        elif a.startswith("-"):
            print("неизвестный ключ %s" % a)
            return 2
        else:
            args.append(int(a, 0))
        i += 1

    if mode == "--pals":
        pals = find_pals()
        used = loaders()
        lvl = level_pals()
        mp = map_pals()
        print(u"палитр по правилу 0BGR: %d (по 128 байт, четыре ряда)"
              % len(pals))
        print(u"из них ГРУЗЯТ %d, и ещё %d блоков код грузит мимо находок"
              % (sum(1 for a in pals if any(abs(a - u) <= 4 for u in used)),
                 sum(1 for u in used if not any(abs(a - u) <= 4 for a in pals))))
        print()
        print(u"| блок | негодных | разных | длиннейший повтор | грузят из |")
        print(u"|---|---|---|---|---|")
        for a in sorted(set(list(used) + list(lvl) + pals)):
            near = [u for u in used if abs(a - u) <= 4]
            if a >= len(ROM):
                print(u"| `$%06X` | — | — | — | %s (адрес в ОЗУ: блок уровня) |"
                      % (a, u", ".join(u"$%06X %s" % (x, k)
                                       for x, k in used[a])))
                continue
            if a in pals and a not in used and a not in lvl and (
                    any(abs(a - u) <= 4 for u in used)
                    or any(abs(a - u) <= 4 for u in lvl)):
                continue          # та же палитра, найденная со сдвигом
            bad, uniq, run = check_block(a)
            who = used.get(a)
            lv = lvl.get(a)
            if who:
                src = u", ".join(u"$%06X %s" % (x, k) for x, k in who)
                if lv:
                    src += (u"; он же у уровня %s"
                            % u", ".join(str(x) for x in lv))
            elif lv:
                src = (u"запись уровня `+$00`: %s"
                       % u", ".join(str(x) for x in lv))
                if a in mp:
                    src += (u"; она же лежит перед картой %s"
                            % u", ".join(str(x) for x in mp[a]))
            else:
                near_map = [x for x in mp if abs(a - x) <= 4]
                known = [x for x in list(used) + list(lvl)
                         if x < len(ROM) and 0 < abs(a - x) < 128]
                if near_map:
                    src = (u"перед картой уровня %s, но не грузится"
                           % u", ".join(str(x) for x in mp[near_map[0]]))
                elif known:
                    src = u"*никто*; накладывается на $%06X" % known[0]
                else:
                    src = u"*никто*"
            print(u"| `$%06X` | %d | %d | %d | %s |"
                  % (a, bad, uniq, run, src))
        print()
        print(u"Длиннейший повтор НЕ отличает палитру от данных: у"
              u" загружаемого `$1F80BA` он 48.")
        return 0
    if mode == "--sheet":
        render_sheet(args[0] if args else 0, args[1] if len(args) > 1 else 64,
                     scale, row)
        return 0
    if mode == "--parts":
        for a in args or [6]:
            render_parts(a, scale, row)
        return 0
    for a in args or [0]:
        render_frame(a, scale, row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
