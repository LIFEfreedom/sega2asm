#!/usr/bin/env python3
u"""Анимации шести видов в раскладке ремейка Dyna.

    python tools/exportanim.py          # шесть видов игрока 1
    python tools/exportanim.py --all    # плюс те же виды у игрока 2

Пишет в `out/<имя>/export/` дерево, которое кладётся прямо в `Content`:

    objects/units/<папка>/<анимация>/{top,bottom,right}.png
    layouts.cs        — записи для UnitAnimationOverrides
    animations.json   — покадровые длительности оригинала

## Что во что легло

`LevelScene` грузит пять анимаций на вид и три стороны на анимацию
(левая — зеркало правой). В оригинале анимаций 33 и сторон четыре; вот
соответствие, выведенное из того, КТО ставит номер в `+$7` записи юнита:

| ремейк | оригинал | ставит |
|---|---|---|
| `idle` | `$05` | `EnterIdleFacing` |
| `walking` | `$0A` | `EnterWalkStateNormal` (чётное направление) |
| `dying` | `$1A` | `UnitDie` |
| `kicking` | `$13` | `EnterTrampleState` |
| `eat` | `$0D` | `EnterAction1E`, `GrazeHeal300` |

Стороны опознаны по самим кадрам ходьбы ｽﾃｺﾞ: сторона 0 рисует спину,
сторона 4 — морду, сторона 6 — профиль вправо, сторона 2 — тот же профиль
с взведённым битом отражения.

| оригинал | ремейк |
|---|---|
| 0 | `top` |
| 4 | `bottom` |
| 6 | `right` |
| 2 | не выводится: это `right` зеркально, ремейк отражает сам |

Виды: папка ремейка — вид оригинала — тип расстановки игрока 1.

| папка | вид | тип |
|---|---|---|
| `pacific` | 1 ｽﾃｺﾞ | 5 |
| `fat` | 2 ﾄﾘｹﾗ | 6 |
| `defender` | 3 ｱﾛ | 7 |
| `hunter` | 4 ﾃｨﾗﾉ | 8 |
| `scout` | 5 ﾌﾟﾃﾗ | 9 |
| `egg_eater` | 6 ﾋﾟｰﾁｬﾝ | 10 |

## Время

`Animation` держит ОДНУ задержку на всю анимацию, а в оригинале
длительность своя у каждого кадра — у ходьбы это 6, 24, 6, 24, то есть
разница вчетверо. Поэтому кадры здесь **размножены**: при задержке ремейка
в 50 мс и такте оригинала в 1/60 с один такт это примерно треть ячейки, и
кадр занимает `round(длительность / 3)` ячеек, но не меньше одной.
Анимация из одного кадра остаётся одним кадром.

Точные длительности лежат в `animations.json` — если в `Animation`
появится задержка на кадр, сетку можно будет пересобрать плотной.

## Чего здесь нет

- **Размер.** Кадр оригинала 32x32, а перерисованная графика ремейка
  64x64. `FromSpriteSheet` берёт размер ячейки из ширины листа, так что
  лист заработает как есть, но юниты выйдут вдвое меньше нынешних.
- **Палитра игрока.** Берётся ряд из `UnitPaletteRow`: у типов 5…10 это
  ряд 1, то есть цвета игрока 1. У игрока 2 те же кадры в ряду 2 —
  `--all` выводит и их.
"""
import io
import json
import math
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
import unitanim                                              # noqa: E402
from paths import OUT as out_path                            # noqa: E402

FRAME = unitanim.FRAME                 # 32

# папка ремейка -> (тип игрока 1, тип игрока 2, вид, имя)
SPECIES = (
    ("pacific",   5, 15, 1, u"ｽﾃｺﾞ"),
    ("fat",       6, 16, 2, u"ﾄﾘｹﾗ"),
    ("defender",  7, 17, 3, u"ｱﾛ"),
    ("hunter",    8, 26, 4, u"ﾃｨﾗﾉ"),
    ("scout",     9, 19, 5, u"ﾌﾟﾃﾗ"),
    ("egg_eater", 10, 27, 6, u"ﾋﾟｰﾁｬﾝ"),
)

# имя в ремейке -> номер анимации оригинала
ANIMS = (("idle", 0x05), ("walking", 0x0A), ("dying", 0x1A),
         ("kicking", 0x13), ("eat", 0x0D))

# сторона оригинала -> имя файла ремейка
SIDES = ((0, "top"), (4, "bottom"), (6, "right"))

TICK_MS = 1000.0 / 60.0                # такт оригинала
SLOT_MS = 50.0                         # задержка Animation в LevelScene


