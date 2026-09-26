#!/usr/bin/env python3
u"""Миссии оригинала в формате ремейка (dyna #204).

    make exportmissions

Пишет `out/<имя>/export/campaigns/<кампания>/`: `campaign.json` и
`maps/<N>/mission.json`, где N — номер миссии в главе, плюс общий
`report.md` о том, что не вошло. Кампания — режим оригинала, то есть
его главы (`ChapterTable` `$060400`); какой пункт меню какую главу
открывает, прослежено по коду в [game-modes.md](../docs/game-modes.md):

| кампания | глава | в оригинале |
|---|---|---|
| Training | 0 | れんしゅうモード |
| Story | 1 | ストーリーモード |
| Original: Easy / Normal / Hard | 3 / 4 / 5 | オリジナルモード, три уровня |
| Duel | 2 | たいけつモード, карты для двоих |
| Extra | 8 | в меню нет, только пароли |

Названия английские, как весь интерфейс ремейка: у сюжета и поединка —
названия оригинала латиницей, у уроков — номер урока, у прочих
названий в ROM нет. Кампании открыты целиком (`all_unlocked`): цели с
ﾎﾟﾝﾎﾟﾝ и ﾒｶﾞｻﾞｳﾙｽ ещё отложены (dyna #206), а демо-бои Extra 9 и 14
человеку не пройти — последовательное открытие заперло бы всё за ними.

## Карта

40x40 клеток. Байт карты — после `BuildMapEdgeCodes`, если бит 7 `+$2F`
взведён, как это делает сама игра; тип — по таблице «байт -> тип»
записи графики `+$2A`. Ремейк держит растения объектами, поэтому:

| тип ROM | местность | растение ремейка |
|---|---|---|
| 1…4 | 0 | трава, стадии 0…3 (коды 1…4) |
| 5, 6, 7 | 0 | цветы: росток, малый, выросший (коды 5, 6, 8) |
| 21, 22, 23 | 0 | колючки: росток, малый, выросший (коды 9, 10, 12) |
| 24…26 | 0 | дерево (код 13) |
| прочие | как есть | — |

Стадии совпадают по часам (`TerrainCounterSeeds` `$02246C`: ростки 5 и
21 живут 85 и 56 шагов, как у ремейка) и по питательности
(`GrazeTakeNutrition`: 6 и 7 дают 10 и 230). У оригинала три стадии
цветов и колючек, у ремейка четыре; последний тип оригинала — это
выросшее растение ремейка.

Байт карты уходит отдельным слоем `map_bytes`: по нему ремейк рисует
клетку, пока её тип не изменился, — края, берега и виды деревьев
остаются как в оригинале.

`tileset` — запись графики `+$2A`, `palette` — палитра внутри неё
`+$4C` (dyna #205): ею, рядом CRAM 3, нарисована вся местность. У 95
миссий из 123 она нулевая.

Поле — клетки 1…38: `CanStepToCell` `$01E050` отказывает в шаге, если
новая координата равна 0 или не меньше 39. Отсюда `playable_margin` 1.
Край при этом бывает любой местностью, чаще всего водой.

## Игроки

Расстановка — `LoadPlacement` `$01EA54`: четыре байта на запись, запись
на клетке типов 22…30 (маска `$7FC00000`) пропускается. К расстановке
карты добавляется та, что грузит обработчик входа на карту: такой один,
у этапа 222 (Extra 20) — `data_245`, 18 яиц ﾃｨﾗﾉ игрока 2, 18 ﾋﾟｰﾁｬﾝ
игрока 1 и 38 пустых яиц. Владелец и вид —
`UnitTypeTable` `$01FAEE`: младшие пять бит байта `+$1` — вид, бит 6 —
«принадлежит игроку», знаковый бит — второму.

- Гнёзда: тип 1 — игрока 1, типы 2…4 — игрока 2.
- Юниты игроков видов 1…6: поза 3 — яйцо, 4 и 8 — падаль, прочие —
  ходьба. Направление — те же три бита, нумерация ремейка совпадает.
- Ничьё, команда 0 (dyna #206, разбор в game-neutral.md): мясо — типы
  69…74, падаль видов 1…6 (`unit_type` 0…5), поза `carcass`; кости —
  тип 67, падаль с блоком ﾋﾟｰﾁｬﾝ (`unit_type` 5), поза `bones`; пустое
  яйцо — тип 68, поза `empty_egg`.
- Прочие нейтральные, части ﾒｶﾞｻﾞｳﾙｽ, падаль вида 20 (тип 75) и виды
  8/9 игроков не выгружаются — это отдельные задачи.

Деньги — BCD `+$34` и `+$38`. Доступность — слова подкоманд с `+$3C`
по номеру команды (`data_177` `$024B52`): погода — команда 2
(`+$3E`: полив, ливень, буря, засуха, землетрясение, молния,
метеорит), яйца — команда 5 (`+$44`, подпункт через `EggMenuToRoster`
`$00879E` в слот ростера `+$04`).

## Цели

Разбор в [game-mission-end.md](../docs/game-mission-end.md). Вердикт
у оригинала один на обоих, с точки зрения игрока 1, и цели выгружаются
для него; у игрока 2 те же списки наоборот — его победа есть поражение
первого. По умолчанию победа — `DestroyPlayer 2`, поражение —
`DestroyPlayer 1`. Особое читается из ROM:

- вход на карту (`table_stagestart` `$02CE90`) запрещает победу по
  переписи на этапах 20, 51 и 222;
- покадровый сценарий (`table_stageframe` `$02D0B8`) первым делом зовёт
  тело цели: восемь травоядных на этапе 51 — `HerbivoresReach`;
  исчезновение пустых яиц на этапе 222 — `AllOf [DestroyPlayer 2,
  EmptyEggsGone]`, потому что оно победу лишь разрешает.

ﾎﾟﾝﾎﾟﾝ (этапы 29, 30, 34, 36) и ﾒｶﾞｻﾞｳﾙｽ (этап 20) у ремейка ещё нет:
эти миссии идут с обычной целью, отложенное перечислено в `report.md`.
"""
import collections
import io
import json
import os
import re
import shutil
import struct
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import maptex as mt                                          # noqa: E402
import missions as ms                                        # noqa: E402
import dumptext as dt                                        # noqa: E402
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
MEAT = range(69, 75)               # падаль видов 1…6, по классу типа
BONES, EMPTY_EGG = 67, 68
BONES_SPECIES = 6                  # дескриптор $06A4 -> блок ﾋﾟｰﾁｬﾝ $022AEA
PONPON = 50                        # нейтрал, за которым следят этапы 29, 30, 34, 36

