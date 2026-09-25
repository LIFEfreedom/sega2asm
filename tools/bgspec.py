#!/usr/bin/env python3
"""Камера и слои фона Maui Mallard для движка ремейка.

    python tools/bgspec.py              сводка: камера и фон по 23 уровням
    python tools/bgspec.py --level 16   один уровень целиком (JSON)

Сам инструмент ничего не пишет: его зовёт `tools/levelspec.py`, и камера
ложится в `levels.json` (`rules.camera`), а фон — в запись каждого уровня
(`background`, `effects`). Числа прочитаны из ROM тем же механизмом, что в
`tools/specjson.py`: `at()` ищет команду в листинге, `dw()`/`dl()` читают
данные, `D()` — вывод с формулой. Спецификация —
docs/mauimallard/scrolling.md.

Условности (они же в `meta` выгрузки):

* плоскость B — фон, плоскость A — карта уровня;
* по X: `hscroll = k * camX + drift * t (+ волна)` — значение
  горизонтальной прокрутки VDP, плюс сдвигает картинку ВПРАВО; у карты
  `k = -1`, у фона от 0 до -2;
* по Y: `vscroll = k * camY + drift * t (+ волна)` — значение вертикальной
  прокрутки VDP, плюс сдвигает картинку ВВЕРХ; у карты `k = 1`;
* `t` — счётчик кадров `$FFFFE196`, камера — вместе с тряской
  (`$FFFFE1BC`/`$FFFFE1BE`); деления — сдвигом, то есть с округлением вниз;
* волна: `amp * cos(2pi * (phase_f * t + phase_step * i) / 1024)`, где i —
  номер строки или столбца в полосе, таблица косинуса `$1EAF94`.
"""
import os
import struct
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import specjson as SJ                                        # noqa: E402
from specjson import D, V, at, dw, dl, hexa, ok              # noqa: E402

ROM = SJ.ROM
COS = 0x1EAF94


def U16(a):
    return struct.unpack_from(">H", ROM, a)[0]


def U32(a):
    return struct.unpack_from(">I", ROM, a)[0]


def frac(num, den, why, *src):
    return D(float(num) / den, why, *src)


def count(x, add=1):
    """`moveq #n` / `move.w #n` под `dbf`: повторов n + 1."""
    return D(x.v + add, u"dbf: n + 1", x) if ok(x) else x


def band(frm, to, k, drift=None, wave=None, note=None):
    b = OrderedDict([("from", frm), ("to", to), ("k", k)])
    b["drift_px_f"] = drift if drift is not None else D(0, u"без дрейфа")
    if wave:
        b["wave"] = wave
    if note:
        b["note"] = note
    return b


def wave(amp, phase_f, step, period):
    return OrderedDict([("amp_px", amp), ("phase_f", phase_f),
                        ("phase_step", step), ("period_f", period)])


def cos_amp(shift_cmd, bits):
    """Размах `cos * 2**bits >> 16` при косинусе с размахом $7FFF."""
    if not ok(shift_cmd):
        return shift_cmd
    return D(0x7FFF * (1 << bits) // 65536,
             u"$7FFF * 2**%d / 65536, вниз до целого" % bits, shift_cmd)


# ------------------------------------------------------------ камера

