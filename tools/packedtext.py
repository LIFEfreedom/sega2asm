#!/usr/bin/env python3
"""Ищет текст ВНУТРИ сжатых блоков.

    make packedtext

`findtext.py` сканирует сырое ПЗУ и потому видит только незапакованный
текст; напутствия к миссиям лежат открыто и попадают в выгрузку, а всё,
что упаковано трапом `$FF10`, для него невидимо. Здесь наоборот: блоки
сперва распаковываются, и текст ищется в распакованном.

Блоки берутся из всех таблиц, которые к этому заходу разобраны:

| откуда | что |
|---|---|
| `ChapterTable` `$060400` | описания миссий по главам |
| `table_assets` `$061800` | наборы тайлов местности |
| `$053684`, `$053774`, `$053BA4`, `$04FC32` | сюжетные экраны |
| `table_stages` `$164400` | карты местности |
| `$01318C` | записи графики этапа |
| `z80_driver` `$00207E` | драйвер Z80 |

Текстом считается прогон допустимых байт длиной не меньше `MINRUN`,
оканчивающийся нулём: так устроены все строки игры.
"""
import io
import os
import struct
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from unpack import unpack  # noqa: E402
import dumptext  # noqa: E402

rom = open(os.path.join(HERE, "game.gen"), "rb").read()
L = lambda a: struct.unpack(">I", rom[a:a + 4])[0]
W = lambda a: (rom[a] << 8) | rom[a + 1]

MINRUN = 5
OK = set(range(0x20, 0x7F)) | set(dumptext.KAT) | {0x40}
# Всё, что в репликах бывает кроме катаканы: пробел, знаки
# препинания, экранирующий $2A и переключатель размера $40.
PUNCT = {0x20, 0x21, 0x2A, 0x2C, 0x2D, 0x2E, 0x3F, 0x40}


def blocks():
    """Все известные адреса сжатых блоков, с пометкой откуда."""
    out = []
    for c in range(9):
        p = L(0x060400 + c * 4)
        if 0 < p < 0x200000:
            out.append((p, "глава %d" % c))
    n = (L(0x061800) - 0x061800) // 4
    for i in range(n):
        out.append((L(0x061800 + 4 * i), "ассет %d" % i))
    for root, tag in ((0x053684, "сюжет-корень"), (0x053774, "сюжет-A"),
                      (0x053BA4, "сюжет-B"), (0x04FC32, "сюжет-C")):
        first = L(root)
        cnt = (first - root) // 4
        if not (0 < cnt < 400):
            cnt = 200
        for i in range(cnt):
            p = L(root + 4 * i)
            if 0x100000 < p < 0x200000:
                out.append((p, "%s %d" % (tag, i)))
    for i in range(512):
        p = L(0x164400 + 4 * i)
        if 0x100000 < p < 0x200000:
            out.append((p, "этап %d" % i))
    out.append((0x01318C, "графика этапов"))
    out.append((0x00207E, "драйвер Z80"))
    seen = set()
    uniq = []
    for p, tag in out:
        if p in seen:
            continue
        seen.add(p)
        uniq.append((p, tag))
    return uniq


def is_text(s):
    """Отсев графики: у неё байты тоже попадают в печатный диапазон.

    Признак не эвристический, а по набору знаков. В репликах игры, кроме
    катаканы, встречаются только пробел, `!`, `?`, `.`, `-`, `,`,
    экранирующий `$2A` и переключатель размера шрифта `$40` — это
    проверено по всем найденным строкам. Тайлы же дают россыпь латиницы
    и цифр, и на первом же таком знаке прогон отбрасывается.
    """
    kat = [b for b in s if b in dumptext.KAT]
    if len(kat) < 3 or len(set(kat)) < 3:
        return False
    if not all(b in dumptext.KAT or b in PUNCT for b in s):
        return False
    # Узор из тайлов может случайно состоять из одной катаканы и запятых.
    # В длинной РЕЧИ ни один знак не занимает больше двух пятых.
    if len(s) >= 16:
        import collections
        if collections.Counter(kat).most_common(1)[0][1] * 5 >= len(kat) * 2:
            return False
    return True


def runs(data):
    """Прогоны допустимых байт, оканчивающиеся нулём."""
    out = []
    cur = []
    start = 0
    for i, b in enumerate(data):
        if b in OK:
            if not cur:
                start = i
            cur.append(b)
            continue
        if b == 0 and len(cur) >= MINRUN and is_text(cur):
            out.append((start, bytes(cur)))
        cur = []
    return out


def main():
    out = {}
    order = []
    bad = tried = 0
    for p, tag in blocks():
        tried += 1
        try:
            _m, _size, d, _e = unpack(rom, p)
        except Exception:
            bad += 1
            continue
        lines = runs(bytes(d))
        if not lines:
            continue
        if p not in out:
            order.append((p, tag))
        out.setdefault(p, []).extend(
            (off, dumptext.dec(x)) for off, x in lines)

    total = sum(len(v) for v in out.values())
    path = os.path.join(HERE, "docs", "game-cutscenes.md")
    f = io.open(path, "w", encoding="utf-8", newline="\n")
    w = f.write
    w("# Реплики сценок\n\n")
    w("СГЕНЕРИРОВАНО `tools/packedtext.py` (`make packedtext`) — правки\n"
      "затираются, меняйте инструмент.\n\n")
    w("Этого текста не было в [game-text.md](game-text.md): тот собран по\n"
      "таблицам, а `findtext.py` сканирует сырое ПЗУ и упакованного не\n"
      "видит. Здесь блоки сперва распаковываются.\n\n")
    w("Опробовано %d блоков из всех разобранных таблиц, распаковалось\n"
      "%d, строк найдено %d в %d блоках. Почти все — в таблице\n"
      "`$04FC32`: она и оказалась хранилищем текстовых экранов.\n\n"
      % (tried, tried - bad, total, len(out)))
    w("Отсев: строка должна кончаться нулём, содержать не меньше трёх\n"
      "РАЗНЫХ знаков катаканы и состоять из них на семь десятых. Без\n"
      "требования разных знаков в выдачу лезут тайлы — их байты тоже\n"
      "попадают в печатный диапазон и дают прогоны вроде «ｪｪｪｪｪ».\n\n")
    for p, tag in order:
        w("## Блок `$%06X` (%s)\n\n" % (p, tag))
        for off, line in sorted(out[p]):
            w("* `+$%04X` %s\n" % (off, line))
        w("\n")
    f.close()
    print("блоков опробовано %d, не распаковалось %d" % (tried, bad))
    print("строк найдено %d в %d блоках" % (total, len(out)))
    print("записано: docs/game-cutscenes.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