START_TABLE = 0x02CE90             # table_stagestart: вход на карту
FRAME_TABLE = 0x02D0B8             # table_stageframe: каждый тик
ENABLE_WIPEOUT, DISABLE_WIPEOUT = 0x01673C, 0x016754
LOAD_PLACEMENT = 0x01EA12
GOAL_BODIES = {0x02EAF6: "herbivores",       # WinIfHerbivoresReach
               0x02EB50: "allow_if_gone",    # AllowWinIfNeutralTypeGone
               0x02EB16: "lose_if_gone"}     # LoseIfNeutralTypeGone

# ConditionType ремейка
DESTROY_PLAYER, HERBIVORES_REACH, EMPTY_EGGS_GONE, ALL_OF = 0, 5, 6, 7

# тип ROM -> (местность, код растения ремейка)
PLANTS = {}
for _t in range(1, 5):
    PLANTS[_t] = _t                # трава: стадия t-1 -> код t
PLANTS.update({5: 5, 6: 6, 7: 8})          # цветы: росток, малый, выросший
PLANTS.update({21: 9, 22: 10, 23: 12})     # колючки: то же
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


# (папка, название, глава) в порядке меню оригинала; Extra — последней
CAMPAIGNS = (("Training", u"Training", 0),
             ("Story", u"Story", 1),
             ("OriginalEasy", u"Original: Easy", 3),
             ("OriginalNormal", u"Original: Normal", 4),
             ("OriginalHard", u"Original: Hard", 5),
             ("Duel", u"Duel", 2),
             ("Extra", u"Extra", 8))

DUEL_NAMES = 0x04F22A              # 16 строк «NN:название», таблица $04F1EC

KANA = {}
for _row, _cons in (("アイウエオ", ""), ("カキクケコ", "k"), ("ガギグゲゴ", "g"),
                    ("サシスセソ", "s"), ("ザジズゼゾ", "z"), ("タチツテト", "t"),
                    ("ダヂヅデド", "d"), ("ナニヌネノ", "n"), ("ハヒフヘホ", "h"),
                    ("バビブベボ", "b"), ("パピプペポ", "p"), ("マミムメモ", "m"),
                    ("ラリルレロ", "r")):
    for _k, _v in zip(_row, "aiueo"):
        KANA[_k] = _cons + _v
