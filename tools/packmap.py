#!/usr/bin/env python3
"""Что лежит в bin-сегментах банков кода: карта сжатых блоков.

    make packmap         (нужен свежий `make split`: читает листинги)

Между процедурами вывода в банках `$03`–`$05` лежат крупные `bin`-куски,
которые выглядели таблицами и потому не разбирались. Таблиц там нет:
это **связки сжатых блоков**, сложенных встык, и рисует их тот же код,
рядом с которым они лежат.

Как ищется. Ground truth — литеральные ссылки: `pea ($xxxxxx).l` и
следом трап `$FF10`, то есть распаковщик. От каждой такой ссылки блок
разворачивается `tools/unpack.py`, который сообщает, сколько байт входа
съел; со следующего байта пробуется следующий блок, и так пока блоки
сходятся и не вылезают за сегмент.

Осторожно с методом 1. Простой LZ77 «распаковывает» почти любые байты до
объявленной длины, так что найденный им блок без литеральной ссылки —
ещё не блок. Такие помечены, и ограничение по границе сегмента снимает
большую часть ложных: настоящий блок за свой сегмент не вылезает.
"""
import collections
import glob
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from unpack import unpack

ROM = open(os.path.join(HERE, "game.gen"), "rb").read()
CODE_HI = 0x05E244
OK_METHOD = {1, 2, 3, 6, 7}

PEA = re.compile(r"^\t(?:pea\t\(|lea\t\()\$([0-9A-F]{6})\)\.l")


def literal_refs():
    """Адреса, которые код передаёт распаковщику и BiosBlitRegion."""
    packed, raw = collections.Counter(), collections.Counter()
    for f in glob.glob(os.path.join(HERE, "out", "asm", "m68k", "*.asm")):
        src = [l.rstrip("\n") for l in
               io.open(f, encoding="utf-8", errors="replace") if l.startswith("\t")]
        for i, l in enumerate(src):
            m = PEA.match(l)
            if not m:
                continue
            a = int(m.group(1), 16)
            if a >= CODE_HI:
                continue
            trap = [t for t in src[i + 1:i + 7] if t.startswith("\tdc.w\t$FF")]
            if trap and trap[0] == "\tdc.w\t$FF10":
                packed[a] += 1
            else:
                raw[a] += 1
    return packed, raw


def block_at(a, hi):
    """(метод, сжатых, распакованных) либо None."""
    if a + 3 >= len(ROM) or ROM[a + 2] not in OK_METHOD:
        return None
    size = (ROM[a] << 8) | ROM[a + 1]
    if not (16 <= size <= 0x8000):
        return None
    try:
        m, size, data, end = unpack(ROM, a)
    except Exception:
        return None
    if len(data) != size or end <= a or end > hi:
        return None
    return m, end - a, size


def yaml_segments():
    cur = {}
    for line in io.open(os.path.join(HERE, "game.yaml"), encoding="utf-8"):
        m = re.match(r"\s*-?\s*name:\s*(\S+)", line)
        if m:
            cur = {"name": m.group(1)}
        m = re.match(r"\s*type:\s*(\S+)", line)
        if m and cur:
            cur["type"] = m.group(1)
        m = re.match(r"\s*start:\s*0x([0-9A-Fa-f]+)", line)
        if m and cur:
            cur["start"] = int(m.group(1), 16)
        m = re.match(r"\s*end:\s*0x([0-9A-Fa-f]+)", line)
        if m and cur:
            cur["end"] = int(m.group(1), 16)
            yield cur
            cur = {}


