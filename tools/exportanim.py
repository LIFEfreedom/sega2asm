#!/usr/bin/env python3
u"""Анимации шести видов в раскладке ремейка Dyna.

    python tools/exportanim.py          # шесть видов игрока 1
    python tools/exportanim.py --all    # все 45 различных наборов
    python tools/exportanim.py --props  # яйца и гнёзда под имена ремейка

Пишет в `out/<имя>/export/` дерево, которое кладётся прямо в `Content`:

    objects/units/<папка>/<анимация>.png   — одна анимация, все стороны
    animations.json   — раскладка листов и покадровые длительности

## Лист

Одна анимация — один файл. Строка листа — сторона, столбец — кадр по
времени, ячейка 32x32. Восемь сторон идут по кругу от верхней против
часовой стрелки:

| строка | сторона | сторона оригинала | что на кадрах |
|---|---|---|---|
| 0 | `top` | 0 | спина |
| 1 | `top_left` | 7 | спина в три четверти, влево |
| 2 | `left` | 6 | профиль влево |
| 3 | `bottom_left` | 5 | морда в три четверти, влево |
| 4 | `bottom` | 4 | морда |
| 5 | `bottom_right` | 3 | морда в три четверти, вправо |
| 6 | `right` | 2 | профиль вправо |
| 7 | `top_right` | 1 | спина в три четверти, вправо |

«В три четверти» — это у покоя и шага; у остальных анимаций на месте
диагонали соседняя прямая сторона, см. «Стороны». Правые стороны
выводятся, потому что в оригинале они не всегда зеркало левых.
Строки бывают разной длины (у ﾄﾘｹﾗ
`eat` — 17, 20 и 21 ячейка): хвост короткой строки прозрачен, а сколько
в ней кадров на деле, пишет `animations.json`.

## Стороны

Номер стороны оригинала — это направление юнита, и идёт оно ПО часовой
стрелке от «вверх». Так говорят таблицы шага `DirDeltaX` `$016956` и
`DirDeltaY` `$01695E` (у стороны 2 шаг X+1, у стороны 6 X−1), и так же
выглядят сами кадры: у ｱﾛ и ﾃｨﾗﾉ на стороне 2 морда смотрит вправо, на
стороне 6 — влево. Обычно сторона 2 — это кадры стороны 6 с битом
отражения, но не всегда (ниже).

ИСПРАВЛЕНО: прежняя версия опознавала стороны по ходьбе ｽﾃｺﾞ, у которого
голову легко спутать с хвостом, сочла сторону 6 профилем вправо и писала
её в `right.png`. На деле там был левый профиль.

Внутри одной анимации у диагонали своей ячейки нет: `unitgfx.script_addr`
берёт `сторона & ~1`, и на нечётной стороне показывается ячейка
соседней чётной (7 -> 6, 5 -> 4, 3 -> 2, 1 -> 0). Но у покоя и шага
диагонали СВОИ — отдельными анимациями: `EnterWalkStateNormal` и
`EnterStepState` выбирают номер по чётности стороны (`$0A`/`$0B` у
покоя, `$18`/`$19` у шага), и в `$0B` и `$19` лежат виды в три
четверти. Строка диагонали строится ровно так же, как её показывает
игра: номер анимации по чётности, ячейка `сторона & ~1`. Поэтому у
ударов, смертей и `eat` строки диагоналей повторяют соседние прямые —
своих кадров для них в ROM нет; `animations.json` пишет у каждой
строки, какая анимация и ячейка в неё пошли.

**Правая сторона не всегда зеркало левой.** По каждой анимации
`animations.json` пишет поле `right`: `mirror` — правая это левая
зеркально, `same` — кадры не зависят от стороны (например, смерть),
`own` — у правой СВОИ кадры, и отражением левой их не получить. У
шести видов `own` девять раз: `eat` у ｱﾛ, ﾃｨﾗﾉ и ﾌﾟﾃﾗ, все четыре удара
и `eat` у ﾋﾟｰﾁｬﾝ, `kicking_4` у ｽﾃｺﾞ. У ｱﾛ, например, на левой стороне
он ест мордой к зрителю (кадры 71…78), на правой — спиной (79…86).

## Какие анимации

`LevelScene` грузит пять анимаций на вид. В оригинале их 33, и там, где
игра выбирает между несколькими, выводятся все, а правило выбора пишет
`animations.json` в поле `select` (см. «Как игра выбирает»). Соответствие
выведено из того, КТО ставит номер в `+$7` записи юнита:

| файл | оригинал | ставит |
|---|---|---|
| `idle` | `$0A` (`$0B` на диагоналях) | `EnterWalkStateNormal`: действие `$0B`, покой |
| `walking` | `$18` (`$19`) | `EnterStepState`: действие `$0E`, шаг в клетку |
| `kicking_1` | `$13` | `ResolveCombat`, исход 1; ещё `EnterTrampleState` |
| `kicking_2` | `$14` | `ResolveCombat`, исход 2 |
| `kicking_3` | `$15` | `ResolveCombat`, исход 3 |
| `kicking_4` | `$16` | `ResolveCombat`, редкий исход |
| `dying` | `$1A` | `UnitDie` |
| `dying_flame` | `$01` | `UnitDieFlame`: лава и огонь, бедствия |
| `dying_splash` | `$02` | `UnitDieSplash`; `UnitDie` у яйца и падали |
| `dying_pop` | `$03` | `UnitDiePop`: клетка с битом 5 плитки |
| `eat` | `$0D` | `EnterAction1E`, `GrazeHeal300` |

`dying_flame`, `dying_splash` и `dying_pop` — из общего банка: кадры у
всех видов одни, отличается только палитра.

## Как игра выбирает

**Удар.** `ResolveCombat` `$01B1AE` бросает дважды. Первый бросок из
256 — против шанса редкого исхода, байта `+$AC` блока параметров
нападающего, а если у него взведён бит 5 `+$11` (постоянное
улучшение), то `+$AD`: выпало меньше — `kicking_4`. Иначе второй
бросок: 0…`$60` — `kicking_1`, `$61`…`$DC` — `kicking_2`, `$DD`…`$FF` —
`kicking_3`, то есть 38%, 48% и 14%. У шести видов обычный шанс
редкого исхода 1/256, после улучшения — от 32/256 у ﾌﾟﾃﾗ до 50/256;
значения по видам — в `select.kicking`. Разбор боя целиком — в
`docs/game-actions.md`.

Разные кадры у всех четырёх исходов только у ｱﾛ и ﾃｨﾗﾉ. У ｽﾃｺﾞ, ﾄﾘｹﾗ
и ﾋﾟｰﾁｬﾝ исходы 1–3 — один и тот же скрипт, отличается только редкий,
у ﾌﾟﾃﾗ совпадают 1 и 2. Листы всё равно выводятся все четыре, чтобы
правило выбора работало одинаково для любого вида.

**Смерть.** Сначала местность: `CheckLethalTerrain` `$019DF4` смотрит
клетку под ногами в таком порядке — бит 5 плитки даёт `dying_pop`,
лава или огонь — `dying_flame`, плитки `$53`/`$54` — `dying_splash`, а
плитка `$0D` — `UnitVanish`: юнит пропадает вовсе без анимации. Иначе
смерть идёт через `UnitDie` `$01A8AE`: `dying`, но юнит в действиях
`$02`…`$09` (яйцо) и `$26`, `$27`, `$29`, `$31` (падаль) исчезает
всплеском `dying_splash`. Этот список лежит в ROM по `$016894` и
выводится в `select.dying.splash_actions`.

Жертва удара тоже получает свою анимацию (`$0F`…`$11`, по таблице
вида нападающего), но анимации «получил удар» у ремейка нет, и здесь
она не выводится (`docs/game-animations.md`).

ИСПРАВЛЕНО: было `idle` = `$05` и `walking` = `$0A`. Но `$05` у шести
видов — это ЯЙЦО из общего банка (кадры 1, 4, 7, 10, 13, 16), а `$0A`
— покой, а не ходьба. Разбор такой. Вернуть юнита в покой — это
`EnterWalkState` `$01A404`, и он развилкой по байту `+$C` выбирает
позу: гнездо (вид 0) получает `$04`, декорации и неигровые виды (бит
5) — `EnterIdleFacing` с `$05`, все прочие — `EnterWalkStateNormal`,
то есть действие `$0B` и анимацию `$0A`. Идёт же юнит в действии `$0E`,
и его ставит `EnterStepState` `$01A238` с анимацией `$18`. На глаз то
же: `$0A` — неторопливое покачивание на месте (у ｱﾛ 6, 16, 6, 16
тактов), `$18` — быстрый шаг (4, 4, 4, 4).

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
видно, что заполнены у них не все. Им выводится ещё и `$05`: это поза
покоя декораций (`EnterIdleFacing`), у пустого яйца только она и есть.

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
длительность своя у каждого кадра — у покоя ｱﾛ это 6, 16, 6, 16, то
есть разница почти втрое. Поэтому кадры здесь **размножены**: при задержке ремейка
в 50 мс и такте оригинала в 1/60 с один такт это примерно треть ячейки, и
кадр занимает `round(длительность / 3)` ячеек, но не меньше одной.
Анимация из одного кадра остаётся одним кадром.

Точные длительности лежат в `animations.json` — если в `Animation`
появится задержка на кадр, сетку можно будет пересобрать плотной.

## Чего здесь нет

- **`layouts.cs`.** Прежняя версия писала записи `AnimationLayout` для
  листов по одной стороне; под лист на восемь сторон загрузчика в ремейке
  пока нет, и выдумывать его API здесь незачем. Старый файл удаляется.
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
import shutil
import struct
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

# имя в ремейке -> номер анимации оригинала на чётной и нечётной стороне
ANIMS = (("idle", 0x0A, 0x0B), ("walking", 0x18, 0x19),
         ("kicking_1", 0x13, 0x13), ("kicking_2", 0x14, 0x14),
         ("kicking_3", 0x15, 0x15), ("kicking_4", 0x16, 0x16),
         ("dying", 0x1A, 0x1A), ("dying_flame", 0x01, 0x01),
         ("dying_splash", 0x02, 0x02), ("dying_pop", 0x03, 0x03),
         ("eat", 0x0D, 0x0D))
# неигровым наборам — свои ячейки набора, без общего банка, плюс поза
# покоя декораций (EnterIdleFacing)
OTHER_ANIMS = tuple(a for a in ANIMS if a[1] > 0x03) + (("rest", 0x05, 0x05),)

DESC_OFFSET = 0x01FAEE       # +$2 записи типа: смещение дескриптора
DESCRIPTORS = 0x01FC5A       # +$0 дескриптора: указатель на блок параметров
SPLASH_ACTIONS = 0x016894    # UnitDie: при этих действиях смерть — всплеск

# строки листа: сторона оригинала и имя, по кругу от верхней против
# часовой стрелки
FACINGS = ((0, "top"), (7, "top_left"), (6, "left"), (5, "bottom_left"),
           (4, "bottom"), (3, "bottom_right"), (2, "right"),
           (1, "top_right"))
LEFT, RIGHT = 6, 2            # сверяются: зеркало ли правая левой

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


def param_block(t):
    u"""Адрес блока параметров вида для типа t: через дескриптор."""
    off = struct.unpack_from(">H", gfx.rom, DESC_OFFSET + t * 4 + 2)[0]
    return struct.unpack_from(">I", gfx.rom, DESCRIPTORS + off)[0]


def action_set(addr):
    u"""Номера действий из набора `TestActionInSet`: два длинных слова.

    Первое — биты действий `$20`…`$3F`, второе — `$00`…`$1F`; `btst` по
    регистру берёт номер бита по модулю 32.
    """
    hi, lo = struct.unpack_from(">II", gfx.rom, addr)
    return [a for a in range(0x40)
            if ((hi if a >= 0x20 else lo) >> (a & 31)) & 1]


def selection(t):
    u"""Правило, по которому оригинал выбирает удар и смерть, для типа t."""
    b = param_block(t)
    return {
        "kicking": {
            "source": "ResolveCombat $01B1AE",
            "roll_of": 256,
            "rare": {"anim": "kicking_4",
                     "chance": gfx.rom[b + 0xAC],
                     "chance_upgraded": gfx.rom[b + 0xAD]},
            "otherwise": [{"anim": "kicking_1", "roll_to": 0x60},
                          {"anim": "kicking_2", "roll_to": 0xDC},
                          {"anim": "kicking_3", "roll_to": 0xFF}],
        },
        "dying": {
            "source": "CheckLethalTerrain $019DF4, UnitDie $01A8AE",
            "terrain_first": [
                {"cell": "tile bit 5", "anim": "dying_pop"},
                {"cell": "lava or fire (types 11, 12)",
                 "anim": "dying_flame"},
                {"cell": "tile $53 or $54", "anim": "dying_splash"},
                {"cell": "tile $0D", "anim": None},
            ],
            "default": "dying",
            "splash_actions": ["$%02X" % a
                               for a in action_set(SPLASH_ACTIONS)],
        },
    }


def facing_steps(t, an, side, entries):
    u"""(кадры, петля, продолжение) стороны или None, если её нет."""
    try:
        seq, loop, ok, nxt = unitanim.steps(unitgfx.script_addr(t, an, side),
                                            entries)
        ok = ok and unitanim.frames_fit(t, seq)
    except Exception:
        return None
    if not ok or not seq:
        return None
    return seq, loop, nxt


def right_relation(left, right):
    u"""Как правая сторона соотносится с левой: mirror, same, own, none."""
    if left is None or right is None:
        return "none"
    if right[0] == left[0]:
        return "same"
    if [(w ^ 0x800, d) for w, d in right[0]] == left[0]:
        return "mirror"
    return "own"


def rows_sheet(t, rows, pal, path):
    u"""Лист «строка — сторона, столбец — кадр»; пустые ячейки прозрачны."""
    cols = max(len(r) for r in rows)
    w, h = cols * FRAME, len(rows) * FRAME
    img = [[(0, 0, 0, 0)] * w for _ in range(h)]
    cache = {}
    for r, words in enumerate(rows):
        for i, word in enumerate(words):
            if word not in cache:
                cache[word] = unitanim.frame_pixels(t, word, pal)
            f = cache[word]
            if f is None:
                continue
            ox, oy = i * FRAME, r * FRAME
            for y in range(FRAME):
                row = img[oy + y]
                src = f[y]
                for x in range(FRAME):
                    if src[x] is not None:
                        row[ox + x] = src[x] + (255,)
    gfx.png(path, w, h, img, alpha=True)
    return cols


def main():
    if "--props" in sys.argv[1:]:
        return export_props()
    both = "--all" in sys.argv[1:]
    root = os.path.join(out_path("export"), "objects", "units")
    manifest, made, missing = {}, 0, []
    rights = collections.Counter()
    own = []

    for key, t, sp, name in (sets_all() if both else sets_six()):
        pal = unitgfx.row_palette(unitgfx.palette_row(t))
        entries = unitanim.entry_map(t)
        manifest[key] = {"species": sp, "name": name, "type": t,
                         "palette_row": unitgfx.palette_row(t),
                         "cell": FRAME,
                         "directions": [n for _s, n in FACINGS],
                         "anims": {}}
        playable = sp in PLAYABLE
        if playable:
            manifest[key]["select"] = selection(t)
        written = set()
        for anim, an, odd in (ANIMS if playable else OTHER_ANIMS):
            # Имена ремейка осмысленны только у шести видов. У гнезда
            # или яйца ячейка $0A это не «покой», а просто ячейка
            # $0A, поэтому файл называется по номеру.
            anim = anim if playable else "anim_%02X" % an
            rows, info = [], []
            for side, dname in FACINGS:
                # как показывает игра: номер по чётности стороны, а
                # ячейка сторона & ~1 (это делает script_addr)
                num = odd if side & 1 else an
                place = {"direction": dname, "row": len(info),
                         "rom_facing": side, "rom_anim": "$%02X" % num,
                         "rom_slot": side & ~1}
                got = facing_steps(t, num, side, entries)
                if got is None:
                    missing.append((key, anim, dname))
                    rows.append([])
                    place["frame_count"] = 0
                    info.append(place)
                    continue
                seq, loop, nxt = got
                words = expand(seq)
                rows.append(words)
                place.update({
                    "loop": loop,
                    "next": ("$%02X" % nxt[0]) if nxt else None,
                    "frame_count": len(words),
                    "frames": [{"frame": w & 0xFF,
                                "common": bool(w & 0x100),
                                "hflip": bool(w & 0x800),
                                "dur": d} for w, d in seq],
                })
                info.append(place)
            if not any(rows):
                continue
            rel = right_relation(facing_steps(t, an, LEFT, entries),
                                 facing_steps(t, an, RIGHT, entries))
            rights[rel] += 1
            if rel == "own":
                own.append((key, anim))
            d = os.path.join(root, key)
            os.makedirs(d, exist_ok=True)
            stale = os.path.join(d, anim)          # прежний каталог сторон
            if os.path.isdir(stale):
                shutil.rmtree(stale)
            cols = rows_sheet(t, rows, pal, os.path.join(d, anim + ".png"))
            made += 1
            written.add(anim + ".png")
            manifest[key]["anims"][anim] = {
                "rom_anim": "$%02X" % an,
                "rom_anim_diagonal": "$%02X" % odd,
                "columns": cols, "rows": len(FACINGS),
                "right": rel,
                "directions": info,
            }

        d = os.path.join(root, key)
        if written and os.path.isdir(d):      # листы прежних раскладок
            for name in os.listdir(d):
                if name.endswith(".png") and name not in written:
                    os.remove(os.path.join(d, name))

    io.open(os.path.join(out_path("export"), "animations.json"), "w",
            encoding="utf-8", newline="\n").write(
        json.dumps(manifest, ensure_ascii=False, indent=1))
    old = os.path.join(out_path("export"), "layouts.cs")
    if os.path.exists(old):
        os.remove(old)

    print(u"наборов: %d, листов: %d -> %s"
          % (len(manifest), made, os.path.relpath(root, HERE)))
    print(u"строки листа: %s"
          % ", ".join("%d %s (сторона %d)" % (i, n, s)
                      for i, (s, n) in enumerate(FACINGS)))
    if missing:
        byset = collections.Counter(m[0] for m in missing)
        print(u"нет стороны: %d сочетаний; больше всего у %s"
              % (len(missing),
                 ", ".join("%s (%d)" % kv for kv in byset.most_common(5))))
    print(u"правая сторона: %s"
          % ", ".join("%s %d" % kv for kv in sorted(rights.items())))
    six = [k for k in own if k[0] in {v[0] for v in PLAYABLE.values()}]
    if six:
        print(u"своя правая сторона у шести видов: %s"
              % ", ".join("%s/%s" % k for k in six))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
