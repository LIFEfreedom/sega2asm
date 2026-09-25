#!/usr/bin/env python3
u"""Миссии оригинала в формате ремейка (dyna #204).

    make exportmissions

Пишет `out/<имя>/export/campaigns/Original/`: `campaign.json` и
`maps/<N>/mission.json` на каждую из 123 миссий, в порядке глав ROM
(0 — уроки, 1…5, 8 — галерея), плюс `report.md` о том, что не вошло.

## Карта

40x40 клеток. Байт карты — после `BuildMapEdgeCodes`, если бит 7 `+$2F`
взведён, как это делает сама игра; тип — по таблице «байт -> тип»
записи графики `+$2A`. Ремейк держит растения объектами, поэтому:

| тип ROM | местность | растение ремейка |
|---|---|---|
| 1…4 | 0 | трава, стадии 0…3 (коды 1…4) |
| 5…7 | 0 | цветы, стадии 1…3 (коды 6…8) |
| 21…23 | 0 | колючки, стадии 1…3 (коды 10…12) |
| 24…26 | 0 | дерево (код 13) |
| прочие | как есть | — |

Байт карты уходит отдельным слоем `map_bytes`: по нему ремейк рисует
клетку, пока её тип не изменился, — края, берега и виды деревьев
остаются как в оригинале.

## Игроки

Расстановка — `LoadPlacement` `$01EA54`: четыре байта на запись, запись
на клетке типов 22…30 (маска `$7FC00000`) пропускается. Владелец и вид —
`UnitTypeTable` `$01FAEE`: младшие пять бит байта `+$1` — вид, бит 6 —
«принадлежит игроку», знаковый бит — второму.

- Гнёзда: тип 1 — игрока 1, типы 2…4 — игрока 2.
- Юниты игроков видов 1…6: поза 3 — яйцо, 4 и 8 — падаль, прочие —
  ходьба. Направление — те же три бита, нумерация ремейка совпадает.
- Нейтральные, декор и виды 8/9 не выгружаются — это отдельные задачи.

Деньги — BCD `+$34` и `+$38`. Доступность — слова подкоманд с `+$3C`
по номеру команды (`data_177` `$024B52`): погода — команда 2
(`+$3E`: полив, ливень, буря, засуха, землетрясение, молния,
метеорит), яйца — команда 5 (`+$44`, подпункт через `EggMenuToRoster`
`$00879E` в слот ростера `+$04`). Победа и поражение — по умолчанию
игры: у противника не осталось юнитов.
"""
import collections
import io
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import maptex as mt                                          # noqa: E402
from unpack import unpack                                    # noqa: E402
from paths import OUT as out_path                            # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROM = mt.ROM
W = H = 40
UNIT_TYPES = 0x01FAEE
EGG_MENU_TO_ROSTER = 0x00879E
SKIP_ON = 0x7FC00000               # LoadPlacement: типы 22…30

# подпункт погоды -> WeatherType ремейка (Sun 0, Rain 1, Wind 2,
# HeavyRain 3, Earthquake 4, Meteorite 5, Lightning 6)
WEATHER_ITEMS = (1, 3, 2, 0, 4, 6, 5)
POSES = {3: "egg", 4: "carcass", 8: "carcass"}

# тип ROM -> (местность, код растения ремейка)
PLANTS = {}
for _t in range(1, 5):
    PLANTS[_t] = _t                # трава: стадия t-1 -> код t
for _t in range(5, 8):
    PLANTS[_t] = _t + 1            # цветы: стадия t-4 -> код 5 + стадия
for _t in range(21, 24):
    PLANTS[_t] = _t - 11           # колючки: стадия t-20 -> код 9 + стадия
for _t in range(24, 27):
    PLANTS[_t] = 13                # дерево


def u16(r, o):
    return struct.unpack_from(">H", r, o)[0]


def bcd(b):
    return int("".join("%02X" % x for x in b) or "0")


def unit_type(t):
    u"""(владелец 0/1/2, вид, декор) по `UnitTypeTable`."""
    b = ROM[UNIT_TYPES + t * 4 + 1]
    owner = (2 if b & 0x80 else 1) if b & 0x40 else 0
    return owner, b & 0x1F, bool(b & 0x20)


def mission_name(c, m):
    if c == 0:
        return u"Урок %d" % m
    if c == 8:
        return u"Галерея, карта %d" % m
    return u"Глава %d, миссия %d" % (c, m)


def conditions(team):
    other = 2 if team == 1 else 1
    cond = lambda target: {"type": 0, "target_player_id": target,
                           "target_unit_type": 0, "target_amount": 0,
                           "target_x": 0, "target_y": 0, "radius": 0}
    return [cond(other)], [cond(team)]