def chain(lo, hi, seeds, raw):
    """Блоки сегмента: от каждой литеральной ссылки вперёд встык.

    Адрес, который код где-то передаёт БЕЗ распаковки, цепочку обрывает:
    что бы метод 1 из него ни «развернул», использует его игра как есть.
    """
    found = {}
    # Сначала все семена, потом продолжения: иначе перешагнутая дыра
    # съедает семя, которое в неё попало.
    for a in sorted(seeds):
        r = block_at(a, hi)
        if r:
            found[a] = r
    for a0 in sorted(seeds):
        a, slack = a0, 0
        while lo <= a < hi:
            if a in found and a != a0:
                a += found[a][1]
                a += a & 1
                slack = 0
                continue
            if a in raw and a not in seeds:
                break
            r = block_at(a, hi)
            if r:
                found[a] = r
                a += r[1]
                a += a & 1
                slack = 0
                continue
            # Между блоками попадаются палитры и карты имён. Небольшую
            # дыру перешагиваем и пробуем снова; большая значит, что
            # связка кончилась.
            if slack >= 0x80:
                break
            a += 2
            slack += 2
    return found


def main():
    packed, raw = literal_refs()
    rows = []
    for sg in yaml_segments():
        if sg["type"] != "bin" or sg["start"] >= CODE_HI:
            continue
        lo, hi = sg["start"], sg["end"]
        if hi - lo < 512:
            continue
        # Без литеральной ссылки не начинаем: метод 1 «распакует» что
        # угодно, и от одной догадки посыплются ложные блоки. Так из
        # отчёта сами собой выпали data_215 и table_stageframe — оба
        # настоящие таблицы, оба метод 1 с первого байта.
        seeds = [a for a in packed if lo <= a < hi]
        if not seeds:
            continue
        blocks = chain(lo, hi, seeds, set(raw))
        if not blocks:
            continue
        rows.append((sg["name"], lo, hi, blocks,
                     sorted(a for a in packed if lo <= a < hi),
                     sorted(a for a in raw if lo <= a < hi)))

    out = os.path.join(HERE, "docs", "game-assets.md")
    f = io.open(out, "w", encoding="utf-8", newline="\n")
    p = f.write
    p("# Сжатые блоки внутри банков кода\n\n")
    p("Собрано `tools/packmap.py` (`make packmap`).\n\n")
    p(__doc__[__doc__.index("Между процедурами"):].strip() + "\n\n")
    p("## Сводка\n\n")
    p("| сегмент | адреса | байт | блоков | сжато | покрыто |\n"
      "|---|---|---|---|---|---|\n")
    tot_seg = tot_cov = 0
    for nm, lo, hi, blocks, ref, _rawr in rows:
        cov = sum(b[1] for b in blocks.values())
        tot_seg += hi - lo
        tot_cov += cov
        p("| `%s` | `$%06X`–`$%06X` | %d | %d | %d | %d%% |\n"
          % (nm, lo, hi, hi - lo, len(blocks), cov, 100 * cov // (hi - lo)))
    p("\nВсего %d байт в %d сегментах, из них %d (%d%%) — сжатые блоки.\n\n"
      % (tot_seg, len(rows), tot_cov, 100 * tot_cov // max(tot_seg, 1)))
    p("## По сегментам\n\n")
    for nm, lo, hi, blocks, ref, rawr in rows:
        p("### `%s` `$%06X`–`$%06X`\n\n" % (nm, lo, hi))
        if rawr:
            p("Передаётся без распаковки: %s.\n\n"
              % ", ".join("`$%06X`" % a for a in rawr))
        p("| адрес | метод | сжато | распаковано | ссылка в коде |\n"
          "|---|---|---|---|---|\n")
        for a in sorted(blocks):
            m, comp, size = blocks[a]
            p("| `$%06X` | %d | %d | %d | %s |\n"
              % (a, m, comp, size, "да" if a in ref else "по цепочке"))
        gap = (hi - lo) - sum(b[1] for b in blocks.values())
        p("\nНе покрыто: %d байт.\n\n" % gap)
    f.close()
    print("записано: %s (%d сегментов, %d блоков)"
          % (os.path.relpath(out, HERE), len(rows),
             sum(len(r[3]) for r in rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
