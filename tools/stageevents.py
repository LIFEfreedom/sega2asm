#!/usr/bin/env python3
u"""Покадровые сценарии этапов как данные ремейка (dyna #207, часть 2).

Главный цикл сразу после приращения `GameTick` зовёт `RunStageFrameHook`
`$02D090`, тот прыгает по `table_stageframe` `$02D0B8` по номеру этапа.
Разбор — [game-stage-events.md](../docs/game-stage-events.md). Здесь
сценарий этапа читается из кода и переводится в два списка:

- **таймер** — вызов общего тела с порогом `d7` и периодом `d6`. У этапа
  один счётчик `StageEventTimer` `$FFE0BC`, и все тела ведут его одинаково:

      если счётчик не ноль: уменьшить; дошёл до нуля — `fire`, счётчик = период
                            (у тел «Once» — ничего, счётчик остаётся нулём);
      иначе, если младшее слово GameTick > d7: `start`, счётчик = `arm`.

  Тела различаются только тем, что делают `start` и `fire`;
- **событие на тике** — `cmpi.l #N` с `GameTick` и строгое равенство, или
  проверка «каждые N тиков» с условием (этап 33).

Проход по местности — одна из процедур `$0210CE…$0212A2` или
`SpreadTypeMapWide` `$020EF0`, с маской типов из `d4` и типом из `d5`.

Не выгружается (у каждого своя задача ремейка): лава `TickLavaEruption`
(#142), яд `StagePoisonTick` (#188), пожары под юнитами этапов 12, 17 и
223, марш ﾒｶﾞｻﾞｳﾙｽ (#209), подсказки уроков (#68), прыжок часов
этапа 38, а также звук, палитры, тряска, камера и текст.
"""
import collections
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import maptex as mt                                          # noqa: E402

ROM = mt.ROM
FRAME_TABLE = 0x02D0B8
LIBRARY = 0x02F1D2                 # за ним — только общие тела
GAME_TICK = 0xFFE05C
TIMER = 0xFFE0BC

# процедуры, которые сценарии зовут
LOAD_PLACEMENT = 0x01EA12
SPREAD_RANDOM, CONVERT_INNER, CONVERT_ALL = 0x0211BC, 0x02123A, 0x0212A2
SEED_ONE, REPAINT_LAST, SPREAD_NEIGHBOURS = 0x0210CE, 0x021150, 0x020EF0
PAINT_LIST = 0x02FB0A              # PlaceTerrainListFiltered
PASS_OF = {SPREAD_RANDOM: "spread_random", CONVERT_INNER: "convert_inner",
           CONVERT_ALL: "convert_all", SEED_ONE: "seed_one",
           REPAINT_LAST: "repaint_last", SPREAD_NEIGHBOURS: "spread_neighbours"}

# оформление: звук, палитра, камера, тряска, перерисовка
COSMETIC = {0x00DFEE, 0x00DAB0, 0x00DAA0, 0x016192, 0x00E10C, 0x00E036,
            0x00E0CC, 0x0218BE, 0x0158A0, 0x00E328, 0x00E356, 0x00D572}

# тела, которые ремейк не исполняет, и где они будут сделаны
LATER = {0x02F55E: u"извержение лавы (#142)",
         0x02F6EE: u"яд (#188)",
         0x02F7BC: None,                          # звуковая петля
         0x02FA6E: u"пожар под юнитом (отдельная задача)",
         0x01F570: u"марш ﾒｶﾞｻﾞｳﾙｽ (#209)",
         0x02F12C: u"шаг ﾒｶﾞｻﾞｳﾙｽ по воротам (#209)",
         0x02EB8C: None}                          # подсказка урока (#68)
GOAL_BODIES = {0x02EAF6, 0x02EB50, 0x02EB16}      # цели, их пишет exportmissions

# этапы с пожаром прямо в сценарии, без общего тела
FIRE_STAGES = {12, 17, 223}


def u16(a):
    return struct.unpack_from(">H", ROM, a)[0]


def u32(a):
    return struct.unpack_from(">I", ROM, a)[0]


def s16(a):
    return struct.unpack_from(">h", ROM, a)[0]


def mask_types(m):
    return [t for t in range(32) if m >> t & 1]


def imm(a, op, size):
    u"""Непосредственное значение инструкции `op` по адресу `a`; код
    сверяется, чтобы разбор не читал чужие байты."""
    assert u16(a) == op, u"$%06X: ждал $%04X, там $%04X" % (a, op, u16(a))
    return u16(a + 2) if size == 2 else u32(a + 2)


