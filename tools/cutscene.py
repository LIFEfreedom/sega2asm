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

## Движок общий, сценка — один из клиентов

Приставка `Cutscene*`, которую я навесил на весь движок, оказалась узкой,
и имена уже исправлены на `Scene*`. Площадок `SceneActorSetup` двадцать,
площадок кадрового шага `UploadSpritesFrom1D64` `$0564CE` тоже двадцать,
в четырнадцати разных процедурах от `$04FF12` до `$05A4F2`. Кроме сценки
среди них опознаны `DrawStoryScreen` `$0539E0` (сюжетный экран),
`ScrollWorldMap` `$059A3A` и `ShowDemoEpisode` `$059ACA`; остальные носят
машинные имена, и что именно они показывают, пока не установлено.

**Базу `a5` каждый экран ставит себе сам**, отступом от `GfxWorkBuffer`
`$FFE45C`: сценка берёт `+$10`, сюжетный экран `+$16`. Поэтому все
смещения ниже даны ОТ БАЗЫ; абсолютных адресов у полей нет, и попытка
подставить какой-нибудь один раз уже стоила неверного адреса в
[game-data.md](../docs/game-data.md).

Первые байты до базы — четыре длинных слова с указателями на графику; их
подменяет команда `2.5`.

`DrawStoryScreen` распаковывает свой блок в ТОТ ЖЕ `$FF2564`, что и
`ShowCutscene`, но шапка у него другая: слово в `ScreenUnpackFromData297`,
слово в `LoadSceneGfxSet`, два слова — номера в `StoryBlockTable`, и
дальше сразу скрипты актёров. Инструмент разбирает пока только сценки:
блоки сюжетных экранов лежат не в таблице, а длинными словами внутри
сценариев банка `$05`, и их ещё надо собрать.

## Актёры

`SceneActorSetup` `$056370`
раскладывает по записи на актёра, `$5A` байт каждая, начиная с `$86(a5)`,
и ставит каждому указатель на его скрипт. Больше двадцати актёров не
берёт (`cmpi.w #$0014,d0`). Аргументы: указатель на блок+6, слово в
`$4(a5)` — добавка к атрибутам всех спрайтов, и два слова в `$5E`/`$60`.
Счётчики актёров `$0(a5)` и `$2(a5)` получают одно и то же число: первый
остаётся «всех», второй убавляется на каждом «конце скрипта». Если слово
по блоку+6 равно нулю, `$6(a5)` обнуляется — у экрана нет реплик вовсе.

Поля записи, которые трогает скрипт:

| поле | что |
|---|---|
| `$20` | счётчик до следующего шага анимации |
| `$3C` | номер звука для трапа `$FF2F` |
| `$3E` | тип юнита — тот же номер, что в `unitgfx`/`unitanim` |
| `$40` | номер анимации (`$04`…`$20`) |
| `$42` | направление, 0…7 |
| `$44`, `$46` | X и Y на экране (к обоим прибавлено `$80`, как у спрайтов) |
| `$48`, `$4C` | шаг по X и по Y: старший байт — период, младший знаковый — сдвиг |
| `$4A`, `$4E` | счётчики к ним; команда шага их НЕ сбрасывает |
| `$50` | сколько кадров ещё ждать |
| `$52` | СВОЙ указатель команд, у каждого актёра отдельный |
| `$58` | флаги: бит 0 — жив, бит 1 — анимация заведена, бит 2 — зациклена, бит 3 — «дошёл» |
| `$59` | ряд палитры, 0…3 |

Эта же `$5A`-байтная запись разобрана в
[game-data.md](../docs/game-data.md) со стороны построения спрайта: `$28`
и `$2E` — базовые Y и X, к ним прибавляются `$46` и `$44`, `$56` даёт
номер тайла, `$2C` и `$59` — атрибуты. Там она была названа «отображаемый
объект», и вот кто эти объекты: актёры сценки.

## Команды

