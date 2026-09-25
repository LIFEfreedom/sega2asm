#!/usr/bin/env python3
"""Спецификация уровней (docs/mauimallard/levels.md) в JSON.

    python tools/levelspec.py            записать out/mauimallard/export/
    python tools/levelspec.py --check    только проверить
    python tools/levelspec.py --level 7  расстановка одного уровня по ролям
    python tools/levelspec.py --table    сводная таблица 23 уровней

Пишет:

* `levels.json` — общие правила (как кончается уровень, от чего гибнут,
  что переносится между уровнями, легенда местности) и сводку по каждому
  из 23 уровней; `levels.sources.json` — то же дерево с происхождением
  каждого числа (тот же механизм, что в `tools/specjson.py`);
* `levels/levelNN.json` — сам уровень для движка: сетка клеток (номер
  метатайла), метатайлы (четыре имени VDP), свойства метатайлов (профиль
  высоты, код местности, код порождения), профили высоты, фон 64x32,
  палитра и **расстановка объектов** с ролями;
* `levels/levelNN_tiles.png` — тайлы 8x8 по 32 в ряд, **индексами**:
  серый `17 * i` — цвет i ряда палитры, цвет 0 прозрачен. Ряд берётся из
  битов 13-14 имени VDP, отражения — из битов 11 и 12.

Объекты в игре не лежат отдельным списком: у каждого метатайла четвёртый
байт свойств — код порождения, и объект заводится, когда клетка въезжает
в окно камеры. Поэтому расстановка здесь не переписана, а снята с карты.
Роль объекта определяется по трём признакам, в таком порядке:
обработчик касания (подбираемое), конструктор (виды противников, боссы,
генераторы), процедура обновления (механизмы из `tools/objects.py`).
"""
import io
import json
import os
import struct
import sys
from collections import Counter, OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import enemies as E                                          # noqa: E402
import levels as L                                           # noqa: E402
import objects as O                                          # noqa: E402
import scroll as SC                                          # noqa: E402
import specjson as SJ                                        # noqa: E402
from paths import OUT                                        # noqa: E402
from specjson import D, V, at, dw, dl, hexa                  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM = L.ROM
U16, U32 = L.U16, L.U32
COUNT = 23
TERRAIN_PROPS = 0x1FCF14    # бит 0 — не пройти
TERRAIN_HANDLERS = 0x1FD014  # обработчик под игроком по коду местности
PASSWORDS = 0x1FCB26

WORLDS = [
    (u"THE MOJO MANSION", (0, 1, 2)),
    (u"NINJA TRAINING GROUNDS", (3, 4, 5, 6)),
    (u"MUDDRAKE MAYHEM", (7, 8, 9)),
    (u"THE SACRIFICE OF MAUI", (10, 11)),
    (u"THE TEST OF DUCKHOOD", (12, 13)),
    (u"THE FLYING DUCKMAN", (14, 15)),
    (u"THE REALM OF THE DEAD", (16, 17)),
    (u"MOJO STRONGHOLD", (18,)),
    (u"BABALUAU BABY (бонус)", (19, 20, 21, 22)),
]
BONUS_FROM = {2: 19, 9: 20, 13: 21, 17: 22}      # $2982A0

# Легенда кодов местности: что с кодом делает игра. Коды, которых на
# картах нет, сюда не попали; см. terrain.md и levels.md.
TERRAIN = OrderedDict([
    (0, u"пусто"),
    (1, u"лиана: утка хватается (состояние 5), не в воде"),
    (2, u"стена: не пройти"),
    (3, u"лиана, второй вид (ещё и бит 8 в +$30)"),
    (4, u"упор для толкаемого ящика ($2A30EE)"),
    (5, u"ВЫХОД с уровня: $FF1A6C = 1"),
    (7, u"опасная клетка: урон 25, кроме состояния 15"),
    (10, u"восходящий поток вправо: вверх до -$0900, вбок $0200"),
    (11, u"восходящий поток: вверх, к середине клетки"),
    (12, u"восходящий поток влево"),
    (13, u"шипы снизу: урон 25 и подброс -$0680"),
    (15, u"без обработчика у игрока"),
    (16, u"облик игрока: снять бит 10, палитра $288B80"),
    (20, u"разворот катящейся бочки ($29F9C2)"),
    (23, u"облик игрока: снять бит 10 и схватиться за лиану"),
    (28, u"стена (бит 1 никем не читается)"),
    (32, u"шипы сверху: урон 25 и сброс +$0800"),
    (33, u"пасть в земле: проверка на 16 ниже"),
    (34, u"пасть в земле: глотает падающего, урон 25, выплёвывает"),
])
for _c in range(0x28, 0x31):
    TERRAIN[_c] = u"склон, профиль %d из $1EAAE6" % (_c - 0x28)
