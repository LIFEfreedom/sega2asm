#!/usr/bin/env python3
u"""Анимации юнитов в раскладке ремейка Dyna.

    python tools/exportanim.py          # наборы, которые ставят миссии, в их палитрах
    python tools/exportanim.py --all    # все 45 различных наборов, для обзора
    python tools/exportanim.py --props  # яйца и гнёзда под имена ремейка
    python tools/exportanim.py --scale 2  # любое из них, увеличенное вдвое

Пишет в `out/<имя>/export/` дерево, которое кладётся прямо в `Content`:

    objects/units/<набор>/palette<P>/<анимация>.png   — одна анимация, все стороны
    animations.json   — раскладка листов и покадровые длительности

## Какие наборы и в каких палитрах (dyna #213)

Юнит ремейка рисуется по ТИПУ оригинала, а не по виду: у игрока 2 свои
существа (слизень 15, шлемоголовый 16…), и какие — решает ростер миссии.
Поэтому вывод по умолчанию идёт от миссий: `exportmissions.mission_docs()`
даёт ростеры обоих игроков и типы всех юнитов расстановки и подкреплений,
плюс умолчания ремейка (`DEFAULT_TYPES`). Каждый тип рисуется рядом CRAM из
`UnitPaletteRow` `$015156`: ряд 1 — палитрой `data_99[+$28]` (1 у всех
миссий), ряд 2 — `data_99[+$29]` своей миссии (3, у теней 2 и 4). Так
набираются пары «тип, палитра».

Типы с одинаковыми листами — одинаковыми до шага скрипта: банк кадров,
кадры общего банка, длительности, петли (`sheet_key`, строже
`unitgfx.signature`) — делят один НАБОР: тени 38…43, ﾌﾞﾗﾎﾞｰｽﾞ 44…49 и мясо
69…74 — это наборы 5…10, 25 = 50, 26 = 51, 27 = 52 = 57, 58 = 75, 32 = 33.
Набор выводится один раз на каждую палитру, в которой его рисуют, и
называется по младшему типу, который ставят миссии: папка игрока 1 без
суффикса, прочие `<вид>_r<тип>`. `animations.json` тогда — два словаря:
`sets` (раскладка набора, от палитры не зависящая, и список `palettes`) и
`types` (тип -> набор и ряд палитры). Типы, которых миссии не ставят, но
листы у которых ровно те же, тоже попадают в `types`: так тип 57 рисуется
листами 27 без единого нового файла.

`data_99[4]` — шестнадцать нулей: тени Story 39 и 41 рисуются сплошь
чёрными силуэтами. Перекрашивает ли их скрипт этапа по ходу — проверяется
только эмулятором.

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
`eat` — от 6 до 8 кадров): хвост короткой строки прозрачен, а сколько
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
| `species20` | 20, ничей | 58 |

Четыре подвижных нейтрала (dyna #206) выводятся вместе с шестью видами и
под теми же именами анимаций: у ремейка они такие же юниты. Три из них
делят листы с запасными ростерами врага и потому лежат в их наборах
(dyna #213): 50 — в `defender_r25`, 51 — в `hunter_r26`, 52 — в
`egg_eater_r27` (там в палитре 1, у 27 — в палитре 3). Своя папка — только
у вида 20.

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
`objects/eggs/<вид>/<стадия>.png` и `objects/spawner.png` / `spawner2.png`.
Под эти же имена кладётся и вывод. Яйца игрока 2 (dyna #213) — в
`objects/eggs/p2/palette<P>/<вид>/<стадия>.png`, по набору на каждую
палитру ряда 2, которую берут миссии.

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

Яйцо ремейк рисует картинкой своей стадии (dyna #213):
`objects/eggs/<вид>/{cocoon,rest,stir,ready}.png` у игрока 1 и
`objects/eggs/p2/palette<P>/<вид>/...` у игрока 2 — первые кадры анимаций
`$04` (кокон ｶｲｿﾞｳ), `$05`, `$06`, `$07`.

Кроме одиночных картинок `--props` пишет `eggs/shared/` (кладка,
трещина, вылупление) — лентами, как `unitanim`.

## Время

Ячейка листа — один шаг скрипта оригинала, без повторов. Длительность
у каждого кадра своя — у покоя ｱﾛ это 6, 16, 6, 16 тактов, — и лежит в
`animations.json`: `frames[i].dur` в тактах по 1/60 с. Ремейк держит
задержку на кадр, поэтому размножать кадры под одну общую задержку, как
делала прежняя версия, больше незачем.

Что делать после последнего кадра, пишут два поля строки. `loop` —
номер кадра, с которого скрипт идёт по кругу (у покоя 0, у смерти
последний, то есть «застыть»). `next` — номер анимации, в которую
скрипт перетекает, дойдя до её входа: так `dying_pop` (`$03`) уходит в
пустой кадр `$00`. Если нет ни того, ни другого, строка кончается
предохранителем обходчика.

## Чего здесь нет

- **`layouts.cs`.** Прежняя версия писала записи `AnimationLayout` для
  листов по одной стороне; под лист на восемь сторон загрузчика в ремейке
  пока нет, и выдумывать его API здесь незачем. Старый файл удаляется.
- **Размер по умолчанию.** Кадр оригинала 32x32, и клетка карты у него
  тоже 32x32 (`tools/maptex.py`), а у ремейка клетка 64. Для ремейка
  выгружать с `--scale 2`: ближайший сосед, пропорция «спрайт = клетка»
  сохраняется, а `cell` в `animations.json` становится 64.
- **Палитры, которых миссии не берут.** Набор выводится только в тех
  палитрах, которыми его рисуют миссии и умолчания ремейка; `--all`
  выводит каждый набор в палитре его ряда по умолчанию (ряд 2 — `data_99[3]`).
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


def arg_scale():
    u"""Масштаб из `--scale N`: во сколько раз увеличить картинки."""
    a = sys.argv[1:]
    if "--scale" in a:
        return max(1, int(a[a.index("--scale") + 1]))
    return 1


SCALE = arg_scale()


def write_png(path, w, h, img):
    u"""PNG с прозрачностью, увеличенный в SCALE раз ближайшим соседом."""
    if SCALE > 1:
        img = [[c for c in row for _ in range(SCALE)]
               for row in img for _ in range(SCALE)]
        w, h = w * SCALE, h * SCALE
    gfx.png(path, w, h, img, alpha=True)

SPECIES_BYTE = 0x01FAEE            # +$1 записи: вид плюс флаги

# вид оригинала -> папка ремейка и имя
PLAYABLE = {1: ("pacific", u"ｽﾃｺﾞ"), 2: ("fat", u"ﾄﾘｹﾗ"),
            3: ("defender", u"ｱﾛ"), 4: ("hunter", u"ﾃｨﾗﾉ"),
            5: ("scout", u"ﾌﾟﾃﾗ"), 6: ("egg_eater", u"ﾋﾟｰﾁｬﾝ")}

# типы игрока 1: у них ряд палитры 1 и они дают папку без суффикса
PLAYER1 = {1: 5, 2: 6, 3: 7, 4: 8, 5: 9, 6: 10}

# Подвижные нейтралы (dyna #206): вид -> (папка, тип расстановки), под
# именами анимаций шести видов — у ремейка это такие же юниты. Имя папки
# нужно только виду 20: у 50, 51 и 52 листы общие с 25, 26 и 27, и набор
# зовётся по ним (dyna #213); в `--all` — по своему типу.
NEUTRAL = {11: ("species11", 50), 12: ("species12", 51),
           13: ("species13", 52), 20: ("species20", 58)}

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

TICK_HZ = 60                           # такт оригинала: кадр развёртки NTSC


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
    write_png(path, w, h, img)
    return cols, rows


EGG_SPECIES = 6                    # шесть видов, по три кадра на каждый
# Стадии яйца ремейка -> анимация оригинала, по кадру на стадию (dyna #213):
# кокон ｶｲｿﾞｳ ($04, действие $04), лежит ($05), шевелится ($06: кадр держится
# 20…42 такта и лишь коротко мелькает покоем), вот-вот вылупится ($07).
EGG_STAGES = ((0x04, "cocoon"), (0x05, "rest"), (0x06, "stir"), (0x07, "ready"))
EMPTY_EGG, BONES = 68, 67             # вид 25 и вид 26 без сторон
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
    write_png(path, FRAME, FRAME, img)
    return True


def export_props():
    root = out_path("export")
    eggs = os.path.join(root, "objects", "eggs")
    objects = os.path.join(root, "objects")
    shared = os.path.join(root, "eggs", "shared")
    for d in (eggs, objects, shared):
        os.makedirs(d, exist_ok=True)

    # Яйца (dyna #213): по картинке на стадию, `<вид>/<стадия>.png`. У игрока
    # 1 — ряд 1, палитра 1. У игрока 2 яйцо своё — у всех типов ряда 2, тени
    # 38…43 тоже, кадры 19 + (вид − 1) * 3 общего банка — и рисуется рядом 2,
    # поэтому выводится в каждой палитре, которой миссии красят этот ряд:
    # `p2/palette<P>/<вид>/<стадия>.png`.
    row2 = sorted({p for t, p in mission_palettes()
                   if unitgfx.palette_row(t) == 2})
    made, note = 0, {}
    for sp in sorted(PLAYABLE):
        folder, _name = PLAYABLE[sp]
        jobs = [(PLAYER1[sp], unitgfx.row_palette(1), os.path.join(eggs, folder))]
        jobs += [(p2_type(sp), data99(p), os.path.join(eggs, "p2", "palette%d" % p, folder))
                 for p in row2]
        for t, pal, d in jobs:
            os.makedirs(d, exist_ok=True)
            ent = unitanim.entry_map(t)
            for an, stage in EGG_STAGES:
                seq, _l, ok, _n = unitanim.steps(
                    unitgfx.script_addr(t, an, 0), ent)
                if ok and seq and single(t, seq[0][0], pal,
                                         os.path.join(d, stage + ".png")):
                    made += 1
                    if stage == "rest" and t == PLAYER1[sp]:
                        note[folder] = seq[0][0] & 0xFF
        if sp != 1:
            continue
        t = PLAYER1[sp]
        ent = unitanim.entry_map(t)
        for an, nm in EGG_SHARED:
            seq, _l, ok, _n = unitanim.steps(
                unitgfx.script_addr(t, an, 0), ent)
            if not ok or not seq:
                continue
            sheet(t, [w for w, _d in seq], unitgfx.row_palette(1),
                  os.path.join(shared, nm + ".png"))
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
    # Нейтральное из расстановки (dyna #206), game-neutral.md: пустое яйцо
    # (тип 68) — кадр покоя анимации 5; кости (тип 67) — кадр позы падали
    # $20, один на пару курсов: 0–1, 2–3, 4–5, 6–7.
    for t, an, facings, path in (
            (EMPTY_EGG, 0x05, (0,), lambda k: os.path.join(eggs, "empty.png")),
            (BONES, 0x20, (0, 2, 4, 6),
             lambda k: os.path.join(objects, "bones", "%d.png" % (k // 2)))):
        pal = unitgfx.row_palette(unitgfx.palette_row(t))
        ent = unitanim.entry_map(t)
        for k in facings:
            seq, _l, ok, _n = unitanim.steps(
                unitgfx.script_addr(t, an, k), ent)
            if ok and seq:
                os.makedirs(os.path.dirname(path(k)), exist_ok=True)
                if single(t, seq[0][0], pal, path(k)):
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
    write_png(path, w, h, img)
    return cols


# Умолчания ремейка (dyna #213): чем рисуется карта без ростеров и без
# типов у юнитов — Tiled и тесты. Их листы нужны, даже если ни одна миссия
# оригинала их так не ставит.
ROW1_PALETTE = 1                  # +$28: 1 у всех 123 миссий
DEFAULT_ROW2 = 3                  # +$29 у 119 миссий из 123
DEFAULT_TYPES = (5, 6, 7, 8, 9, 10,             # ростер игрока 1
                 15, 16, 25, 26, 19, 27,         # ростер игрока 2, как у Duel 1
                 50, 51, 52, 58,                 # подвижные нейтралы
                 69, 70, 71, 72, 73, 74, 75)     # мясо: ничья падаль
SKIP_POSES = ("bones", "empty_egg")   # у ремейка свои картинки, не листы


TYPE_RECORDS = 91                 # UnitTypeTable $01FAEE: записи типов 0…90
PARAM_BLOCKS = range(0x022000, 0x023400)   # блоки параметров видов и гнёзд


def is_unit_type(t):
    u"""Настоящий ли t тип: запись в `UnitTypeTable` и дескриптор, чей блок
    параметров — один из блоков видов. Графика есть и у типа 91, и у мёртвых
    типов с дескриптором `$0784`, но записи типа у первого нет, а у вторых
    `+$0` указывает в никуда ($818283): длительности там мусор, и ремейк
    упал бы на таком типе посреди боя, а не при загрузке."""
    return t < TYPE_RECORDS and param_block(t) in PARAM_BLOCKS


def data99(p):
    u"""Палитра `data_99[p]` — то, что `BuildStagePalettes` кладёт в ряд."""
    return gfx.read_palette(gfx.PAL_ARRAY + 32 * p)


def palette_of(t, row2):
    u"""Номер палитры `data_99`, которой миссия рисует тип t: ряд 1 — `+$28`,
    ряд 2 — `+$29`. Рядов 0 и 3 у юнитов игроков и нейтралов не бывает."""
    row = unitgfx.palette_row(t)
    return {1: ROW1_PALETTE, 2: row2}.get(row)


def mission_units(node):
    u"""Все записи юнитов миссии: карта и подкрепления сценария, где угодно."""
    if isinstance(node, dict):
        if "rom_type" in node:
            yield node
        for v in node.values():
            for u in mission_units(v):
                yield u
    elif isinstance(node, list):
        for v in node:
            for u in mission_units(v):
                yield u


def mission_palettes():
    u"""{(тип, палитра)} по всем миссиям плюс умолчания ремейка.

    Всё, что может появиться на карте: ростеры обоих игроков (яйца по
    команде и ｶｲｿﾞｳ), типы расстановки и подкреплений (размножение
    копирует тип родителя) — в палитре своей миссии."""
    import exportmissions as em
    pairs = {(t, palette_of(t, DEFAULT_ROW2)) for t in DEFAULT_TYPES}
    for _folder, _m, doc in em.mission_docs():
        mp = doc["map"]
        types = set()
        for p in mp["players"]:
            types.update(p["roster"])
        types.update(u["rom_type"] for u in mission_units(mp)
                     if u.get("pose") not in SKIP_POSES)
        pairs.update((t, palette_of(t, mp["unit_palette"])) for t in types)
    missing = sorted(k for k in pairs if k[1] is None)
    assert not missing, missing
    return pairs


def sheet_key(t):
    u"""Чем листы типа t отличимы от чужих: банк кадров и все шаги скриптов.

    Строже `unitgfx.signature`: сравнивает и кадры общего банка, и
    длительности, и петли — всё, что попадает в листы и в манифест."""
    ent = unitanim.entry_map(t)
    parts = [unitgfx.frame_table(t)]
    for _anim, an, odd in ANIMS:
        for side, _n in FACINGS:
            got = facing_steps(t, odd if side & 1 else an, side, ent)
            parts.append(None if got is None
                         else (tuple(got[0]), got[1], got[2]))
    return tuple(parts)


def set_name(rep):
    u"""Папка набора по младшему типу группы."""
    sp = species_of(rep)
    if sp in PLAYABLE:
        folder = PLAYABLE[sp][0]
        return folder if rep == PLAYER1[sp] else "%s_r%d" % (folder, rep)
    if sp in NEUTRAL:
        return NEUTRAL[sp][0]
    return "type%03d" % rep


def describe_set(t, playable):
    u"""Раскладка листов набора, от палитры не зависящая.

    [(анимация, строки слов по сторонам, запись манифеста)], пропущенные
    стороны и то, как правая сторона соотносится с левой."""
    entries = unitanim.entry_map(t)
    out, missing, rights = [], [], []
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
                missing.append(anim + "/" + dname)
                rows.append([])
                place["frame_count"] = 0
                info.append(place)
                continue
            seq, loop, nxt = got
            words = [w for w, _d in seq]
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
        rights.append((anim, rel))
        out.append((anim, rows, {
            "rom_anim": "$%02X" % an,
            "rom_anim_diagonal": "$%02X" % odd,
            "columns": max(len(r) for r in rows), "rows": len(FACINGS),
            "right": rel,
            "directions": info,
        }))
    return out, missing, rights


def set_entry(t, sp, name, playable, layout):
    entry = {"species": sp, "name": name, "type": t,
             "cell": FRAME * SCALE,
             "directions": [n for _s, n in FACINGS]}
    if playable:
        entry["select"] = selection(t)
    entry["anims"] = collections.OrderedDict((a, e) for a, _r, e in layout)
    return entry


def write_set(t, layout, pal, d):
    os.makedirs(d, exist_ok=True)
    for anim, rows, _e in layout:
        rows_sheet(t, rows, pal, os.path.join(d, anim + ".png"))
    return len(layout)


def write_manifest(manifest):
    io.open(os.path.join(out_path("export"), "animations.json"), "w",
            encoding="utf-8", newline="\n").write(
        json.dumps(manifest, ensure_ascii=False, indent=1))
    old = os.path.join(out_path("export"), "layouts.cs")
    if os.path.exists(old):
        os.remove(old)


def report(sets, made, root, missing, rights):
    print(u"наборов: %d, листов: %d -> %s"
          % (sets, made, os.path.relpath(root, HERE)))
    print(u"строки листа: %s"
          % ", ".join("%d %s (сторона %d)" % (i, n, s)
                      for i, (s, n) in enumerate(FACINGS)))
    if missing:
        byset = collections.Counter(m[0] for m in missing)
        print(u"нет стороны: %d сочетаний; больше всего у %s"
              % (len(missing),
                 ", ".join("%s (%d)" % kv for kv in byset.most_common(5))))
    print(u"правая сторона: %s"
          % ", ".join("%s %d" % kv for kv in sorted(
              collections.Counter(r for _k, _a, r in rights).items())))
    six = [(k, a) for k, a, r in rights
           if r == "own" and k in {v[0] for v in PLAYABLE.values()}]
    if six:
        print(u"своя правая сторона у шести видов: %s"
              % ", ".join("%s/%s" % k for k in six))


def export_remake():
    u"""Выгрузка для ремейка (dyna #213): наборы, которые встречаются в
    миссиях, в палитрах этих миссий, по папке на палитру."""
    root = os.path.join(out_path("export"), "objects", "units")
    if os.path.isdir(root):
        shutil.rmtree(root)            # всё здесь пишет только этот скрипт
    pairs = mission_palettes()
    groups = collections.OrderedDict()           # ключ листов -> типы
    for t in sorted({t for t, _p in pairs}):
        groups.setdefault(sheet_key(t), []).append(t)
    # Представитель и имя набора — младший тип, который миссии ставят: у
    # ﾄﾘｹﾗ игрока 2 (16) младший в группе — неиспользуемый вид 7 (тип 11).
    reps = {k: v[0] for k, v in groups.items()}
    # Типы, которых в миссиях нет, но листы у них ровно те же: ремейку
    # незачем их выгружать, а нарисовать ими такой тип можно (так 57 — это
    # 52 в ряду 2, а 38…49 и мясо 69…74 — это 5…10). Только ряды 1 и 2:
    # других у юнитов не бывает, и только настоящие типы (`is_unit_type`).
    for t in range(1, unitgfx.N_TYPES + 1):
        if unitgfx.palette_row(t) not in (1, 2) or not is_unit_type(t):
            continue
        try:
            k = sheet_key(t)
        except Exception:
            continue
        if k in groups and t not in groups[k]:
            groups[k].append(t)

    manifest = collections.OrderedDict([
        ("sets", collections.OrderedDict()),
        ("types", collections.OrderedDict())])
    made, missing, rights = 0, [], []
    for key, types in groups.items():
        types.sort()
        rep = reps[key]
        sp, name = species_of(rep), set_name(rep)
        palettes = sorted({p for t, p in pairs if t in types})
        layout, miss, rel = describe_set(rep, True)
        missing += [(name, m) for m in miss]
        rights += [(name, a, r) for a, r in rel]
        entry = set_entry(rep, sp,
                          PLAYABLE.get(sp, (None, u"вид %d" % sp))[1],
                          True, layout)
        entry["types"] = types
        entry["palettes"] = palettes
        manifest["sets"][name] = entry
        for t in types:
            manifest["types"][str(t)] = {"set": name,
                                         "row": unitgfx.palette_row(t)}
        for p in palettes:
            made += write_set(rep, layout, data99(p),
                              os.path.join(root, name, "palette%d" % p))
    manifest["types"] = collections.OrderedDict(
        sorted(manifest["types"].items(), key=lambda kv: int(kv[0])))
    write_manifest(manifest)
    report(len(manifest["sets"]), made, root, missing, rights)
    print(u"пар «набор, палитра»: %d" % sum(
        len(e["palettes"]) for e in manifest["sets"].values()))
    return 0


def export_all():
    u"""Все 45 наборов, каждый в палитре своего ряда, плоско: для обзора."""
    root = os.path.join(out_path("export"), "objects", "units")
    if os.path.isdir(root):
        shutil.rmtree(root)
    manifest, made, missing, rights = {}, 0, [], []
    for key, t, sp, name in sets_all():
        playable = sp in PLAYABLE or (sp in NEUTRAL and t == NEUTRAL[sp][1])
        layout, miss, rel = describe_set(t, playable)
        missing += [(key, m) for m in miss]
        rights += [(key, a, r) for a, r in rel]
        manifest[key] = set_entry(t, sp, name, playable, layout)
        manifest[key]["palette_row"] = unitgfx.palette_row(t)
        made += write_set(t, layout,
                          unitgfx.row_palette(unitgfx.palette_row(t)),
                          os.path.join(root, key))
    write_manifest(manifest)
    report(len(manifest), made, root, missing, rights)
    return 0


def main():
    if "--props" in sys.argv[1:]:
        return export_props()
    if "--all" in sys.argv[1:]:
        return export_all()
    return export_remake()


if __name__ == "__main__":
    raise SystemExit(main())
