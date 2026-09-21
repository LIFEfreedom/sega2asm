#!/usr/bin/env python3
u"""Анимации юнитов поодиночке: своя полоса кадров на каждую анимацию.

    python tools/unitanim.py            # все различные наборы
    python tools/unitanim.py 5          # только тип 5
    python tools/unitanim.py 5 --split  # и отдельным файлом на анимацию

`unitgfx.py` сваливает все кадры типа в один лист и убирает повторы —
этого хватает, чтобы опознать вид, но не чтобы им анимировать. Здесь
каждая анимация выводится **отдельной полосой** в порядке показа, с
длительностями и точкой возврата, а рядом кладётся `units.json` для
переноса в чужой движок.

## Что такое одна анимация

Набор анимаций юнита — 232 байта, то есть **29 записей по 8 байт**, и
номера в них идут с 4: `$04`…`$20`. Каждая запись — четыре слова, по
слову на сторону, и слово это смещение на скрипт от начала набора.
Анимации `$00`…`$03` общие для всех типов и лежат в отдельной таблице
(`CommonFrameTable`). Итого 33 анимации на тип.

Сторон в записи четыре, а не восемь: скрипт индексируется **чётным**
направлением, а восточные стороны получаются отражением — бит 11 слова
кадра. Поэтому у половины анимаций все четыре стороны различны, а у
другой половины (яйцо, смерть, общие) — одна на все.

## Скрипт

`RunAnimScript` `$014F80` читает записи **по три байта**: слово кадра и
байт длительности. Значения от `$F0` — команды (`AnimScriptCommands`
`$014FB8`):

| код | операндов | что |
|---|---:|---|
| `$FF` | 2 | цикл со счётчиком, назад на знаковое смещение |
| `$FE` | 1 | переход назад или вперёд |
| `$FD` | 1 | пропуск |
| `$FC` | 0 | выравнивание и переход по длинному слову |
| `$FB` | 6 | кадр сразу для двух слоёв |
| `$FA` | 1 | записать в `+$1E` |
| `$F9` | 1 | записать в `+$1F` |
| `$F8` | 0 | пусто |

У слова кадра младший байт — номер кадра, **бит 8** переключает на общий
банк вместо своего, **бит 11** отражает по горизонтали.

## Чего здесь нет

- **Счётчик цикла `$FF`** не отслеживается: обратный переход считается
  точкой возврата, а сколько раз игра его повторит — не выводится.
- **Длительность кадра команды `$FB`** взята из первого операнда; это
  догадка, остальные пять байт не разобраны.
"""
import collections
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import gfx                                                   # noqa: E402
import unitgfx                                               # noqa: E402
from paths import OUT as out_path                            # noqa: E402

rom = gfx.rom
L = gfx.L
W = unitgfx.W

N_TYPES = unitgfx.N_TYPES          # 91
COMMON_ANIMS = range(0, 4)
OWN_ANIMS = range(4, 33)           # 29 записей набора
FACINGS = (0, 2, 4, 6)
SIDE = 4                           # кадр — 4x4 тайла
FRAME = SIDE * 8                   # 32 точки
MAX_STEPS = 64                     # предохранитель на длинный скрипт


def steps(a):
    u"""[(слово, длительность)] и индекс кадра, на который скрипт вернулся."""
    out, seen, loop = [], {}, None
    while len(out) < MAX_STEPS:
        if not (0 < a < len(rom) - 8):
            break
        if a in seen:
            loop = seen[a]
            break
        seen[a] = len(out)
        b = rom[a]
        if b < 0xF0:
            out.append((W(a), rom[a + 2]))
            a += 3
        elif b == 0xFB:                       # кадр двух слоёв
            out.append((W(a + 2), rom[a + 1]))
            a += 7
        elif b == 0xFE:
            d = rom[a + 1]
            a += 2 + (d - 256 if d > 127 else d)
        elif b == 0xFF:
            d = rom[a + 2]
            a += 3 + (d - 256 if d > 127 else d)
        elif b == 0xFC:
            p = a + 1 + ((a + 1) & 1)
            a = L(p)
        else:
            a += 1 + unitgfx.OPERANDS.get(b, 0)
    return out, loop


def frame_pixels(t, word, pal):
    u"""32x32 цветов, None вместо прозрачного; None, если кадра нет."""
    idx = word & 0xFF
    tbl = L(unitgfx.COMMON_FRAMES) if word & 0x100 else unitgfx.frame_table(t)
    n = gfx.table_len(tbl)
    if not n or idx >= n:
        return None
    p = L(tbl + 4 * idx)
    if not (0 < p < 0x200000):
        return None
    try:
        data = gfx.columnwise(bytes(gfx.unpack(rom, p)[2]))
    except Exception:
        return None
    hf = bool(word & 0x800)
    out = [[None] * FRAME for _ in range(FRAME)]
    for ty in range(SIDE):
        for tx in range(SIDE):
            tile = data[(ty * SIDE + tx) * 32:(ty * SIDE + tx + 1) * 32]
            if len(tile) < 32:
                continue
            for y in range(8):
                row = out[ty * 8 + y]
                for x in range(8):
                    b = tile[y * 4 + (x >> 1)]
                    v = (b >> 4) if x % 2 == 0 else (b & 15)
                    if v:
                        px = tx * 8 + x
                        row[FRAME - 1 - px if hf else px] = pal[v]
    return out