for _c in range(0x3C, 0x44):
    TERRAIN[_c] = (u"полоса разгона: сила %d, %s" %
                   (_c & 3, u"вперёд" if _c < 0x40 else u"назад"))
for _c in (0x45, 0x46, 0x47, 0x48):
    TERRAIN[_c] = u"без обработчика у игрока (что делает — не установлено)"

# Подбираемое — по обработчику касания (вторая таблица уровня, +$24).
TOUCH = {
    0x29A0AE: ("weapon", u"ружьё жуков: открыт набор 0"),
    0x29A0E0: ("ammo1", u"жук-припас: запас 1 +16"),
    0x29A0EC: ("ammo2", u"жук-припас: запас 2 +16"),
    0x29A0F8: ("ammo3", u"жук-припас: запас 3 +16"),
    0x2A4998: ("heal_small", u"запас здоровья +25"),
    0x2A472E: ("heal_big", u"потолок и запас здоровья +50"),
    0x2A46D4: ("heal_full", u"запас здоровья до потолка"),
    0x2A4584: ("extra_life", u"жизнь +1, не больше 9"),
    0x29986A: ("fuel", u"топливо превращения +100"),
    0x2A4890: ("fuel_icon", u"топливо +100; значок гаснет и загорается "
                            u"снова, когда топлива меньше 100"),
    0x29988C: ("fuel_full", u"топливо превращения до 999"),
    0x2A4934: ("combo", u"серия ударов ниндзя +1, не больше 4"),
    0x2A45E6: ("treasure", u"мешок денег: $FF1352 +1, не больше 50"),
    0x2A4664: ("checkpoint", u"точка возврата"),
    0x29D318: ("spring", u"подкидывает падающего сверху: -$0800, "
                         u"состояние 18"),
    0x29A28C: ("hook", u"крюк: ниндзя повисает"),
    0x2A360E: ("hook", u"крюк: ниндзя повисает"),
    0x2A35CA: ("hook", u"крюк на колесе"),
    0x29FF0C: ("stack_item", u"предмет 0 в стопку бонусной игры"),
    0x29FF30: ("stack_item", u"предмет 1 в стопку бонусной игры"),
    0x29FF54: ("stack_item", u"предмет 2 в стопку бонусной игры"),
    0x29FF78: ("stack_item", u"предмет 3 в стопку бонусной игры"),
}
STUB = 0x2A526C

# Виды противников — по конструктору, номера как в enemy-catalog.md.
KINDS = {
    0x2A2E04: (1, "green_spirit"), 0x2A0DC4: (2, "spear_native"),
    0x29B95C: (3, "ninja_duck"), 0x2A2290: (4, "green_fish"),
    0x29DFC4: (5, "beetle"), 0x2A0DFC: (6, "boomerang_native"),
    0x29F47A: (7, "larva"), 0x2A0DE0: (8, "weight_native"),
    0x29F304: (9, "weight_native"), 0x29F2D6: (10, "spear_native"),
    0x2A144A: (11, "fire_spirit"), 0x2A0E2A: (12, "flying_insect"),
    0x29F320: (13, "boomerang_native"), 0x29F448: (14, "flying_insect"),
    0x29F53E: (15, "jumping_wedge"), 0x2A339C: (16, "fireball_native"),
    0x29DCA4: (17, "jumping_wedge"), 0x2A27DE: (18, "dark_fish"),
    0x2A344A: (19, "zombie"), 0x29E274: (20, "voodoo_mask"),
    0x29F162: (21, "small_insect"), 0x2A2C02: (22, "fireball_native"),
    0x2A33DE: (23, "zombie"), 0x29E06E: (24, "butler"),
    0x2A0EDE: (25, "red_drop"), 0x2A1822: (26, "tnt_barrel"),
    0x2A1BC4: (27, "blue_crate"), 0x2A1C06: (28, "mine"),
    0x29DFDA: (29, "beetle"), 0x29F2F2: (31, "spear_native"),
    0x29FB6A: (32, "dark_weight"), 0x2A0E18: (33, "boomerang_native"),
    0x2A3438: (34, "zombie"),
}
# Бит 2 в +$31 ставят ровно эти четыре: при гибели роняют жетон бонуса
# ($299CF8 / $2AB21C -> $299D70, код касания 34 -> $299DC8).
TOKEN = {0x29DFDA: "$29DFE4", 0x29F2F2: "$29F2F6", 0x2A0E18: "$2A0E1C",
         0x2A3438: "$2A343C"}