KANA.update({u"シ": "shi", u"ジ": "ji", u"チ": "chi", u"ヂ": "ji", u"ツ": "tsu",
             u"ヅ": "zu", u"フ": "fu", u"ヤ": "ya", u"ユ": "yu", u"ヨ": "yo",
             u"ワ": "wa", u"ヲ": "o", u"ン": "n", u"ヴ": "vu"})
SMALL_VOWEL = {u"ァ": "a", u"ィ": "i", u"ゥ": "u", u"ェ": "e", u"ォ": "o"}
SMALL_Y = {u"ャ": "a", u"ュ": "u", u"ョ": "o"}


def romaji(text):
    u"""Полуширинная катакана ROM -> латиница по Хепбёрну, слово с заглавной.

    ッ удваивает следующую согласную, ー тянет гласную повтором, малые
    гласные и я/ю/ё сливаются с предыдущим слогом; латиница и цифры
    остаются как есть."""
    s = unicodedata.normalize("NFKC", text)
    s = re.sub(r"([A-Za-z0-9]+)", r" \1 ", s)
    s = re.sub(r"!(?=\S)", "! ", s)
    words = []
    for word in s.split():
        out, double = "", False
        for ch in word:
            if ch in KANA:
                syl = KANA[ch]
                if double:
                    syl = ("t" if syl.startswith("ch") else syl[0]) + syl
                    double = False
                out += syl
            elif ch == u"ッ":
                double = True
            elif ch in SMALL_VOWEL:
                if out and out[-1] in "aiueo":
                    # ウィ -> wi: одна гласная уступает место w
                    bare = len(out) == 1 or out[-2] in "aiueon"
                    out = out[:-1] + ("w" if bare and out[-1] == "u" else "")
                out += SMALL_VOWEL[ch]
            elif ch in SMALL_Y:
                if out.endswith(("shi", "chi")):
                    out = out[:-1] + SMALL_Y[ch]
                elif out.endswith("ji"):
                    out = out[:-1] + SMALL_Y[ch]
                else:
                    out = out[:-1] + "y" + SMALL_Y[ch]
            elif ch == u"ー":
                out += next((c for c in reversed(out) if c in "aiueo"), "")
            else:
                out += ch
        words.append(out[:1].upper() + out[1:] if re.search(u"[\u30a0-\u30ff]", word) else out)
    return " ".join(words)


def mission_name(c, m):
    u"""Название миссии m главы c; пустое, если у оригинала его нет."""
    if c == 0:
        return u"Lesson %d" % m
    if c == 1:
        return romaji(ms.briefing_name(1, m))
    if c == 2:
        return romaji(dt.seq(DUEL_NAMES, 16)[m - 1].split(":", 1)[1])
    return u""


def s16(a):
    return struct.unpack_from(">h", ROM, a)[0]


def start_hook(st):
    u"""(победа по переписи разрешена, адреса расстановок) — обработчик
    входа на карту этапа st.

    Тела короткие и прямые (game-events.md, «Что делается при входе на
    карту»), так что хватает разобрать их коды подряд до `rts`. Незнакомый
    код — остановка: значит, тело устроено иначе, чем разобрано. В `bsr.w`
    не заходим, это местность и ﾒｶﾞｻﾞｳﾙｽ."""
    a = START_TABLE + u16(ROM, START_TABLE + 2 * st)
    allowed, placements, a6 = None, [], None
    while u16(ROM, a) != 0x4E75:                     # rts
        op = u16(ROM, a)
        if op == 0x4EB9:                             # jsr (xxx).l
            t = mt.U32(a + 2)
            if t in (ENABLE_WIPEOUT, DISABLE_WIPEOUT):
                allowed = t == ENABLE_WIPEOUT
            elif t == LOAD_PLACEMENT:
                placements.append(a6)
            a += 6
        elif op == 0x4DFA:                           # lea (d16,pc),a6
            a6 = a + 2 + s16(a + 2)
            a += 4
        elif op == 0x6100:                           # bsr.w
            a += 4
        elif op in (0x0280, 0x23C0):                 # andi.l #,d0 / move.l d0,(xxx).l
            a += 6
        else:
            raise AssertionError(u"этап %d: код $%04X по $%06X" % (st, op, a))
    assert allowed is not None, st
    return allowed, placements