`SceneActorTick` `$0564FC` раз в кадр читает у каждого живого актёра
СЛОВО: старший ниббл — команда, младшие двенадцать бит — аргумент.
Таблица переходов — `$056688`, шестнадцать слов; коды `9`…`F` ведут
обратно в выборку, то есть пустые.

| код | аргумент | что делает |
|---|---|---|
| 0 | — | конец скрипта: снять бит 0, убавить счётчик живых |
| 1 | младший байт, биты 8…11 | завести анимацию трапом `$FF08` по `$3E`/`$40`/`$42`, потом промотать её трапом `$FF09` столько раз, сколько в младшем байте; ненулевые биты 8…11 взводят «зациклена» |
| 2 | биты 8…11 — подкоманда | работа с текстовым окном, см. ниже |
| 3 | биты 8…9 — поле, младший байт — значение | положить значение в `$3E`, `$40`, `$42` или `$59` |
| 4 | период и знаковый байт | шаг по X: `$48(a1) = аргумент` |
| 5 | период и знаковый байт | шаг по Y: `$4C(a1) = аргумент` |
| 6 | слово | X: `$44(a1) = аргумент` |
| 7 | слово | Y: `$46(a1) = аргумент` |
| 8 | биты 8…10 — подкоманда | ожидания, см. ниже |

**Какие команды кончают кадр.** Обработчик или уходит на `$0569D8` (тогда
актёр в этом кадре сделал своё), или обратно на выборку `$056668` (тогда
берётся следующее слово тут же). Кончают кадр коды 0, 1, 8 и подкоманды
2.1 и 2.4; остальное — идёт дальше, включая почти весь код 2. То есть
`2201` и `2002` кадра не стоят.

Подкоманды кода 2 — их семь, скрипты берут четыре:

| под | что |
|---|---|
| 0 | **звук**: трап `$FF38` с номером из `table_sfx` `$00201C`. Сторож `d7` пускает за кадр только один запрос на всю сцену |
| 1 | **реплика**: `$C(a5) = номер актёра`, `$12(a5) = 1`, вызов `SceneOpenBubble` `$0503B4` |
| 2 | текстовое окно: заводит `SceneWindowSlide` `$050678` на `$68` кадров и гонит по плану B тринадцать строк с `$E380`, по строке за восемь кадров. Аргумент 0 кладёт в `$84(a5)` `-$50` и в `$82(a5)` `$3C0`, иначе `+$50` и ноль — то есть выезд наверх или вниз. Что это «показать» и «убрать» — видно по употреблению: на пятнадцать сценок ровно по одной паре, `$201` всегда перед первой репликой, `$200` всегда последней командой |
| 3 | эффект по таблице `$0568AE` на шестнадцать входов; скрипты зовут только вход 1 — `SceneFadePalettes` `$056C2E`, четырнадцать шагов палитры |
| 4 | экран выбора: `$12(a5) = 2`, и дальше кадр уходит не в актёров, а в опрос креста |
| 5 | взять блок сюжета из `StoryBlockTable`; в сценках не встречается |
| 6 | музыка трапом `$FF30`; в сценках не встречается |

Подкоманды кода 8 (рабочих пять, скрипты берут четыре; 5…7 пустые):

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

## Кто говорит

Указатель на список реплик один на всю сцену — `$6(a5)`. Своего у актёров
нет: каждая команда «реплика» снимает следующую запись с этого общего
курсора. Поэтому реплики идут СТРОГО по порядку файла, кто бы их ни
произносил, и совпадение «196 показов на 196 записей» не случайность, а
устройство.

А кто произносит — берётся из индекса цикла:

```asm
loc_0567AC:                     ; подкоманда 2.1
	move.w	#$0000,$A(a5)
	move.w	d0,$C(a5)       ; d0 — НОМЕР АКТЁРА в цикле $05664E
	move.w	#$0001,$12(a5)
	jsr	(SceneOpenBubble).l
```

`$0503B4` по этому номеру находит запись (`$86(a5)` плюс `$5A` за
актёра) и ставит хвостик пузыря под её `$44`. То есть говорит тот, чей
скрипт дошёл до команды, и доказательство этому — не соглашение, а
геометрия: хвостик указывает именно на него.