BOSSES = {
    0x29E47A: ("boss", u"шаман (бой 4.1 behavior.md)"),
    0x2A0E6C: ("boss", u"огненные змеи (бой 4.3)"),
    0x2A7FA0: ("boss", u"летучий корабль (бой 4.4)"),
    0x2A0A4A: ("boss", u"страж уровня 13: голова $2A6E40 и три шеста "
                       u"по эллипсам (не разобран)"),
}
GENERATORS = set([0x29E698, 0x29E6A2, 0x29E6AC, 0x2A163C, 0x29D12C,
                  0x29DFEC, 0x29E55E] +
                 list(range(0x29B7A4, 0x29B893)))
EXIT_UPDATE = 0x29C6C2
# Механизмы облика игрока — по конструктору (behavior.md, 1.7 и 1.8).
FORM_OBJECTS = {
    0x29F33C: ("shrinker", u"колдун: облачко в 42 точках впереди уменьшает "
                           u"утку или возвращает рост ($29F410)"),
    0x29A4A4: ("brace_post", u"опора для распора ниндзя; рушится через 66 "
                             u"тактов после распора"),
}


def load_groups():
    rows, _none, _tot = O.groups()
    by_ctor = {}
    for r in rows:
        for h in r["h"]:
            by_ctor[h] = r
    return by_ctor


GROUPS = None


def role_of(ctor, touch):
    """-> (роль, подпись, подробности) для одного объекта."""
    global GROUPS
    if touch in TOUCH:
        r, what = TOUCH[touch]
        return r, what, {}
    if ctor in BOSSES:
        return BOSSES[ctor][0], BOSSES[ctor][1], {}
    if ctor in KINDS:
        num, key = KINDS[ctor]
        extra = {"kind": num, "spec": key}
        if ctor in TOKEN:
            extra["drops_bonus_token"] = True
        return ("enemy" if num < 25 or num > 28 and num != 32
                else "destructible"), key, extra
    if ctor in FORM_OBJECTS:
        return FORM_OBJECTS[ctor][0], FORM_OBJECTS[ctor][1], {}
    if ctor in GENERATORS:
        return "generator", u"выпускает бойцов (enemy-catalog.md)", {}
    if GROUPS is None:
        GROUPS = load_groups()
    g = GROUPS.get(ctor)
    if g is None:
        if ctor in O.CTORS:
            return "static", O.CTORS[ctor][0], {}
        return "static", u"без процедуры обновления", {}
    upd = tuple(g["upd"])
    if EXIT_UPDATE in upd:
        return "exit", u"выход с уровня", {}
    name = O.name_of(g)
    if upd == (0x2A4A7A,):
        return "decoration", name or u"украшение", {}
    return "mechanism", name or u"[%s] %s" % (g["kind"], ", ".join(g["fp"])), \
        {"update": [hexa(u) for u in upd]}


# ------------------------------------------------------------ сдвиг