D4_L, D5_W, D4_W, D5_B = 0x283C, 0x3A3C, 0x383C, 0x1A3C


def op(kind, **kw):
    d = collections.OrderedDict([("pass", kind)])
    d.update(kw)
    return d


def masked(kind, a4, a5):
    u"""Проход по маске типов: `move.l #маска,d4` и `move.w #тип,d5`."""
    return op(kind, **{"from": mask_types(imm(a4, D4_L, 4)),
                       "to": imm(a5, D5_W, 2)})


def exact(kind, a4, a5):
    u"""Проход по одному типу: `move.w #тип,d4` и `move.w #тип,d5`."""
    return op(kind, **{"from": [imm(a4, D4_W, 2)], "to": imm(a5, D5_W, 2)})


def weighted(a4, a8, a128, a9, a80, a5):
    u"""Один бросок `Random` на срабатывание (`$02F32E`): меньше `$80` —
    тип 8, затем меньше `$50` — тип 9, иначе тип 5."""
    w1, w2 = imm(a128, 0x0400, 2), imm(a80, 0x0400, 2)
    choice = [[imm(a8, D5_W, 2), w1], [imm(a9, D5_W, 2), w2],
              [imm(a5, D5_W, 2), 256 - w1 - w2]]
    return op("spread_random", **{"from": mask_types(imm(a4, D4_L, 4)),
                                  "choice": choice})


def neighbours(a4, a5, byte):
    exc = imm(a4, D4_L, 4)
    to = (imm(a5, D5_B, 2) & 0xFF) if byte else imm(a5, D5_W, 2)
    return op("spread_neighbours", **{"except": mask_types(exc), "to": to})


def stop_fishing():
    # `st $FFE11F` — его читает только RuleGrazeTile53 ﾌﾟﾃﾗ
    assert u16(0x02F204) == 0x50F9 and u32(0x02F206) == 0xFFE11F
    return op("stop_fishing")


def body_templates():
    u"""Общее тело -> (start, fire, rearm). Числа читаются из самих тел."""
    wide = [neighbours(0x020EE4, 0x020EEA, True), stop_fishing()]
    rnd_type = weighted(0x02F324, 0x02F32A, 0x02F334, 0x02F33C, 0x02F340, 0x02F34C)
    rnd_89 = weighted(0x02F3A8, 0x02F3AE, 0x02F3B8, 0x02F3C0, 0x02F3C4, 0x02F3D0)
    assert u16(0x02F4EC) == 0x7801                   # moveq #1,d4
    wave = [op("spread_random", **{"from": [0], "to": imm(0x02F4EE, D5_W, 2)})] * 2
    wave += [masked("spread_random", 0x02F4FE, 0x02F504)] * 2
    wave += [masked("spread_random", 0x02F514, 0x02F51A)] * 2
    return {
        0x02F1D2: (wide, wide, True),                        # SpreadWide, режим B
        0x02F222: ([], [exact("seed_one", 0x02F23C, 0x02F240)], True),
        0x02F26C: ([], [masked("spread_random", 0x02F286, 0x02F28C)], True),
        0x02F2B8: ([], [masked("spread_random", 0x02F2D8, 0x02F2DE)], True),
        0x02F30A: ([masked("convert_inner", 0x02F372, 0x02F378)], [rnd_type], True),
        0x02F38E: ([masked("convert_all", 0x02F3F6, 0x02F3FC)], [rnd_89], True),
        0x02F412: ([masked("spread_random", 0x02F432, 0x02F438)],
                   [masked("spread_random", 0x02F432, 0x02F438)], True),
        0x02F46C: ([masked("convert_inner", 0x02F4A2, 0x02F4A8)], [], True),
        0x02F4CC: ([], wave, True),
        0x02F5B2: ([], [masked("convert_inner", 0x02F5D2, 0x02F5D8)], True),
        0x02F604: ([], [masked("convert_all", 0x02F624, 0x02F62A)], True),
        0x02F656: ([masked("convert_inner", 0x02F686, 0x02F68C)], [], False),
        0x02F6A2: ([masked("convert_all", 0x02F6D2, 0x02F6D8)], [], False),
        0x02F76E: ([neighbours(0x02F788, 0x02F78E, False)],
                   [neighbours(0x02F788, 0x02F78E, False)], True),
    }