## Пузырь реплики

Рисует его `SceneOpenBubble`, и это НЕ строка внизу экрана, а пузырь над
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

Хвостик и тело считаются РАЗДЕЛЬНО: `$78(a5)` — столбец хвостика, он
всегда под актёром, `$72(a5)` — левый столбец тела, и только его прижимают
к краю. Поэтому у актёра справа пузырь съезжает влево, а хвостик остаётся
на месте. В верхней кромке под хвостиком дырка — там кладут тайл 0, чтобы
хвостик соединился с внутренностью.

Строки в таблице имён: 19 — хвостик (`$C980`), 20 — верхняя кромка,
с 21-й через одну текст (`$CA82`), потом нижняя кромка. То есть на строку
текста приходится ДВЕ строки таблицы имён, а знак — один тайл 8x8.
Весь пузырь живёт в строках 19…27: столько же (девять) потом
восстанавливают из `$FF20C4`, стирая его.

Текст печатает `SceneTypeReply` `$05056E`, и время у него всё своё:

| кадры | на что |
|---|---|
| 1 на строку | трап `$FF24` разбирает её в слова имён в `$14(a5)` |
| 2 на знак | кадр рисует и ставит `$A(a5) = 1`, следующий эту единицу съедает |
| `$18` = 24 | после последнего знака последней строки |
| 1 | вернуть девять строк из `$FF20C4` |

**Кнопку не ждут.** Раньше здесь стояло обратное; в `$05056E` нет ни
одного опроса креста, реплика уходит сама. Кнопку читает только режим
`$12(a5) = 2`, а это экран выбора, не пузырь.

Пока пузырь висит, `$12(a5)` равно единице, и `$0565C0` уводит кадр в
`SceneTypeReply` — цикл актёров не работает вовсе. Значит **на время
реплики сцена стоит**; из `TickSceneObjects` двигается только снос по X и
Y самого говорящего (`$057228`).

Байты гоняются через трап `$FF24` и `CharToTileTable`, а глифы лежат в
`FontTiles` `$010322`.

**Кодировка полуширинная, а глифы хираганные:** `ｾｯｼｬﾊ` выходит на экран
как `せっしゃは`. Катакана в выгрузках текста — транслитерация.

Рамка пузыря — четыре тайла `$259`…`$25C`: хвостик-треугольник, кромка,
бок и угол (углы и низ получаются отражениями, `$8A5C`, `$925C`,
`$9A5C`). Своей выгрузки у них нет, и поиск по адресу `$4B20` ничего не
давал: они едут ХВОСТОМ общего экрана. `ScreenUnpack17755C` `$050290`
распаковывает `$17755C` и выгружает `$680` СЛОВ в VRAM `$3EA0` — это
ровно 104 тайла, `$1F5`…`$25C`, и последние четыре из них рамка.

## Проигрывание (`--play`)

`--play K` прогоняет сценку кадр в кадр и пишет GIF. Порядок тот же, что
у `SceneActorTick`: сперва у каждого живого актёра выполняются команды
до первой останавливающей (коды 0, 1, 2 и 8 кончают кадр, коды 3…7 идут
дальше в том же), потом всем убавляются счётчики и применяется шаг.
Спрайт берётся из `unitanim` по тройке (`$3E`, `$40`, `$42`), палитра —
по `$59`, место — `$44`/`$46` минус `$80`.

Экран режется до полосы, где что-то есть: пейзаж лежит с точки 56 по
152, а текстовое окно игры сюда не переносится, и пустой чёрный низ
незачем.

Длительность реплики теперь не выдумана: `reply_frames` считает её по
таблице выше, и на время пузыря сцена стоит, как в игре. Сценки выходят
от 15 до 36 секунд.

## Что подтвердил прогон

Три проверки, и ни одна не «выглядит правдоподобно»:

- все **2984** командных слова во всех пятнадцати блоках попали в девять
  рабочих кодов, ни одного в пустые;
- каждый из **67** скриптов кончается ровно там, где начинается рамка
  текстового окна, — зазор ноль байт во всех пятнадцати;