def spawn_offset(ctor, depth=0):
    """Сдвиг места рождения, который конструктор прибавляет к углу клетки.

    Читает команды конструктора до вызова `loc_29974C` и складывает
    непосредственные прибавки к `d1` (X) и `d2` (Y); в помощник, если он
    вызван раньше, заходит один раз.
    """
    dx = dy = 0
    a = ctor
    for _ in range(12):
        t = E.BY.get(a)
        if t is None:
            break
        if "loc_29974C" in t or "loc_299780" in t or t.startswith("rts"):
            return dx, dy
        if t.startswith(("bsr", "jsr")) and depth == 0:
            tgt = E.TARGET.search(t)
            if tgt:
                sx, sy = spawn_offset(int(tgt.group(1), 16), 1)
                return dx + sx, dy + sy
        for reg, is_x in (("d1", True), ("d2", False)):
            if t.endswith("," + reg):
                v = None
                if t.startswith(("addq.w", "addi.w")):
                    v = SJ._operand(t, None, True)
                elif t.startswith(("subq.w", "subi.w")):
                    v = -SJ._operand(t, None, True)
                if v is not None:
                    if is_x:
                        dx += v
                    else:
                        dy += v
        a = E.NEXT.get(a)
        if a is None:
            break
    return dx, dy


# ------------------------------------------------------------ уровень

def level_map(n):
    """Сетки и таблицы уровня -> словарь (без происхождения)."""
    g = L.gfx(n)
    d, pr = g["map_data"], L.props(g)
    mw, mh = struct.unpack_from(">HH", d, 0)
    cells = [[struct.unpack_from(">H", d, 4 + (y * mw + x) * 2)[0] // 8
              for x in range(mw)] for y in range(mh)]
    meta = L.metatiles(g)
    prof = U32(L.record(n) + 4)
    used = sorted(set(p[0] for p in pr if p[0]))
    bg = g["bg_data"]
    bw, bh = struct.unpack_from(">HH", bg, 0)
    pal = []
    pa = U32(L.record(n))
    for i in range(64):
        v = struct.unpack_from(">H", ROM, pa + 2 * i)[0]
        pal.append(v)
    return {
        "size_cells": [mw, mh], "cell_px": 16,
        "cells": cells,
        "metatiles": [list(m) for m in meta],
        "metatile_props": [{"profile": p[0], "terrain": p[1],
                            "spawn": p[2]} for p in pr[:len(meta)]],
        "profiles": {str(o): list(ROM[prof + o:prof + o + 16])
                     for o in used},
        "profile_table": hexa(prof),
        "background_names": [[struct.unpack_from(
            ">H", bg, 4 + (y * bw + x) * 2)[0] for x in range(bw)]
            for y in range(bh)],
        "palette_cram": pal,
        "tiles": len(g["tiles_data"]) // 32,
    }, g, pr, cells


def placements(n, pr, cells):
    """Все объекты карты: клетка, код, конструктор, касание, роль."""
    rec = L.record(n)
    sp, to = U32(rec + 0x20), U32(rec + 0x24)
    out = []
    offs = {}
    for cy, row in enumerate(cells):
        for cx, m in enumerate(row):
            code = pr[m][2]
            if not code:
                continue
            ctor, touch = U32(sp + 4 * code), U32(to + 4 * code)
            role, what, extra = role_of(ctor, touch)
            if ctor not in offs:
                offs[ctor] = spawn_offset(ctor)
            ox, oy = offs[ctor]
            o = OrderedDict([
                ("cell", [cx, cy]),
                ("x", cx * 16 + ox), ("y", cy * 16 + oy),
                ("code", code), ("ctor", hexa(ctor)),
                ("touch", hexa(touch) if touch != STUB else None),
                ("role", role), ("what", what)])
            o.update(extra)
            out.append(o)
    return out


def terrain_counts(pr, cells):
    c = Counter()
    for row in cells:
        for m in row:
            c[pr[m][1]] += 1
    return c


