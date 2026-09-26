#!/usr/bin/env python3
"""Графика кадров для ремейка Maui Mallard: атлас тайлов и `sprites.json`.

    SEGA2ASM_CONFIG=platformer.yaml python tools/spritespec.py          выгрузка
    SEGA2ASM_CONFIG=platformer.yaml python tools/spritespec.py --check  только проверка

Ремейк собирает спрайты сам, кусок за куском, как `$29612E`/`$296208`, поэтому
получает кадры **как у видеочипа** (решение 3b): тайлы индексами и записи
кадров без перерисовки.

* `sprites/sprite_tiles.png` — тайлы кадров 8x8 по 32 в ряд, индексами (серая
  шкала `17 * цвет`, цвет 0 прозрачен), как `levels/levelNN_tiles.png`. Тайлы
  кадров в ROM не сжаты и уходят в VRAM прямым DMA; куски ссылаются на один
  сплошной отрезок `$003938`-`$1AE558`, поэтому атлас — этот отрезок как есть,
  и тайл атласа `t` лежит в ROM по `$003938 + 32 * t` (`tiles_sha256` —
  SHA-256 этих байт ROM, для сверки атласа). Тайлы куска идут **по
  столбцам**: сверху вниз, потом следующий столбец.
* `sprites/sprites.json`:
  * `shapes` — 16 описателей `$3898`-`$392E` (по 10 байт): слово размера для
    таблицы спрайтов, ширина, высота, шаг VRAM в байтах, длина DMA в словах;
  * `frames` — 2 880 кадров таблицы `$000200` в её порядке: адрес записи
    (его держит `+$C` объекта), общая коробка `+4` (x0, x1, y0, y1),
    куски `[описатель, имя, x, y, первый тайл атласа]` (имя — слово как в
    ROM: бит 15 приоритет, 14-13 ряд палитры, тайл 0), подробные коробки
    `[x0, x1, y0, y1, номер бита]` (по 6 байт, `$2A028A`, `$2964DA`);
  * `sets` — шесть наборов графики `$2F00`-`$2F14`: номера кадров;
  * `composites` — 608 сборных объектов `$2F18`-`$3894`: слот набора и
    части как два слова ROM `[A, B]` — их разбирает `$296D88` (A: биты 4-0
    кадр в наборе, 15-5 x; B: 10-0 y, 11/12 отражения, 13/14 флаги).

Проверка: все 2 880 записей разбираются как кадры, описатели — формула
размеров Mega Drive, тайлы кусков внутри отрезка и отрезок без дыр, номера
кадров наборов — в таблице, номер части — в своём наборе.
"""
import hashlib
import io
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT, rom_bytes  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM = rom_bytes()
U16 = lambda o: struct.unpack_from(">H", ROM, o)[0]
U32 = lambda o: struct.unpack_from(">I", ROM, o)[0]
S8 = lambda o: struct.unpack_from(">b", ROM, o)[0]

FRAMES = 0x000200          # таблица кадров: длинное слово на кадр
FRAME_COUNT = 2880         # до $002F00
PARTS = 0x002F00           # наборы графики, потом сборные объекты
TAB_END = 0x003898
SETS = 6
SHAPES = (0x003898, 0x003938)
TILES = 0x003938           # первый тайл кадров
TILES_PER_ROW = 32


class Bad(Exception):
    pass


def check(cond, what):
    if not cond:
        raise Bad(what)


def shapes():
    out = []
    for k, d in enumerate(range(SHAPES[0], SHAPES[1], 10)):
        size, w, h, step, words = (U16(d + i) for i in range(0, 10, 2))
        tw, th = k >> 2, k & 3
        check((size, w, h, step, words) ==
              (((tw << 2) | th) << 8, 8 * (tw + 1), 8 * (th + 1),
               32 * (tw + 1) * (th + 1), 16 * (tw + 1) * (th + 1)),
              "описатель $%04X не по формуле" % d)
        out.append(dict(at="$%04X" % d, size=size, width=w, height=h,
                        vram_bytes=step, dma_words=words))
    return out