# --- разбор кода сценария -------------------------------------------------

Ins = collections.namedtuple("Ins", "a op size arg")

# код -> длина; для кодов с аргументом аргумент читается ниже
LENGTHS = {0x4E75: 2, 0x48E7: 4, 0x4CDF: 4, 0x2039: 6, 0x2E39: 6, 0x0C80: 6,
           0x0C87: 6, 0x0CB9: 10, 0x0287: 6, 0x0280: 6, 0x103C: 4, 0x303C: 4,
           0x3C3C: 4, 0x3E3C: 4, 0x3A3C: 4, 0x383C: 4, 0x1E3C: 4, 0x1A3C: 4,
           0x2E3C: 6, 0x283C: 6, 0x203C: 6, 0x4EB9: 6, 0x4DFA: 4, 0x4879: 6,
           0x3F3C: 4, 0xFF26: 2, 0x4FEF: 4, 0x3039: 6, 0x33C0: 6, 0x33C6: 6,
           0x33FC: 8, 0x4279: 6, 0x5340: 2, 0xBE40: 2, 0xBE80: 2, 0x4A39: 6,
           0x50F9: 6, 0x0C39: 8, 0x7000: 2, 0x23FC: 10, 0x2239: 6, 0x0207: 4,
           0x0C00: 4, 0x0C01: 4, 0x123C: 4, 0x343C: 4, 0x6100: 4, 0x6000: 4, 0x6600: 4, 0x6700: 4,
           0x6500: 4, 0x6400: 4, 0x6200: 4, 0x6300: 4, 0x6D00: 4, 0x6C00: 4}
BRANCHES = {0x6000, 0x6600, 0x6700, 0x6500, 0x6400, 0x6200, 0x6300, 0x6D00,
            0x6C00}


def decode(a):
    u"""Сценарий от точки входа до последнего `rts`, за которым нет цели
    перехода. Незнакомый код — остановка: значит, разбор устарел."""
    out, reach = [], a
    while True:
        o = u16(a)
        if (o & 0xFF00) in (0x6000, 0x6100) and o & 0xFF and o not in LENGTHS:
            disp = o & 0xFF                                     # .s
            disp = disp - 256 if disp & 0x80 else disp
            size, arg, base = 2, a + 2 + disp, 0x6000 if o < 0x6100 else 0x6100
            out.append(Ins(a, base, size, arg))
        else:
            assert o in LENGTHS, u"$%06X: код $%04X" % (a, o)
            size = LENGTHS[o]
            arg = None
            if o in BRANCHES or o == 0x6100:
                arg = a + 2 + s16(a + 2)
            elif o == 0x4DFA:
                arg = a + 2 + s16(a + 2)
            elif o == 0x4EB9:
                arg = u32(a + 2)
            elif size == 6:
                arg = u32(a + 2)
            elif size == 4:
                arg = u16(a + 2)
            out.append(Ins(a, o, size, arg))
        ins = out[-1]
        if ins.op in BRANCHES and ins.arg > reach:
            reach = ins.arg
        a += size
        if ins.op in (0x4E75, 0x6000) and a > reach:
            return out


def call_target(ins):
    if ins.op == 0x4EB9 or ins.op == 0x6100:
        return ins.arg
    return None


def entry(st):
    return FRAME_TABLE + u16(FRAME_TABLE + 2 * st)


def tick_blocks(ins):
    u"""[(тик, начало, конец)] — блоки «GameTick == N»: `move.l GameTick,d0;
    cmpi.l #N,d0; bne конец` или `move.l #N,d7; move.l GameTick,d0;
    cmp.l d0,d7; bne конец`."""
    out = []
    for i in range(len(ins) - 2):
        a, b, c = ins[i], ins[i + 1], ins[i + 2]
        if a.op == 0x2039 and a.arg == GAME_TICK and b.op == 0x0C80 \
                and c.op == 0x6600:
            out.append((b.arg, c.a + c.size, c.arg))
        if i + 3 < len(ins) and a.op == 0x2E3C and b.op == 0x2039 \
                and b.arg == GAME_TICK and c.op == 0xBE80 \
                and ins[i + 3].op == 0x6600:
            d = ins[i + 3]
            out.append((a.arg, d.a + d.size, d.arg))
    return out