def level_proc_notes():
    """Что делает процедура уровня `+$2C` — прочитано по телу каждой."""
    return {
        0x2A5F6A: u"облик игрока (бит 10), $FF216E = 1; линия воды у дна "
                  u"минус $1C и растровая подмена палитры ($295C86); дно "
                  u"камеры $234; два поплавка на линии воды ($2A5EC6)",
        0x2A5FAC: u"выше Y $360 — тёмные комнаты: обработчик $29C9BA и "
                  u"палитра $225F9C; ниже — облик игрока (бит 10); линия "
                  u"воды у дна минус $18; тень и подсветка VDP ($8C89)",
        0x2A6454: u"ничего (один rts)",
        0x2A5F5E: u"после победы — сцена $28E9C6 ($FF1360)",
        0x2A61A2: u"бой школы ниндзя (behavior.md 4.2)",
        0x2A6014: u"$FF213E = 0 (тёмный груз ещё не катит)",
        0x2A605A: u"маска левого края для поколоночной прокрутки ($298F60)",
        0x2A6066: u"маска левого края; ЛАВА: линия $FF1390 от дна, "
                  u"поднимается на точку раз в 4 кадра, растровый "
                  u"градиент $295CAA, гул $9B",
        0x2A6042: u"маска левого края для поколоночной прокрутки",
        0x2A604E: u"маска левого края; зона $FF1380-$FF138A и объект "
                  u"$2A06FA ($2A07A4)",
        0x2A612E: u"источник корабельных звуков $5F/$60/$66 раз в 192-255 "
                  u"кадров ($2A60A8)",
        0x2A611E: u"$FF2150 = 1, $FF2222 = 0",
        0x2A6134: u"растровая подмена палитры $295C98; вязкость $FF2131 "
                  u"= 1, пока игрок левее $510 и выше $E0 ($2A3188)",
        0x2A6154: u"ничего (один rts)",
        0x2A6156: u"последний бой: отступ камеры, бесконечное топливо, "
                  u"арена и босс (behavior.md 4.5)",
        0x2A601C: u"бонус: игроку состояние $2C и скрипт $1D7732 (танец), "
                  u"стопка предметов пуста",
    }


def password_for(n):
    """Пароль, который ведёт НА уровень n: слово таблицы + 1 == n."""
    for i in range(7):
        w = U16(PASSWORDS + 6 * i)
        if w + 1 == n:
            p = U32(PASSWORDS + 6 * i + 2)
            return D(ROM[p:p + 6].decode("ascii"),
                     u"таблица паролей: слово %d + 1" % w,
                     dw(PASSWORDS + 6 * i))
    return None


def world_of(n):
    for i, (name, lv) in enumerate(WORLDS):
        if n in lv:
            return i, name
    return None, None


def level_facts(n, pl, tc, size):
    r = L.record(n)
    proc = U32(r + 0x2C)
    wi, wn = world_of(n)
    notes = level_proc_notes()
    h, v, bg = U32(r + 0x0C), U32(r + 0x10), U32(r + 0x14)
    roles = Counter(p["role"] for p in pl)
    enemies = Counter(p["what"] for p in pl if p["role"] == "enemy")
    items = Counter(p["role"] for p in pl if p["role"] in (
        "weapon", "ammo1", "ammo2", "ammo3", "heal_small", "heal_big",
        "heal_full", "extra_life", "fuel", "fuel_icon", "fuel_full",
        "combo", "treasure", "checkpoint", "stack_item"))
    exits_tiles = tc.get(5, 0)
    exits_obj = roles.get("exit", 0)
    ends = []
    if exits_tiles:
        ends.append(u"клетка выхода (код 5): %d" % exits_tiles)
    if exits_obj:
        ends.append(u"объект выхода $29C6C2: %d" % exits_obj)
    boss = {2: u"шаман", 6: u"школа ниндзя", 10: u"огненные змеи",
            13: u"страж уровня 13", 15: u"летучий корабль",
            18: u"последний бой"}.get(n)
    if boss:
        ends.append(u"победа над боссом: %s" % boss)
    if n == 9:
        ends.append(u"арена: бойцов не осталось -> 121 кадр, звук $7C, "
                    u"ещё 91 кадр ($29EDA0)")
    if n == 17:
        ends.append(u"идол вернулся домой ($2A2DBC)")
    if n >= 19:
        ends.append(u"стопка предметов опустела ($2A000C)")
    f = OrderedDict([
        ("index", n),
        ("name", L.title_text(n)),
        ("world", wi), ("world_name", wn),
        ("record", hexa(r)),
        ("map_cells", [size[0], size[1]]),
        ("map_px", [size[0] * 16, size[1] * 16]),
        ("start_px", {"x": dw(r + 0x36), "y": dw(r + 0x38)}),
        ("music", dw(r + 0x3C, signed=False)),
        ("scroll", {
            "vdp_reg11": dw(r + 0x34, signed=False),
            "horizontal": SC.HSCROLL.get(h, (u"?", u"?"))[1],
            "vertical": SC.VSCROLL.get(v, (u"?", u"?"))[1],
            "background": SC.BG.get(bg, hexa(bg))}),
        ("sticky", dw(r + 0x3E)),
        ("cutscene_after", dw(r + 0x40)),
        ("tile_animation", dw(r + 0x3A)),
        ("palette_animation", dl(r + 0x1C, addr=True)
         if U32(r + 0x1C) else None),
        ("spawn_table", dl(r + 0x20, addr=True)),
        ("touch_table", dl(r + 0x24, addr=True)),
        ("level_proc", dl(r + 0x2C, addr=True)),
        ("level_proc_does", notes.get(proc, u"не прочитано")),
        ("password_to_here", password_for(n)),
        ("bonus_after", BONUS_FROM.get(n)),
        ("boss", boss),
        ("ends_by", ends),
        ("objects_total", len(pl)),
        ("roles", dict(sorted(roles.items()))),
        ("enemies", dict(sorted(enemies.items()))),
        ("items", dict(sorted(items.items()))),
        ("bonus_token_carriers", [p["what"] for p in pl
                                  if p.get("drops_bonus_token")]),
        ("terrain", {str(k): tc[k] for k in sorted(tc) if k}),
    ])
    return f