def frame_goals(st):
    u"""[(цель, d7)] — тела целей, которые покадровый сценарий этапа st
    зовёт первым делом: `move.b #d7,d7`, затем `bsr.w` или `jsr`.

    Смотрим только до первого `rts`: сценарии лежат впритык, и за ним уже
    чужой — у этапа 45 весь сценарий это `rts` прямо перед этапом 51."""
    a = FRAME_TABLE + u16(ROM, FRAME_TABLE + 2 * st)
    out = []
    for o in range(a, a + 16, 2):
        if u16(ROM, o) == 0x4E75:
            break
        if u16(ROM, o) != 0x1E3C:
            continue
        c = o + 4
        if u16(ROM, c) == 0x6100:
            t = c + 2 + s16(c + 2)
        elif u16(ROM, c) == 0x4EB9:
            t = mt.U32(c + 2)
        else:
            continue
        if t in GOAL_BODIES:
            out.append((GOAL_BODIES[t], ROM[o + 3]))
    return out


def cond(kind, player=0, amount=0, parts=None):
    d = collections.OrderedDict([
        ("type", kind), ("target_player_id", player), ("target_unit_type", 0),
        ("target_amount", amount), ("target_x", 0), ("target_y", 0),
        ("radius", 0)])
    if parts is not None:
        d["conditions"] = parts
    return d


def goals(st):
    u"""(победа игрока 1, его поражение, что отложено).

    Вердикт оригинала — `$0166B2`, один на обоих с точки зрения игрока 1:
    навязанный исход, перепись игрока 1 пуста — поражение, перепись
    игрока 2 пуста — победа, если её не запретил вход на карту.
    У игрока 2 списки те же, только наоборот."""
    allowed, _ = start_hook(st)
    frame = frame_goals(st)
    win, lose, later = [], [cond(DESTROY_PLAYER, 1)], []
    for body, d7 in frame:
        if body == "herbivores":
            win.append(cond(HERBIVORES_REACH, 1, d7))
        elif body == "lose_if_gone":
            assert d7 == PONPON, (st, d7)
            later.append(u"поражение, если не осталось ﾎﾟﾝﾎﾟﾝ (тип 50)")
    if allowed:
        win.append(cond(DESTROY_PLAYER, 2))
    elif ("allow_if_gone", EMPTY_EGG) in frame:
        win.append(cond(ALL_OF, parts=[cond(DESTROY_PLAYER, 2),
                                       cond(EMPTY_EGGS_GONE)]))
    elif not win:
        # Этап 20: победу разрешает гибель ﾒｶﾞｻﾞｳﾙｽ (Species18Collapse), а
        # его марш к гнезду — поражение. У ремейка его нет, и пока цель
        # остаётся обычной, иначе миссию не выиграть.
        win.append(cond(DESTROY_PLAYER, 2))
        later.append(u"победу разрешает гибель ﾒｶﾞｻﾞｳﾙｽ, поражение — "
                     u"его приход к гнезду")
    assert all(b != "allow_if_gone" or d7 == EMPTY_EGG for b, d7 in frame), st
    return win, lose, later


def describe(c):
    kind = c["type"]
    if kind == DESTROY_PLAYER:
        return u"у игрока %d пусто" % c["target_player_id"]
    if kind == HERBIVORES_REACH:
        return u"травоядных у игрока %d не меньше %d" % (
            c["target_player_id"], c["target_amount"])
    if kind == EMPTY_EGGS_GONE:
        return u"пустых яиц не осталось"
    return u" и ".join(describe(p) for p in c["conditions"])


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

    # Сначала расстановка карты, затем то, что грузит вход на карту: так
    # идёт и сам StartMatch — LoadPlacement, потом RunStageStartHook.
    _allowed, extra = start_hook(st)
    records = mt.placement(pl)
    for a in extra:
        records += mt.placement(a, lo=0)

    nests = {1: [], 2: []}
    units = []
    for x, y, d, typ, pose in records:
        if (SKIP_ON >> types[y * W + x]) & 1:
            skipped[u"клетка типов 22…30"] += 1
            continue
        if typ == 1 or typ in (2, 3, 4):
            nests[1 if typ == 1 else 2].append({"x": x, "y": y})
            continue
        neutral = None
        if typ in MEAT:
            neutral = (typ - MEAT.start, "carcass")
        elif typ == BONES:
            neutral = (BONES_SPECIES - 1, "bones")
        elif typ == EMPTY_EGG:
            neutral = (0, "empty_egg")
        if neutral:
            units.append({"team_id": 0, "unit_type": neutral[0], "x": x,
                          "y": y, "facing": d, "pose": neutral[1]})
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

    win1, lose1, later = goals(st)
    players = []
    for team, money, avail, wth in ((1, bcd(r[0x34:0x38]), avail1, weathers1),
                                    (2, bcd(r[0x38:0x3C]), avail2,
                                     sorted(WEATHER_ITEMS))):
        first = nests[team][0] if nests[team] else {"x": -1, "y": -1}
        win, lose = (win1, lose1) if team == 1 else (lose1, win1)
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
        ("palette", r[0x4C]),
        ("starting_energy", players[0]["starting_energy"]),
        ("playable_margin", 1),
        ("tilemap", []),
        ("terrain_types", terrain),
        ("map_bytes", list(cells)),
        ("vegetation", veg),
        ("units", units),
        ("players", players),
    ])
    return doc, len(units), len(nests[2]), later