def camera():
    step = 0x297748
    vstep = 0x297870
    return OrderedDict([
        ("entry", OrderedDict([
            ("offset_x_facing_right_px",
             at(0x2976B2, "move.w #$0069,($FF1322).l")),
            ("offset_x_facing_left_px",
             at(0x2976B2, "subi.w #$00D7,d0")),
            ("offset_y_px", at(0x2976B2, "subi.w #$007C,d0")),
            ("note", u"камера ставится сразу, без подъезда; зажим — "
                     u"размером уровня, а не пределами"),
        ])),
        ("target", OrderedDict([
            ("x", u"игрок X - $FF1322, при взгляде влево игрок X - 320 + "
                  u"$FF1322; зажать пределами $FF1A8C..$FF1A8E - 320"),
            ("y", u"игрок Y - 124; зажать $FF1A90..$FF1A92 - 224"),
            ("offset_x_px", at(0x2976B2, "move.w #$0069,($FF1322).l")),
            ("offset_x_level18_px",
             at(0x2A6156, "move.w #$0048,($FF1322).l")),
            ("offset_y_px", at(vstep, "subi.w #$007C,d0")),
        ])),
        ("step", OrderedDict([
            ("dead_zone_x_px", at(step, "cmpi.w #$000C,d1")),
            ("dead_zone_y_px", at(vstep, "cmpi.w #$0004,d1")),
            ("chase_div", D(16, u"lsr.w #4: промах / 16",
                            at(step, "lsr.w #4,d1"))),
            ("accel_px_f2", at(step, "moveq #1,d2")),
            ("brake_px_f2", at(step, "move.w #$0001,d2")),
            ("y_no_player_cap_if_chase_le",
             at(vstep, "cmpi.w #$0002,d1")),
            ("y_skip_if_player_below_bottom_minus_px",
             at(vstep, "subi.w #$0010,d1")),
            ("rule", u"мёртвая зона — только при нулевой скорости; знак "
                     u"скорости разошёлся со знаком промаха — скорость "
                     u"к нулю на 1; иначе желаемая = max(промах / 16, "
                     u"сдвиг игрока с прошлого замера), к ней по 1 за "
                     u"кадр; по Y ограничение сдвигом игрока не "
                     u"действует, пока промах / 16 <= 2"),
            ("player_speed_note", u"сдвиг игрока меряется от $FF1318 "
                                  u"(по Y $FF131A), а замер обновляется "
                                  u"только в ветке «догоняем»"),
        ])),
        ("shake", OrderedDict([
            ("axis", u"только Y: $FF131E прибавляется к камере на один "
                     u"кадр и гасится; итог по Y не меньше 0"),
            ("pattern", u"кадры с t % 4 == 2 — вверх на размах, "
                        u"остальные — 0"),
            ("period_f", D(4, u"andi #1 и andi #2 кадрового счётчика",
                           at(0x2995D0, "andi.w #$0002,d0"))),
            ("steady", u"$2995D0: размах $FF04D2 перезаряжается из "
                       u"$FF04D4 — трясёт, пока не снимут"),
            ("decaying", u"$2926DC: размах -1 за каждый толчок, снимается "
                         u"сам"),
            ("sources", [
                OrderedDict([("where", u"уровень 3: сломан четвёртый "
                                       u"объект кода 164 ($29BDCC)"),
                             ("kind", "steady"),
                             ("amp_px", u"$FF214C / 16: от 20 к 0 по "
                                        u"мере отсчёта ($299500)"),
                             ("also", u"вертикаль камеры замерзает "
                                      u"($FF1327), таймеры $FF2148-$FF214C, "
                                      u"звук $9B")]),
                OrderedDict([("where", u"уровень 17: идол всплывает "
                                       u"($2A2D84)"),
                             ("kind", "steady"),
                             ("amp_px", at(0x2A2D84,
                                           "move.w #$0002,($FF04D4).l",
                                           span=0x10))]),
                OrderedDict([("where", u"$29B4C8: тяжёлый объект "
                                       u"приземлился (звук $0B)"),
                             ("kind", "decaying"),
                             ("amp_px", at(0x29B4C8,
                                           "move.w #$0004,($FF04D2).l",
                                           span=0x10))]),
                OrderedDict([("where", u"$2A66EC: порождает три "
                                       u"предмета над игроком (x, x ± 64)"),
                             ("kind", "decaying"),
                             ("amp_px", at(0x2A66EC,
                                           "move.w #$0006,($FF04D2).l",
                                           span=0x10))]),
            ]),
        ])),
        ("freeze", OrderedDict([
            ("x", u"$FF1326: горизонталь стоит (выброс игрока $2A2530)"),
            ("y", u"$FF1327: вертикаль стоит (землетрясение уровня 3, "
                  u"$29BE9C)"),
        ])),
        ("dead_modes", u"$FF1320 (игрок в центре, 160) и $FF1324 "
                       u"(вертикаль к низу арены) при входе гасятся и "
                       u"больше нигде не пишутся"),
        ("limits", OrderedDict([
            ("init", u"левый и верхний 0, правый и нижний — размер уровня "
                     u"($29866A)"),
            ("fall_death", u"игрок ниже нижнего предела — гибель "
                           u"($2A4EA6)"),
            ("events", limit_events()),
        ])),
    ])