def placement_at(ins, i):
    u"""Адрес расстановки у `jsr LoadPlacement` номер i: предыдущий `lea`."""
    for j in range(i - 1, -1, -1):
        if ins[j].op == 0x4DFA:
            return ins[j].arg
    raise AssertionError(u"LoadPlacement без lea по $%06X" % ins[i].a)


def timer(after, period, start, fire, rearm=True, arm=None, above=None,
          below=None):
    d = collections.OrderedDict([("after", after), ("period", period),
                                 ("arm", period if arm is None else arm)])
    if not rearm:
        d["rearm"] = False
    if above is not None:
        d["above"] = above
    if below is not None:
        d["below"] = below
    d["start"] = start
    d["fire"] = fire
    return d


def tick_event(tick, ops, every=0, when=None, once=False):
    d = collections.OrderedDict()
    if every:
        d["every"] = every
    else:
        d["tick"] = tick
    if when:
        d["when"] = when
    if once:
        d["once"] = True
    d["ops"] = ops
    return d


# --- особые этапы: разобраны вручную, байты сверяются ----------------------

def special_6(place):
    u"""Этап 6: один раз после тика 9000 край (тип 30) внутри поля
    зарастает — пять `SpreadTerrainRandom` 30 -> 24, 4, 3, 2, 7, — остаток
    края по всей карте становится землёй, клетки списка `data_231` тоже
    землёй, и по тому же списку `LoadPlacement` выводит ﾎﾟﾝﾎﾟﾝ. Счётчик
    взводится в `$FF` и перезаряжается без действия: сработать второй раз
    сценарий не может (`$02DAFE…$02DB98`)."""
    assert imm(0x02DAFE, 0x2E3C, 4) == 9000
    assert imm(0x02DB32, 0x33FC, 2) == 0xFF and imm(0x02DB1A, 0x33FC, 2) == 0xFF
    mask = imm(0x02DB40, D4_L, 4)
    ops = []
    for a in (0x02DB46, 0x02DB50, 0x02DB5A, 0x02DB64, 0x02DB6E):
        ops.append(op("spread_random", **{"from": mask_types(mask),
                                          "to": imm(a, D5_W, 2)}))
        assert u32(a + 6) == SPREAD_RANDOM
    ops.append(op("convert_all", **{"from": mask_types(mask),
                                    "to": imm(0x02DB78, D5_W, 2)}))
    assert u32(0x02DB7E) == CONVERT_ALL
    data = 0x02DB82 + 2 + s16(0x02DB84)
    assert u16(0x02DB82) == 0x4DFA and u32(0x02DB8C) == LOAD_PLACEMENT
    cells = [[x, y] for x, y, _d, _t, _p in mt.placement(data, lo=0)]
    ops.append(op("paint_cells", cells=cells, to=imm(0x02DB78, D5_W, 2)))
    ops.append(place(data))
    return [timer(9000, 0xFF, ops, [])], []


def special_31(place):
    u"""Этап 31: две фазы на одном счётчике (`$02DC1E…$02DD44`).

    До тика 8000: порог 30, период 900, раз в период дважды
    `RepaintLastCellOfType` 26 -> 25. Взведя счётчик, тело проваливается в
    код второй фазы и там же уменьшает его на один: первое срабатывание —
    на тике 930. Ровно на тике 8000 счётчик сбрасывается. После: порог
    8100 — `ConvertTerrainAll` 19 -> 30, затем раз в 1800 тиков
    `SpreadTypeMapWide` края (тип 30)."""
    assert imm(0x02DC62, 0x0CB9, 4) == 8000
    d6a, d7a = imm(0x02DC7E, 0x3C3C, 2), imm(0x02DC82, 0x3E3C, 2)
    rep = exact("repaint_last", 0x02DC9C, 0x02DCA0)
    assert u32(0x02DCA6) == REPAINT_LAST and u32(0x02DCAC) == REPAINT_LAST
    d6b, d7b = imm(0x02DCCC, 0x3C3C, 2), imm(0x02DCD0, 0x3E3C, 2)
    wide = neighbours(0x02DCEA, 0x02DCF0, False)
    assert u32(0x02DCFC) == SPREAD_NEIGHBOURS
    conv = masked("convert_all", 0x02DD28, 0x02DD2E)
    assert u32(0x02DD34) == CONVERT_ALL
    timers = [timer(d7a, d6a, [], [rep, rep], arm=d6a - 1, below=8000),
              timer(d7b, d6b, [conv], [wide], above=8000)]
    return timers, [tick_event(8000, [op("reset_timer")])]


