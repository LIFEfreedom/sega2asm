#!/usr/bin/env python3
u"""Карты миссий настоящими тайлами игры.

    make maptex                     # все 123 миссии
    make maptex MTARGS="1 5"        # только глава 1, миссия 5
    make maptex MTARGS=--types      # лист образцов местности
    make maptex MTARGS=--export     # местность в раскладке ремейка

`maps.py` рисует карту клетками по восемь точек, одним усреднённым цветом
на клетку. Здесь она собирается так же, как её собирает сама игра: байт
карты -> четыре метатайла -> четыре тайла 8x8 -> пиксели палитрой этапа,
плюс спрайты юнитов. Клетка выходит 32x32 точки, вся карта — 1280x1280.

## Цепочка

Набор графики выбирает байт `+$2A` описания миссии: `LoadStageGraphics`
`$0053DA` берёт запись `$1CC` байт из `StageGfxRecords` `$01318C` (их
одиннадцать) и кладёт в `$FF02E6`. В записи 14 палитр по 32 байта и четыре
номера ассетов:

| поле | что |
|---|---|
| `+$1C0` | описание метатайлов, 6144 байта |
| `+$1C2` | 96 тайлов -> VRAM `$0EA0`, то есть номера `$75`…`$D4` |
| `+$1C4` | 256 тайлов -> VRAM `$1AA0`, номера `$D5`…`$1D4` |
| `+$1C6` | 32 тайла -> VRAM `$3AA0`, номера `$1D5`…`$1F4` |

Описание метатайлов `$FF10` распаковывает и раскладывает по `data_35`
`$00541C` на три куска:

| байты | куда | что |
|---|---|---|
| 0…255 | `$FFBBBC` | **байт карты -> тип местности** |
| 256…2303 | `$FF2C00` (`+$269C`) | плитка -> четыре метатайла |
| 2304…6143 | `$FF3400` (`+$2E9C`) | метатайл -> четыре тайла |

**Рисование идёт мимо типа.** Это главное, что здесь легко понять
неправильно: у карты две независимые жизни.

- **Правила** работают по типу: `BuildTerrainMap` `$0203FE` гоняет байт
  через таблицу `$FFBBBC` и кладёт в `TerrainMap` пару «счётчик, плитка»,
  где плитка = `data_165` `$020454` по типу. Отсюда стоимость шага, урон,
  съедобность.
- **Картинка** строится по САМОМУ БАЙТУ. `DrawMapColumn` `$015A80` берёт
  слово прямо из буфера карты `$FF9FC6` и отдаёт его `DrawCellTiles`
  `$015B3C`, а тот вычитает единицу и идёт во вторую таблицу. `TerrainMap`
  при отрисовке не читается вовсе.

Дальше: четыре слова записи, каждое по младшим девяти битам идёт в третью
таблицу, и оттуда четыре слова имени. К каждому прибавляется `$6075` —
номер первого тайла набора плюс палитра 3.

Поэтому один и тот же тип может выглядеть по-разному: типу 19 отвечают
байты 25…71, и каждый рисуется своей кромкой.

## Чего здесь нет

- **Стыки.** `DrawTerrainEdges` `$0158A0` дорисовывает краевые тайлы по
  двухбитным кодам соседства, а коды считает `RefreshCellTileStyle`
  `$0215DA` — с обращением к `Random`. То есть у самой игры стыки от
  запуска к запуску разные, и воспроизводить их бессмысленно.
- **Движение анимации.** Берётся только ПЕРВЫЙ кадр каждого потока (см.
  «Вода нарисована не в наборе тайлов»), дальше они не крутятся.
  `SeedAnimatedTiles` `$0214D2` раздаёт клеткам ещё и случайную фазу;
  здесь всегда нулевая.
- **Кадр юнита взят первый.** Спрайты рисуются, но анимация стоит на
  первом кадре своей последовательности.

## Вода нарисована не в наборе тайлов

Долго выглядело так, будто вода — чёрная. На деле её тайлы в наборе
**пустые**: сплошной цвет 15, а он в палитре этапа тёмно-серый. Настоящая
картинка приходит из потоковой анимации фона.

Третий ассет записи (`+$1C6`) — 4096 байт, из которых в VRAM уходит
только первый килобайт. Остальные 3072 `LoadStageGraphics` кладёт в
`$3EB4(a5)` = `$FF4418` (`$005168`), и это кадры анимации. Дальше пара
процедур из `StagePalettes` `$013686`, выбранная байтом `+$1CA` записи,
раз в несколько кадров переливает куски этого буфера в VRAM поверх
пустых тайлов — `DrawHudList` `$00C62C` и `VramUploadBlocks` `$00C600`.

Десять наборов написаны по-разному, и здесь разобраны все:

| набор | как устроен |
|---|---|
| 0, 2, 3, 8 | таблица словных смещений на списки кадров, `DrawHudList` в цикле |
| 4, 9 | те же списки, но развёрнутые в цепочку `lea`/`jsr` |
| 1 | четыре прямых выгрузки по `$0136D6` — по два тайла с шагом `$200` |
| 5, 6, 7 | общий хвост `$013DB2`, три вызова `VramUploadBlocks` |

Здесь подставляется **первый кадр** каждого потока — то, что игрок видит
в первый миг после загрузки.

## Юниты

Спрайт юнита — ровно `4x4` тайла, то есть 32x32 точки, то есть одна
клетка карты. Ставится он в свою клетку без смещения: `+$4` и `+$5`
записи юнита при расстановке обнулены.

Какую анимацию включить, говорит **байт позы** расстановки. `LoadPlacement`
`$01EA12` разбирает его длинной цепочкой сравнений, и каждая ветка кладёт
номер анимации в `+$7` записи юнита:

| поза | сколько в данных | что зовётся | анимация |
|---|---:|---|---|
| 0 | 619 | `EnterWalkStateNormal` | `$0A` при чётном направлении, `$0B` при нечётном |
| 1 | 237 | `EnterNestPose` | `$06` |
| 3 | 153 | `BeginHatchStages` | `$05` |
| 7 | 108 | `EnterIdleFacing` | `$05` |
| 4 | 60 | `UnitDieOnCell` -> `MakeCarcass` | `$20`, а у декора (бит 5 `+$C`) `$06` |
| 8 | 17 | то же плюс бит 4 `+$11` | `$20` / `$06` |
| 2 | 10 | `EnterIdleFacing` | `$05` |

Остальных поз (`$05`, `$06`, `$09`, `$0A`, `$0B`, `$0C`) разбор ждёт, но в
данных нет ни одной.

Направление берётся из тех же трёх бит слова расстановки; таблица
скриптов индексируется ЧЁТНЫМ направлением (`facing & ~1`), а нечётность
уже учтена выбором анимации. Палитра — ряд из `UnitPaletteRow` `$015156`.
Нулевой цвет у спрайтов прозрачен, и рисуются они в порядке возрастания
Y, чтобы ближний перекрывал дальнего — так же, как их сортирует сама игра
(`UpdateUnitScreenPos`, ключ `+$3 * 32 + +$5`).

## Лист образцов

`--types` рисует таблицу «тип x набор графики»: строка — номер типа
местности сверху вниз от 0 до 31, столбец — один из девяти различных
наборов. За тип берётся его первый байт карты, то есть самый обычный его
вид без кромок. Имён у типов в ROM нет, и это единственный способ
увидеть, что за ними стоит.

## Экспорт местности (`--export`)

Ремейк рисует растительность и прочие мелочи карты **объектами поверх
плитки**, а в оригинале это сами типы местности. Клетка там и там 32x32,
так что перенос прямой. Пишется в `out/<имя>/export/`:

    objects/grass.png, flowers.png, thorns.png   — сетка 2x2, стадии роста
    objects/stone.png, fire.png, dried_dirt.png,
    tree.png, crack.png, dry_land.png            — по одной картинке
    terrain/set<N>/type_<NN>.png                 — все 32 типа по всем девяти наборам

**Что подтверждено кодом**, а не глазом:

| имя ремейка | тип | откуда известно |
|---|---|---|
| `grass` | 1, 2, 3, 4 | `GrowGrassStage` растит «пока тип не 4», `SeedGrass` ставит 1 |
| `flowers` | 5, 6, 7 | `GrowFlowerStage`, «стадии 5…7» |
| `thorns` | 21, 22, 23 | `GrowOrShrinkThorn` работает ровно с 21/22/23 |
| `stone` | 10 | `LavaCoolToStone`: лава 11 остывает в 10 |
| `dried_dirt` | 18 | `FireBurnOut` переводит выгоревшую клетку в 18 |
| `water` | 19 | кромку ей достраивает `BuildMapEdgeCodes`, и она анимирована |
| `ice` | 14 | видно глазом: единственная ярко-синяя клетка |
| `vent` | 20 | жерло; вместе с водой единственные анимированные типы |

### Огонь рисуется в обход таблицы метатайлов

Клетка типа 12 в наборе тайлов — это шестнадцать раз тайл `$075`, то есть
голая земля, и так во всех девяти наборах. Пламени в наборах нет вовсе.
Рисует его отдельная ветка:

```asm
DrawCellTiles:                 ; $015B3C
	cmpi.b	#$14,d0            ; байт карты $14 = 20 — это огонь
	bne.w	DrawCellTilesPlain
	bsr.w	DrawFireCell       ; $015D18
```

`DrawFireCell` собирает клетку 4x4 сам: для каждого тайла берёт либо
обычную землю `$6075`, либо одну из двух плиток пламени `$0372`/`$0373`.
Какие места заняты пламенем, решает битовая маска из `FireTilePattern`
`$015E10` (восемь масок по четыре значащих бита), а выбирает её хеш
адреса клетки — поэтому узор у каждой клетки свой и от кадра к кадру не
дрожит.

Плитки пламени **не из набора этапа**: они лежат в VRAM по `$6E40` и
`$6E60`, сразу под областью спрайтов юнитов (`$374`), и рисуются
**палитрой ряда 0** — системной, где есть `$B40000`, `$FC2400` и
`$FCFC00`. В ROM это последние 64 байта блока `SharedTiles` `$010A6C`.

Анимирует их `TickFireTiles` `$00B7EE`: DMA копирует `$6E40` в `$6E60`
(так что второй тайл отстаёт на кадр), потом выгружает 32 байта из
`FireTileFrames`, щёлкая смещением между 0 и `$20`. Кадра всего два.

Поэтому `objects/fire.png` — это два тайла 8x8, а не клетка 32x32, и
рядом кладётся `fire_cell.png`: та же клетка, собранная как её собирает
игра, для сверки.

**Что поставлено по картинке** и потому может быть неверно: `tree` — тип
24 (рядом кладутся 25, розовое цветущее, и 26, хвойные); `crack` — тип 13
(чёрные разломы); `dry_land` — тип 17 (потрескавшаяся сушь, соседний 18
выглядит так же, но он занят выгоревшей землёй).

У цветов и колючек стадий в оригинале **три**, а ремейк ждёт четыре
(`GrowState`: Nothing, Small, Medium, Big). Три ложатся в ячейки 1…3, а
нулевая остаётся пустой: «только что посеянного» цветка в оригинале нет,
клетка сразу становится типом 5. У травы стадий ровно четыре, и они
ложатся без натяжки.

**Набор графики меняет смысл.** Тип 27 в первом наборе это зелёный куб, а
в четвёртом — каменный истукан. Одиночные картинки взяты из набора 0
(его берут 22 миссии), а `terrain/set<N>/` даёт все девять, чтобы было из
чего выбрать.

## Байт 0 читает мимо таблицы

Вычитание единицы означает, что у байта `$00` записи нет: индекс уходит
на восемь байт ПЕРЕД таблицей, в `$FF2BF8`. Таблица перевода и типа ему
не назначает (`$FF`), так что клетка, похоже, просто не предполагалась.
В картах он встречается; здесь такие клетки оставлены фоном.
"""
import collections
import io
import os
import struct
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from unpack import unpack                                    # noqa: E402
from gfx import png, columnwise, table_len                   # noqa: E402
from gfx import L as gfx_L                                   # noqa: E402
from paths import OUT as out_path, rom_bytes                 # noqa: E402