def limit_events():
    return [
        OrderedDict([
            ("level", 2), ("object", "$29E4FC"),
            ("trigger", u"игрок выше объекта"),
            ("bottom_start_px", at(0x29E524, "move.w #$0200,($FF1A92).l")),
            ("bottom_step_px_f", D(-8, u"subq.w #8",
                                   at(0x29E524, "subq.w #8,d0"))),
            ("bottom_end_px", at(0x29E524, "cmpi.w #$00F0,d0"))]),
        OrderedDict([
            ("level", 5), ("object", "$29C018"),
            ("trigger_x_px", D(0x0BB0 + 0x40, u"$0BB0 + $40",
                               at(0x29C036, "subi.w #$0BB0,d0"),
                               at(0x29C036, "cmpi.w #$0040,d0"))),
            ("left_start", u"камера X - 32"),
            ("left_step_px_f",
             at(0x29C42C, "addi.w #$0002,($FF1A8C).l", span=0x20)),
            ("left_end_px", at(0x29C3FA, "move.w #$0BB0,d0", nth=0))]),
        OrderedDict([
            ("level", 9), ("object", "$29E55E"),
            ("trigger", u"игрок в полосе высот у объекта"),
            ("top_bottom_px", [D(0, u"старшее слово move.l",
                                 at(0x29E586, "move.l #$000000E0,"
                                    "($FF1A90).l", span=0x40, part="hi")),
                               at(0x29E586, "move.l #$000000E0,"
                                  "($FF1A90).l", span=0x40, part="lo")]),
            ("then_at_x_le_px", at(0x29E586, "cmpi.w #$01F0,d0", span=0x60)),
            ("left_right_px", [at(0x29E586, "move.l #$00200230,"
                                  "($FF1A8C).l", span=0x60, part="hi"),
                               at(0x29E586, "move.l #$00200230,"
                                  "($FF1A8C).l", span=0x60, part="lo")]),
            ("sound", at(0x29E586, "pea ($000054).w", span=0xC0))]),
        OrderedDict([
            ("level", 13), ("object", u"зона воды $2A06FA"),
            ("trigger_x_px", at(0x2A06FA, "cmpi.w #$0CE0,d0", span=0x10)),
            ("left_start", u"камера X"),
            ("left_step_px_f", D(2, u"addq.w #2",
                                 at(0x2A077E, "addq.w #2,d0", span=8))),
            ("left_end_px", at(0x2A0722, "move.w #$0CA0,$4C(a0)", span=8))]),
        OrderedDict([
            ("level", 17), ("object", u"процедура фона $2A5B9E"),
            ("trigger", u"идол взвёл $FF2150"),
            ("bottom_step_px", D(-1, u"subq.w #1",
                                 at(0x2A5B9E, "subq.w #1,($FF1A92).l"))),
            ("bottom_every_f", D(4, u"moveq #3 / and",
                                 at(0x2A5B9E, "moveq #3,d0"))),
            ("bottom_end_px", at(0x2A5B9E, "cmpi.w #$00F0,d0"))]),
    ]


# ------------------------------------------------------------ фон

def h(unit, bands, note=None):
    d = OrderedDict([("unit", unit), ("bands", bands)])
    if note:
        d["note"] = note
    return d


def v_fixed():
    return h("whole", [band(0, 0, D(0, u"слово 1 VSRAM за кадр не пишут: "
                                        u"$2A55B2 кладёт только плоскость "
                                        u"A"))])


def bg_mansion():
    p = 0x2A5C56
    half = frac(-1, 2, u"-camX, asr #1", at(p, "asr.w #1,d3"))
    acc = [at(p, "move.l #$00008000,d1"), at(p, "move.w #$4000,d1"),
           at(p, "move.w #$2000,d1")]
    dr = [D(-a.v / 65536.0, u"накопитель 16.16 вычитается: картинка "
                           u"влево", a) for a in acc]
    r0 = count(at(p, "moveq #7,d0"))
    r1 = count(at(p, "moveq #2,d0", nth=0))
    r2 = count(at(p, "moveq #2,d0", nth=1))
    r3 = count(at(p, "moveq #17,d0"))
    a, b, c = r0.v, r0.v + r1.v, r0.v + r1.v + r2.v
    return OrderedDict([
        ("h", h("row8", [band(0, a - 1, half, dr[0]),
                         band(a, b - 1, half, dr[1]),
                         band(b, c - 1, half, dr[2]),
                         band(c, c + r3.v - 1, half)],
                u"четвёртый накопитель (+$1000) считается, но не "
                u"читается")),
        ("v", v_fixed())])