def special_33(place, base):
    u"""Этап 33: кроме общего тела — один раз, на тике, кратном 1024, если
    у игрока 1 не меньше двух ﾃｨﾗﾉ (`$FFE089` — перепись вида 4 игрока 1):
    `ConvertTerrainInner` 19 -> 8 (`$02D974…$02D9C2`). Флаг «было» —
    `$FFE0DF`."""
    assert imm(0x02D984, 0x0280, 4) == 0x3FF
    assert u16(0x02D98E) == 0x0C39 and u32(0x02D992) == 0xFFE089
    least = u16(0x02D990)
    conv = masked("convert_inner", 0x02D9A0, 0x02D9A6)
    assert u32(0x02D9AC) == CONVERT_INNER
    when = collections.OrderedDict([("team_id", 1), ("unit_type", 3),
                                    ("at_least", least)])
    return base[0], base[1] + [tick_event(0, [conv], every=0x400, when=when,
                                          once=True)]


def special_117_extra(ins):
    u"""Этап 117, тик 12600: `ConvertTerrainInner` 19 -> 8."""
    conv = masked("convert_inner", 0x02E4AE, 0x02E4B4)
    assert u32(0x02E4BA) == CONVERT_INNER
    return conv


def stage_events(st, place):
    u"""(таймеры, события на тике, отложенное) этапа st.

    `place(адрес)` переводит расстановку в операцию `place` — её пишет
    exportmissions, потому что юниты выгружаются по его правилам."""
    if st in FIRE_STAGES:
        # весь сценарий — пожар под случайным стоящим юнитом игрока 1
        return [], [], [LATER[0x02FA6E]]
    if 51 <= st <= 58:
        # уроки: подсказки на экране (#68) и цель урока 1 — её пишет
        # exportmissions
        return [], [], []
    if st == 132:
        # как этап 6, но его не берёт ни одна миссия
        return [], [], []
    if st == 20:
        # сценарий ﾒｶﾞｻﾞｳﾙｽ целиком: марш, распад, камера
        return [], [], [LATER[0x01F570]]
    ins = decode(entry(st))
    later = []
    bodies = body_templates()
    timers, ticks = [], []
    blocks = tick_blocks(ins)
    handled = set()
    for i, x in enumerate(ins):
        t = call_target(x)
        if t is None or t in COSMETIC or t in GOAL_BODIES:
            continue
        if t in bodies:
            d6 = d7 = None
            for j in range(i - 1, max(i - 4, -1), -1):
                if ins[j].op == 0x3C3C and d6 is None:
                    d6 = ins[j].arg
                if ins[j].op in (0x3E3C, 0x2E3C) and d7 is None:
                    d7 = ins[j].arg
            assert d6 is not None and d7 is not None, (st, hex(x.a))
            start, fire, rearm = bodies[t]
            timers.append(timer(d7, d6, start, fire, rearm))
            handled.add(x.a)
        elif t == LOAD_PLACEMENT:
            blk = [b for b in blocks if b[1] <= x.a < b[2]]
            if st == 6:
                continue
            assert len(blk) == 1, (st, hex(x.a))
            ticks.append(tick_event(blk[0][0], [place(placement_at(ins, i))]))
            handled.add(x.a)
        elif t in LATER:
            if LATER[t] and LATER[t] not in later:
                later.append(LATER[t])
        elif t in PASS_OF or t == PAINT_LIST:
            if st in (6, 31, 33, 117):
                continue
            raise AssertionError(u"этап %d: проход $%06X вне тела" % (st, t))
        else:
            raise AssertionError(u"этап %d: зов $%06X по $%06X" % (st, t, x.a))
    if st == 6:
        return special_6(place) + (later,)
    if st == 31:
        timers, ticks = special_31(place)
    elif st == 33:
        timers, ticks = special_33(place, (timers, ticks))
    elif st == 117:
        blk = [b for b in blocks if b[0] == 12600]
        assert len(blk) == 1
        ticks.insert(0, tick_event(12600, [special_117_extra(ins)]))
    if st == 38:
        later.append(u"прыжок часов на тик 12600")
    return timers, ticks, later


def all_stages(place):
    return {st: stage_events(st, place) for st in range(256)
            if entry(st) != 0x02E8FA}
