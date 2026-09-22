#!/usr/bin/env python3
u"""Сценки между миссиями: заголовок блока, скрипты актёров, реплики.

    make cutscene                   # все 15 сценок
    make cutscene CSARGS=3          # только сценка 3
    make cutscene CSARGS=--back     # четыре фона в PNG
    make cutscene CSARGS="--play 0" # проиграть сценку 0 в GIF

## Где они и когда играют

`CutsceneIndex` `$04FC14` — три строки по десять байт. Строка это ГЛАВА
МИНУС ТРИ, то есть доступны только главы 3, 4 и 5; в строке байт по
номеру миссии минус один, `$FF` значит «сценки нет». Заполнены только
нечётные места — миссии 1, 3, 5, 7 и 9. Итого пятнадцать сценок, ровно
столько же указателей в `CutsceneTable` `$04FC32`.

Байт из индекса — это номер блока, а не номер миссии: порядок в главе
перемешан (в главе 3 идут 0, 1, 3, 4, 2).

## Блок

`ShowCutscene` `$04FD28` распаковывает блок в `$FF2564`. Заголовок:

| смещение | что |
|---|---|
| `+$0` | номер записи `StageGfxRecords` — от неё палитры и тайлы |
| `+$2` | смещение от `+$2` до рамки текстового окна |
| `+$4` | смещение в `CutsceneScreens` `$1CC68C` — какой из четырёх фонов |
| `+$6` | смещение от `+$6` до списка реплик |
| `+$8` | сколько актёров |
| `+$A` | скрипты актёров подряд, каждый кончается нулевым словом |

Фон — таблица имён на 2240 байт; `ScreenUnpackByArg` `$050230` берёт из
неё 481 слово, гонит через `(n + $75) & $1FFF | $6000` (то же правило,
что у карты) и кладёт двенадцать строк в VRAM `$C380`. Все четыре фона —
один и тот же пейзаж с переставленными цветочками.

Рамку окна (`+$2`) рисуют дважды, в VRAM `$4BA0` и `$55A0`, а имена
кладут в `$C124` и `$C224` — это две строки текста внизу экрана.

## Актёры

`ScreenBig` `$056370` (имя механическое, на деле «завести актёров»)
раскладывает по записи на актёра, `$5A` байт каждая, начиная с `$86(a5)`,
и ставит каждому указатель на его скрипт. Больше двадцати актёров не
берёт. Поля записи, которые трогает скрипт:

| поле | что |
|---|---|
| `$3E` | тип юнита — тот же номер, что в `unitgfx`/`unitanim` |
| `$40` | номер анимации (`$04`…`$20`) |
| `$42` | направление, 0…7 |
| `$44`, `$46` | X и Y на экране (к обоим прибавлено `$80`, как у спрайтов) |
| `$48`, `$4C` | шаг по X и по Y за кадр, знаковый байт |
| `$50` | сколько кадров ещё ждать |
| `$58` | флаги: бит 0 — жив, бит 2 — анимация зациклена, бит 3 — «дошёл» |
| `$59` | ряд палитры, 0…3 |

## Команды

`ScreenObjRecords` `$0564FC` раз в кадр читает у каждого живого актёра
СЛОВО: старший ниббл — команда, младшие двенадцать бит — аргумент.
Таблица переходов — `$056688`, шестнадцать слов; коды `9`…`F` ведут
обратно в выборку, то есть пустые.

| код | аргумент | что делает |
|---|---|---|
| 0 | — | конец скрипта: снять бит 0, убавить счётчик живых |
| 1 | младший байт, биты 8…11 | завести анимацию трапом `$FF08` по `$3E`/`$40`/`$42`, потом промотать её трапом `$FF09` столько раз, сколько в младшем байте; ненулевые биты 8…11 взводят «зациклена» |
| 2 | биты 8…11 — подкоманда | работа с текстовым окном, см. ниже |
| 3 | биты 8…9 — поле, младший байт — значение | положить значение в `$3E`, `$40`, `$42` или `$59` |
| 4 | знаковый байт | шаг по X |
| 5 | знаковый байт | шаг по Y |
| 6 | слово | X |
| 7 | слово | Y |
| 8 | биты 8…10 — подкоманда | ожидания, см. ниже |

Подкоманды кода 2 (в таблице шесть рабочих, скрипты берут две):

| под | что |
|---|---|
| 1 | показать реплику: `$12(a5) = 1` и вызов `$0503B4` |
| 2 | текстовое окно: аргумент 0 кладёт в `$84(a5)` `-$50`, иначе `+$50`. Что это «убрать» и «показать» — видно по употреблению: на пятнадцать сценок ровно по одной паре, `$201` всегда перед первой репликой, `$200` всегда последней командой |

Подкоманды кода 8:

| под | что |
|---|---|
| 0 | ждать N кадров (N — младший байт) |
| 1 | отметиться «дошёл»: `$7E(a5)` плюс один, бит 3 |
| 2 | ждать остальных: пока `$7E(a5)` меньше «всех минус один», указатель откатывается на слово назад и команда повторяется в следующем кадре |
| 3 | ждать конца анимации; у зацикленной (бит 2) не ждать вовсе |
| 4 | ждать текст: если `$12(a5)` не ноль — ещё десять кадров |

Пара «1 и 2» — это точка встречи: все актёры доходят до своего места,
отмечаются, и только когда отметились все, сценка идёт дальше.

## Реплики

Список реплик лежит по смещению `+$6` и состоит из записей вида

    <ширина + 1> <сколько строк> {строка, ноль} ... <ноль>

Ширина — это длина самой длинной строки записи вместе с нулём, плюс
единица; по ней подбирается ширина пузыря. Сам текст уже выписан
`tools/packedtext.py` в [game-cutscenes.md](../docs/game-cutscenes.md), но
там он лежит плоским списком, без привязки к тому, кто говорит.

## Пузырь реплики

Рисует его `$0503B4`, и это НЕ строка внизу экрана, а пузырь над
говорящим. Ширина — тот самый первый байт записи реплики; левый столбец
считается от X актёра:

```asm
	move.w	$44(a1),d4
	subi.w	#$0080,d4
	lsr.w	#3,d4          ; в клетки по восемь точек
	addq.w	#1,d4          ; столбец хвостика, но не меньше двух
	...
	cmpi.w	#$0027,d3      ; если правый край за 39-м столбцом —
	...                    ; прижать пузырь к краю
```

Строки в таблице имён: 19 — хвостик (`$C980`), 20 — верхняя кромка,
с 21-й через одну текст (`$CA82`), потом нижняя кромка. То есть на строку
текста приходится ДВЕ строки таблицы имён, а знак — один тайл 8x8.

Текст выводится по знаку в кадр (`$05056E` ставит `$A(a5) = 1`), в конце
строки пауза `$18` кадров. Байты гоняются через трап `$FF24` и
`CharToTileTable`, а глифы лежат в `FontTiles` `$010322`.

**Кодировка полуширинная, а глифы хираганные:** `ｾｯｼｬﾊ` выходит на экран
как `せっしゃは`. Катакана в выгрузках текста — транслитерация.

## Проигрывание (`--play`)

`--play K` прогоняет сценку кадр в кадр и пишет GIF. Порядок тот же, что
у `ScreenObjRecords`: сперва у каждого живого актёра выполняются команды
до первой останавливающей (коды 0, 1, 2 и 8 кончают кадр, коды 3…7 идут
дальше в том же), потом всем убавляются счётчики и применяется шаг.
Спрайт берётся из `unitanim` по тройке (`$3E`, `$40`, `$42`), палитра —
по `$59`, место — `$44`/`$46` минус `$80`.

Экран режется до полосы, где что-то есть: пейзаж лежит с точки 56 по
152, а текстовое окно игры сюда не переносится, и пустой чёрный низ
незачем.

**Одно расхождение с игрой, и оно намеренное:** команда «реплика» в игре
ждёт кнопку, здесь держится 90 кадров (меняется третьим аргументом).
Поэтому длительность целиком моя, а не игровая; всё остальное — по
счётчикам ROM.

## Что подтвердил прогон

Три проверки, и ни одна не «выглядит правдоподобно»:

- все **2984** командных слова во всех пятнадцати блоках попали в девять
  рабочих кодов, ни одного в пустые;
- каждый из **67** скриптов кончается ровно там, где начинается рамка
  текстового окна, — зазор ноль байт во всех пятнадцати;
- при прогоне ни одна сценка не зависла на точке встречи, и в каждой
  число выполненных команд «реплика» **в точности** равно числу записей
  текста в блоке. Всего 196 на 196.

Последнее заодно говорит, что `$0503B4` берёт записи ПО ПОРЯДКУ: иначе
совпадение пятнадцать раз подряд было бы случайностью.

## Чего здесь нет

Кто именно говорит, по-прежнему не выведено: номер актёра кладётся в
`$C(a5)`, но что с ним делает `$0503B4` — не разобрано, и проверяется
только запуском. Поэтому в `--play` реплики не рисуются.
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
from gfx import png, gif                                     # noqa: E402
from paths import OUT as out_path, rom_bytes                 # noqa: E402
from dumptext import dec                                     # noqa: E402

ROM = rom_bytes()
U32 = lambda o: struct.unpack_from(">I", ROM, o)[0]

CUT_INDEX = 0x04FC14       # CutsceneIndex: три строки по десять байт
CUT_TABLE = 0x04FC32       # CutsceneTable: пятнадцать указателей
CUT_SCREENS = 0x1CC68C     # CutsceneScreens: четыре таблицы имён
FIRST_CHAPTER = 3          # строка индекса = глава минус три
PER_CHAPTER = 10
COLS, SCREEN_ROWS = 40, 12  # ScreenUnpackByArg кладёт 481 слово = 12 строк

FIELDS = ("тип", "анимация", "направление", "палитра")


def missions():
    u"""[(глава, миссия, номер сценки)] по CutsceneIndex."""
    out = []
    for row in range(3):
        for m in range(PER_CHAPTER):
            b = ROM[CUT_INDEX + row * PER_CHAPTER + m]
            if b != 0xFF:
                out.append((FIRST_CHAPTER + row, m + 1, b))
    return out


def block(k):
    u"""Распакованный блок сценки k."""
    return bytes(unpack(ROM, U32(CUT_TABLE + k * 4))[2])


def header(d):
    u"""(запись графики, рамка окна, номер фона, список реплик, актёров)."""
    w = lambda o: struct.unpack_from(">H", d, o)[0]
    return (w(0), 2 + w(2), w(4) // 4, 6 + w(6), w(8))


def sbyte(v):
    v &= 0xFF
    return v - 0x100 if v & 0x80 else v


def _every(arg):
    u"""Старший байт слова шага — задержка: шаг раз в (N + 1) кадров."""
    n = (arg >> 8) & 0xFF
    return u" раз в %d кадра" % (n + 1) if n else u""


def command(word):
    u"""Слово скрипта -> (код, человеческая запись)."""
    op, arg = word >> 12, word & 0x0FFF
    if op == 0:
        return op, u"конец"
    if op == 1:
        loop = u", зациклить" if arg & 0x0F00 else u""
        n = arg & 0xFF
        return op, (u"анимация: пустить%s%s"
                    % (u", промотать %d" % n if n else u"", loop))
    if op == 2:
        sub = (arg >> 8) & 0x0F
        if sub == 1:
            return op, u"реплика"
        if sub == 2:
            return op, (u"показать окно" if arg & 0xFF
                        else u"убрать окно")
        return op, u"окно: подкоманда %d, аргумент $%02X" % (sub, arg & 0xFF)
    if op == 3:
        sub = (arg >> 8) & 3
        return op, u"%s = %d" % (FIELDS[sub], arg & 0xFF)
    if op == 4:
        return op, u"шаг X = %+d%s" % (sbyte(arg), _every(arg))
    if op == 5:
        return op, u"шаг Y = %+d%s" % (sbyte(arg), _every(arg))
    if op == 6:
        return op, u"X = %d" % (arg - 0x80)
    if op == 7:
        return op, u"Y = %d" % (arg - 0x80)
    if op == 8:
        sub = (arg >> 8) & 7
        if sub == 0:
            return op, u"ждать %d кадров" % (arg & 0xFF)
        if sub == 1:
            return op, u"отметиться «дошёл»"
        if sub == 2:
            return op, u"ждать остальных"
        if sub == 3:
            return op, u"ждать конца анимации"
        if sub == 4:
            return op, u"ждать текст"
        return op, u"ожидание: подкоманда %d" % sub
    return op, u"пусто (код %X)" % op


def actor_brief(one):
    u"""«тип 17; палитра 2; анимации 6, 10, 19…» — по командам кода 3."""
    seen = {0: [], 1: [], 2: [], 3: []}
    for _o, w, _t in one:
        if w >> 12 == 3:
            sub, v = (w >> 8) & 3, w & 0xFF
            if v not in seen[sub]:
                seen[sub].append(v)
    bits = []
    if seen[0]:
        bits.append(u"тип %s" % u"/".join(str(v) for v in seen[0]))
    if seen[3]:
        bits.append(u"палитра %s" % u"/".join(str(v) for v in seen[3]))
    if seen[1]:
        bits.append(u"анимации %s"
                    % u", ".join(str(v) for v in sorted(seen[1])))
    return u"; ".join(bits) or u"без типа"


def actors(d, start, count):
    u"""[[(смещение, слово, запись)]] — скрипт каждого актёра."""
    out, o = [], start
    for _ in range(count):
        one = []
        while o + 1 < len(d):
            w = struct.unpack_from(">H", d, o)[0]
            one.append((o, w) + (command(w)[1],))
            o += 2
            if w == 0:
                break
        out.append(one)
    return out, o


def lines(d, start, raw=False):
    u"""[(ширина, [строки])] — список реплик; raw отдаёт сырые байты."""
    out, o = [], start
    while o + 1 < len(d):
        width, n = d[o], d[o + 1]
        if not n or n > 8 or width < 2:
            break
        o += 2
        got = []
        for _ in range(n):
            e = o
            while e < len(d) and d[e]:
                e += 1
            got.append(d[o:e] if raw else dec(d[o:e]))
            o = e + 1
        out.append((width, got))
        if o < len(d) and d[o] == 0:
            o += 1
        if o < len(d) and d[o] == 0:
            break
    return out


def stage(k):
    u"""(запись графики, палитры, номер фона) сценки k."""
    import maptex
    grec, _frame, scr, _txt, _n = header(block(k))
    rec = maptex.gfx_records()[grec]
    pals = [maptex.array_palette(0), maptex.array_palette(1),
            maptex.array_palette(3), maptex.rec_palette(rec, 0)]
    return rec, pals, scr


def backdrop_indexes(rec, scr):
    u"""Фон НОМЕРАМИ цветов: [строка][столбец], 320x96."""
    import maptex
    names = bytes(unpack(ROM, U32(CUT_SCREENS + scr * 4))[2])
    tiles = maptex.tileset(rec)
    w, h = COLS * 8, SCREEN_ROWS * 8
    px = [bytearray(w) for _ in range(h)]
    for r in range(SCREEN_ROWS):
        for c in range(COLS):
            n = struct.unpack_from(">H", names, (r * COLS + c) * 2)[0]
            n = ((n + 0x0075) & 0x1FFF) | 0x6000      # ScreenUnpackByArg
            g = tiles.get(n & 0x7FF)
            if g is None:
                continue
            row0 = ((n >> 13) & 3) * 16
            hf, vf = (n >> 11) & 1, (n >> 12) & 1
            for y in range(8):
                sy = 7 - y if vf else y
                row = px[r * 8 + y]
                for x in range(8):
                    sx = 7 - x if hf else x
                    v = g[sy * 4 + (sx >> 1)]
                    row[c * 8 + x] = row0 + ((v >> 4) if sx % 2 == 0
                                             else (v & 15))
    return px


def backdrop(k, path):
    u"""Фон сценки k в PNG: двенадцать строк тайлами записи графики."""
    rec, pals, scr = stage(k)
    flat = [c for row in pals for c in row]
    px = backdrop_indexes(rec, scr)
    png(path, COLS * 8, SCREEN_ROWS * 8,
        [[flat[v] for v in row] for row in px])
    return scr


FONT_TILES = 0x010322      # FontTiles: 5440 байт, три блока
CHAR_TO_TILE = 0x00F8A8    # CharToTileSource: 256 слов, код -> номер тайла
# (смещение в распакованном блоке, первый номер тайла, сколько тайлов)
FONT_BLOCKS = ((0x0000, 0x002, 54), (0x06C0, 0x038, 61),
               (0x0E60, 0x780, 55))
BUBBLE_ROW = 19            # $C980: ($C980 - $C000) / 128
TEXT_ROW = 21              # $CA82, и дальше через строку

SCREEN_W, SCREEN_H = 320, 224
BACK_Y = 56                # фон с седьмой строки: $C380 - $C000 = 7 x $80
SPRITE_BIAS = 0x80         # у спрайтов VDP начало экрана в $80
TALK_FRAMES = 90           # сколько держать реплику; в игре ждут кнопку
PLAY_LIMIT = 20000         # предохранитель от незакрывшегося ожидания


_FONT = {}


def font_glyphs():
    u"""{номер тайла: 32 байта} — графика шрифта из `FontTiles` `$010322`."""
    if not _FONT:
        d = bytes(unpack(ROM, FONT_TILES)[2])
        for off, first, count in FONT_BLOCKS:
            for i in range(count):
                o = off + i * 32
                _FONT[first + i] = d[o:o + 32]
    return _FONT


def line_tiles(raw):
    u"""Байты строки -> номера тайлов, как `BiosParseString` `$00172A`.

    `$40` переключает размер шрифта и сам ничего не печатает; в поднятом
    состоянии коды `$A6`…`$DD` уменьшаются на `$40` и попадают в крупный
    диапазон. `$2A` — экранирование, здесь просто пропускается.
    """
    out, big = [], False
    i = 0
    while i < len(raw):
        c = raw[i]
        i += 1
        if c == 0x40:
            big = not big
            continue
        if c == 0x2A:
            i += 1
            continue
        if big and 0xA6 <= c <= 0xDD:
            c -= 0x40
        out.append(struct.unpack_from(">H", ROM, CHAR_TO_TILE + c * 2)[0])
    return out


def bubble_box(x, width):
    u"""(левый столбец, столбец хвостика) — по `$0503B4`."""
    tail = max(2, ((x - SPRITE_BIAS) >> 3) + 1)
    left = tail - 1
    if left < 0:
        left = 1
    elif left + width > 39:
        left = 39 - width
    return left, tail


class Actor(object):
    u"""Запись актёра: те поля `$5A`-байтной записи, что трогает скрипт."""

    def __init__(self, pc):
        self.pc, self.alive = pc, True
        self.wait = 0                       # $50
        self.parked = False                 # бит 3: «дошёл», ждёт остальных
        self.looped = False                 # бит 2
        self.kind = self.anim = self.face = self.pal = 0   # $3E $40 $42 $59
        self.x = self.y = 1                 # $44 $46
        self.stepx = self.stepy = 0         # $48 $4C: задержка и шаг
        self.cntx = self.cnty = 0           # $4A $4E
        self.seq, self.idx, self.timer = None, 0, 0

    def word(self):
        return self.seq[self.idx][0] if self.seq else None


def _load_anim(a):
    import unitanim, unitgfx
    try:
        addr = unitgfx.script_addr(a.kind, a.anim, a.face)
        seq, loop, ok, _nxt = unitanim.steps(addr, unitanim.entry_map(a.kind))
    except Exception:
        seq, loop, ok = [], None, False
    a.seq = seq if (ok and seq) else None
    a.loop_to = loop or 0
    a.idx, a.timer = 0, (seq[0][1] if a.seq else 0)


def _advance(a):
    if not a.seq:
        return
    if a.idx + 1 < len(a.seq):
        a.idx += 1
    elif a.looped or a.loop_to:
        a.idx = a.loop_to
    a.timer = a.seq[a.idx][1]


def _rest(a):
    u"""Сколько кадров до конца одноразовой анимации."""
    if not a.seq:
        return 1
    return max(1, a.timer + sum(d for _w, d in a.seq[a.idx + 1:]))


def step_actor(a, d, ctx):
    u"""Выполнить команды до первой останавливающей, как `$056668`."""
    while a.alive:
        w = struct.unpack_from(">H", d, a.pc)[0]
        a.pc += 2
        op, arg = w >> 12, w & 0x0FFF
        if op == 0:
            a.alive = False
            return
        if op == 3:                         # мгновенные: сразу следующая
            sub, v = (arg >> 8) & 3, arg & 0xFF
            if sub == 0:
                a.kind = v
            elif sub == 1:
                a.anim = v
            elif sub == 2:
                a.face = v
            else:
                a.pal = v & 3
            continue
        if op == 4:
            a.stepx, a.cntx = arg, 0
            continue
        if op == 5:
            a.stepy, a.cnty = arg, 0
            continue
        if op == 6:
            a.x = arg
            continue
        if op == 7:
            a.y = arg
            continue
        if op == 1:                         # останавливающие: кадр кончился
            a.looped = bool(arg & 0x0F00)
            _load_anim(a)
            for _ in range(arg & 0xFF):
                _advance(a)
            return
        if op == 2:
            if ((arg >> 8) & 0x0F) == 1:
                a.wait = ctx["talk"]
                rec = (ctx["lines"][ctx["said"]]
                       if ctx["said"] < len(ctx["lines"]) else None)
                ctx["said"] += 1
                if rec:
                    width, got = rec
                    left, tail = bubble_box(a.x, width)
                    ctx["bubble"] = [got, width, left, tail, ctx["talk"]]
            return
        if op == 8:
            sub = (arg >> 8) & 7
            if sub == 0:
                a.wait = arg & 0xFF
            elif sub == 1:
                a.parked, a.wait = True, 1
                ctx["arrived"] += 1
            elif sub == 2:
                if ctx["arrived"] < ctx["total"] - 1:
                    a.pc -= 2               # откат на слово, как в игре
                else:
                    for b in ctx["all"]:
                        b.parked = False
                    ctx["arrived"] = 0
            elif sub == 3 and not a.looped:
                a.wait = _rest(a)
            return
        return                              # коды 9…F — пусто


BUBBLE_FILL = 0            # ряд 0, цвет 0
BUBBLE_EDGE = 15           # ряд 0, цвет 15


def draw_bubble(px, font, got, width, left, band):
    u"""Пузырь реплики: место и размер игры, рамка моя.

    Столбцы и строки взяты из `$0503B4` и `$05056E` как есть: верхняя
    кромка на строке 20, текст с 21-й через строку, ширина — байт записи.
    **Рамку рисую сам:** тайлы `$259`…`$25C`, которыми её рисует игра, в
    банках `$04`-`$05` никто не выгружает, и найти их не удалось. Буквы
    же настоящие — `FontTiles` через `CharToTileTable`.
    """
    rows = 2 * len(got) + 1
    x0, y0 = left * 8, (BUBBLE_ROW + 1) * 8
    x1, y1 = min(SCREEN_W, x0 + width * 8), min(SCREEN_H, y0 + rows * 8)
    if y1 > band[1]:
        band[1] = y1
    for y in range(max(0, y0), y1):
        edge = y in (y0, y1 - 1)
        o = y * SCREEN_W
        for x in range(max(0, x0), x1):
            px[o + x] = (BUBBLE_EDGE if edge or x in (x0, x1 - 1)
                         else BUBBLE_FILL)
    for li, raw in enumerate(got):
        row = TEXT_ROW + 2 * li
        for ci, tile in enumerate(line_tiles(raw)):
            g = font.get(tile)
            if g is None:
                continue
            bx, by = (left + 1 + ci) * 8, row * 8
            if bx + 8 > SCREEN_W or by + 8 > SCREEN_H:
                continue
            for y in range(8):
                o = (by + y) * SCREEN_W + bx
                for x in range(8):
                    v = g[y * 4 + (x >> 1)]
                    px[o + x] = (v >> 4) if x % 2 == 0 else (v & 15)


def play(k, path, talk=TALK_FRAMES, scale=1):
    u"""Проиграть сценку k и записать GIF.

    Кадр в кадр повторяет `ScreenObjRecords`: сперва у каждого живого
    актёра выполняются команды до первой останавливающей, потом всем
    убавляются счётчики и применяется шаг. Разница одна и она названа:
    команда «реплика» в игре ждёт кнопку, здесь — `talk` кадров.
    """
    import unitanim
    d = block(k)
    _grec, _frame, scr, txt, n = header(d)
    rec, pals, _scr = stage(k)
    flat = [c for row in pals for c in row]

    base = bytearray(SCREEN_W * SCREEN_H)
    for y, row in enumerate(backdrop_indexes(rec, scr)):
        o = (BACK_Y + y) * SCREEN_W
        base[o:o + SCREEN_W] = row

    scripts, _end = actors(d, 0x0A, n)
    acts = [Actor(one[0][0]) for one in scripts]
    ctx = {"all": acts, "total": n, "arrived": 0, "said": 0, "talk": talk,
           "lines": lines(d, txt, raw=True), "bubble": None}
    font = font_glyphs()

    cache = {}

    def sprite(a):
        w = a.word()
        if w is None:
            return None
        key = (a.kind, w, a.pal)
        if key not in cache:
            pal = [a.pal * 16 + i for i in range(16)]
            cache[key] = unitanim.frame_pixels(a.kind, w, pal)
        return cache[key]

    # обрезка: экран 320x224, но восстановлена только полоса пейзажа —
    # текстовое окно игры сюда не переносится, и пустой чёрный низ незачем
    band = [BACK_Y, BACK_Y + SCREEN_ROWS * 8]
    frames, delays, held = [], [], 0
    for _tick in range(PLAY_LIMIT):
        for a in acts:                      # проход первый: скрипты
            if a.alive and not a.wait:
                step_actor(a, d, ctx)
        for a in acts:                      # проход второй: счётчики и шаг
            if not a.alive:
                continue
            if a.timer > 0:
                a.timer -= 1
            elif a.seq:
                _advance(a)
            if not a.parked and a.wait:
                a.wait -= 1
            if a.cntx:
                a.cntx -= 1
            else:
                a.cntx = a.stepx >> 8
                a.x = (a.x + sbyte(a.stepx)) & 0xFFFF
            if a.cnty:
                a.cnty -= 1
            else:
                a.cnty = a.stepy >> 8
                a.y = (a.y + sbyte(a.stepy)) & 0xFFFF

        px = bytearray(base)
        for a in acts:
            if not a.alive:
                continue
            spr = sprite(a)
            if spr is None:
                continue
            ox, oy = a.x - SPRITE_BIAS, a.y - SPRITE_BIAS
            if 0 <= oy < SCREEN_H:
                band[0] = min(band[0], oy)
            if 0 < oy + 32 <= SCREEN_H:
                band[1] = max(band[1], oy + 32)
            for sy in range(32):
                dy = oy + sy
                if not (0 <= dy < SCREEN_H):
                    continue
                line, o = spr[sy], dy * SCREEN_W
                for sx in range(32):
                    dx = ox + sx
                    if 0 <= dx < SCREEN_W and line[sx] is not None:
                        px[o + dx] = line[sx]
        b = ctx["bubble"]
        if b:
            got, width, left, _tail, rest = b
            draw_bubble(px, font, got, width, left, band)
            b[4] = rest - 1
            if b[4] <= 0:
                ctx["bubble"] = None
        frames.append(px)
        held += 1
        if not any(a.alive for a in acts):
            break

    y0, y1 = max(0, band[0]), min(SCREEN_H, band[1])
    h = y1 - y0
    if h < SCREEN_H:
        cut = []
        for f in frames:
            cut.append(f[y0 * SCREEN_W:y1 * SCREEN_W])
        frames = cut
    delays = [2] * len(frames)              # такт 1/60 -> две сотых
    kept = gif(path, SCREEN_W, h, flat, frames, delays)
    say = lines(d, txt)
    print(u"сценка %d: актёров %d, кадров %d (в файле %d), %.1f с, "
          u"реплик показано %d из %d, полоса y %d…%d, %d Кб -> %s"
          % (k, n, len(frames), kept, len(frames) / 60.0,
             ctx["said"], len(say), y0, y1,
             (os.path.getsize(path) + 1023) // 1024,
             os.path.relpath(path, HERE)))
    return 0


def do_play(k, talk):
    d = out_path("cutscene")
    os.makedirs(d, exist_ok=True)
    return play(k, os.path.join(d, "scene_%d.gif" % k), talk)


def do_backdrops():
    d = out_path("cutscene")
    os.makedirs(d, exist_ok=True)
    seen = {}
    for _c, _m, k in missions():
        grec, _f, scr, _t, _n = header(block(k))
        seen.setdefault(scr, (k, grec))
    for scr, (k, grec) in sorted(seen.items()):
        p = os.path.join(d, "backdrop_%d.png" % scr)
        backdrop(k, p)
        print(u"фон %d (сценка %d, запись графики %d) -> %s"
              % (scr, k, grec, os.path.relpath(p, HERE)))
    return 0


def report(f, only=None):
    p = f.write
    by_block = {}
    for c, m, k in missions():
        by_block.setdefault(k, []).append((c, m))
    ops, gaps = collections.Counter(), []
    for k in sorted(by_block):
        if only is not None and k != only:
            continue
        d = block(k)
        grec, frame, scr, txt, n = header(d)
        where = u", ".join(u"гл.%d м.%d" % cm for cm in by_block[k])
        p(u"\n## Сценка %d — %s\n\n" % (k, where))
        p(u"Блок `$%06X`, %d байт. Запись графики %d, фон %d, актёров %d.\n"
          u"Рамка окна `+$%03X`, реплики `+$%03X`.\n\n"
          % (U32(CUT_TABLE + k * 4), len(d), grec, scr, n, frame, txt))
        acts, end = actors(d, 0x0A, n)
        for i, one in enumerate(acts):
            for _o, w, _t in one:
                ops[w >> 12] += 1
            p(u"### Актёр %d (%s) — %d команд\n\n"
              % (i, actor_brief(one), len(one)))
            p(u"```\n")
            for o, w, t in one:
                p(u"+%03X  %04X  %s\n" % (o, w, t))
            p(u"```\n\n")
        say = lines(d, txt)
        if say:
            p(u"### Реплики: %d\n\n" % len(say))
            for width, got in say:
                p(u"* ширина %d: %s\n"
                  % (width, u" / ".join(s or u"—" for s in got)))
            p(u"\n")
        gaps.append(frame - end)
    return ops, gaps


def main():
    args = sys.argv[1:]
    if args and args[0] == "--back":
        return do_backdrops()
    if args and args[0] == "--play":
        k = int(args[1]) if len(args) > 1 else 0
        talk = int(args[2]) if len(args) > 2 else TALK_FRAMES
        return do_play(k, talk)
    only = int(args[0]) if args else None

    doc = os.path.join(HERE, "docs", "game-cutscene-scripts.md")
    f = io.open(doc, "w", encoding="utf-8", newline="\n")
    f.write(u"# Скрипты сценок между миссиями\n\n")
    f.write(u"Собрано `tools/cutscene.py` (`make cutscene`).\n\n")
    f.write(u"СГЕНЕРИРОВАНО — правки затираются, меняйте инструмент.\n"
            u"Вывод, который надо сохранить, пишите в соседний, ручной "
            u"файл.\n\n")
    f.write(u"Формат блока и таблица команд разобраны в шапке "
            u"`tools/cutscene.py`.\n\n")
    f.write(u"## Какая сценка где играет\n\n")
    f.write(u"| глава | миссия | сценка |\n|---|---|---|\n")
    for c, m, k in missions():
        f.write(u"| %d | %d | %d |\n" % (c, m, k))
    ops, gaps = report(f, only)
    f.close()

    print(u"сценок: %d, разобрано блоков: %d"
          % (len(missions()), 1 if only is not None else 15))
    print(u"команд по кодам: %s"
          % u", ".join(u"%X: %d" % kv for kv in sorted(ops.items())))
    if gaps:
        print(u"хвост от конца скриптов до рамки окна: %d…%d байт"
              % (min(gaps), max(gaps)))
    print(u"сводка: %s" % os.path.relpath(doc, HERE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