- при прогоне ни одна сценка не зависла на точке встречи, и в каждой
  число выполненных команд «реплика» **в точности** равно числу записей
  текста в блоке. Всего 196 на 196.

Последнее заодно говорит, что `$0503B4` берёт записи ПО ПОРЯДКУ, — а
теперь видно и почему: курсор реплик один на сцену.

Четвёртая проверка, к раздаче реплик по актёрам: у каждого актёра число
слов «реплика» в скрипте и число его показов при прогоне сошлись во всех
пятнадцати сценках, у всех 67 актёров. Поэтому в сводке можно приписать
текст прямо к команде: k-е слово — это k-й показ.

## Чего здесь нет

`TickSceneObjects` в режимах 1 и 2 счётчик анимации `$20` не убавляет, а
ПРИБАВЛЯЕТ, и всем, кроме текущего актёра. В режиме 0 его убавляют. Зачем
прибавлять — из кода не видно; на картинку это не влияет, потому что шаг
анимации в этих режимах всё равно не делается (трап `$FF09` зовут только
из цикла актёров), но счётчики к концу реплики уезжают.
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


SFX_TABLE = 0x00201C       # table_sfx: 49 пар «банк, команда драйверу»


def sfx_command(n):
    u"""«$A7» — команда драйверу по номеру из `table_sfx`, как трап `$FF38`."""
    if not 0 <= n < 49:
        return u"вне таблицы"
    return u"$%02X" % ROM[SFX_TABLE + n * 2 + 1]


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
        sub, low = (arg >> 8) & 0x0F, arg & 0xFF
        if sub == 0:
            return op, u"звук %d (%s)" % (low, sfx_command(low))
        if sub == 1:
            return op, u"реплика"
        if sub == 2:
            return op, (u"показать окно" if low else u"убрать окно")
        if sub == 3:
            return op, (u"затемнение палитры, 14 шагов" if low == 1
                        else u"эффект %d" % low)
        if sub == 4:
            return op, u"экран выбора, аргумент $%02X" % low
        if sub == 5:
            return op, u"взять блок %d" % low
        if sub == 6:
            return op, u"музыка %d" % low
        return op, u"окно: подкоманда %d, аргумент $%02X" % (sub, low)
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
    return op, u"пусто (код %X): взять следующую в том же кадре" % op


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


REPLY_TAIL = 24            # `$A(a5) = $18` после последнего знака


def reply_frames(got):
    u"""Сколько кадров держится реплика — по счётчикам `$05056E`.

    На строку кадр подготовки (`$FF24` разбирает её в слова имён), на
    знак два кадра (кадр рисует и ставит `$A(a5) = 1`, следующий эту
    единицу съедает), после последнего знака `$18` кадров, и ещё кадр на
    то, чтобы вернуть на место девять строк из `$FF20C4`.
    """
    chars = sum(len(line_tiles(raw)) for raw in got)
    return len(got) + 2 * chars + (REPLY_TAIL - 2) + 1


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
        if op == 4:                         # счётчик НЕ сбрасывается:
            a.stepx = arg                   # `$0568CE` трогает только `$48`
            continue
        if op == 5:
            a.stepy = arg
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
            sub = (arg >> 8) & 0x0F
            if sub not in (1, 4):           # только эти две кончают кадр
                continue
            if sub == 1:
                rec = (ctx["lines"][ctx["said"]]
                       if ctx["said"] < len(ctx["lines"]) else None)
                ctx["said"] += 1
                ctx["who"].append(ctx["all"].index(a))
                if rec:
                    width, got = rec
                    left, tail = bubble_box(a.x, width)
                    rest = reply_frames(got)
                    ctx["bubble"] = [got, width, left, tail, rest, a]
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
        continue                            # коды 9…F ведут обратно в выборку


SCREEN_TILES = 0x17755C    # весь экран сценки: 104 тайла с $1F5
SCREEN_FIRST = 0x1F5
_SCREEN = {}


