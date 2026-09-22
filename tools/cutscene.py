#!/usr/bin/env python3
u"""Сценки между миссиями: заголовок блока, скрипты актёров, реплики.

    make cutscene                   # все 15 сценок
    make cutscene CSARGS=3          # только сценка 3
    make cutscene CSARGS=--back     # четыре фона в PNG

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

## Чего здесь нет

Порядок «какая реплика к какой команде» не выведен: код 2 подкоманда 1
не несёт номера, а зовёт `$0503B4`, и тот берёт следующую запись сам.
Кто именно говорит — тоже: `$C(a5)` получает номер актёра, но связь
проверяется только запуском.
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
from gfx import png                                          # noqa: E402
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
        return op, u"шаг X = %+d" % sbyte(arg)
    if op == 5:
        return op, u"шаг Y = %+d" % sbyte(arg)
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


def lines(d, start):
    u"""[(ширина, [строки])] — список реплик."""
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
            got.append(dec(d[o:e]))
            o = e + 1
        out.append((width, got))
        if o < len(d) and d[o] == 0:
            o += 1
        if o < len(d) and d[o] == 0:
            break
    return out


def backdrop(k, path):
    u"""Фон сценки k в PNG: двенадцать строк тайлами записи графики."""
    import maptex
    d = block(k)
    grec, _frame, scr, _txt, _n = header(d)
    rec = maptex.gfx_records()[grec]
    names = bytes(unpack(ROM, U32(CUT_SCREENS + scr * 4))[2])
    tiles = maptex.tileset(rec)
    pals = [maptex.array_palette(0), maptex.array_palette(1),
            maptex.array_palette(3), maptex.rec_palette(rec, 0)]
    w, h = COLS * 8, SCREEN_ROWS * 8
    img = [[(0, 0, 0)] * w for _ in range(h)]
    for r in range(SCREEN_ROWS):
        for c in range(COLS):
            n = struct.unpack_from(">H", names, (r * COLS + c) * 2)[0]
            n = ((n + 0x0075) & 0x1FFF) | 0x6000      # ScreenUnpackByArg
            g = tiles.get(n & 0x7FF)
            if g is None:
                continue
            p = pals[(n >> 13) & 3]
            hf, vf = (n >> 11) & 1, (n >> 12) & 1
            for y in range(8):
                sy = 7 - y if vf else y
                row = img[r * 8 + y]
                for x in range(8):
                    sx = 7 - x if hf else x
                    v = g[sy * 4 + (sx >> 1)]
                    row[c * 8 + x] = p[(v >> 4) if sx % 2 == 0 else (v & 15)]
    png(path, w, h, img)
    return scr


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
            p(u"### Актёр %d — %d команд\n\n" % (i, len(one)))
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