def bg_ninja():
    p = 0x2A5C1C
    top = count(at(p, "moveq #19,d2"))
    d0 = D(0.25, u"t asr 2", at(p, "asr.w #2,d1"))
    d1 = D(0.125, u"ещё asr 1", at(p, "asr.w #1,d1", nth=0))
    d2 = D(0.0625, u"ещё asr 1", at(p, "asr.w #1,d1", nth=1))
    step = at(p, "asr.w #3,d0")
    n = count(at(p, "moveq #9,d2"))
    bands = [band(0, top.v - 1, D(0, u"камеры нет"), d0),
             band(top.v, top.v, D(0, u"камеры нет"), d1),
             band(top.v + 1, top.v + 1, D(0, u"камеры нет"), d2)]
    for j in range(n.v):
        r = top.v + 2 + j
        bands.append(band(r, r, frac(-j, 8, u"j * (-camX asr 3), j = 0..9",
                                     step)))
    return OrderedDict([
        ("h", h("row8", bands, u"ряды 0-21 от камеры не зависят; нижние "
                               u"ряды — «пол» с растущей долей камеры")),
        ("v", v_fixed()),
        ("event", OrderedDict([
            ("every_f", at(0x2A5972, "cmpi.w #$021C,d0")),
            ("palette_once", dl(0x2A5990 + 2, addr=True)),
            ("what", u"раз в 540 кадров — вспышка: палитра $2887F4 "
                     u"проигрывается один раз ($2A58EE)")]))])


def bg_school():
    return OrderedDict([
        ("h", h("row8", [band(0, 31, frac(-1, 2, u"$2A5520: asr.w #1",
                                          at(0x2A5520, "asr.w #1,d0",
                                             span=8)))])),
        ("v", v_fixed())])


def bg_muddrake():
    p = 0x2A5CCC
    q = frac(-1, 4, u"-camX asr 2", at(p, "asr.w #2,d4"))
    h2 = frac(-1, 2, u"-camX asr 1", at(p, "asr.w #1,d0"))
    q3 = frac(-3, 4, u"-camX/4 + -camX/2", at(p, "add.w d0,d1", value=1))
    dA = D(-0.5, u"-t asr 1: картинка влево", at(p, "asr.w #1,d3", nth=0))
    dB = D(-0.25, u"ещё asr 1", at(p, "asr.w #1,d3", nth=1))
    n = [count(at(p, "moveq #3,d2")), count(at(p, "moveq #4,d2", nth=0)),
         count(at(p, "moveq #6,d2", nth=0)), count(at(p, "moveq #4,d2",
                                                     nth=1)),
         count(at(p, "moveq #6,d2", nth=1))]
    edges = [0]
    for x in n:
        edges.append(edges[-1] + x.v)
    ks = [(q, dA), (q, dB), (q, None), (h2, None), (q3, None)]
    return OrderedDict([
        ("h", h("row8", [band(edges[i], edges[i + 1] - 1, ks[i][0],
                              ks[i][1]) for i in range(5)],
                u"ряды 28-31 не пишутся")),
        ("v", v_fixed())])


def zero_h():
    return h("row8", [band(0, 31, D(0, u"$2A552C: плоскость B стоит",
                                    at(0x2A552C, "moveq #0,d0", span=8)))])


def bg_volcano():
    p = 0x2A5A0C
    return OrderedDict([
        ("h", zero_h()),
        ("v", h("column16", [band(0, 19, D(0, u"камеры в формуле нет"),
                                  D(-0.5, u"$FF2150 +1 в чётные кадры, "
                                          u"берётся со знаком минус",
                                    at(p, "addq.w #1,d1")),
                                  wave(cos_amp(at(p, "lsl.l #4,d2"), 4),
                                       D(8, u"t << 3, слово таблицы",
                                         at(p, "lsl.w #3,d0")),
                                       D(0x164 // 2, u"$164 байт на столбец",
                                         at(p, "move.w #$0164,d4")),
                                       D(128, u"1024 / 8")))]))])


