#!/usr/bin/env python3
"""Карты этапов: местность 40x40 и расстановка юнитов.

    make maps

`StageTable` `$164400` — 256 записей по 8 байт: длинное слово на карту
местности и длинное слово на сценарий расстановки (`$006C56`). Карта лежит
сжатой, разворачивается в **ровно 1600 байт = 40x40 клеток по байту**.
Расстановка читается `LoadPlacement` `$01EA12` по 4 байта на юнита, пока не
встретится отрицательное слово: слово с упакованными координатами (Y — шесть
младших бит, направление — следующие три, X — следующие шесть), байт типа и
байт позы.

Порядок осей именно такой: на 40 умножается младшее поле, и `CreateUnit`
кладёт его в `+$3` записи юнита, а `+$3` это вертикаль (см. разбор в
docs/game-stages.md). Раньше здесь было наоборот, и точки юнитов ложились
на PNG зеркально относительно диагонали.

Пишет PNG по карте на этап в `out/<имя>/maps/` и сводку в `docs/game-maps.md`.
Цвета условные: имён у типов местности нет, известны только растения
(`$01`, `$05`, `$15`, `$16`) и четвёрка смертельных 11, 12, 13, 20
([game-terrain.md](game-terrain.md)).
"""
import collections
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

from unpack import unpack                                    # noqa: E402
from gfx import png                                          # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT as out_path, rom_bytes

ROM = rom_bytes()
U16 = lambda o: struct.unpack_from(">H", ROM, o)[0]
S16 = lambda o: struct.unpack_from(">h", ROM, o)[0]
U32 = lambda o: struct.unpack_from(">I", ROM, o)[0]

STAGES = 0x164400
N_STAGES = 256
W = H = 40
CELL = 8                      # пикселей на клетку
LETHAL = (11, 12, 13, 20)
PLANTS = (1, 5, 21, 22)

# Палитра условная: под номер типа, а не под смысл. Смертельные красным,
# растения зелёным, остальное — ровная серо-синяя шкала, чтобы рельеф
# читался глазом.
def colour(t):
    if t in LETHAL:
        return (170, 30, 30)
    if t in PLANTS:
        return (60, 150, 60)
    if t <= 7:                       # открытое, чем выше — тем гуще трава
        g = 90 + t * 12
        return (70, g, 70)
    if t in (8, 9):
        return (60, 90, 170)
    if t <= 14:
        return (150, 140, 110)
    return (110, 110, 120)


def placement(a):
    """[(x, y, dir, type, pose)] — пока не встретится отрицательное слово."""
    out = []
    if not (0x100000 <= a < len(ROM) - 4):
        return out
    for _ in range(400):
        w = S16(a)
        if w < 0:
            break
        v = U16(a)
        y = v & 0x3F
        d = (v >> 6) & 0x07
        x = (v >> 9) & 0x3F
        out.append((x, y, d, ROM[a + 2], ROM[a + 3]))
        a += 4
    return out


def render(path, cells, units):
    rows = []
    for y in range(H):
        line = []
        for x in range(W):
            line.extend([colour(cells[y * W + x] & 0x1F)] * CELL)
        for _ in range(CELL):
            rows.append(list(line))
    # юниты — светлая точка 4x4 в центре клетки
    for x, y, _d, _t, _p in units:
        if not (0 <= x < W and 0 <= y < H):
            continue
        for dy in range(2, CELL - 2):
            for dx in range(2, CELL - 2):
                rows[y * CELL + dy][x * CELL + dx] = (245, 240, 120)
    png(path, W * CELL, H * CELL, rows)


SHEET_SCALE = 2               # пикселей на клетку в контактном листе
SHEET_COLS = 12
SHEET_GAP = 3
SHEET_BG = (24, 24, 28)