def slots(dur):
    u"""Сколько ячеек листа занимает кадр длительностью dur тактов."""
    return max(1, int(round(dur * TICK_MS / SLOT_MS)))


def expand(seq):
    u"""Кадры, размноженные под равномерную задержку."""
    if len(seq) <= 1:
        return [w for w, _d in seq]
    out = []
    for w, d in seq:
        out.extend([w] * slots(d))
    return out


def grid(n):
    u"""(столбцов, строк) под n ячеек: сетка поближе к квадрату."""
    cols = max(1, int(math.ceil(math.sqrt(n))))
    return cols, int(math.ceil(n / float(cols)))


def sheet(t, words, pal, path):
    cols, rows = grid(len(words))
    w, h = cols * FRAME, rows * FRAME
    img = [[(0, 0, 0, 0)] * w for _ in range(h)]
    for i, word in enumerate(words):
        f = unitanim.frame_pixels(t, word, pal)
        if f is None:
            continue
        ox, oy = (i % cols) * FRAME, (i // cols) * FRAME
        for y in range(FRAME):
            row = img[oy + y]
            src = f[y]
            for x in range(FRAME):
                if src[x] is not None:
                    row[ox + x] = src[x] + (255,)
    gfx.png(path, w, h, img, alpha=True)
    return cols, rows


def main():
    both = "--all" in sys.argv[1:]
    root = os.path.join(out_path("export"), "objects", "units")
    layouts, manifest, made, missing = [], {}, 0, []

    for folder, t1, t2, sp, name in SPECIES:
        for t, suffix in ((t1, ""), (t2, "_p2")) if both else ((t1, ""),):
            pal = unitgfx.row_palette(unitgfx.palette_row(t))
            key = folder + suffix
            manifest[key] = {"species": sp, "name": name, "type": t,
                             "palette_row": unitgfx.palette_row(t),
                             "anims": {}}
            for anim, an in ANIMS:
                d = os.path.join(root, key, anim)
                os.makedirs(d, exist_ok=True)
                for side, fname in SIDES:
                    try:
                        seq, loop, ok = unitanim.steps(
                            unitgfx.script_addr(t, an, side))
                    except Exception:
                        ok = False
                    if not ok or not seq:
                        missing.append((key, anim, fname))
                        continue
                    words = expand(seq)
                    cols, rows = sheet(t, words, pal,
                                       os.path.join(d, fname + ".png"))
                    made += 1
                    layouts.append((key, anim, fname, cols, rows, len(words)))
                    manifest[key]["anims"].setdefault(anim, {})[fname] = {
                        "rom_anim": "$%02X" % an,
                        "rom_facing": side,
                        "loop": loop,
                        "columns": cols, "rows": rows,
                        "frame_count": len(words),
                        "frames": [{"frame": w & 0xFF,
                                    "common": bool(w & 0x100),
                                    "hflip": bool(w & 0x800),
                                    "dur": d} for w, d in seq],
                    }

    io.open(os.path.join(out_path("export"), "animations.json"), "w",
            encoding="utf-8", newline="\n").write(
        json.dumps(manifest, ensure_ascii=False, indent=1))

    cs = [u"// Сгенерировано tools/exportanim.py — записи для",
          u"// UnitAnimationOverrides в LevelScene.", u""]
    seen = set()
    for key, anim, fname, cols, rows, n in layouts:
        base = key[:-3] if key.endswith("_p2") else key
        ut = {"pacific": "Pacific", "fat": "Fat", "defender": "Defender",
              "hunter": "Hunter", "scout": "Scout",
              "egg_eater": "EggEater"}[base]
        dirn = {"top": "Top", "bottom": "Bottom", "right": "Right"}[fname]
        an = {"idle": "IdleAnim", "walking": "WalkingAnim",
              "dying": "DyingAnim", "kicking": "KickingAnim",
              "eat": "EatAnim"}[anim]
        line = (u"    [(UnitType.%s, %s, Direction.%s)] = "
                u"new AnimationLayout(%d, %d, Rows: %d),"
                % (ut, an, dirn, cols, n, rows))
        if line not in seen:
            seen.add(line)
            cs.append(line)
    io.open(os.path.join(out_path("export"), "layouts.cs"), "w",
            encoding="utf-8", newline="\n").write(u"\n".join(cs) + u"\n")

    print(u"листов: %d -> %s" % (made, os.path.relpath(root, HERE)))
    if missing:
        print(u"не нашлось: %s" % ", ".join("%s/%s/%s" % m for m in missing))
    print(u"раскладки: %s" % os.path.relpath(
        os.path.join(out_path("export"), "layouts.cs"), HERE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