def bg_climb():
    p = 0x2A5A5E
    f = [(D(1, u"целиком"), (0, 1, 18, 19)),
         (frac(3, 4, u"v - v/4", at(p, "asr.w #2,d2"),
               at(p, "sub.w d2,d1", nth=0, value=1)),
          (2, 3, 16, 17)),
         (frac(1, 2, u"v asr 1", at(p, "asr.w #1,d1", nth=0)),
          (4, 5, 14, 15)),
         (frac(1, 4, u"v/2 - v/4", at(p, "sub.w d2,d1", nth=1, value=1)),
          (6, 7, 12, 13)),
         (frac(1, 8, u"(v/4) asr 1", at(p, "asr.w #1,d1", nth=1)),
          (8, 9, 10, 11))]
    return OrderedDict([
        ("h", zero_h()),
        ("v", OrderedDict([
            ("unit", "column16"),
            ("base", u"v = camY - (t << ($FF2150 + 1)); столбец = v * доля"),
            ("stage_drift_px_f", [D(-(2 << s), u"t << (%d + 1)" % s,
                                    at(p, "asl.w d1,d4", value=1)) for s in range(4)]),
            ("stages", u"$FF2150 = 0 на входе; 1, 2, 3 ставят метки "
                       u"$2A169A, $2A16A4, $2A16AE"),
            ("columns", [OrderedDict([("columns", list(c)), ("share", s)])
                         for s, c in f])]))])


def bg_bowl():
    p = 0x2A59C6
    half = frac(1, 2, u"camY asr 1", at(p, "asr.w #1,d1"))
    return OrderedDict([
        ("h", zero_h()),
        ("v", OrderedDict([
            ("unit", "column16"),
            ("columns", [
                OrderedDict([("columns", [0, 1, 2, 17, 18, 19]),
                             ("k", D(1, u"camY", at(p, "move.w d1,(a1)", value=1)))]),
                OrderedDict([("columns", [3, 4, 5, 14, 15, 16]),
                             ("k", half)]),
                OrderedDict([("columns", list(range(6, 14))),
                             ("k", D(0, u"не пишутся; $FF20E0 гасит "
                                        u"вход на уровень $29863A"))])])]))])


def bg_ship14():
    p = 0x2A5DFE
    n0 = D(2 * (at(p, "moveq #6,d2").v + 1), u"(n + 1) длинных = 2 ряда",
           at(p, "moveq #6,d2"))
    k8 = frac(-1, 8, u"-camX asr 3", at(p, "asr.w #3,d1"))
    k4 = frac(-1, 4, u"-camX asr 2", at(p, "asr.w #2,d0"))
    k38 = frac(-3, 8, u"-camX/4 + -camX/8", at(p, "add.w d1,d0", nth=0, value=1))
    k2 = frac(-1, 2, u"ещё + -camX/8", at(p, "add.w d1,d0", nth=1, value=1))
    a = n0.v
    return OrderedDict([
        ("h", h("row8", [band(0, a - 1, k8), band(a, a + 1, k4),
                         band(a + 2, a + 5, k38), band(a + 6, a + 11, k2)],
                u"ряды 26-31 не пишутся")),
        ("v", v_fixed()),
        ("camera_sway", sway(0x2A5B02, 4))])


def bg_ship15():
    p = 0x2A5E44
    k = frac(-1, 2, u"-camX asr 1", at(p, "asr.w #1,d3"))
    s0 = at(p, "move.l #$00010000,d1")
    s1 = at(p, "addi.l #$00010000,d1", nth=0)
    dr = [D(float(i), u"накопитель +%d.0 в кадр прибавляется: картинка "
                      u"вправо" % i, s0, s1) for i in (1, 2, 3, 4)]
    n0 = count(at(p, "moveq #13,d0"))
    a = n0.v
    return OrderedDict([
        ("h", h("row8", [band(0, a - 1, k, dr[0]), band(a, a + 1, k, dr[1]),
                         band(a + 2, a + 5, k, dr[2]),
                         band(a + 6, a + 11, k, dr[3])],
                u"ряды 26-31 не пишутся")),
        ("v", v_fixed()),
        ("camera_sway", sway(0x2A5ADC, 5))])


def sway(p, bits):
    return OrderedDict([
        ("axis", u"Y всей камеры (карта и объекты тоже), через $FF131E"),
        ("amp_px", cos_amp(at(p, "lsl.l #%d,d0" % bits), bits)),
        ("period_f", D(128, u"(t & $7F) * 8 точек таблицы",
                       at(p, "andi.w #$007F,d0")))])