def screen_tiles():
    u"""{номер тайла: 32 байта} — то, что уходит в VRAM `$3EA0`.

    `ScreenUnpack17755C` `$050290` распаковывает блок и выгружает `$680`
    СЛОВ, то есть ровно 104 тайла, `$1F5`…`$25C`. Последние четыре и есть
    рамка пузыря — потому её и не находил поиск по адресу `$4B20`: своей
    выгрузки у неё нет, она едет хвостом общего экрана.
    """
    if not _SCREEN:
        d = bytes(unpack(ROM, SCREEN_TILES)[2])
        for i in range(104):
            _SCREEN[SCREEN_FIRST + i] = d[i * 32:(i + 1) * 32]
    return _SCREEN


def _blit_name(px, tiles, name, col, row):
    u"""Тайл по слову имени в клетку (col, row); цвет 0 — чёрный."""
    g = tiles.get(name & 0x7FF)
    if g is None:
        g = bytes(32)
    hf, vf = (name >> 11) & 1, (name >> 12) & 1
    bx, by = col * 8, row * 8
    if bx < 0 or by < 0 or bx + 8 > SCREEN_W or by + 8 > SCREEN_H:
        return
    for y in range(8):
        sy = 7 - y if vf else y
        o = (by + y) * SCREEN_W + bx
        for x in range(8):
            sx = 7 - x if hf else x
            v = g[sy * 4 + (sx >> 1)]
            px[o + x] = (v >> 4) if sx % 2 == 0 else (v & 15)


def draw_bubble(px, font, got, width, left, tail, band):
    u"""Пузырь реплики ровно так, как его кладёт `$0503B4`.

    | строка | слева | посередине | справа |
    |---|---|---|---|
    | 19 | — | `$8259` только в столбце хвостика | — |
    | 20 | `$825C` | `$825A`, в столбце хвостика `$8000` | `$8A5C` |
    | 21… | `$825B` | `$8000` | `$8A5B` |
    | низ | `$925C` | `$925A` | `$9A5C` |
    """
    tiles = screen_tiles()
    nrows = 2 * len(got)
    # нижняя кромка стоит строкой BUBBLE_ROW + 2 + nrows, значит
    # её точки кончаются на строку ниже — иначе обрезка её срежет
    y1 = min(SCREEN_H, (BUBBLE_ROW + 3 + nrows) * 8)
    if y1 > band[1]:
        band[1] = y1
    _blit_name(px, tiles, 0x8259, tail, BUBBLE_ROW)
    for i in range(width):
        col = left + i
        if i == 0:
            top, mid, bot = 0x825C, 0x825B, 0x925C
        elif i == width - 1:
            top, mid, bot = 0x8A5C, 0x8A5B, 0x9A5C
        else:
            top = 0x8000 if col == tail else 0x825A
            mid, bot = 0x8000, 0x925A
        _blit_name(px, tiles, top, col, BUBBLE_ROW + 1)
        for r in range(nrows):
            _blit_name(px, tiles, mid, col, BUBBLE_ROW + 2 + r)
        _blit_name(px, tiles, bot, col, BUBBLE_ROW + 2 + nrows)
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


def _drift(a):
    u"""Снос по X и Y: `loc_056B16` в режиме 0, хвост `TickSceneObjects`
    в режимах 1 и 2. Счётчик сперва убавляется, и только на нуле
    перезаряжается старшим байтом и прибавляет знаковый младший."""
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


def tick(acts, d, ctx):
    u"""Один кадр движка сценки.

    Пока пузырь висит, `$12(a5)` равно единице, и `$0565C0` уводит кадр
    в `SceneTypeReply`: цикл актёров не работает вовсе. Из него зовут
    `TickSceneObjects`, а тот применяет снос ТОЛЬКО к говорящему
    (`$057228`). То есть на время реплики сцена стоит, и двигается
    один он. Кадр, в котором реплика заводится, ещё целиком свой:
    `$12(a5)` проверяют раз за кадр, до цикла.
    """
    if ctx["bubble"]:
        _drift(ctx["bubble"][5])
        return
    for a in acts:                          # проход первый: скрипты
        if a.alive and not a.wait:
            step_actor(a, d, ctx)
    for a in acts:                          # проход второй: счётчики и шаг
        if not a.alive:
            continue
        if a.timer > 0:
            a.timer -= 1
        elif a.seq:
            _advance(a)
        if not a.parked and a.wait:
            a.wait -= 1
        _drift(a)