def sheet(path, plates):
    """Все различные карты одним листом: [(cells, units)] по порядку этапов."""
    tile = W * SHEET_SCALE
    step = tile + SHEET_GAP
    cols = SHEET_COLS
    lines = (len(plates) + cols - 1) // cols
    wpx = cols * step + SHEET_GAP
    hpx = lines * step + SHEET_GAP
    img = [[SHEET_BG] * wpx for _ in range(hpx)]
    for i, (cells, units) in enumerate(plates):
        ox = SHEET_GAP + (i % cols) * step
        oy = SHEET_GAP + (i // cols) * step
        for y in range(H):
            for x in range(W):
                c = colour(cells[y * W + x] & 0x1F)
                for dy in range(SHEET_SCALE):
                    row = img[oy + y * SHEET_SCALE + dy]
                    for dx in range(SHEET_SCALE):
                        row[ox + x * SHEET_SCALE + dx] = c
        for ux, uy, _d, _t, _p in units:
            if not (0 <= ux < W and 0 <= uy < H):
                continue
            for dy in range(SHEET_SCALE):
                row = img[oy + uy * SHEET_SCALE + dy]
                for dx in range(SHEET_SCALE):
                    row[ox + ux * SHEET_SCALE + dx] = (245, 240, 120)
    png(path, wpx, hpx, img)
    return wpx, hpx


def main():
    import stagescript
    # Карты индексируются байтом +$3 МИНУС ОДИН, в отличие от таблиц
    # сценариев и ИИ. Раньше здесь стоял stage_to_missions(), и каждая
    # карта подписывалась соседней миссией.
    miss = stagescript.maptable_to_missions()

    outdir = out_path("maps")
    os.makedirs(outdir, exist_ok=True)

    rows, by_map, plates = [], collections.defaultdict(list), []
    hist, flags = collections.Counter(), collections.Counter()
    drawn = 0
    for st in range(N_STAGES):
        o = STAGES + st * 8
        m, pl = U32(o), U32(o + 4)
        if not (0x164C00 <= m < 0x200000):
            continue
        try:
            _meth, size, cells, _end = unpack(ROM, m)
        except Exception:
            continue
        if size != W * H:
            continue
        units = placement(pl)
        if m not in by_map:
            plates.append((cells, units))
        by_map[m].append(st)
        name = "stage_%03d" % st
        render(os.path.join(outdir, name + ".png"), cells, units)
        drawn += 1
        hist.update(c & 0x1F for c in cells)
        flags.update(c >> 5 for c in cells)
        rows.append((st, m, pl, len(units),
                     sorted({c & 0x1F for c in cells}), name))

    sheet(os.path.join(outdir, "_all.png"), plates)

    out = os.path.join(HERE, "docs", "game-maps.md")
    f = io.open(out, "w", encoding="utf-8", newline="\n")
    p = f.write
    p("# Карты этапов\n\n")
    p("Собрано `tools/maps.py` (`make maps`). Картинки — в `out/<имя>/maps/`:\n"
      "по PNG на этап плюс `_all.png` — контактный лист со всеми различными\n"
      "картами в порядке этапов.\n\n")
    p("СГЕНЕРИРОВАНО — правки затираются, меняйте инструмент.\n"
      "Вывод, который надо сохранить, пишите в соседний, ручной файл.\n\n")
    p(__doc__[__doc__.index("`StageTable`"):].strip() + "\n\n")

    p("## Сколько их\n\n")
    p("- записей в таблице: %d\n" % N_STAGES)
    p("- этапов с разворачиваемой картой: **%d**\n" % drawn)
    p("- различных карт: **%d** (некоторые этапы делят одну)\n" % len(by_map))
    p("- юнитов в расстановках: %d\n\n" % sum(r[3] for r in rows))

    p("## Из чего сложены карты\n\n")
    p("Байт клетки держит **тип в младших пяти битах**, старшие три — флаги\n"
      "([game-map.md](game-map.md)). Гистограмма по типам, всего %d клеток:\n\n"
      % sum(hist.values()))
    p("| тип | клеток | доля | что известно |\n|---|---|---|---|\n")
    tot = sum(hist.values())
    for t, n in sorted(hist.items()):
        note = ("**смертельный**" if t in LETHAL else
                "растение" if t in PLANTS else "")
        p("| %d | %d | %.1f%% | %s |\n" % (t, n, 100.0 * n / tot, note))
    p("\nСтаршие три бита:\n\n| флаги | клеток | доля |\n|---|---|---|\n")
    for v, n in sorted(flags.items()):
        p("| %d | %d | %.1f%% |\n" % (v, n, 100.0 * n / tot))
    p("\n")

    p("## Что видно\n\n")
    top = hist.most_common(1)[0]
    p("Треть всех клеток — **тип %d** (%.0f%%), и по краям карт его ещё\n"
      "больше. Он непроходим для всех видов, гасит обзор по маске `$7F800000`\n"
      "и **горит**: тип 25 входит в маску поджига `$07E000FE`\n"
      "([game-map.md](game-map.md)). Раньше я записал его как фон за пределами\n"
      "поля — горящий фон это странно, так что вернее читать его как густую\n"
      "растительность. Имён у типов местности всё равно нет\n"
      "([game-terrain.md](game-terrain.md)).\n\n"
      % (top[0], 100.0 * top[1] / tot))
    dead = {}
    for st, m, _pl, _n, _t, _nm in rows:
        dead.setdefault(m, sum(1 for c in unpack(ROM, m)[2]
                               if (c & 0x1F) in LETHAL))
    p("Карты с самой злой местностью — смертельных клеток из 1600 "
      "(по карте, не по этапу):\n\n")
    for m, n in sorted(dead.items(), key=lambda kv: -kv[1])[:6]:
        sts = by_map[m]
        ms = sorted({x for s in sts for x in miss.get(s, [])})
        p("* `$%06X`: **%d** — этап%s %s%s\n"
          % (m, n, "ы" if len(sts) > 1 else "",
             ", ".join(str(s) for s in sts),
             " (%s)" % ", ".join(ms) if ms else ""))
    p("\nПервая строка обманывает: `$1748E0` — **рисунок**, фигура женщины на\n"
      "красном фоне, и 841 «смертельная» клетка это просто фон. Но картой он\n"
      "при этом остаётся: на него смотрят шестнадцать записей подряд, 196…211,\n"
      "и две из них — настоящие миссии главы 8. То же у `$174A56` (329):\n"
      "это портрет мужчины в тёмных очках, глава 8 миссия 7.\n\n")

    p("## Глава 8 нарисована, а не размечена\n\n")
    p("Если разложить все различные карты в один лист, глава 8 отделяется от\n"
      "остальных с первого взгляда. Семь её миссий (10, 11, 13, 15, 21, 22, 23)\n"
      "берут обычные карты из середины таблицы, а остальные — картинки и\n"
      "постановочные арены:\n\n")
    p("| миссия | этап | карта | что нарисовано |\n"
      "|---|---|---|---|\n"
      "| м.1, м.2 | 210, 211 | `$1748E0` | женщина на красном фоне |\n"
      "| м.4 | 213 | `$1FFA42` | морда и надпись «VJ» красным |\n"
      "| м.5, м.9 | 254 | `$175346` | логотип **CRI** синими буквами |\n"
      "| м.6, м.14 | 253 | `$1FFCF2` | надпись **«DB2»** над картой |\n"
      "| м.7 | 214 | `$174A56` | портрет мужчины в очках и с усами |\n"
      "| м.17 | 218 | `$174F07` | женская фигура на звёздном фоне |\n"
      "| м.19 | 220 | `$175166` | пустая синяя арена, стена из 78 юнитов посередине |\n"
      "| м.20 | 221 | `$17518C` | то же поле, один-единственный юнит |\n"
      "| м.24 | 222 | `$1751B2` | существо в рамке |\n\n")
    p("Карту `$175346` с логотипом CRI держат **31** запись таблицы, `$1748E0` —\n"
      "шестнадцать. Лишние записи миссиям не принадлежат: это запас, которым\n"
      "заполнили хвост таблицы, и заполнили его заставкой.\n\n")

    p("## Этапы\n\n")
    p("| этап | карта | расстановка | юнитов | типов | миссии | картинка |\n")
    p("|---|---|---|---|---|---|---|\n")
    for st, m, pl, nu, types, name in rows:
        ms = ", ".join(miss.get(st, [])) or "—"
        p("| %d | `$%06X` | `$%06X` | %d | %d | %s | `%s.png` |\n"
          % (st, m, pl, nu, len(types), ms, name))
    f.close()
    print("нарисовано карт: %d (различных %d), сводка: %s"
          % (drawn, len(by_map), os.path.relpath(out, HERE)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