ROM = rom_bytes()
U16 = lambda o: struct.unpack_from(">H", ROM, o)[0]
U32 = lambda o: struct.unpack_from(">I", ROM, o)[0]

STAGES = 0x164400          # StageTable, индекс = номер этапа минус один
STAGE_GFX = 0x01318C       # StageGfxRecords
STAGE_REC = 0x01CC
ASSETS = 0x061800          # AssetTable, индекс уже в байтах
CHAPTERS = 0x060400        # ChapterTable
MREC = 0x5C                # описание миссии
TYPE_TO_TILE = 0x020454    # data_165: тип -> плитка
PAL_ARRAY = 0x00F784       # data_99
UNIT_PALETTE_ROW = 0x015156  # тип минус один -> ряд CRAM

W = H = 40
CELL = 32                  # точек на клетку: 2x2 метатайла по 2x2 тайла

# Куда ложатся три набора тайлов: (первый номер, поле записи, байт).
TILE_BANKS = ((0x075, 0x1C2, 0x0C00),
              (0x0D5, 0x1C4, 0x2000),
              (0x1D5, 0x1C6, 0x0400))


def chapters():
    u"""[(номер главы, тело)] — распакованные главы."""
    out = []
    for c in range(16):
        p = U32(CHAPTERS + c * 4)
        if not (0 < p < 0x280000):
            continue
        try:
            out.append((c, bytes(unpack(ROM, p)[2])))
        except Exception:
            continue
    return out


