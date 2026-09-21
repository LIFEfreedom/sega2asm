#!/usr/bin/env python3
u"""Анимации шести видов в раскладке ремейка Dyna.

    python tools/exportanim.py          # шесть видов игрока 1
    python tools/exportanim.py --all    # все 45 различных наборов
    python tools/exportanim.py --props  # яйца и гнёзда под имена ремейка

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

## Остальные наборы (`--all`)

Типов 91, но различных наборов анимаций **45**: одна и та же графика
служит нескольким номерам расстановки. `--all` выводит все сорок пять.

Шесть видов встречаются по нескольку раз — это ростеры: те же ｽﾃｺﾞ и
ﾄﾘｹﾗ у игрока 2 и в запасных наборах, с другим банком кадров и другим
рядом палитры. Их папки называются `<вид>_r<тип>`, где тип — номер
расстановки представителя набора. Отличить ростеры глазом легко: у
игрока 1 ряд палитры 1, у прочих 2.

Остальные названы по тому, что про них установлено; где имени нет,
в названии стоит номер вида, а не выдумка:

| папка | вид | что это |
|---|---|---|
| `nest_p1`, `nest_p2_a/b/c` | 0 | гнёзда: одно игрока 1 и три разновидности игрока 2 |
| `species07_unused` | 7 | ни один из четырёх способов создать юнита его не даёт |
| `species08`, `species09` | 8, 9 | взрослые формы; чьи именно — не установлено |
| `species16`, `species20` | 16, 20 | имени в ROM нет |
| `megazaurus_head` | 18 | голова ﾒｶﾞｻﾞｳﾙｽ |
| `megazaurus_neck`, `_leg_a`, `_leg_b` | 19 | загривок и лапы |
| `megazaurus_capsule` | 17 | стеклянная капсула с фигурой внутри |
| `meat` | 26 | падаль и кости |
| `egg_empty` | 25 | пустое яйцо, 108 штук по картам |

У этих наборов папки анимаций названы по НОМЕРУ (`anim_05`, `anim_0A` и
так далее), а не `idle`/`walking`: имена ремейка осмысленны только для
шести видов, а у гнезда ячейка `$0A` это просто ячейка `$0A`. Заодно
видно, что заполнены у них не все пять: у пустого яйца только `$05`,
у головы ﾒｶﾞｻﾞｳﾙｽ только `$13` и `$0D`.

## Яйца и гнёзда (`--props`)

Ремейк рисует их **одной картинкой на целую текстуру**, без сетки:
`objects/eggs/<вид>.png` и `objects/spawner.png` / `spawner2.png`. Под эти
же имена кладётся и вывод.

**Яйцо у всех видов — общий банк кадров**, свои кадры не используются
вовсе. Номера идут с шагом три, по кадру на стадию:

| анимация | что | кадр общего банка |
|---|---|---|
| `$05` | лежит | `1 + (вид - 1) * 3` |
| `$06` | шевелится | `2 + (вид - 1) * 3`, вперемешку с кадром покоя |
| `$07` | вот-вот вылупится | `3 + (вид - 1) * 3` |

То есть ｽﾃｺﾞ это кадры 1, 2, 3, ﾄﾘｹﾗ — 4, 5, 6 и так далее до ﾋﾟｰﾁｬﾝ с
16, 17, 18.

**У игрока 2 яйца СВОИ, а не перекрашенные.** Второй набор начинается с
кадра 19 и устроен так же: `19 + (вид - 1) * 3`, до 34, 35, 36 у ﾋﾟｰﾁｬﾝ.
Узоры те же шесть, а форма другая — у игрока 1 яйцо округлое, у игрока 2
угловатое, с шипами по углам. Восемнадцать кадров против восемнадцати.

Осторожно с выбором представителя: «первый тип с рядом палитры 2» брать
нельзя. Типы 18 и 20 носят виды 4 и 6, но набор анимаций у них общий с
неиспользуемым видом 7, и яйцо оттуда приходит чужое — вида 2. Здесь
представитель выбирается по большинству (`p2_type`).

Ещё три анимации общие для всех шести и для обоих игроков: `$04`
(кладка, кадры 68…73), `$08` (скорлупа трескается, 0 и 46…50) и `$03`
(вылупился, 42…45, дальше перетекает в `$00`).

**Гнездо, наоборот, целиком в своём банке.** Спокойное гнездо — это
анимация `$04`, один кадр 0 с длительностью 255. Анимация `$06`, которую
включает `EnterNestPose` при расстановке, это разовая искра (кадры 0, 3,
4, 5, 6, 0), и она перетекает обратно в `$04`. Разновидностей гнезда
игрока 2 три — типы 2, 3 и 4; `spawner2.png` берётся с типа 2, остальные
кладутся рядом с суффиксом. Они заметно разные: у типа 2 существо с
красным куполом и синими крыльями, у типов 3 и 4 — механические пульты,
серые, с лампами и кольцом. Рядом кладётся `_spark` — та самая разовая
искра анимации `$06`.

Кроме одиночных картинок `--props` пишет `eggs/stages/` (три стадии по
видам) и `eggs/shared/` (кладка, трещина, вылупление) — лентами, как
`unitanim`.

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
import collections
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

SPECIES_BYTE = 0x01FAEE            # +$1 записи: вид плюс флаги

# вид оригинала -> папка ремейка и имя
PLAYABLE = {1: ("pacific", u"ｽﾃｺﾞ"), 2: ("fat", u"ﾄﾘｹﾗ"),
            3: ("defender", u"ｱﾛ"), 4: ("hunter", u"ﾃｨﾗﾉ"),
            5: ("scout", u"ﾌﾟﾃﾗ"), 6: ("egg_eater", u"ﾋﾟｰﾁｬﾝ")}

# типы игрока 1: у них ряд палитры 1 и они дают папку без суффикса
PLAYER1 = {1: 5, 2: 6, 3: 7, 4: 8, 5: 9, 6: 10}

# представитель набора -> папка, для всего, что не шестёрка видов
OTHERS = {
    1: "nest_p1", 2: "nest_p2_a", 3: "nest_p2_b", 4: "nest_p2_c",
    11: "species07_unused",
    12: "species08", 13: "species09",
    22: "species08_p2", 23: "species09_p2",
    55: "species16", 56: "megazaurus_head", 58: "species20",
    62: "megazaurus_neck", 64: "megazaurus_leg_a", 65: "megazaurus_leg_b",
    66: "megazaurus_capsule",
    67: "meat", 68: "egg_empty",
}


def species_of(t):
    return gfx.rom[SPECIES_BYTE + t * 4 + 1] & 0x1F


def sets_all():
    u"""[(папка, представитель, вид, имя)] по всем различным наборам."""
    seen, out = {}, []
    for t in range(1, unitgfx.N_TYPES + 1):
        try:
            k = unitgfx.signature(t)
        except Exception:
            continue
        if k in seen:
            continue
        seen[k] = t
        sp = species_of(t)
        if sp in PLAYABLE:
            folder, name = PLAYABLE[sp]
            if t != PLAYER1[sp]:
                folder = "%s_r%d" % (folder, t)
        else:
            folder = OTHERS.get(t, "type%03d" % t)
            name = u"вид %d" % sp
        out.append((folder, t, sp, name))
    return out


def sets_six():
    return [(PLAYABLE[sp][0], PLAYER1[sp], sp, PLAYABLE[sp][1])
            for sp in sorted(PLAYABLE)]

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


EGG_SPECIES = 6                    # шесть видов, по три кадра на каждый
EGG_STAGES = ((0x05, "rest"), (0x06, "stir"), (0x07, "ready"))
EGG_SHARED = ((0x04, "lay"), (0x08, "crack"), (0x03, "hatch"))
NESTS = ((1, "spawner", u"гнездо игрока 1"),
         (2, "spawner2", u"гнездо игрока 2"),
         (3, "spawner2_b", u"гнездо игрока 2, вариант B"),
         (4, "spawner2_c", u"гнездо игрока 2, вариант C"))
NEST_IDLE = 0x04                   # спокойное гнездо: один кадр, 255 тактов


def p2_type(sp):
    u"""Представитель вида у игрока 2: по БОЛЬШИНСТВУ кадра яйца.

    Просто «первый тип с рядом палитры 2» брать нельзя: типы 18 и 20
    носят вид 4 и 6, а набор анимаций у них общий с неиспользуемым видом
    7, и яйцо оттуда приходит чужое — вида 2. Большинство их отсекает.
    """
    votes = collections.Counter()
    where = {}
    for k in range(1, unitgfx.N_TYPES + 1):
        if species_of(k) != sp or unitgfx.palette_row(k) != 2:
            continue
        try:
            seq, _l, ok, _n = unitanim.steps(unitgfx.script_addr(k, 0x05, 0),
                                             unitanim.entry_map(k))
        except Exception:
            continue
        if not ok or not seq or not (seq[0][0] & 0x100):
            continue
        f = seq[0][0] & 0xFF
        votes[f] += 1
        where.setdefault(f, k)
    if not votes:
        return None
    return where[votes.most_common(1)[0][0]]


def single(t, word, pal, path):
    u"""Один кадр целой картинкой: ремейк берёт текстуру регионом целиком."""
    f = unitanim.frame_pixels(t, word, pal)
    if f is None:
        return False
    img = [[(c + (255,)) if c is not None else (0, 0, 0, 0) for c in row]
           for row in f]
    gfx.png(path, FRAME, FRAME, img, alpha=True)
    return True


def export_props():
    root = out_path("export")
    eggs = os.path.join(root, "objects", "eggs")
    objects = os.path.join(root, "objects")
    stages = os.path.join(root, "eggs", "stages")
    shared = os.path.join(root, "eggs", "shared")
    for d in (eggs, objects, stages, shared):
        os.makedirs(d, exist_ok=True)

    made, note = 0, {}
    for sp in sorted(PLAYABLE):
        folder, name = PLAYABLE[sp]
        for t, suffix in ((PLAYER1[sp], ""), (None, "_p2")):
            if t is None:                      # тот же вид у игрока 2
                t = p2_type(sp)
                if t is None:
                    continue
            pal = unitgfx.row_palette(unitgfx.palette_row(t))
            ent = unitanim.entry_map(t)
            for an, stage in EGG_STAGES:
                seq, _l, ok, _n = unitanim.steps(
                    unitgfx.script_addr(t, an, 0), ent)
                if not ok or not seq:
                    continue
                w = seq[0][0]
                if stage == "rest" and not suffix:
                    if single(t, w, pal, os.path.join(eggs, folder + ".png")):
                        made += 1
                        note[folder] = w & 0xFF
                if single(t, w, pal, os.path.join(
                        stages, "%s%s_%s.png" % (folder, suffix, stage))):
                    made += 1
            if suffix:
                continue
            for an, nm in EGG_SHARED:
                seq, _l, ok, _n = unitanim.steps(
                    unitgfx.script_addr(t, an, 0), ent)
                if not ok or not seq or sp != 1:
                    continue
                path = os.path.join(shared, nm + ".png")
                words = [w for w, _d in seq]
                cols, rows = sheet(t, words, pal, path)
                made += 1

    for t, fname, human in NESTS:
        pal = unitgfx.row_palette(unitgfx.palette_row(t))
        ent = unitanim.entry_map(t)
        seq, _l, ok, _n = unitanim.steps(
            unitgfx.script_addr(t, NEST_IDLE, 0), ent)
        if ok and seq:
            if single(t, seq[0][0], pal,
                      os.path.join(objects, fname + ".png")):
                made += 1
        seq, _l, ok, _n = unitanim.steps(
            unitgfx.script_addr(t, 0x06, 0), ent)
        if ok and seq:
            sheet(t, [w for w, _d in seq], pal,
                  os.path.join(objects, fname + "_spark.png"))
            made += 1
    print(u"яйца и гнёзда: %d картинок -> %s"
          % (made, os.path.relpath(root, HERE)))
    print(u"кадр покоя по видам: %s"
          % ", ".join("%s %d" % kv for kv in sorted(note.items())))
    return 0


def main():
    if "--props" in sys.argv[1:]:
        return export_props()
    both = "--all" in sys.argv[1:]
    root = os.path.join(out_path("export"), "objects", "units")
    layouts, manifest, made, missing = [], {}, 0, []

    for key, t, sp, name in (sets_all() if both else sets_six()):
        if True:
            pal = unitgfx.row_palette(unitgfx.palette_row(t))
            entries = unitanim.entry_map(t)
            manifest[key] = {"species": sp, "name": name, "type": t,
                             "palette_row": unitgfx.palette_row(t),
                             "anims": {}}
            playable = sp in PLAYABLE
            for anim, an in ANIMS:
                # Имена ремейка осмысленны только у шести видов. У гнезда
                # или яйца ячейка $0A это не «ходьба», а просто ячейка
                # $0A, поэтому папка называется по номеру.
                anim = anim if playable else "anim_%02X" % an
                d = os.path.join(root, key, anim)
                for side, fname in SIDES:
                    try:
                        seq, loop, ok, nxt = unitanim.steps(
                            unitgfx.script_addr(t, an, side), entries)
                        ok = ok and unitanim.frames_fit(t, seq)
                    except Exception:
                        ok, nxt = False, None
                    if not ok or not seq:
                        missing.append((key, anim, fname))
                        continue
                    words = expand(seq)
                    os.makedirs(d, exist_ok=True)
                    cols, rows = sheet(t, words, pal,
                                       os.path.join(d, fname + ".png"))
                    made += 1
                    layouts.append((key, anim, fname, cols, rows, len(words)))
                    manifest[key]["anims"].setdefault(anim, {})[fname] = {
                        "rom_anim": "$%02X" % an,
                        "rom_facing": side,
                        "loop": loop,
                        "next": ("$%02X" % nxt[0]) if nxt else None,
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
          u"// UnitAnimationOverrides в LevelScene. Только шесть видов",
          u"// игрока 1: у остальных наборов нет своего UnitType.", u""]
    seen = set()
    types = {"pacific": "Pacific", "fat": "Fat", "defender": "Defender",
             "hunter": "Hunter", "scout": "Scout", "egg_eater": "EggEater"}
    for key, anim, fname, cols, rows, n in layouts:
        if key not in types:
            continue
        ut = types[key]
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

    print(u"наборов: %d, листов: %d -> %s"
          % (len(manifest), made, os.path.relpath(root, HERE)))
    if missing:
        byset = collections.Counter(m[0] for m in missing)
        print(u"нет анимации: %d сочетаний; больше всего у %s"
              % (len(missing),
                 ", ".join("%s (%d)" % kv for kv in byset.most_common(5))))
    print(u"раскладки: %s" % os.path.relpath(
        os.path.join(out_path("export"), "layouts.cs"), HERE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