def expire(ctx):
    u"""Убавить остаток реплики; на нуле пузырь стирают девятью строками
    из `$FF20C4` (`$050648`)."""
    b = ctx["bubble"]
    if b:
        b[4] -= 1
        if b[4] <= 0:
            ctx["bubble"] = None


def new_ctx(d, n, acts):
    return {"all": acts, "total": n, "arrived": 0, "said": 0,
            "lines": lines(d, txt_off(d), raw=True), "bubble": None,
            "who": []}


def txt_off(d):
    return header(d)[3]


def speakers(k):
    u"""[номер актёра] на каждую реплику сценки k, по порядку показа.

    Прогон без картинки. Номер берётся там же, где его берёт игра:
    `$0567AC` кладёт в `$C(a5)` индекс цикла актёров, а `$0503B4` по
    нему находит запись и ставит хвостик пузыря под её `$44`.
    """
    d = block(k)
    n = header(d)[4]
    scripts, _end = actors(d, 0x0A, n)
    acts = [Actor(one[0][0]) for one in scripts]
    ctx = new_ctx(d, n, acts)
    for _i in range(PLAY_LIMIT):
        tick(acts, d, ctx)
        expire(ctx)
        if not any(a.alive for a in acts):
            break
    return ctx["who"]


def play(k, path, scale=1):
    u"""Проиграть сценку k и записать GIF.

    Кадр в кадр повторяет `SceneActorTick`: сперва у каждого живого
    актёра выполняются команды до первой останавливающей, потом всем
    убавляются счётчики и применяется шаг. Реплика держится ровно
    столько, сколько насчитал `reply_frames`.
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
    ctx = new_ctx(d, n, acts)
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
    for _n in range(PLAY_LIMIT):
        tick(acts, d, ctx)

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
            got, width, left, tail, _rest, _who = b
            draw_bubble(px, font, got, width, left, tail, band)
        expire(ctx)
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


def do_play(k):
    d = out_path("cutscene")
    os.makedirs(d, exist_ok=True)
    return play(k, os.path.join(d, "scene_%d.gif" % k))


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
        say = lines(d, txt)
        who = speakers(k)
        # каждому актёру его реплики по порядку: скрипт линеен, назад
        # ходит только «ждать остальных» и только на себя, так что k-е
        # слово «реплика» в скрипте — это k-й его показ при прогоне
        queue = {}
        for j, ai in enumerate(who):
            queue.setdefault(ai, []).append(j)
        for i, one in enumerate(acts):
            for _o, w, _t in one:
                ops[w >> 12] += 1
            p(u"### Актёр %d (%s) — %d команд\n\n"
              % (i, actor_brief(one), len(one)))
            p(u"```\n")
            mine = list(queue.get(i, []))
            for o, w, t in one:
                if w >> 12 == 2 and (w >> 8) & 0x0F == 1 and mine:
                    j = mine.pop(0)
                    t = u"%s %d: %s" % (t, j, u" / ".join(
                        x or u"—" for x in say[j][1]))
                p(u"+%03X  %04X  %s\n" % (o, w, t))
            p(u"```\n\n")
        if say:
            p(u"### Реплики: %d\n\n" % len(say))
            for j, (width, got) in enumerate(say):
                p(u"* %d, актёр %s, ширина %d: %s\n"
                  % (j, who[j] if j < len(who) else u"?", width,
                     u" / ".join(x or u"—" for x in got)))
            p(u"\n")
        gaps.append(frame - end)
    return ops, gaps


def main():
    args = sys.argv[1:]
    if args and args[0] == "--back":
        return do_backdrops()
    if args and args[0] == "--play":
        k = int(args[1]) if len(args) > 1 else 0
        return do_play(k)
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