def missions():
    u"""[(глава, номер миссии, запись)] по всем главам."""
    out = []
    for c, body in chapters():
        for i in range(len(body) // MREC):
            r = body[i * MREC:(i + 1) * MREC]
            if not r[3]:
                continue
            out.append((c, i + 1, r))
    return out


def gfx_records():
    _m, size, d, _e = unpack(ROM, STAGE_GFX)
    return [bytes(d[k * STAGE_REC:(k + 1) * STAGE_REC])
            for k in range(size // STAGE_REC)]


def asset(w):
    u"""w — сырое слово записи, уже байтовое смещение в AssetTable."""
    return bytes(unpack(ROM, U32(ASSETS + w))[2])


def cram(v):
    return (((v >> 1) & 7) * 36, ((v >> 5) & 7) * 36, ((v >> 9) & 7) * 36)


def rec_palette(rec, n):
    o = n * 32
    return [cram((rec[o + 2 * j] << 8) | rec[o + 2 * j + 1]) for j in range(16)]


def array_palette(n):
    a = PAL_ARRAY + 32 * n
    return [cram(U16(a + 2 * j)) for j in range(16)]


VRAM_BASE = 0x0EA0         # к нему прибавляются смещения в списках

# Как заведена фоновая анимация каждого из десяти наборов. Адреса —
# процедуры StageAnimStartN, разобранные поодиночке.
ANIM_SETS = {
    0: ("table", 0x013806),
    1: ("pairs", ((0x000, 0x1EA0), (0x040, 0x1EE0),
                  (0x400, 0x22A0), (0x500, 0x1C60))),
    2: ("table", 0x013A20),
    3: ("table", 0x013B56),
    4: ("lists", (0x013BE8, 0x013C06, 0x013C24)),
    5: ("blocks", None),
    6: ("blocks", None),
    7: ("blocks", None),
    8: ("table", 0x014014),
    9: ("lists", (0x0140A8, 0x0140DE, 0x014114, 0x01413E)),
}

# Общий хвост наборов 5, 6 и 7, `$013DB2`: (источник, VRAM, тайлов, блоков)
BLOCKS_567 = ((0x900, 0x1EA0, 2, 2), (0x800, 0x22A0, 2, 2),
              (0x000, 0x3620, 4, 4))


def _S16(a):
    v = U16(a)
    return v - 0x10000 if v & 0x8000 else v


def _frame0(a):
    u"""Первый кадр списка: [(источник, VRAM, тайлов, блоков)]."""
    n = U16(a)
    a += 2
    if n == 0:                       # список начинается с перехода
        a = U32(a)
        n = U16(a)
        a += 2
    out = []
    for _ in range(n):
        src, dst, d1 = U16(a), U16(a + 2), U32(a + 4)
        out.append((src, VRAM_BASE + dst, d1 >> 16, d1 & 0xFFFF))
        a += 8
    return out


def anim_blocks(setno):
    u"""Что набор выгружает в VRAM первым кадром."""
    kind, arg = ANIM_SETS.get(setno, (None, None))
    if kind == "table":
        # lea (d16,pc),a2 ; moveq #n,d7 ; ... ; lea (d8,pc,d0.w),a0
        tbl = arg + 0x0C + _S16(arg + 0x0A + 2)
        count = ROM[arg + 0x0F] + 1
        base = arg + 0x14 + (U16(arg + 0x12 + 2) & 0xFF)
        out = []
        for i in range(count):
            out += _frame0((base + _S16(tbl + 2 * i)) & 0xFFFFFF)
        return out
    if kind == "lists":
        out = []
        for a in arg:
            out += _frame0(a)
        return out
    if kind == "pairs":                       # $0136D6: по 2 тайла дважды
        return [(src, vram, 2, 2) for src, vram in arg]
    if kind == "blocks":
        return list(BLOCKS_567)
    return []


def tileset(rec):
    u"""{номер тайла в VRAM: 32 байта}, уже с первым кадром анимации."""
    w = lambda o: (rec[o] << 8) | rec[o + 1]
    out = {}
    for base, off, nbytes in TILE_BANKS:
        d = asset(w(off))
        for t in range(nbytes // 32):
            out[base + t] = d[t * 32:(t + 1) * 32]
    # поверх пустых тайлов — первый кадр фоновой анимации
    frames = asset(w(0x1C6))[0x400:]
    for src, vram, per, blocks in anim_blocks(rec[0x1CB]):
        for b in range(blocks):
            so = src + b * 0x200
            t0 = (vram + b * 0x200) // 32
            for k in range(per):
                chunk = frames[so + k * 32:so + (k + 1) * 32]
                if len(chunk) == 32:
                    out[t0 + k] = chunk
    return out


def meta_tables(rec):
    u"""(байт карты -> тип, плитка -> метатайлы, метатайл -> тайлы)."""
    w = lambda o: (rec[o] << 8) | rec[o + 1]
    d = asset(w(0x1C0))
    d += b"\0" * max(0, 6144 - len(d))
    cells = [struct.unpack_from(">4H", d, 256 + 8 * i) for i in range(256)]
    metas = [struct.unpack_from(">4H", d, 2304 + 8 * i) for i in range(480)]
    return d[:256], cells, metas


EDGE_ADD = 0x00558A        # data_36: маска соседей -> добавка к байту


def autotile(cells):
    u"""Достройка берегов, `BuildMapEdgeCodes` `$00546E`.

    Работает, только когда взведён бит 7 байта `+$2F` описания миссии
    (93 миссии из 123), и только для байтов `$19` и `$49`: у них по восьми
    соседям собирается маска «сосед НЕ такой же», и `data_36` по ней даёт
    добавку к байту. То есть в данных лежит сплошная заливка, а кромку
    игра досчитывает при загрузке.
    """
    src = bytes(cells)
    out = bytearray(src)
    add = ROM[EDGE_ADD:EDGE_ADD + 256]
    for y in range(H):
        for x in range(W):
            i = y * W + x
            v = src[i]
            if v not in (0x19, 0x49):
                continue
            m = 0
            if y:
                if src[i - 40] != v:
                    m |= 1 << 0
                if x and src[i - 41] != v:
                    m |= 1 << 7
                if x != 39 and src[i - 39] != v:
                    m |= 1 << 1
            if y != 39:
                if src[i + 40] != v:
                    m |= 1 << 4
                if x and src[i + 39] != v:
                    m |= 1 << 5
                if x != 39 and src[i + 41] != v:
                    m |= 1 << 3
            if x and src[i - 1] != v:
                m |= 1 << 6
            if x != 39 and src[i + 1] != v:
                m |= 1 << 2
            out[i] = (v + add[m]) & 0xFF
    return bytes(out)


def placement(a):
    u"""[(x, y, направление, тип, поза)] расстановки."""
    out = []
    if not (0x100000 <= a < len(ROM) - 4):
        return out
    for _ in range(400):
        v = U16(a)
        if v & 0x8000:
            break
        out.append(((v >> 9) & 0x3F, v & 0x3F, (v >> 6) & 7,
                    ROM[a + 2], ROM[a + 3]))
        a += 4
    return out


SPECIES_BYTE = 0x01FAEE    # +$1 записи: вид плюс флаги, бит 5 — декор


def is_decor(t):
    return bool(ROM[SPECIES_BYTE + t * 4 + 1] & 0x20)


def pose_anim(t, pose, facing):
    u"""Номер анимации по байту позы; см. таблицу в шапке."""
    if pose == 0:
        return 0x0B if facing & 1 else 0x0A
    if pose == 1:
        return 0x06
    if pose in (2, 3, 7):
        return 0x05
    if pose in (4, 8):
        return 0x06 if is_decor(t) else 0x20
    return 0x0A


def unit_sprite(t, pose, facing, pal_rows):
    u"""32x32 цветов, None вместо прозрачного; None, если кадра нет."""
    import unitgfx
    anim = pose_anim(t, pose, facing)
    try:
        words = unitgfx.walk(unitgfx.script_addr(t, anim, facing & ~1))
    except Exception:
        return None
    if not words:
        return None
    w = words[0]
    tbl = (gfx_L(unitgfx.COMMON_FRAMES) if w & 0x100
           else unitgfx.frame_table(t))
    idx = w & 0xFF
    n = table_len(tbl)
    if not n or idx >= n:
        return None
    p = gfx_L(tbl + 4 * idx)
    if not (0 < p < 0x200000):
        return None
    try:
        data = columnwise(bytes(unpack(ROM, p)[2]))
    except Exception:
        return None
    pal = pal_rows[ROM[UNIT_PALETTE_ROW + t - 1] & 3]
    hf = bool(w & 0x800)
    out = [[None] * 32 for _ in range(32)]
    for ty in range(4):
        for tx in range(4):
            tile = data[(ty * 4 + tx) * 32:(ty * 4 + tx + 1) * 32]
            if len(tile) < 32:
                continue
            for y in range(8):
                row = out[ty * 8 + y]
                for x in range(8):
                    b = tile[y * 4 + (x >> 1)]
                    v = (b >> 4) if x % 2 == 0 else (b & 15)
                    if v:
                        row[31 - (tx * 8 + x) if hf else tx * 8 + x] = pal[v]
    return out


def draw(cells, rec, mrec, units, path, nosprite=None):
    if nosprite is None:
        nosprite = set()
    _typeof, celltab, metatab = meta_tables(rec)
    tiles = tileset(rec)
    pals = [array_palette(0), array_palette(mrec[0x28]),
            array_palette(mrec[0x29]), rec_palette(rec, mrec[0x4C])]
    back = pals[3][15]
    px = [[back] * (W * CELL) for _ in range(H * CELL)]
    skipped = 0

    cache = {}

    def block(name):
        u"""8x8 готовых цветов по слову имени; слов на карту немного."""
        b = cache.get(name)
        if b is None:
            g = tiles.get(name & 0x7FF)
            p = pals[(name >> 13) & 3]
            hf, vf = (name >> 11) & 1, (name >> 12) & 1
            if g is None:
                b = None
            else:
                b = []
                for y in range(8):
                    sy = 7 - y if vf else y
                    line = []
                    for x in range(8):
                        sx = 7 - x if hf else x
                        v = g[sy * 4 + (sx >> 1)]
                        line.append(p[(v >> 4) if sx % 2 == 0 else (v & 15)])
                    b.append(line)
            cache[name] = b
        return b

    for cy in range(H):
        for cx in range(W):
            b = cells[cy * W + cx]
            if b == 0:                 # см. «Байт 0» в шапке
                skipped += 1
                continue
            entry = celltab[b - 1]
            for q in range(4):
                meta = metatab[entry[q] & 0x1FF]
                ox0 = cx * CELL + (q & 1) * 16
                oy0 = cy * CELL + (q >> 1) * 16
                for s in range(4):
                    b = block((meta[s] + 0x6075) & 0xFFFF)
                    if b is None:
                        continue
                    bx = ox0 + (s & 1) * 8
                    by = oy0 + (s >> 1) * 8
                    for y in range(8):
                        px[by + y][bx:bx + 8] = b[y]

    # ближний перекрывает дальнего: рисуем сверху вниз
    for ux, uy, ud, ut, upose in sorted(units, key=lambda u: (u[1], u[0])):
        if not (0 <= ux < W and 0 <= uy < H):
            continue
        spr = unit_sprite(ut, upose, ud, pals)
        if spr is None:
            nosprite.add(ut)
            continue
        ox, oy = ux * CELL, uy * CELL
        for y in range(32):
            dst = px[oy + y]
            src = spr[y]
            for x in range(32):
                if src[x] is not None:
                    dst[ox + x] = src[x]

    png(path, W * CELL, H * CELL, px)
    return skipped


def record_palette_no(recs):
    u"""{запись графики: номер палитры +$4C первой миссии, что её берёт}."""
    out = {}
    for _c, _m, r in missions():
        out.setdefault(r[0x2A], r[0x4C])
    return out


def type_sheet(recs, path, scale=2):
    u"""Лист образцов: строка — тип местности, столбец — набор графики.

    Каждая клетка нарисована так же, как на карте, 32x32 точки. Это
    единственный способ увидеть, что за местность скрыта за номером: имён
    у типов в ROM нет.
    """
    uniq = []
    for k, rec in enumerate(recs):
        key = (rec[0x1C0:0x1C8],)
        if key not in [u[0] for u in uniq]:
            uniq.append((key, k))
    cols = [k for _key, k in uniq]
    palno = record_palette_no(recs)
    gap = 4
    step = CELL * scale + gap
    wpx = len(cols) * step + gap
    hpx = 32 * step + gap
    img = [[(20, 20, 24)] * wpx for _ in range(hpx)]

    for ci, k in enumerate(cols):
        rec = recs[k]
        _typeof, celltab, metatab = meta_tables(rec)
        tiles = tileset(rec)
        pals = [array_palette(0), array_palette(1),
                array_palette(3), rec_palette(rec, palno.get(k, 0))]
        typeof = meta_tables(rec)[0]
        first = {}
        for b in range(255, 0, -1):
            first[typeof[b]] = b
        for t in range(32):
            b = first.get(t)
            if b is None:
                continue
            entry = celltab[b - 1]
            ox = gap + ci * step
            oy = gap + t * step
            for q in range(4):
                meta = metatab[entry[q] & 0x1FF]
                for s in range(4):
                    name = (meta[s] + 0x6075) & 0xFFFF
                    g = tiles.get(name & 0x7FF)
                    if g is None:
                        continue
                    p = pals[(name >> 13) & 3]
                    hf, vf = (name >> 11) & 1, (name >> 12) & 1
                    bx = ox + ((q & 1) * 16 + (s & 1) * 8) * scale
                    by = oy + ((q >> 1) * 16 + (s >> 1) * 8) * scale
                    for y in range(8):
                        sy = 7 - y if vf else y
                        for x in range(8):
                            sx = 7 - x if hf else x
                            b = g[sy * 4 + (sx >> 1)]
                            c = p[(b >> 4) if sx % 2 == 0 else (b & 15)]
                            for ky in range(scale):
                                row = img[by + y * scale + ky]
                                for kx in range(scale):
                                    row[bx + x * scale + kx] = c
    png(path, wpx, hpx, img)
    return cols


# Имя ремейка -> типы оригинала. Стадии идут в ячейки сетки по порядку.
STAGED = (("grass", (1, 2, 3, 4)),
          ("flowers", (None, 5, 6, 7)),
          ("thorns", (None, 21, 22, 23)))
SINGLE = (("stone", 10), ("dried_dirt", 18), ("dry_land", 17),
          ("crack", 13), ("tree", 24), ("tree_pink", 25),
          ("tree_fir", 26), ("water", 19), ("ice", 14),
          ("vent", 20), ("lava", 11))


def cell_pixels(t, celltab, metatab, tiles, pals, typeof):
    u"""32x32 цветов клетки типа t, или None если такого типа в наборе нет."""
    b = None
    for k in range(255, 0, -1):
        if typeof[k] == t:
            b = k
    if b is None:
        return None
    entry = celltab[b - 1]
    px = [[(0, 0, 0, 0)] * CELL for _ in range(CELL)]
    for q in range(4):
        meta = metatab[entry[q] & 0x1FF]
        for sx in range(4):
            name = (meta[sx] + 0x6075) & 0xFFFF
            g = tiles.get(name & 0x7FF)
            if g is None:
                continue
            p = pals[(name >> 13) & 3]
            hf, vf = (name >> 11) & 1, (name >> 12) & 1
            bx = (q & 1) * 16 + (sx & 1) * 8
            by = (q >> 1) * 16 + (sx >> 1) * 8
            for y in range(8):
                yy = 7 - y if vf else y
                for x in range(8):
                    xx = 7 - x if hf else x
                    v = g[yy * 4 + (xx >> 1)]
                    px[by + y][bx + x] = p[(v >> 4) if xx % 2 == 0
                                           else (v & 15)] + (255,)
    return px


SHARED_TILES = 0x010A6C            # общий блок; пламя — последние 64 байта
FIRE_TILES = 2


def export_fire(objects):
    u"""Две плитки пламени: их в наборах этапа нет, см. шапку."""
    data = bytes(unpack(ROM, SHARED_TILES)[2])
    fire = data[-32 * FIRE_TILES:]
    pal = array_palette(0)                 # имя $0372 -> ряд 0, не ряд этапа
    w, h = 8 * FIRE_TILES, 8
    img = [[(0, 0, 0, 0)] * w for _ in range(h)]
    for t in range(FIRE_TILES):
        g = fire[t * 32:(t + 1) * 32]
        for y in range(8):
            for x in range(8):
                b = g[y * 4 + (x >> 1)]
                v = (b >> 4) if x % 2 == 0 else (b & 15)
                if v:
                    img[y][t * 8 + x] = pal[v] + (255,)
    png(os.path.join(objects, "fire.png"), w, h, img, alpha=True)

    # клетка целиком, как её собирает DrawFireCell
    masks = ROM[0x015E10:0x015E18]
    cell = [[(0, 0, 0, 0)] * CELL for _ in range(CELL)]
    for row in range(4):
        m = masks[row]
        for col in range(4):
            if not (m >> col) & 1:
                continue
            g = fire[(col % FIRE_TILES) * 32:(col % FIRE_TILES + 1) * 32]
            for y in range(8):
                for x in range(8):
                    b = g[y * 4 + (x >> 1)]
                    v = (b >> 4) if x % 2 == 0 else (b & 15)
                    if v:
                        cell[row * 8 + y][col * 8 + x] = pal[v] + (255,)
    png(os.path.join(objects, "fire_cell.png"), CELL, CELL, cell, alpha=True)
    return 2


def export_terrain():
    recs = gfx_records()
    palno = record_palette_no(recs)
    root = out_path("export")
    objects = os.path.join(root, "objects")
    os.makedirs(objects, exist_ok=True)

    uniq = []
    for k, rec in enumerate(recs):
        key = rec[0x1C0:0x1C8]
        if key not in [u[0] for u in uniq]:
            uniq.append((key, k))

    made = 0
    made += export_fire(objects)
    for _key, k in uniq:
        rec = recs[k]
        typeof, celltab, metatab = meta_tables(rec)
        tiles = tileset(rec)
        pals = [array_palette(0), array_palette(1), array_palette(3),
                rec_palette(rec, palno.get(k, 0))]
        d = os.path.join(root, "terrain", "set%d" % k)
        os.makedirs(d, exist_ok=True)
        cells = {}
        for t in range(32):
            px = cell_pixels(t, celltab, metatab, tiles, pals, typeof)
            if px is None:
                continue
            cells[t] = px
            png(os.path.join(d, "type_%02d.png" % t), CELL, CELL, px,
                alpha=True)
            made += 1
        if k != 0:
            continue
        # именованные картинки — из набора 0
        for name, stages in STAGED:
            w = h = CELL * 2
            img = [[(0, 0, 0, 0)] * w for _ in range(h)]
            for i, t in enumerate(stages):
                if t is None or t not in cells:
                    continue
                ox, oy = (i % 2) * CELL, (i // 2) * CELL
                for y in range(CELL):
                    img[oy + y][ox:ox + CELL] = cells[t][y]
            png(os.path.join(objects, name + ".png"), w, h, img, alpha=True)
            made += 1
        for name, t in SINGLE:
            if t not in cells:
                continue
            png(os.path.join(objects, name + ".png"), CELL, CELL, cells[t],
                alpha=True)
            made += 1

    print(u"местность: %d картинок, наборов %d -> %s"
          % (made, len(uniq), os.path.relpath(root, HERE)))
    return 0


def main():
    args = sys.argv[1:]
    if "--export" in args:
        return export_terrain()
    want = None
    if args and args[0] == "--types":
        recs = gfx_records()
        d = out_path("maptex")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "_types.png")
        cols = type_sheet(recs, p)
        print("лист образцов: 32 типа x %d набора -> %s"
              % (len(cols), os.path.relpath(p, HERE)))
        print("столбцы — записи графики: %s"
              % ", ".join(str(c) for c in cols))
        return 0
    if len(args) >= 2:
        want = (int(args[0]), int(args[1]))

    recs = gfx_records()
    outdir = out_path("maptex")
    os.makedirs(outdir, exist_ok=True)

    by_rec = collections.defaultdict(list)
    nosprite = set()
    drawn = skipped_total = 0
    for c, m, r in missions():
        if want and (c, m) != want:
            continue
        st = r[3]
        o = STAGES + (st - 1) * 8
        mp, pl = U32(o), U32(o + 4)
        if not (0x164C00 <= mp < 0x200000):
            continue
        try:
            _me, size, cells, _e = unpack(ROM, mp)
        except Exception:
            continue
        if size != W * H:
            continue
        if r[0x2F] & 0x80:
            cells = autotile(cells)
        rec_no = r[0x2A]
        if rec_no >= len(recs):
            continue
        by_rec[rec_no].append("гл.%d м.%d" % (c, m))
        # этап в имени — ИНДЕКС StageTable, то есть байт +$3 минус один:
        # так имя совпадает со stage_NNN.png от tools/maps.py
        name = "ch%d_m%02d_stage%03d.png" % (c, m, st - 1)
        skipped_total += draw(cells, recs[rec_no], r,
                              placement(pl), os.path.join(outdir, name),
                              nosprite)
        drawn += 1

    print("нарисовано карт: %d -> %s"
          % (drawn, os.path.relpath(outdir, HERE)))
    if want:
        return 0
    print("клеток с байтом 0 (записи нет, не нарисованы): %d"
          % skipped_total)
    if nosprite:
        print("типы без кадра: %s" % sorted(nosprite))

    doc = os.path.join(HERE, "docs", "game-tilesets.md")
    f = io.open(doc, "w", encoding="utf-8", newline="\n")
    p = f.write
    p(u"# Наборы тайлов этапов\n\n")
    p(u"Собрано `tools/maptex.py` (`make maptex`). Картинки — "
      u"в `out/<имя>/maptex/`, по PNG 1280x1280 на миссию.\n\n")
    p(u"СГЕНЕРИРОВАНО — правки затираются, меняйте инструмент.\n"
      u"Вывод, который надо сохранить, пишите в соседний, ручной файл.\n\n")
    p(u"Цепочка «байт карты -> пиксели» разобрана в шапке "
      u"`tools/maptex.py`; там же перечислено, чего в этих картинках "
      u"нет (стыки, анимация, спрайты юнитов).\n\n")
    p(u"## Одиннадцать записей `StageGfxRecords` `$01318C`\n\n")
    p(u"| запись | метатайлы | наборы тайлов | анимация `+$1CA` | миссии |\n")
    p(u"|---|---|---|---|---|\n")
    for k, rec in enumerate(recs):
        w = lambda o: (rec[o] << 8) | rec[o + 1]
        ms = by_rec.get(k, [])
        p(u"| %d | `$%06X` | %s | %d | %d: %s |\n"
          % (k, U32(ASSETS + w(0x1C0)),
             ", ".join("`$%06X`" % U32(ASSETS + w(0x1C2 + 2 * i))
                       for i in range(3)),
             rec[0x1CB], len(ms),
             ", ".join(ms[:6]) + (" …" if len(ms) > 6 else "") or "—"))
    p(u"\n## Байт карты -> тип местности\n\n")
    p(u"Первые 256 байт описания метатайлов. Это **не** «младшие пять бит "
      u"байта», как считалось раньше: таблица своя у каждого набора, хотя "
      u"по делу они почти совпадают.\n\n")
    tabs = collections.OrderedDict()
    for k, rec in enumerate(recs):
        tabs.setdefault(meta_tables(rec)[0], []).append(k)
    p(u"Различных таблиц: **%d** на одиннадцать записей.\n\n" % len(tabs))
    first = list(tabs)[0]
    p(u"| байт | тип | байт | тип | байт | тип | байт | тип |\n")
    p(u"|---|---|---|---|---|---|---|---|\n")
    shown = [b for b in range(64) if first[b] != 0xFF]
    for i in range(0, len(shown), 4):
        row = shown[i:i + 4]
        p(u"| " + " | ".join("%d | %d" % (b, first[b]) for b in row)
          + " |" * (4 - len(row)) * 2 + u" |\n")
    f.close()
    print("сводка: %s" % os.path.relpath(doc, HERE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