def export_mission(c, m, r, recs, skipped):
    st = r[3]
    o = mt.STAGES + (st - 1) * 8
    mp, pl = mt.U32(o), mt.U32(o + 4)
    _me, size, cells, _e = unpack(ROM, mp)
    assert size == W * H, (c, m, size)
    if r[0x2F] & 0x80:
        cells = mt.autotile(cells)
    typeof = mt.meta_tables(recs[r[0x2A]])[0]

    terrain, veg, types = [], [], []
    for b in cells:
        t = typeof[b] if b else 30
        types.append(t)
        if t in PLANTS:
            terrain.append(0)
            veg.append(PLANTS[t])
        else:
            terrain.append(t)
            veg.append(0)

    nests = {1: [], 2: []}
    units = []
    for x, y, d, typ, pose in mt.placement(pl):
        if (SKIP_ON >> types[y * W + x]) & 1:
            skipped[u"клетка типов 22…30"] += 1
            continue
        if typ == 1 or typ in (2, 3, 4):
            nests[1 if typ == 1 else 2].append({"x": x, "y": y})
            continue
        owner, sp, decor = unit_type(typ)
        if owner == 0:
            skipped[u"декор" if decor else u"нейтральный вид %d" % sp] += 1
            continue
        if not 1 <= sp <= 6:
            skipped[u"вид %d игрока" % sp] += 1
            continue
        units.append({"team_id": owner, "unit_type": sp - 1, "x": x, "y": y,
                      "facing": d, "pose": POSES.get(pose, "walk")})

    roster1 = r[0x04:0x0E]
    eggs = u16(r, 0x44)
    menu = ROM[EGG_MENU_TO_ROSTER:EGG_MENU_TO_ROSTER + 6]
    avail1 = sorted({unit_type(roster1[menu[i] - 1])[1] - 1
                     for i in range(6) if eggs >> i & 1
                     and 1 <= unit_type(roster1[menu[i] - 1])[1] <= 6})
    weather = u16(r, 0x3E)
    weathers1 = sorted(WEATHER_ITEMS[i] for i in range(7) if weather >> i & 1)
    avail2 = sorted({unit_type(t)[1] - 1 for t in r[0x0E:0x18]
                     if 1 <= unit_type(t)[1] <= 6})

    players = []
    for team, money, avail, wth in ((1, bcd(r[0x34:0x38]), avail1, weathers1),
                                    (2, bcd(r[0x38:0x3C]), avail2,
                                     sorted(WEATHER_ITEMS))):
        first = nests[team][0] if nests[team] else {"x": -1, "y": -1}
        win, lose = conditions(team)
        players.append({"team_id": team, "start_x": first["x"],
                        "start_y": first["y"], "nests": nests[team],
                        "victory_conditions": win, "defeat_conditions": lose,
                        "available_units": avail, "available_weathers": wth,
                        "starting_energy": money})
    start = nests[1][0] if nests[1] else {"x": W // 2, "y": H // 2}
    doc = collections.OrderedDict()
    doc["name"] = mission_name(c, m)
    doc["map"] = collections.OrderedDict([
        ("width", W), ("height", H),
        ("start_x", start["x"]), ("start_y", start["y"]),
        ("tileset", str(r[0x2A])),
        ("starting_energy", players[0]["starting_energy"]),
        ("playable_margin", 0),
        ("tilemap", []),
        ("terrain_types", terrain),
        ("map_bytes", list(cells)),
        ("vegetation", veg),
        ("units", units),
        ("players", players),
    ])
    return doc, len(units), len(nests[2])


def main():
    root = out_path("export", "campaigns", "Original")
    maps = os.path.join(root, "maps")
    os.makedirs(maps, exist_ok=True)
    recs = mt.gfx_records()
    skipped = collections.Counter()
    n = 0
    rows = []
    for c, m, r in mt.missions():
        n += 1
        doc, nunits, nests2 = export_mission(c, m, r, recs, skipped)
        d = os.path.join(maps, str(n))
        os.makedirs(d, exist_ok=True)
        with io.open(os.path.join(d, "mission.json"), "w", encoding="utf-8",
                     newline="\n") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
        rows.append((n, doc["name"], r[3], nunits, nests2,
                     doc["map"]["starting_energy"]))
    with io.open(os.path.join(root, "campaign.json"), "w", encoding="utf-8",
                 newline="\n") as f:
        json.dump({"name": u"Оригинал"}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with io.open(os.path.join(root, "report.md"), "w", encoding="utf-8",
                 newline="\n") as f:
        p = f.write
        p(u"# Миссии оригинала для ремейка\n\nСобрано `tools/exportmissions.py`.\n\n")
        p(u"## Не выгружено\n\n| что | записей |\n|---|---:|\n")
        for k, v in sorted(skipped.items()):
            p(u"| %s | %d |\n" % (k, v))
        p(u"\n## Миссии\n\n| № | название | этап | юнитов | гнёзд у игрока 2 | деньги |\n"
          u"|---:|---|---:|---:|---:|---:|\n")
        for row in rows:
            p(u"| %d | %s | %d | %d | %d | %d |\n" % row)
    print(u"миссий: %d -> %s" % (n, os.path.relpath(root, HERE)))
    for k, v in sorted(skipped.items()):
        print(u"  не выгружено: %s — %d" % (k, v))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
