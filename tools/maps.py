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

Байт клетки — **не тип местности**. Тип даёт таблица перевода на 256
байт, которую `LoadStageGraphics` кладёт в `$FFBBBC`; она приходит вместе
с набором графики этапа и своя у каждого из девяти наборов, хотя по делу
они почти совпадают. `BuildTerrainMap` `$0203FE` гоняет карту через неё.
Разбор цепочки — в `tools/maptex.py`; там же карты рисуются настоящими
тайлами игры, а не условными цветами.

Пишет PNG по карте на этап в `out/<имя>/maps/` и сводку в `docs/game-maps.md`.
Цвет клетки — средний цвет её настоящей текстуры, посчитанный по набору
графики 0; имён у типов местности в ROM всё равно нет
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

# Цвет типа — СРЕДНИЙ цвет его клетки, посчитанный по настоящим тайлам
# игры (набор графики 0). Раньше здесь была выдуманная шкала; после того
# как `tools/maptex.py` научился собирать клетку так же, как её собирает
# игра, придумывать цвета стало незачем.
TYPE_COLOUR = None


def build_type_colours():
    import maptex
    rec = maptex.gfx_records()[0]
    _typeof, celltab, metatab = maptex.meta_tables(rec)
    tiles = maptex.tileset(rec)
    pals = [maptex.array_palette(0), maptex.array_palette(1),
            maptex.array_palette(3), maptex.rec_palette(rec, 0)]
    t2t = ROM[0x020454:0x020474]     # data_165: тип -> плитка
    out = {0xFF: (24, 24, 28)}
    for t in range(32):
        tile = t2t[t]
        entry = (0, 0, 0, 0) if tile == 0 else celltab[tile - 1]
        acc = [0, 0, 0]
        n = 0
        for q in range(4):
            for v in metatab[entry[q] & 0x1FF]:
                name = (v + 0x6075) & 0xFFFF
                g = tiles.get(name & 0x7FF)
                if g is None:
                    continue
                pal = pals[(name >> 13) & 3]
                for b in g:
                    for c in (pal[b >> 4], pal[b & 15]):
                        acc[0] += c[0]
                        acc[1] += c[1]
                        acc[2] += c[2]
                        n += 1
        out[t] = tuple(v // n for v in acc) if n else (24, 24, 28)
    return out


def colour(t):
    return TYPE_COLOUR[t]


def terrain_types():
    """Байт карты -> тип местности, из набора графики 0."""
    import maptex
    return maptex.meta_tables(maptex.gfx_records()[0])[0]


TYPE_OF = None


def cell_type(b):
    """$FF означает «типа нет»; такие клетки игра не рисует."""
    return TYPE_OF[b]


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
            line.extend([colour(cell_type(cells[y * W + x]))] * CELL)
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
                c = colour(cell_type(cells[y * W + x]))
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

    global TYPE_OF, TYPE_COLOUR
    TYPE_OF = terrain_types()
    TYPE_COLOUR = build_type_colours()

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
        hist.update(cell_type(c) for c in cells)
        rows.append((st, m, pl, len(units),
                     sorted({cell_type(c) for c in cells
                             if cell_type(c) != 0xFF}), name))

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
    p("ПОПРАВКА. Раньше здесь стояло «тип в младших пяти битах байта, старшие\n"
      "три — флаги». Это неверно: байт целиком идёт в таблицу перевода\n"
      "`$FFBBBC`, которая приходит с набором графики этапа, и уже она даёт\n"
      "тип. Числа ниже пересчитаны по ней; прежние — и доля типа 25, и доля\n"
      "типа 31 — были посчитаны не про то.\n\n")
    p("Гистограмма по типам, всего %d клеток:\n\n" % sum(hist.values()))
    p("| тип | клеток | доля | что известно |\n|---|---|---|---|\n")
    tot = sum(hist.values())
    for t, n in sorted(hist.items()):
        note = ("типа нет: игра такую клетку не рисует" if t == 0xFF else
                "**смертельный**" if t in LETHAL else
                "растение" if t in PLANTS else "")
        p("| %s | %d | %.2f%% | %s |\n"
          % ("$FF" if t == 0xFF else t, n, 100.0 * n / tot, note))
    p("\n")

    p("## Что видно\n\n")
    big = [(t, n) for t, n in hist.most_common(4) if t != 0xFF][:2]
    p("Вся поверхность игры держится на двух типах: **%d** (%.0f%%) и **%d**\n"
      "(%.0f%%). Первый занимает середину карт, второй — края и всё\n"
      "непроходимое. Остальные тридцать делят оставшуюся треть.\n\n"
      % (big[0][0], 100.0 * big[0][1] / tot,
         big[1][0], 100.0 * big[1][1] / tot))
    rare = sorted((n, t) for t, n in hist.items() if t != 0xFF)[:4]
    p("На другом конце — типы, которых в исходных картах почти нет: %s.\n"
      "Это важно помнить, читая разборы кода: правило, которое срабатывает\n"
      "на типе 31, в реальных данных не срабатывает никогда.\n\n"
      % ", ".join("**%d** (%d клет.)" % (t, n) for n, t in rare))
    dead = {}
    for st, m, _pl, _n, _t, _nm in rows:
        dead.setdefault(m, sum(1 for c in unpack(ROM, m)[2]
                               if cell_type(c) in LETHAL))
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