def strip(frames, pal, t, path, bg=(24, 24, 28)):
    u"""Полоса кадров одной анимации, слева направо."""
    w = FRAME * len(frames)
    img = [[bg + (0,)] * w for _ in range(FRAME)]
    for i, (word, _dur) in enumerate(frames):
        f = frame_pixels(t, word, pal)
        if f is None:
            continue
        for y in range(FRAME):
            row = img[y]
            src = f[y]
            for x in range(FRAME):
                if src[x] is not None:
                    row[i * FRAME + x] = src[x] + (255,)
    gfx.png(path, w, FRAME, img, alpha=True)


def anim_rows(t):
    u"""[(номер анимации, стороны, кадры, петля)] — по строке на показ.

    Стороны, у которых скрипт совпадает кадр в кадр, склеиваются в одну
    строку: у яйца, смерти и общих анимаций она всегда одна.
    """
    rows = []
    for an in list(COMMON_ANIMS) + list(OWN_ANIMS):
        groups = collections.OrderedDict()
        for f in FACINGS:
            try:
                seq, loop = steps(unitgfx.script_addr(t, an, f))
            except Exception:
                continue
            key = (tuple(seq), loop)
            groups.setdefault(key, []).append(f)
        for (seq, loop), fs in groups.items():
            if seq:
                rows.append((an, fs, list(seq), loop))
    return rows


def sheet(t, rows, pal, path):
    u"""Лист типа: строка — одна анимация одной группы сторон."""
    gap = 2
    cols = max(len(r[2]) for r in rows)
    w = cols * FRAME + gap * 2
    h = len(rows) * (FRAME + gap) + gap
    img = [[(24, 24, 28, 255)] * w for _ in range(h)]
    for i, (_an, _fs, seq, _loop) in enumerate(rows):
        oy = gap + i * (FRAME + gap)
        for k, (word, _dur) in enumerate(seq):
            f = frame_pixels(t, word, pal)
            if f is None:
                continue
            ox = gap + k * FRAME
            for y in range(FRAME):
                row = img[oy + y]
                src = f[y]
                for x in range(FRAME):
                    if src[x] is not None:
                        row[ox + x] = src[x] + (255,)
    gfx.png(path, w, h, img, alpha=True)


def describe(word):
    return {"frame": word & 0xFF,
            "common": bool(word & 0x100),
            "hflip": bool(word & 0x800)}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    split = "--split" in sys.argv[1:]
    only = int(args[0]) if args else None

    # типы с одинаковым набором сводятся к первому: 43 различных из 91
    same, first = {}, {}
    for t in range(1, N_TYPES + 1):
        try:
            s = unitgfx.signature(t)
        except Exception:
            continue
        if s in first:
            same[t] = first[s]
        else:
            first[s] = t

    outdir = out_path("units")
    os.makedirs(outdir, exist_ok=True)
    manifest, drawn, strips = {}, 0, 0

    for t in range(1, N_TYPES + 1):
        if only is not None and t != only:
            continue
        if only is None and t in same:
            manifest[t] = {"same_as": same[t]}
            continue
        try:
            rows = anim_rows(t)
        except Exception:
            continue
        if not rows:
            continue
        row = unitgfx.palette_row(t)
        pal = unitgfx.row_palette(row)
        sheet(t, rows, pal, os.path.join(outdir, "type_%03d.png" % t))
        drawn += 1

        rec = {"bank": "$%06X" % unitgfx.frame_table(t),
               "palette_row": row, "anims": {}}
        for an, fs, seq, loop in rows:
            entry = {"facings": fs,
                     "loop": loop,
                     "frames": [dict(describe(w), dur=d) for w, d in seq]}
            rec["anims"].setdefault("$%02X" % an, []).append(entry)
            if split:
                d = os.path.join(outdir, "type_%03d" % t)
                os.makedirs(d, exist_ok=True)
                strip(seq, pal, t,
                      os.path.join(d, "anim_%02X_f%d.png" % (an, fs[0])))
                strips += 1
        manifest[t] = rec

    path = os.path.join(outdir, "units.json")
    io.open(path, "w", encoding="utf-8", newline="\n").write(
        json.dumps(manifest, ensure_ascii=False, indent=1))

    print("наборов нарисовано: %d (типов всего %d, различных наборов %d)"
          % (drawn, N_TYPES, len(first)))
    if split:
        print("отдельных полос: %d" % strips)
    print("роспись: %s" % os.path.relpath(path, HERE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