def write_json(path, doc, **kw):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, **kw)
        f.write("\n")


def main():
    root = out_path("export", "campaigns")
    if os.path.isdir(root):
        shutil.rmtree(root)            # всё здесь пишет только этот скрипт
    # Победу по переписи запрещают три этапа (game-mission-end.md); если
    # таблица входа скажет иное, разбор устарел.
    closed = [st for st in range(256) if not start_hook(st)[0]]
    assert closed == [20, 51, 222], closed
    recs = mt.gfx_records()
    skipped = collections.Counter()
    by_chapter = collections.defaultdict(list)
    for c, m, r in mt.missions():
        by_chapter[c].append((m, r))
    rows, special, n = [], [], 0
    for order, (folder, title, c) in enumerate(CAMPAIGNS, 1):
        for m, r in by_chapter[c]:
            n += 1
            doc, nunits, nests2, later = export_mission(c, m, r, recs, skipped)
            write_json(os.path.join(root, folder, "maps", str(m), "mission.json"),
                       doc, separators=(",", ":"))
            rows.append((folder, m, doc["name"], r[3], nunits, nests2,
                         doc["map"]["starting_energy"]))
            p1 = doc["map"]["players"][0]
            if later or [x["type"] for x in p1["victory_conditions"]] != [DESTROY_PLAYER]:
                special.append((folder, m, r[3],
                                u"; ".join(map(describe, p1["victory_conditions"])),
                                u"; ".join(map(describe, p1["defeat_conditions"])),
                                u"; ".join(later) or u"—"))
        write_json(os.path.join(root, folder, "campaign.json"),
                   collections.OrderedDict([("name", title), ("order", order),
                                            ("all_unlocked", True)]),
                   indent=2)
    with io.open(os.path.join(root, "report.md"), "w", encoding="utf-8",
                 newline="\n") as f:
        p = f.write
        p(u"# Миссии оригинала для ремейка\n\nСобрано `tools/exportmissions.py`.\n\n")
        p(u"## Не выгружено\n\n| что | записей |\n|---|---:|\n")
        for k, v in sorted(skipped.items()):
            p(u"| %s | %d |\n" % (k, v))
        p(u"\n## Цели\n\nУ остальных миссий победа — у игрока 2 пусто, поражение — "
          u"у игрока 1 пусто. Цели игрока 2 — те же, наоборот. «Отложено» — "
          u"правило оригинала, которое ждёт нейтралов ремейка (dyna #206, "
          u"часть 2); пока миссия идёт с обычной целью.\n\n"
          u"| кампания | № | этап | победа игрока 1 | поражение | отложено |\n"
          u"|---|---:|---:|---|---|---|\n")
        for row in special:
            p(u"| %s | %d | %d | %s | %s | %s |\n" % row)
        p(u"\n## Миссии\n\n| кампания | № | название | этап | юнитов | гнёзд у игрока 2 | деньги |\n"
          u"|---|---:|---|---:|---:|---:|---:|\n")
        for row in rows:
            p(u"| %s | %d | %s | %d | %d | %d | %d |\n" % row)
    print(u"миссий: %d в %d кампаниях -> %s" % (n, len(CAMPAIGNS),
                                              os.path.relpath(root, HERE)))
    for k, v in sorted(skipped.items()):
        print(u"  не выгружено: %s — %d" % (k, v))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
