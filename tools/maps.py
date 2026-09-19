#!/usr/bin/env python3
"""Карты этапов: местность 40x40 и расстановка юнитов.

    make maps

`StageTable` `$164400` — 256 записей по 8 байт: длинное слово на карту
местности и длинное слово на сценарий расстановки (`$006C56`). Карта лежит
сжатой, разворачивается в **ровно 1600 байт = 40x40 клеток по байту**.
Расстановка читается `LoadPlacement` `$01EA12` по 4 байта на юнита, пока не
встретится отрицательное слово: слово с упакованными координатами (X — шесть
младших бит, направление — следующие три, Y — следующие шесть), байт типа и
байт позы.

Пишет PNG по карте на этап в `out/maps/` и сводку в `docs/game-maps.md`.
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

ROM = open(os.path.join(HERE, "game.gen"), "rb").read()
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
        x = v & 0x3F
        d = (v >> 6) & 0x07
        y = (v >> 9) & 0x3F
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


def main():
    import stagescript
    miss = stagescript.stage_to_missions()

    outdir = os.path.join(HERE, "out", "maps")
    os.makedirs(outdir, exist_ok=True)

    rows, by_map = [], collections.defaultdict(list)
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
        by_map[m].append(st)
        name = "stage_%03d" % st
        render(os.path.join(outdir, name + ".png"), cells, units)
        drawn += 1
        hist.update(c & 0x1F for c in cells)
        flags.update(c >> 5 for c in cells)
        rows.append((st, m, pl, len(units),
                     sorted({c & 0x1F for c in cells}), name))

    out = os.path.join(HERE, "docs", "game-maps.md")
    f = io.open(out, "w", encoding="utf-8", newline="\n")
    p = f.write
    p("# Карты этапов\n\n")
    p("Собрано `tools/maps.py` (`make maps`). Картинки — в `out/maps/`.\n\n")
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
    p("\nПервая строка — не карта. `$1748E0` это **рисунок**: если раскрасить\n"
      "клетки по типу, выходит фигура женщины на красном фоне, и 841\n"
      "«смертельная» клетка — просто этот фон. На неё смотрят шестнадцать\n"
      "записей таблицы этапов подряд, 196…211. Похоже на пасхалку или на\n"
      "заготовку, оставшуюся в данных; проверить в игре я не могу.\n\n")

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