def bg_dead(p, top_wave):
    span = 0xAC if top_wave else 0x78     # до следующей процедуры
    wn = 1 if top_wave else 0             # у $2A624A волна неба первая
    k128 = frac(-1, 128, u"-camX lsr 7 (без знака; для плоскости 512 "
                         u"точек то же, что /128)",
                at(p, "lsr.w #7,d4", span=span))
    front = OrderedDict([
        ("lines", count(at(p, "move.w #$001F,d1", span=span))),
        ("k", D(-2, u"add.w d3,d3", at(p, "add.w d3,d3", span=span, value=1))),
        ("wave", wave(cos_amp(at(p, "lsl.l #4,d4", span=span), 4),
                      D(4, u"t << 3 байт = 4 точки",
                        at(p, "lsl.w #3,d0", span=span, nth=wn)),
                      D(12, u"+$18 байт на строку",
                        at(p, "addi.w #$0018,d0", span=span, nth=wn)),
                      D(256, u"1024 / 4"))),
        ("where", u"последние строки списка: снизу экрана столько строк, "
                  u"сколько плоскость B поднята (0-32)")])
    d = OrderedDict([
        ("h", OrderedDict([
            ("unit", "line"),
            ("sky_k", k128),
            ("front_band", front)])),
        ("v", OrderedDict([
            ("unit", "whole"),
            ("formula", u"vscroll B = camY - (нижний предел - 256), "
                        u"зажать 0..32 ($2A6218)"),
            ("offset_from_bottom_px", at(0x2A6218, "subi.w #$0100,d1",
                                         span=0x30)),
            ("max_px", at(0x2A6218, "cmpi.w #$0020,d2", span=0x30))]))])
    if top_wave:
        d["h"]["sky_wave"] = OrderedDict([
            ("lines", u"223 - camY сверху, пока camX <= $500, иначе нет"),
            ("lines_from", at(p, "move.w #$00DF,d6", span=span)),
            ("until_camx_px", at(p, "cmpi.w #$0500,($FFFFE1BC).w",
                                 span=span)),
            ("wave", wave(cos_amp(at(p, "lsl.l #3,d5", span=span), 3),
                          D(4, u"t << 3 байт = 4 точки",
                            at(p, "lsl.w #3,d0", span=span, nth=0)),
                          D(12, u"+$18 байт на строку",
                            at(p, "addi.w #$0018,d0", span=span, nth=0)),
                          D(256, u"1024 / 4")))])
    return d


def bg_stronghold():
    p = 0x2A636E
    return OrderedDict([
        ("h", h("line", [
            band(0, 223, frac(-1, 8, u"(-camX asr 2) asr 1",
                              at(p, "asr.w #1,d4")),
                 D(8, u"t * 8: картинка вправо", at(p, "add.w d1,d1",
                                                    nth=2, value=1)),
                 note=u"чётные строки"),
            band(0, 223, frac(-1, 4, u"-camX asr 2", at(p, "asr.w #2,d4")),
                 D(4, u"t * 4: картинка вправо", at(p, "add.w d1,d1",
                                                    nth=1, value=1)),
                 note=u"нечётные строки")])),
        ("v", v_fixed())])


def bg_bonus():
    p = 0x2A5D26
    steps = [at(p, "addi.l #$%08X,(a2)+" % U32(a + 2), span=0x100)
             for a in range(0x2A5D46, 0x2A5DAC, 6)]
    bands = []
    for i in range(16):
        s = steps[i]
        bands.append(band(4 * i, 4 * i + 3, D(0, u"камеры нет"),
                          D(s.v / 65536.0, u"накопитель 16.16: картинка "
                                           u"вправо", s)))
    bands.append(band(64, 75, D(0, u"ноль")))
    s = steps[16]
    bands.append(band(76, 79, D(0, u"камеры нет"),
                      D(s.v / 65536.0, u"семнадцатый накопитель", s)))
    bands.append(band(80, 105, D(0, u"ноль")))
    bands.append(band(106, 223, frac(-1, 4, u"-camX asr 2",
                                     at(p, "asr.w #2,d2"))))
    return OrderedDict([
        ("h", h("line", bands, u"шаги — ряд 3 * (7/8)^n, кроме 11-го "
                               u"($A800); пишется 225 строк — одна лишняя "
                               u"за концом таблицы")),
        ("v", v_fixed())])