# ------------------------------------------------------------ правила

def rules():
    return OrderedDict([
        ("level_end", {
            "signal": u"$FF1A6C: +1 пройден, -1 гибель ($298AB8, $298120)",
            "exit_tile_code": D(5, u"код местности 5 -> $2A4AF8",
                                dl(TERRAIN_HANDLERS + 4 * 5, addr=True)),
            "exit_object_update": hexa(EXIT_UPDATE),
            "last_level": D(18, u"cmpi.w #$12 в $298186",
                            at(0x298180, "cmpi.w #$0012,d1")),
        }),
        ("death", {
            "health_zero": u"$298CDE",
            "fall_below_camera_bottom": D(True, u"Y ниже $FF1A92 -> -1",
                                          at(0x2A4E90, "move.w #$FFFF,"
                                             "($FF1A6C).l", span=0x40,
                                             value=True)),
            "rising_liquid": u"$2A179A: игрок ниже $FF1390 (уровень 11)",
            "idol_lost": u"$2A2FDE (уровень 17)",
            "countdown_ff214a": u"$2994A8: таймер $FF214A кончился, а "
                                u"игрок правее $A8; где заводится "
                                u"($29BE7C) — не установлено",
        }),
        ("respawn", {
            "checkpoint_touch": hexa(0x2A4664),
            "respawn_point": u"$FFFFFD86 (X, Y); побеждает старт +$36",
            "cleared_on": u"проход уровня ($298148), продолжение "
                          u"($2983C2)",
        }),
        ("reset_2983E2", {
            "what": u"жетон бонуса $FF1350, топливо $FF133E, выбранный "
                    u"набор $FF1A1E = -1, запасы $FF1A22-$FF1A26, ружьё "
                    u"$FF1A20, мешки $FF1352, форма $FF133A",
            "when": u"новая игра ($29804C); конец мира — уровень с +$40 "
                    u"($2981A2); вход в бонус ($2982AA); гибель при "
                    u"оставшихся жизнях ($29837A, но ружьё $FF1A20 "
                    u"сохраняется); перезапуск ($29823A)",
            "on_death_also": u"запас здоровья и потолок = начальный "
                             u"$FF134A; серия ниндзя $FF1356 -1",
        }),
        ("password", {
            "shown_if_treasures_ge": D(12, u"cmpi.w #$000C в $2905EE",
                                       at(0x2905EE,
                                          "cmpi.w #$000C,($FF1352).l")),
            "where": u"заставка после мира ($290494 -> $2905EE)",
            "table": hexa(PASSWORDS),
        }),
        ("bonus", {
            "token_code": D(34, u"код касания 34 -> $299DC8"),
            "token_sets": u"$FF1350 = 1",
            "entered_from": {str(k): v for k, v in BONUS_FROM.items()},
            "switch": u"$2982A0 после уровня с +$40",
        }),
        ("spawning", {
            "by": u"байт +3 свойств метатайла -> таблица +$20 уровня",
            "on_death": u"убитый не возвращается до перезахода "
                        u"(loc_299CF8 стирает +$29, +$2A)",
            "off_screen": u"ушедший с экрана разбирается и появится "
                          u"снова, когда клетка опять въедет в окно "
                          u"(ObjectReleaseCell)",
        }),
        ("terrain_legend", {str(k): OrderedDict([
            ("what", v),
            ("solid", D(ROM[TERRAIN_PROPS + k] & 1,
                        u"бит 0 в $1FCF14", SJ.db(TERRAIN_PROPS + k))),
            ("player_handler", dl(TERRAIN_HANDLERS + 4 * k, addr=True))])
            for k, v in TERRAIN.items()}),
    ])