def frame(i):
    """-> (запись для JSON, [(первый байт тайлов, конец)])"""
    v = U32(FRAMES + 4 * i)
    n = U16(v) + 1
    check(1 <= n <= 80, "кадр %d ($%06X): кусков %d" % (i, v, n))
    pieces, spans, a = [], [], v + 8
    for _ in range(n):
        d, name, src = U16(a), U16(a + 2), U32(a + 6) * 2
        check(SHAPES[0] <= d < SHAPES[1] and (d - SHAPES[0]) % 10 == 0,
              "кадр %d: описатель $%04X" % (i, d))
        check(name & 0x1FFF == 0, "кадр %d: в имени $%04X не только палитра и "
                                  "приоритет" % (i, name))
        check(src >= TILES and (src - TILES) % 32 == 0,
              "кадр %d: источник $%06X не на границе тайла" % (i, src))
        length = U16(d + 6)
        spans.append((src, src + length))
        pieces.append([(d - SHAPES[0]) // 10, name, S8(a + 4), S8(a + 5),
                       (src - TILES) // 32])
        a += 10
    boxes = []
    for _ in range(U16(v + 2)):
        num = U16(a + 4)
        check(num < 16, "кадр %d: номер коробки %d" % (i, num))
        boxes.append([S8(a), S8(a + 1), S8(a + 2), S8(a + 3), num])
        a += 6
    rec = dict(at="$%06X" % v,
               box=[S8(v + 4), S8(v + 5), S8(v + 6), S8(v + 7)],
               pieces=pieces, boxes=boxes)
    return rec, spans


def tile_span(spans):
    """Все куски — один сплошной отрезок от TILES без дыр; -> его конец."""
    spans = sorted(spans)
    end = TILES
    for s, e in spans:
        check(s <= end, "в тайлах кадров дыра $%06X-$%06X" % (end, s))
        end = max(end, e)
    check(end <= len(ROM), "тайлы за концом ROM")
    return end


def sets():
    out = []
    for k in range(SETS):
        slot = PARTS + 4 * k
        v = U32(slot)
        n = U16(v)
        check(1 <= n <= 24, "набор $%04X: кадров %d" % (slot, n))
        frames = []
        for j in range(n):
            w = U16(v + 2 + 2 * j)
            check(FRAMES <= w < PARTS and w % 4 == 0,
                  "набор $%04X: слот $%04X" % (slot, w))
            frames.append((w - FRAMES) // 4)
        out.append(dict(slot="$%04X" % slot, at="$%06X" % v, frames=frames))
    return out


def composites(set_list):
    size = {int(s["slot"][1:], 16): len(s["frames"]) for s in set_list}
    out = []
    for slot in range(PARTS + 4 * SETS, TAB_END, 4):
        v = U32(slot)
        n, link = U16(v), U16(v + 2)
        check(n <= 64, "сборный объект $%04X: частей %d" % (slot, n))
        parts = []
        for j in range(n):
            a, b = U16(v + 4 + 4 * j), U16(v + 6 + 4 * j)
            check(link in size, "сборный объект $%04X: набор $%04X" % (slot, link))
            check((a & 31) < size[link], "сборный объект $%04X: кадр %d вне набора "
                                         "$%04X" % (slot, a & 31, link))
            parts.append([a, b])
        out.append(dict(slot="$%04X" % slot, at="$%06X" % v, set="$%04X" % link,
                        parts=parts))
    return out


def tiles_png(count, path):
    import sprites as S
    rows = (count + TILES_PER_ROW - 1) // TILES_PER_ROW
    w, h = TILES_PER_ROW * 8, rows * 8
    grey = [(17 * c, 17 * c, 17 * c, 255 if c else 0) for c in range(16)]
    buf = [(0, 0, 0, 0)] * (w * h)
    for i in range(count):
        ox, oy = (i % TILES_PER_ROW) * 8, (i // TILES_PER_ROW) * 8
        t = TILES + 32 * i
        for y in range(8):
            row = (oy + y) * w + ox
            for xb in range(4):
                b = ROM[t + 4 * y + xb]
                buf[row + 2 * xb] = grey[b >> 4]
                buf[row + 2 * xb + 1] = grey[b & 15]
    S.png(path, w, h, buf)


def dump(doc):
    """JSON с кадром, набором и сборным объектом на строку — для диффов."""
    head = {k: v for k, v in doc.items() if k not in ("frames", "sets", "composites")}
    text = json.dumps(head, ensure_ascii=False, indent=1)[:-2]
    for key in ("frames", "sets", "composites"):
        rows = ",\n  ".join(json.dumps(r, ensure_ascii=False, separators=(",", ":"))
                            for r in doc[key])
        text += ',\n "%s": [\n  %s\n ]' % (key, rows)
    return text + "\n}\n"


def main():
    try:
        shape_list = shapes()
        frames, spans = [], []
        for i in range(FRAME_COUNT):
            rec, sp = frame(i)
            frames.append(rec)
            spans += sp
        end = tile_span(spans)
        set_list = sets()
        comp = composites(set_list)
    except Bad as e:
        print("ошибка:", e)
        return 1
    count = (end - TILES) // 32
    pieces = sum(len(f["pieces"]) for f in frames)
    boxes = sum(len(f["boxes"]) for f in frames)
    print("кадров %d, кусков %d, коробок %d; тайлов %d ($%06X-$%06X); "
          "наборов %d, сборных объектов %d, частей %d"
          % (len(frames), pieces, boxes, count, TILES, end, len(set_list),
             len(comp), sum(len(c["parts"]) for c in comp)))
    if "--check" in sys.argv:
        return 0

    out = OUT("export", "sprites")
    if not os.path.isdir(out):
        os.makedirs(out)
    tiles_png(count, os.path.join(out, "sprite_tiles.png"))
    doc = {
        "meta": {
            "game": "Maui Mallard in Cold Shadow (Mega Drive)",
            "generator": "tools/spritespec.py",
            "readers": "sprite table $29612E/$296208, DMA $2960DE, VRAM $296D22, "
                       "boxes $296314/$2A028A/$2964DA, parts $296F68/$296D88",
        },
        "frame_table": "$%06X" % FRAMES,
        "composite_table": "$%06X" % PARTS,
        "tiles_png": "sprite_tiles.png",
        "tiles_base": "$%06X" % TILES,
        "tiles": count,
        "tiles_sha256": hashlib.sha256(ROM[TILES:end]).hexdigest(),
        "shapes": shape_list,
        "frames": frames,
        "sets": set_list,
        "composites": comp,
    }
    with io.open(os.path.join(out, "sprites.json"), "w", encoding="utf-8",
                 newline="\n") as f:
        f.write(dump(doc))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