BG = {
    0x2A59B0: bg_mansion, 0x2A5972: bg_ninja, 0x2A5BD4: bg_school,
    0x2A59B6: bg_muddrake, 0x2A5A0C: bg_volcano, 0x2A5A5E: bg_climb,
    0x2A59C6: bg_bowl, 0x2A5B02: bg_ship14, 0x2A5ADC: bg_ship15,
    0x2A5B94: lambda: bg_dead(0x2A624A, True),
    0x2A5B9E: lambda: bg_dead(0x2A62F6, False),
    0x2A5BCA: bg_stronghold, 0x2A59BC: bg_bonus,
}
# Кто из построителей фона зовёт шаг анимации палитры $2A57CA.
PAL_STEP = {0x2A5972, 0x2A59BC, 0x2A59C6, 0x2A5B94, 0x2A5B9E, 0x2A5BCA,
            0x2A5BD4}


def palette_table(a):
    """Таблица анимации палитры: слово N, записи (cnt, idx, par, цвета)."""
    n = U16(a)
    p = a + 2
    out = []
    for _ in range(n):
        cnt, par = U16(p), U16(p + 4)
        out.append(OrderedDict([
            ("cram_index", dw(p + 2, signed=False)),
            ("frames_per_color", D(par + 1, u"subq/bpl: par + 1",
                                   dw(p + 4, signed=False))),
            ("colors", ["$%03X" % U16(p + 6 + 2 * k) for k in range(cnt)]),
        ]))
        p += 6 + 2 * cnt
    return out


def tile_table(a, n):
    out = []
    for r in range(n):
        q = a + 8 * r
        lst, frames = U32(q), U16(q + 4)
        fr = []
        for f in range(frames):
            e = lst + 8 * f
            fr.append(OrderedDict([
                ("src", "$%06X" % (U32(e + 2) * 2)),
                ("words", dw(e, signed=False)),
                ("vram", "$%04X" % U16(e + 6))]))
        out.append(OrderedDict([
            ("every_f", D(U16(q + 6), u"subq/bne: ровно par кадров",
                          dw(q + 6, signed=False))),
            ("frames", fr)]))
    return out


def effects(n, rec):
    bgp = U32(rec + 0x14)
    pal = U32(rec + 0x1C)
    e = OrderedDict()
    if pal:
        plays = bgp in PAL_STEP
        e["palette"] = OrderedDict([
            ("table", hexa(pal)),
            ("plays", plays),
            ("cycles", palette_table(pal))])
        if not plays:
            e["palette"]["note"] = (u"таблица задана, но построитель фона "
                                    u"%s шаг $2A57CA не зовёт — в игре "
                                    u"палитра стоит" % hexa(bgp))
    if n == 3:
        e["palette_by_marker"] = OrderedDict([
            ("on", u"объект $29BFE0 ставит таблицу $288A8A"),
            ("off", u"$29BFFC гасит и шлёт кусок $288B5E"),
            ("cycles", palette_table(0x288A8A))])
    if n in (3, 4, 5):
        e["palette_flash"] = OrderedDict([
            ("every_f", at(0x2A5972, "cmpi.w #$021C,d0")),
            ("table", "$2887F4"),
            ("cycles", palette_table(0x2887F4)),
            ("once", u"первая запись дошла до конца — всё выключается "
                     u"($2A58EE)")])
    cnt = U16(rec + 0x3A)
    if cnt:
        e["tiles"] = tile_table(U32(rec + 0x18), cnt)
    return e


def background(n, rec):
    bgp = U32(rec + 0x14)
    fn = BG.get(bgp)
    if fn is None:
        return None
    d = OrderedDict([("proc", hexa(bgp))])
    d.update(fn())
    return d


def main():
    import levels as L
    import json
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    a = sys.argv[1:]
    if a[:1] == ["--level"]:
        n = int(a[1])
        rec = L.record(n)
        tree = OrderedDict([("background", background(n, rec)),
                            ("effects", effects(n, rec))])
        vals, _src = SJ.split(tree)
        print(json.dumps(vals, ensure_ascii=False, indent=1))
    else:
        tree = camera()
        for n in range(23):
            rec = L.record(n)
            background(n, rec)
            effects(n, rec)
        vals, _src = SJ.split(tree)
        print(json.dumps(vals, ensure_ascii=False, indent=1))
    if SJ.ERRORS:
        for e in SJ.ERRORS:
            print(u"ошибка: %s" % e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