# ------------------------------------------------------------ вывод

def tiles_png(n, g, path):
    t = g["tiles_data"]
    cnt = len(t) // 32
    cols = 32
    rows = (cnt + cols - 1) // cols
    w, h = cols * 8, rows * 8
    buf = [None] * (w * h)
    for i in range(cnt):
        ox, oy = (i % cols) * 8, (i // cols) * 8
        for y in range(8):
            for xb in range(4):
                b = t[i * 32 + y * 4 + xb]
                for half, c in ((0, b >> 4), (1, b & 15)):
                    buf[(oy + y) * w + ox + xb * 2 + half] = (
                        (17 * c, 17 * c, 17 * c, 255 if c else 0))
    L.S.png(path, w, h, buf)


def build(write):
    tree = OrderedDict([("rules", rules()), ("levels", [])])
    outdir = os.path.join(OUT("export"), "levels")
    if write and not os.path.isdir(outdir):
        os.makedirs(outdir)
    for n in range(COUNT):
        m, g, pr, cells = level_map(n)
        pl = placements(n, pr, cells)
        tc = terrain_counts(pr, cells)
        tree["levels"].append(level_facts(n, pl, tc, m["size_cells"]))
        if write:
            m["objects"] = pl
            m["level"] = n
            m["tiles_png"] = "level%02d_tiles.png" % n
            p = os.path.join(outdir, "level%02d.json" % n)
            with io.open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(m, ensure_ascii=False,
                                   separators=(",", ":")))
                f.write(u"\n")
            tiles_png(n, g, os.path.join(outdir, m["tiles_png"]))
    return tree


def do_level(n):
    _m, _g, pr, cells = level_map(n)
    pl = placements(n, pr, cells)
    c = Counter((p["role"], p["what"]) for p in pl)
    print(u"уровень %d, %s: объектов %d" % (n, L.title_text(n), len(pl)))
    for (role, what), k in sorted(c.items(), key=lambda kv: (kv[0][0],
                                                               -kv[1])):
        print(u"  %4d  %-12s %s" % (k, role, what))


def do_table():
    for n in range(COUNT):
        m, _g, pr, cells = level_map(n)
        pl = placements(n, pr, cells)
        tc = terrain_counts(pr, cells)
        f = level_facts(n, pl, tc, m["size_cells"])
        vals, _src = SJ.split(f)
        print(json.dumps(vals, ensure_ascii=False))


def main():
    a = sys.argv[1:]
    if a[:1] == ["--level"]:
        do_level(int(a[1]))
        return 0
    if a[:1] == ["--table"]:
        do_table()
        return 0
    write = "--check" not in a
    tree = build(write)
    if SJ.ERRORS:
        for e in SJ.ERRORS:
            print(u"ошибка: %s" % e)
        return 1
    vals, srcs = SJ.split(tree)
    if not write:
        print(u"проверено чисел: %d" % SJ.count(tree))
        return 0
    out = OUT("export")
    meta = OrderedDict([
        ("game", "Maui Mallard in Cold Shadow (Mega Drive)"),
        ("generator", "tools/levelspec.py"),
        ("spec", "docs/mauimallard/levels.md"),
        ("coords", u"пиксели мира, клетка 16x16; объект: x, y — угол "
                   u"клетки плюс сдвиг, который прибавляет его "
                   u"конструктор"),
        ("maps", u"levels/levelNN.json и levels/levelNN_tiles.png")])
    doc = OrderedDict([("meta", meta)])
    doc.update(vals)
    for name, data in (("levels.json", doc), ("levels.sources.json", srcs)):
        p = os.path.join(out, name)
        with io.open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=1))
            f.write(u"\n")
        print(p)
    print(u"уровней %d, чисел с происхождением %d" % (COUNT,
                                                    SJ.count(tree)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
