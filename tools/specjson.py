#!/usr/bin/env python3
"""Числа спецификации поведения (docs/mauimallard/behavior.md) в JSON.

    python tools/specjson.py             записать out/mauimallard/export/
    python tools/specjson.py --check     только проверить, ничего не писать

Пишет два файла с ОДИНАКОВЫМ деревом ключей:

* `behavior.json` — голые числа для движка;
* `behavior.sources.json` — на месте каждого числа строка-происхождение:
  адрес команды и её текст, адрес слова данных или формула вывода.

Числа сюда не переписаны из текста спецификации, а **прочитаны из ROM**.
Каждое задано одним из способов:

* `at(процедура, "текст команды")` — команда ищется в листинге от начала
  процедуры; совпадение должно быть ровно одно, иначе инструмент падает и
  показывает соседей. Исключение одно: если между первым и вторым
  совпадением стоит `rts` или `jmp`, второе — уже соседняя процедура, и
  берётся первое. Число — непосредственный операнд этой команды;
* `dw(адрес)`, `dl(адрес)`, `db(адрес)` — слово данных (таблицы, программы
  поведения `+$48`, скрипты анимации);
* `cmd(адрес, байты)` — команда программы или скрипта: заголовок сверяется
  побайтово, число — операнд следом;
* `D(значение, формула, входы...)` — выведенное число; в происхождении —
  формула и все входы.

Единицы — по суффиксу ключа (подробно в `meta.units` выходного файла):
`_v` скорость 8.8 (пикселей за кадр × 256), горизонтальная — от взгляда;
`_a` прибавка к скорости за кадр, тоже 8.8; `_f` кадры при 60 Гц; `_px`
пиксели; `_turn` угол в 1/1024 оборота; `_p256` вероятность n/256.
Урон и запас игрока в игре двоично-десятичные, здесь они уже обычные числа.
Скрипты анимации и программы — строки-адреса вида `"$1DAEC2"`.
"""
import hashlib
import io
import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import enemies as E                                          # noqa: E402
from paths import OUT                                        # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM = E.ROM


class SpecError(Exception):
    pass


ERRORS = []


def _fail(msg):
    """Ошибка не роняет прогон: копится, чтобы увидеть все сразу."""
    ERRORS.append(msg)
    return V(None, "ОШИБКА: " + msg)


class V(object):
    """Число и откуда оно взято."""
    __slots__ = ("v", "src")

    def __init__(self, v, src):
        self.v, self.src = v, src

    def __repr__(self):
        return "V(%r, %r)" % (self.v, self.src)


def _signed(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


def hexa(a):
    return "$%06X" % a


IMM_HEX = re.compile(r"#\$([0-9A-F]+)")
IMM_DEC = re.compile(r"#(-?\d+)\b")
SIZE = re.compile(r"^\w+\.([bwl])\b")
PEA = re.compile(r"^pea \(\$([0-9A-F]+)\)\.w")
LEA = re.compile(r"^lea \(\$([0-9A-F]+)\)\.l")


def _operand(text, part, signed):
    m = PEA.match(text) or LEA.match(text)
    if m:
        return int(m.group(1), 16)
    m = IMM_HEX.search(text)
    if m:
        v = int(m.group(1), 16)
        sz = SIZE.match(text)
        bits = {"b": 8, "w": 16, "l": 32}[sz.group(1)] if sz else 16
        if part == "hi":
            v, bits = v >> 16, 16
        elif part == "lo":
            v, bits = v & 0xFFFF, 16
        return _signed(v, bits) if signed else v
    m = IMM_DEC.search(text)
    if m:
        return int(m.group(1))
    raise SpecError("нет непосредственного операнда: %s" % text)


def at(proc, needle, span=0x100, nth=None, part=None, signed=True,
       addr=False, value=None):
    """Операнд единственной команды с текстом `needle` в `[proc, proc+span)`.

    С `value` операнд не берётся: команда только свидетельствует, что число
    `value` в коде есть (например, `tst.w d6` / `bpl` — «нужен бит 15»).
    """
    needle = re.sub(r"\s+", " ", needle.strip())
    hits = [a for a in E.ADDRS
            if proc <= a < proc + span and needle in E.BY[a]]
    if nth is not None:
        hits = hits[nth:nth + 1]
    elif len(hits) > 1 and any(
            E.BY[b].startswith(("rts", "jmp")) for b in
            E.ADDRS if hits[0] < b < hits[1]):
        # Второе совпадение — уже за концом процедуры (соседняя копия
        # того же кода), значит своё — первое.
        hits = hits[:1]
    if len(hits) != 1:
        near = [a for a in E.ADDRS if proc <= a < proc + span]
        num = IMM_HEX.search(needle) or IMM_DEC.search(needle)
        show = [a for a in near if num and num.group(0) in E.BY[a]]
        return _fail("%s: «%s» найдено %d раз%s" % (
            hexa(proc), needle, len(hits), "".join(
                "\n    %s  %s" % (hexa(a), E.BY[a]) for a in (hits or show))))
    a = hits[0]
    text = E.BY[a]
    if value is not None:
        v = value
    elif addr:
        v = "$%06X" % (_operand(text, None, False) & 0xFFFFFF)
    else:
        v = _operand(text, part, signed)
    return V(v, "%s: %s%s" % (hexa(a), text,
                              " [%s]" % part if part else ""))


def dw(a, signed=True):
    v = struct.unpack_from(">H", ROM, a)[0]
    return V(_signed(v, 16) if signed else v, "%s: данные, слово" % hexa(a))


def db(a, signed=False):
    v = ROM[a]
    return V(_signed(v, 8) if signed else v, "%s: данные, байт" % hexa(a))


def dl(a, addr=False):
    v = struct.unpack_from(">I", ROM, a)[0]
    if addr:
        v = "$%06X" % (v & 0xFFFFFF)
    return V(v, "%s: данные, длинное" % hexa(a))


def cmd(a, head, signed=True, size=2):
    """Команда программы `+$48` или скрипта: заголовок и операнд следом."""
    got = bytes(ROM[a:a + len(head)])
    if got != bytes(head):
        return _fail("%s: ждали %s, лежит %s" % (
            hexa(a), " ".join("%02X" % b for b in head),
            " ".join("%02X" % b for b in got)))
    o = a + len(head)
    if size == 1:
        v = ROM[o]
        v = _signed(v, 8) if signed else v
    else:
        v = struct.unpack_from(">H", ROM, o)[0]
        v = _signed(v, 16) if signed else v
    return V(v, "%s: команда %s, операнд" % (
        hexa(a), " ".join("%02X" % b for b in head)))


def D(value, why, *inputs):
    """Выведенное число: формула и входы."""
    src = "вывод: %s" % why
    if inputs:
        src += " <- " + " | ".join(i.src for i in inputs)
    return V(value, src)


def bcd(x):
    """Двоично-десятичное -> обычное."""
    if x.v is None:
        return x
    v = x.v & 0xFFFF
    digits = "%X" % v
    if not digits.isdigit():
        return _fail("не двоично-десятичное: $%X (%s)" % (v, x.src))
    return D(int(digits), "двоично-десятичное $%X" % v, x)


def ok(*xs):
    return all(x.v is not None for x in xs)


def neg(x):
    return D(-x.v, "со знаком минус", x) if ok(x) else x


def half(x):
    """Индекс таблицы в байтах -> в словах (1/1024 оборота)."""
    if not ok(x):
        return x
    return D(x.v // 2, "байты таблицы синуса / 2 = 1/1024 оборота", x)


def amp(shift):
    """Размах `sin * 2**k >> 16` при синусе с амплитудой $7FFF."""
    if not ok(shift):
        return shift
    return D(1 << (shift.v - 1), "$7FFF * 2**k / 65536 = 2**(k-1) точек",
             shift)


def trig_v(shift):
    """Скорость `sin >> k` при амплитуде синуса $7FFF, в 8.8."""
    if not ok(shift):
        return shift
    return D(0x7FFF >> shift.v, "$7FFF >> k", shift)


def pair(x, y):
    return {"x": x, "y": y}


# ------------------------------------------------------------ разделы

def units():
    grav = at(0x29A6A6, "addi.w #$003C,d0", span=0x20)
    return {
        "tick_hz": D(60, "кадровое прерывание NTSC, список $FFFFE176"),
        "gravity_a": grav,
        "fall_max_v": D(0x0600, "обычный предел $FF1B4E"),
        "fall_max_deep_v": D(0x0C00, "предел на уровнях с +$3E записи"),
        "screen_px": pair(D(320, "ширина кадра"), D(224, "высота кадра")),
        "cell_px": D(16, "клетка карты: координата >> 4 в $2996C2"),
        "rng_seed": [D(0x31415926, "зерно $296B0C/$2A564A"),
                     D(0x987E535B, "зерно $296B0C/$2A564A")],
    }


def player():
    tab = 0x1FD7EE
    diff = {}
    for i, name in enumerate(("normal", "hard", "practice")):
        diff[name] = {
            "health": bcd(dw(tab + 8 * i)),
            "lives": dw(tab + 8 * i + 2),
            "continues": dw(tab + 8 * i + 4),
        }
    dmg = {
        "enemy_touch": bcd(at(0x299A7A, "moveq #16,d0")),
        "hazard_tile": bcd(at(0x294956, "moveq #37,d0", nth=0)),
        "other_tile": bcd(at(0x29496A, "moveq #16,d0")),
        "spikes_below": bcd(at(0x29498A, "moveq #37,d0", nth=0)),
        "spikes_below_bounce_v": at(0x29498A, "move.w #$F980,$18(a0)"),
        "spikes_above": bcd(at(0x2949BA, "moveq #37,d0")),
        "spikes_above_push_v": at(0x2949BA, "#$0800,$18(a0)"),
        "knockback_trap": bcd(at(0x29AC3C, "moveq #37,d0")),
        "knockback_trap_v": at(0x29AC3C, "move.w #$0200,$16(a1)"),
        "invulnerable_f": at(0x299920, "move.w #$005A,$A(a0)", nth=0),
        "hurt_state": at(0x299920, "move.b #$0B,$4(a0)", nth=0),
        "hurt_sound": at(0x299920, "pea ($000002).w"),
        "water_push_px": at(0x294180, "subi.w #$0010,$14(a0)"),
        "water_hold_f": at(0x294180, "move.b #$1E,($FF2134).l"),
    }
    heal = {
        "small": bcd(at(0x2A4998, "move.w #$0025,d0")),
        "big_max": bcd(at(0x29FE72, "moveq #80,d0")),
        "big": bcd(at(0x29FE72, "move.w #$0050,d0")),
    }
    move = {
        "walk_a": at(0x29249A, "addi.w #$0080,d2"),
        "walk_max_v": at(0x29249A, "move.w #$0400,d2"),
        "release_div": D(4, "lsr.w #2", at(0x2924E8, "lsr.w #2,d2")),
        "release_decay_div": D(4, "asr.w #2: вычесть четверть за кадр",
                               at(0x2920AE, "asr.w #2,d2")),
        "jump_v": at(0x291F34, "move.w #$FA10,$18(a0)"),
        "run_jump_v": pair(at(0x291F50, "move.w #$0300,$16(a0)"),
                           at(0x291F50, "move.w #$FA30,$18(a0)")),
        "sticky_jump_extra_v": neg(at(0x291F64, "subi.w #$0030,$18(a0)")),
        "short_jump_a": at(0x292662, "addi.w #$0080,d2"),
        "short_jump_until_v": at(0x292662, "cmpi.w #$FE80,d2"),
        "air_toward_a": at(0x292592, "#$0020"),
        "air_toward_max_v": at(0x292592, "#$0300"),
        "air_against_a": neg(at(0x292580, "subi.w #$0120,d2")),
        "air_neutral_a": neg(at(0x2925BE, "subi.w #$0010,d2")),
        "head_probe_px": neg(at(0x29261C, "move.w #$FFE8,d7")),
        "landing_sound": at(0x292722, "pea ($000005).w"),
    }
    hold = {
        "transform_hold_f": at(0x291F74, "cmpi.w #$0032,($FF1A02).l"),
        "hold_clamp_f": at(0x2A4C04, "move.w #$001E,($FF1A02).l"),
        "fuel_drain_every_f": D(8, "andi.w #$0007: раз в 8 кадров",
                                at(0x29895A, "andi.w #$0007,d3")),
        "fuel_drain": at(0x29895A, "moveq #1,d0"),
    }
    throw = [{"ahead_px": dw(0x1EAA82 + 4 * i + 2),
              "up_px": dw(0x1EAA82 + 4 * i)} for i in range(4)]
    return {"difficulty": diff, "damage": dmg, "heal": heal,
            "movement": move, "hold": hold,
            "throw_from": dict(zip(("ahead", "up", "diagonal", "down"),
                                   throw)),
            "ammo_per_pickup": at(0x29A0E0, "moveq #16,d0", nth=0),
            "body": body(), "ninja": ninja(), "small": small(),
            "bungee": bungee()}


# ------------------------------------------------------------ скрипты игрока

SCRIPT_SRC = (u"хронология скрипта $%06X: исполнитель $297074 держит кадр "
              u"+$26 тактов, D8 n — n тактов; такт 0 — кадр, в котором "
              u"скрипт поставлен; первый кадр без D8 в игре держится "
              u"прежний +$26, здесь — записанный самим скриптом")


def timeline(a, d26=None, cap=400):
    """Исполнить скрипт анимации так же, как `$297074`.

    -> (кадры [(такт, кадр, длительность)], записи полей [(такт, поле,
    значение, адрес команды)], такт конца, состояние в конце или None).
    Конец — запись в `+$04`, кадр «навсегда» или повтор адреса; условные
    переходы не берутся.
    """
    import anim as AN
    frames, writes, t, seen = [], [], 0, set()
    start = a
    while cap:
        cap -= 1
        if (a, d26) in seen:
            return frames, writes, t, None
        seen.add((a, d26))
        dur = d26
        while True:
            hi = ROM[a]
            if hi < 0xD8:
                w = struct.unpack_from(">H", ROM, a)[0]
                a += 2
                if w < 3:
                    continue
                if dur is None and not frames and d26 is not None:
                    # Первый кадр: +$28 загружен из ПРЕЖНЕГО +$26 до того,
                    # как скрипт записал свой. Берём записанный скриптом —
                    # в игре тут остаток прошлой анимации.
                    dur = d26
                frames.append((t, (w - AN.FRAMES) // 4, dur))
                if dur is None:
                    raise SpecError("скрипт $%06X: длительность кадра зависит "
                                    "от прежнего +$26, задайте d26" % start)
                if dur == 0:
                    return frames, writes, t, None
                t += dur
                break
            n = ROM[a + 1]
            if hi == 0xD8:
                dur = n
            elif hi == 0xD9:
                a += struct.unpack_from(">h", ROM, a + 2)[0]
                continue
            elif hi in (0xE1, 0xDC, 0xDD, 0xDE, 0xE2, 0xE3, 0xE4):
                v = (ROM[a + 3] if hi == 0xE1 else
                     struct.unpack_from(">I" if hi == 0xDD else ">H",
                                        ROM, a + 2)[0])
                writes.append((t, n, v, a))
                if hi == 0xE1 and n == 0x26:
                    d26 = v
                if n == 0x04 and hi in (0xE1, 0xDC):
                    return frames, writes, t, v >> 8 if hi == 0xDC else v
            a += AN.CMDS[hi][0]
    raise SpecError("скрипт $%06X не кончился" % start)


def script_end(a, d26=None):
    _f, _w, t, st = timeline(a, d26)
    return D(t, SCRIPT_SRC % a + u": такт, когда скрипт сменил состояние")


def script_mark(a, field, value, d26=None, nth=0):
    """Такт n-й записи `+field = value` в скрипте."""
    _f, writes, _t, _s = timeline(a, d26)
    hits = [(t, at_) for t, n, v, at_ in writes if n == field and v == value]
    if len(hits) <= nth:
        return _fail("$%06X: нет записи +$%02X = $%X" % (a, field, value))
    t, at_ = hits[nth]
    return D(t, SCRIPT_SRC % a + u": запись +$%02X = $%X по $%06X" % (
        field, value, at_))


def script_field(a, field, d26=None):
    """Значение первой записи в поле (например скорость `+$18`)."""
    _f, writes, _t, _s = timeline(a, d26)
    for t, n, v, at_ in writes:
        if n == field:
            return V(_signed(v, 16), u"%s: команда скрипта, поле +$%02X, "
                     u"такт %d" % (hexa(at_), field, t))
    return _fail("$%06X: нет записи в +$%02X" % (a, field))


def strike(a, d26=None):
    """Удар по скрипту: такты с коробками удара (биты 8-11) и их охват."""
    import frames as F
    frames, writes, end, _st = timeline(a, d26)
    hit, hook, box = [], [], None
    for t, fr, dur in frames:
        v = F.U32(F.BASE + 4 * fr)
        items = F.parse(v)
        if items is None:
            continue
        for x0, x1, y0, y1, num in F.boxes(v, len(items)):
            if 8 <= num <= 11:
                hit.append((t, t + dur - 1))
                box = ([min(box[0], x0), max(box[1], x1),
                        min(box[2], y0), max(box[3], y1)]
                       if box else [x0, x1, y0, y1])
            elif num == 15:
                hook.append((t, t + dur - 1))
    src = SCRIPT_SRC % a + u"; коробки кадров — tools/frames.py"
    out = {"total_f": D(end, src + u": конец")}
    if hit:
        out["strike_from_f"] = D(min(h[0] for h in hit), src)
        out["strike_to_f"] = D(max(h[1] for h in hit), src)
        out["reach_px"] = {
            "x": [D(box[0], src), D(box[1], src)],
            "y": [D(box[2], src), D(box[3], src)]}
    if hook:
        out["hook_from_f"] = D(min(h[0] for h in hook), src)
        out["hook_to_f"] = D(max(h[1] for h in hook), src)
    opens = [t for t, n, v, _a in writes if n == 0x05 and v == 1]
    shuts = [t for t, n, v, _a in writes if n == 0x05 and v == 0 and
             opens and t > opens[0]]
    if opens and shuts:
        out["chain_from_f"] = D(opens[0], src + u": +$05 = 1")
        out["chain_to_f"] = D(shuts[0] - 1, src + u": +$05 = 0")
    return out


def body():
    """Габариты для столкновений с картой: у утки и ниндзя одни."""
    return {
        "feet_below_y_px": at(0x2A4F6C, "addi.w #$0010,d1", span=0x10),
        "ground_probe_side_px": at(0x2A4F9A, "move.w #$0004,d2", span=0x10),
        "duck_ninja": {
            "half_width_px": at(0x29A8D8, "move.w #$0020,($FF133C).l",
                                span=0x30),
            "wall_rows": D(2, "moveq #1,d2: dbf на две строки клеток",
                           at(0x2A4CBE, "moveq #1,d2", span=4)),
            "head_probe_px": neg(at(0x29261C, "move.w #$FFE8,d7")),
        },
        "small": {
            "half_width_px": at(0x29A8A0, "move.w #$0010,($FF133C).l",
                                span=0x30),
            "wall_rows": D(1, "subq.w #1,d2: одна строка",
                           at(0x2A4CC0, "subq.w #1,d2", span=0x14)),
            "wall_row_below_y_px": at(0x2A4CC0, "addq.w #8,d1", span=0x14),
            "head_probe_px": at(0x2942BC, "moveq #0,d7", span=8),
        },
    }


def _cord(ctor, where):
    return {"ctor": hexa(ctor), "where": where,
            "rest_px": at(ctor, "$4C(a0)", span=0x1A),
            "release_px": at(ctor, "$4E(a0)", span=0x1A),
            "shelf_floor_px": at(ctor, "$50(a0)", span=0x1A),
            "stiffness_shift": at(ctor, "$52(a0)", span=0x1A)}


def bungee():
    """Тарзанка уровней 12 и 13 (то, что раньше звалось «водой»)."""
    ctl, grab, st7, st24 = 0x2A0460, 0x2A0626, 0x293F54, 0x2941A0
    return {
        "levels": [12, 13],
        "cords": {
            "code_124": _cord(0x2A0406, u"уровень 12: (376, 352), "
                                        u"(264, 1488)"),
            "code_125": _cord(0x2A0424, u"уровень 12: (264, 2832)"),
            "level_13": _cord(0x2A0442, u"уровень 13 со старта: процедура "
                                        u"уровня $2A07A4"),
            "cell_offset_px": pair(at(0x2A03DE, "addq.w #8,d1", value=8),
                                   at(0x2A03DE, "addi.w #$0010,d2"))},
        "lines": u"всё от точки крепления (Y шнура): +rest — линия покоя, "
                 u"+release (отрицательное — выше) — линия отцепления, "
                 u"+shelf_floor — ниже неё на полке не устоять",
        "level13": {
            "cord_cell_px": pair(at(0x2A07A4, "move.w #$00A0,d1"),
                                 at(0x2A07A4, "move.w #$0050,d2")),
            "shift_at_x": at(0x2A06FA, "cmpi.w #$0CE0,d0"),
            "shift_up_px": at(0x2A06FA, "move.w #$0030,d0"),
            "left_limit_to": at(0x2A06FA, "move.w #$0CA0,$4C(a0)"),
            "left_limit_step": at(0x2A0756, "addq.w #2,d0", value=2)},
        "grab": {
            "touch_codes": [124, 125, 126],
            "max_rise_v": at(grab, "cmpi.w #$FC00,d1"),
            "probe_up_px": at(grab, "subi.w #$0020,d2"),
            "probe_half_px": at(grab, "moveq #16,d3"),
            "stop_v": at(0x2A05B6, "clr.w $18(a0)", value=0),
            "snap": u"игрока ставят на высоту крепления",
            "x_corridor_px": [neg(at(0x2A05B6, "subi.w #$0140,d0")),
                              D(320, u"-320 + 640",
                                at(0x2A05B6, "addi.w #$0280,d0"))],
            "no_corridor_when_shift": at(0x2A05B6,
                                         "cmpi.w #$0002,$52(a1)"),
            "sound": at(0x2A0654, "pea ($00007D).w"),
            "form_checked": False},
        "pull": {
            "rule": u"каждый кадр: s = Y - линия покоя; s >= 0 и "
                    u"состояние не 24 и не 39 — скорость Y -= s >> k "
                    u"(1/256 точки за кадр); выше линии покоя шнур "
                    u"провисает",
            "gravity_a": at(0x2A4F1C, "move.w #$003C,d0", span=0x10),
            "equilibrium_px": [D(120, u"60 << 1: сила s >> 1 равна "
                                      u"тяжести $3C"),
                               D(240, u"60 << 2 на уровне 13")],
            "ceiling_y_px": at(ctl, "cmpi.w #$0010,d0"),
            "max_fall_v": at(0x2A4E50, "move.w #$0800,d1"),
            "hard_landing_v": at(ctl, "cmpi.w #$0040,($FF138C).l"),
            "hard_landing_pause_shift": at(ctl, "lsr.w #5,d4",
                                           value=5),
            "lift_off_pull": at(ctl, "cmpi.w #$003C,d1"),
            "lift_off_anim": "$1D6F34",
            "step_order": u"утка сначала движется, потом шнур меняет "
                          u"скорость: раскачка энергии не набирает"},
        "release": {
            "rule": u"выше линии отцепления в состоянии 7",
            "sound": at(0x293F26, "pea ($00007E).w"),
            "then_state": at(st7, "move.b #$16,$4(a0)"),
            "also_spikes": u"код местности 13 ($29498A)"},
        "states": {
            "7": {"what": u"прыжки на шнуре", "handler": hexa(st7),
                  "on_ground_state": at(st7, "move.b #$00,$4(a0)"),
                  "stretch_anim_from_px": at(0x293ED2,
                                             "cmpi.w #$0180,d2"),
                  "stretch_anim": "$1D6F14",
                  "stretch_sound": cmd(0x1D6F26, [0xEA], size=1,
                                       signed=False),
                  "hang_anim": "$1D6F34", "fall_anim": "$1D6F46",
                  "air_throw_state": at(st7, "move.b #$0D,$4(a0)"),
                  "down": u"держат вниз — искать полку"},
            "24": {"what": u"стоит на полке, шнур не тянет",
                   "handler": hexa(st24),
                   "walk_v": at(st24, "move.w #$0100,$16(a0)"),
                   "leave": u"B, нет полки или ниже предела полки",
                   "leave_up_px": at(0x294180, "subi.w #$0010,$14(a0)"),
                   "no_shelf_f": at(0x294180,
                                    "move.b #$1E,($FF2134).l"),
                   "throw_state": at(st24, "move.b #$27,$4(a0)")},
            "39": {"what": u"бросок с полки", "handler": "$2942A0",
                   "shot_px": pair(D(42, u"младшее слово $0006002A",
                                     at(0x29426C,
                                        "move.l #$0006002A,d4")),
                                   D(6, u"старшее слово: выше"))}},
        "shelf": {
            "probe_below_px": at(st7, "addi.w #$0010,d4"),
            "terrain_codes": [at(0x294086, "cmpi.w #$0028,d2"),
                              at(0x294086, "cmpi.w #$0030,d2")],
            "profiles": "$1EAAE6",
            "object_bit_mask": at(0x294086, "move.w #$2000,d7"),
            "ride": u"на объекте — едет с ним ($FF2135, $2A4290), шнур "
                    u"тоже; такие объекты — шесты уровня 13"},
        "launch_height": u"из покоя на глубине s под линией покоя: "
                         u"h = (s^2 / (2 * 2^k * 256) - 60 s / 256) / "
                         u"(60 / 256) над линией покоя",
    }


def hook_release():
    out = []
    for i in range(10):
        a = 0x1EAA36 + 6 * i
        out.append({"ahead_px": db(a, signed=True),
                    "below_px": db(a + 1, signed=True),
                    "v": pair(dw(a + 2), dw(a + 4))})
    return out


def ninja():
    """Облик ниндзя: превращение, ход, рывок, удары, распор, крюк."""
    hits = [0x1D78E8]
    for i in range(4):
        j = 0x1D78D8 + 4 * i
        off = cmd(j, [0xD9, 0x00])
        hits.append(j + off.v if ok(off) else j)
    combo = []
    for n, a in enumerate(hits):
        h = strike(a, 3)
        h["anim"] = hexa(a)
        combo.append(h)
    return {
        "enter": {
            "hold_f": at(0x291F74, "cmpi.w #$0032,($FF1A02).l"),
            "hold_crouching_f": at(0x292310, "cmpi.w #$0032,($FF1A02).l",
                                   span=0x20),
            "freeze_f": script_mark(0x1D6EBE, 0x06, 0),
            "sound": at(0x291FC2, "pea ($00004C).w", span=0x10),
            "anim": "$1D6EBE",
        },
        "leave": {
            "hold_f": at(0x29351C, "cmpi.w #$0032,($FF1A02).l", span=0x20),
            "hold_crouching_f": at(0x293670, "cmpi.w #$0032,($FF1A02).l",
                                   span=0x20),
            "freeze_f": script_mark(0x1D779E, 0x06, 0),
            "sound": at(0x29351C, "pea ($00004C).w", span=0x60),
            "crouching_anim_f": script_end(0x1D8C48),
            "fuel_out_anim": "$1D8C48",
        },
        "fuel_dash_drain_per_f": at(0x293BD2, "moveq #2,d0"),
        "movement": {
            "walk_a": at(0x29378A, "addi.w #$0080,d2", span=0x20),
            "walk_max_v": at(0x29378A, "cmpi.w #$0400,d2", span=0x20),
            "stop_keep_half_from_v": at(0x29376E, "cmpi.w #$0400,d2",
                                        span=0x10),
            "stand_decay_div": D(2, "asr.w $16(a0): половина за кадр",
                                 at(0x2935DC, "asr.w $16(a0)", span=0x10,
                                    value=2)),
            "walk_keep_with_a_f": script_mark(0x1D77D8, 0x05, 0),
            "jump_v": at(0x2937FC, "move.w #$FA10,$18(a0)"),
            "run_jump_v": pair(at(0x2937FC, "move.w #$0300,$16(a0)"),
                               at(0x2937FC, "move.w #$FA30,$18(a0)")),
            "short_jump_a": at(0x29385C, "addi.w #$0080,d2", span=0x20),
            "short_jump_until_v": at(0x29385C, "cmpi.w #$FE80,d2",
                                     span=0x20),
            "short_jump_from_f": script_mark(0x1D7B8C, 0x05, 1),
            "run_short_jump_from_f": script_mark(0x1D7B42, 0x05, 1),
            "landing_sound": at(0x2937A4, "pea ($000005).w", span=0x60),
            "crouch_sound": at(0x2935DC, "pea ($00004B).w", span=0x40),
        },
        "dash": {
            "v": at(0x293494, "move.w #$0800,$16(a0)", span=0x50),
            "sound": at(0x293494, "pea ($00005C).w", span=0x50),
            "tap_max_f": at(0x2A4B0A, "cmpi.b #$0F,d3", nth=0),
            "trail_every_f": D(4, "moveq #3 / and кадрового счётчика",
                               at(0x293BD2, "moveq #3,d2", span=4)),
            "trail_behind_px": at(0x293B88, "move.w #$0010,d0", span=0x20),
            "trail_f": script_mark(0x1D6E7A, 0x06, 1),
            "anim": "$1D7AC2",
        },
        "attack": {
            "damage": at(0x2987EE, "move.b #$04,$43(a0)", span=0x10),
            "combo_extra_max": D(4, "cmpi.w #5 / bge: не больше 4",
                                 at(0x2A4934, "cmpi.w #$0005,d6")),
            "sounds": [db(0x1EABE8 + i) for i in range(4)],
            "combo": combo,
            "crouching": dict(strike(0x1D7A9E), anim="$1D7A9E"),
            "air": dict(strike(0x1D7982), anim="$1D7982"),
        },
        "brace": {
            "window_f": script_mark(0x1D7AE0, 0x05, 0),
            "hands_up_px": neg(at(0x293A1A, "subi.w #$002E,d1", span=0x40)),
            "wall_left_px": D(-42, "-$1A - $10",
                              at(0x293A1A, "subi.w #$001A,d0", span=0x40),
                              at(0x293A1A, "subi.w #$0010,d0", span=0x40)),
            "gap_left_px": neg(at(0x293A1A, "subi.w #$001A,d0",
                                  span=0x40)),
            "wall_right_from_cell_px": at(0x293A72, "addi.w #$0040,d0",
                                          span=8),
            "center_from_cell_px": D(32, "+$40 - $20 от клетки x-$1A",
                                     at(0x293A72, "addi.w #$0040,d0",
                                        span=8),
                                     at(0x293ABC, "subi.w #$0020,d0",
                                        span=8)),
            "post_up_px": at(0x2938D2, "subi.w #$0030,d0"),
            "post_up_tol_px": at(0x2938D2, "cmpi.w #$0008,d0"),
            "post_side_px": at(0x2938D2, "subi.w #$0022,d0"),
            "post_side_tol_px": at(0x2938D2, "cmpi.w #$000C,d0", nth=0),
            "sound": at(0x293AE4, "pea ($00000E).w", span=0x10),
            "pullup_jump_f": script_mark(0x1D7B0E, 0x06, 2),
            "pullup_jump_v": script_field(0x1D7B0E, 0x18),
            "pullup_lift_px": at(0x293B00, "subi.w #$0008,$14(a0)",
                                 span=0x40),
            "pullup_lift_rising_px": at(0x293B00, "subi.w #$0010,$14(a0)",
                                        span=0x40),
            "post_break_f": D(66, "перезарядка $3C (61 кадр) + 5 тактов "
                              "скрипта до бита 14",
                              at(0x29A4A4, "move.w #$003C,$6(a0)",
                                 span=0x20),
                              script_mark(0x1D8B70, 0x30, 0x4000)),
        },
        "hook": {
            "hang_below_px": at(0x29A2BA, "addi.w #$0020,d0", span=0x20),
            "sound": at(0x29A28C, "pea ($00000E).w", span=0x30),
            "phase_f": cmd(0x1D79C2, [0xE1, 0x26]),
            "phases": D(10, SCRIPT_SRC % 0x1D79C2 + u": +$4E = 0..9"),
            "release": hook_release(),
            "anim": "$1D79C2",
        },
        "hurt_f": script_end(0x1D7BFA),
        "hurt_tile_bounce_v": script_field(0x1D7C2E, 0x18),
    }


def small():
    """Уменьшенный облик: кто уменьшает, ход, бросок."""
    offs = [{"ahead_px": dw(0x1EAAC6 + 4 * i + 2),
             "up_px": dw(0x1EAAC6 + 4 * i)} for i in range(3)]
    low = {"ahead_px": at(0x294504, "move.l #$FFF80014,d4", part="lo"),
           "up_px": at(0x294504, "move.l #$FFF80014,d4", part="hi")}
    return {
        "caster": {
            "cell_code": D(168, "код клетки уровня 8 -> $29F33C"),
            "spell_ahead_px": at(0x29F3BE, "moveq #42,d3", span=0x30),
            "spell_touch_code": at(0x29F3BE, "move.w #$00DE,d4", span=0x40),
            "spell_f": script_mark(0x1D9684, 0x06, 1),
            "sound": at(0x29F410, "pea ($000093).w", span=0x20),
            "shrink_freeze_f": script_mark(0x1D7E8E, 0x06, 0),
            "grow_freeze_f": script_mark(0x1D7EE4, 0x06, 0),
        },
        "movement": {
            "walk_a": at(0x2945E4, "addi.w #$0080,d2", span=0x20),
            "walk_max_v": at(0x2945E4, "cmpi.w #$0300,d2", span=0x20),
            "release_div": D(4, "lsr.w #2",
                             at(0x29461A, "lsr.w #2,d2", span=0x30)),
            "release_decay_div": D(4, "asr.w #2: вычесть четверть за кадр",
                                   at(0x294424, "asr.w #2,d2", span=0x10)),
            "jump_v": at(0x2942D6, "move.w #$FB80,$18(a0)"),
            "run_jump_v": pair(at(0x2942D6, "move.w #$0300,$16(a0)"),
                               at(0x2942D6, "move.w #$FB90,$18(a0)")),
            "short_jump_a": at(0x294672, "addi.w #$0080,d2", span=0x20),
            "short_jump_until_v": at(0x294672, "cmpi.w #$FE80,d2",
                                     span=0x20),
            "short_jump_from_f": script_mark(0x1D7D2C, 0x05, 1),
        },
        "throw_from": {"ahead": offs[0], "up": offs[1], "diagonal": offs[2],
                       "crouching_or_air": low},
        "throw_at_f": script_mark(0x1D7C86, 0x05, 1),
        "hurt_f": script_end(0x1D7E74),
    }


def touch():
    return {
        "box_bits": {
            "body": D(14, "(d6^d7) & $4000 в $299AD0",
                      at(0x299AD0, "andi.w #$4000,d0", nth=0)),
            "attack_mask": at(0x299AD0, "move.w #$0F00,d0", nth=0,
                              signed=False),
            "hook": D(15, "tst.w d6 / bpl в $2A35CA: нужен бит 15",
                      at(0x2A35CA, "tst.w d6", nth=0, value=15)),
        },
        "clash_sound": at(0x299A8E, "pea ($00004D).w"),
        "box_record_bytes": D(6, "шаг коробки", at(0x2964DA,
                                                   "adda.l #$00000006,a2")),
        "pickup": {
            "weapon_code": D(22, "код клетки -> $29A0AE"),
            "ammo_codes": [D(23, "-> $29A0E0, запас $FF1A22"),
                           D(24, "-> $29A0EC, запас $FF1A24"),
                           D(25, "-> $29A0F8, запас $FF1A26")],
            "weapon_sound": at(0x29A0AE, "pea ($000027).w"),
        },
    }


# ------------------------------------------------------------ виды

CENSUS = None


def census(*ctors):
    """Где стоят клетки этих конструкторов: уровни и число клеток."""
    global CENSUS
    if CENSUS is None:
        CENSUS = E.census()
    cells, where = CENSUS
    lv, n = set(), 0
    for (code, c), k in cells.items():
        if c in ctors:
            n += k
            lv |= set(where[(code, c)])
    why = "перепись клеток карты (enemies.census) по конструкторам %s" % (
        ", ".join(hexa(c) for c in ctors))
    return {"levels": D(sorted(lv), why), "cells": D(n, why)}


def hp_default():
    return D(0, "не задаётся: $2996C2 обнуляет +$1C",
             at(0x2996C2, "move.w d5,$1C(a0)", value=0))


def dmg_default():
    return bcd(at(0x2996C2, "move.b #$10,$43(a0)", signed=False))


def every(x):
    """Счётчик с перезарядкой n срабатывает раз в n + 1 кадров."""
    if not ok(x):
        return x
    return D(x.v + 1, "перезарядка n: раз в n + 1 кадров", x)


def p256(x):
    """Команда `$86 nn`: вероятность (nn + 1)/256."""
    if not ok(x):
        return x
    return D(x.v + 1, "команда $86 nn: вероятность (nn + 1)/256", x)


def prog_anim(a):
    """Скрипт из команды программы `84 00 <длинное>`."""
    x = cmd(a, [0x84, 0x00], size=2)
    if not ok(x):
        return x
    return dl(a + 2, addr=True)


def core(upd, span=0x100):
    """Неуязвимость и маска: `d1` и `d2` перед первым вызовом ядра урона."""
    near = [a for a in E.ADDRS if upd <= a < upd + span]
    for i, a in enumerate(near):
        if "loc_2A2C48" in E.BY[a]:
            got = {}
            for b in near[max(0, i - 3):i]:
                t = E.BY[b]
                if t.endswith(",d1"):
                    got["inv_f"] = V(_operand(t, None, True),
                                     "%s: %s" % (hexa(b), t))
                elif t.endswith(",d2"):
                    got["mask"] = V(_operand(t, None, False) & 0xFFFF,
                                    "%s: %s" % (hexa(b), t))
            if len(got) == 2:
                return got
            break
    return {"inv_f": _fail("%s: не найден вызов ядра урона" % hexa(upd)),
            "mask": V(None, "")}


def k_green_spirit():
    c, u, g = 0x2A2E04, 0x2A2E3E, 0x2A2F5E
    k = {"kinds": [1], "ctors": [hexa(c)], "update": hexa(u),
         "anim": at(c, "$22(a0)", addr=True),
         "hp": hp_default(), "damage": dmg_default(),
         "target": "idol",
         "retarget_every_f": every(at(u, "move.w #$0007,$6(a0)")),
         "aim_offset_px": pair(at(u, "moveq #-41,d0", nth=0),
                               at(u, "moveq #6,d1")),
         "aim_bresenham_steps": at(u, "move.w #$0004,d7"),
         "speed_major_v": D(4 << 6, "4 шага Брезенхэма << 6",
                            at(u, "asl.w #6,d4")),
         "grab_dist_px": at(u, "cmpi.w #$0006,d0", nth=0),
         "grab_anim": at(u, "move.l #$001DB59A,$22(a0)", addr=True),
         "grab_sound": at(u, "pea ($000083).w"),
         "carry_v": pair(at(g, "move.l #$FF00FF80,$16(a0)", part="hi"),
                         at(g, "move.l #$FF00FF80,$16(a0)", part="lo")),
         "carry_offset_px": pair(at(0x2A2F3C, "moveq #41,d0"),
                                 at(0x2A2F3C, "moveq #-6,d1")),
         "lose_if_left_of_scroll_px": at(g, "cmpi.w #$FFC0,d0"),
         "lose_if_right_of_scroll_px": at(g, "cmpi.w #$0180,d0"),
         "death_sound": at(u, "pea ($000078).w")}
    k.update(core(u))
    k.update(census(c))
    return k


def native_common(ctors, upd, chain_hi, chain_far):
    k = {"ctors": [hexa(c) for c in ctors], "update": hexa(upd),
         "hp": at(0x29F2A4, "move.w #$0004,$1C(a0)"),
         "damage": dmg_default(),
         "hit_sound": at(upd, "pea ($000032).w", nth=0),
         "death_sound": at(upd, "pea ($000078).w", nth=0),
         "idle_anim": prog_anim(0x1FF226),
         "hurt_prog": "$1FF24A",
         "hurt_inv_f": cmd(0x1D93CE, [0xDC, 0x0A]),
         "hurt_alt_anim_p256": p256(cmd(0x1FF254, [0x86], size=1,
                                        signed=False)),
         "lunge": {
             "dist_px": at(chain_hi, "cmpi.w #$0080,d1", span=0x10),
             "prog": "$1FF232",
             "anim": prog_anim(0x1FF232),
             "speed_v": cmd(0x1D94C4, [0xDC, 0x16]),
             "edge_probe_px": at(0x2AA476, "moveq #16,d6", span=0x40),
             "wall_probe_px": at(0x2AA476, "moveq #16,d3", span=0x40)},
         }
    k.update(core(upd))
    k.update(census(*ctors))
    if chain_far:
        k["far_dist_px"] = at(chain_far, "cmpi.w #$00C0,d1", span=0x10)
    return k


def k_spear_native():
    k = native_common((0x2A0DC4, 0x29F2D6, 0x29F2F2), 0x2AAAA0,
                      0x2AA95E, 0x2AA96E)
    k["kinds"] = [2, 10, 31]
    k["spear"] = {
        "prog": "$1FF23E", "anim": prog_anim(0x1FF23E),
        "spawn_ahead_px": at(0x2AA4CC, "moveq #48,d0", span=0x80),
        "speed_v": at(0x2AA4CC, "move.w #$0300,$16(a0)", span=0x80),
        "sound": at(0x2AA4C0, "pea ($000037).w", span=0x40),
        "flight": "прямо, до твёрдой клетки"}
    return k


def k_boomerang_native():
    k = native_common((0x2A0DFC, 0x29F320, 0x2A0E18), 0x2AABC0,
                      0x2AA95E, 0x2AA96E)
    b, arc = 0x2AA604, 0x2AA6A0
    k["kinds"] = [6, 13, 33]
    k["boomerang"] = {
        "prog": "$1FF274",
        "sound": at(0x2AA860, "pea ($000074).w", span=0x40),
        "spawn_ahead_px": at(b, "moveq #48,d0"),
        "spawn_up_px": at(b, "subi.w #$0010,$14(a0)"),
        "straight_v": pair(at(b, "move.l #$08000180,$16(a0)", part="hi"),
                           at(b, "move.l #$08000180,$16(a0)", part="lo")),
        "straight_dist_px": at(0x2AA67A, "cmpi.w #$0080,d0", span=0x20),
        "arc_turn_per_f_turn": neg(at(arc, "subi.w #$0018,d3")),
        "arc_stop_below_turn": at(arc, "cmpi.w #$0180,d3"),
        "arc_speed_v": trig_v(at(arc, "asr.w #4,d1")),
        "return_behind_px": at(arc, "addi.w #$0010,d0", span=0x80)}
    return k


def k_weight_native():
    k = native_common((0x2A0DE0, 0x29F304), 0x2AAB42, 0x2AA95E, None)
    w, r = 0x2AA540, 0x2AA742
    k["kinds"] = [8, 9]
    k["drop_dist_px"] = at(0x2AA97E, "cmpi.w #$0020,d1", span=0x10)
    k["weight"] = {
        "prog": "$1FF268",
        "sound": cmd(0x1D9804, [0xEA], size=1, signed=False),
        "spawn_ahead_px": at(w, "moveq #16,d0"),
        "spawn_below_px": at(w, "addi.w #$0030,$14(a0)"),
        "drop_v": at(w, "move.w #$0400,$18(a0)"),
        "drop_depth_px": at(r, "addi.w #$0050,d0"),
        "hang_f": at(r, "move.w #$001E,$6(a0)"),
        "rise_v": at(r, "move.w #$FB00,$18(a0)"),
        "rise_stop_px": at(r, "addi.w #$0014,d0"),
        "rope_px_per_frame": D(16, "lsr.w #4: длина / 16",
                               at(0x2AA70A, "lsr.w #4,d0")),
        "rope_max": at(0x2AA70A, "moveq #7,d0")}
    return k


def k_ninja_duck():
    c, u = 0x29B95C, 0x2A9FF0
    k = {"kinds": [3], "ctors": [hexa(c)], "update": hexa(u),
         "hp": at(c, "move.w #$0008,$1C(a0)"), "damage": dmg_default(),
         "active_margin_px": pair(
             at(u, "move.l #$01000080,d7", part="hi"),
             at(u, "move.l #$01000080,d7", part="lo")),
         "prog": "$1FEEC0",
         "wait_anim": prog_anim(0x1FEEC0),
         "wake_dist_px": at(0x2A9BC0, "cmpi.w #$00D0,d1", span=0x20),
         "walk_v": cmd(0x1FEEC8, [0x81, 0x16]),
         "walk_anim": prog_anim(0x1FEECC),
         "attack_dist_px": pair(at(0x2A9BEA, "cmpi.w #$0080,d1"),
                                at(0x2A9BEA, "cmpi.w #$0020,d1")),
         "edge_probe_px": at(0x2A9BEA, "moveq #16,d6", nth=0),
         "wall_probe_px": at(0x2A9BEA, "moveq #32,d3"),
         "strike_anims": [prog_anim(0x1FEED8), prog_anim(0x1FEEE0)],
         "hurt_prog": "$1FEEEC",
         "hurt_anim": prog_anim(0x1FEEEC),
         "hurt_bounce_v": pair(cmd(0x1FEEF4, [0x81, 0x16]),
                               cmd(0x1FEEF8, [0x81, 0x18])),
         "hit_sound": at(u, "pea ($000018).w", nth=0),
         "death_sound": at(u, "pea ($000078).w", nth=0)}
    k.update(core(u))
    k.update(census(c))
    return k


def k_green_fish():
    c, u = 0x2A2290, 0x2A22E0
    k = {"kinds": [4], "ctors": [hexa(c)], "update": hexa(u),
         "hp": at(c, "move.w #$0001,$1C(a0)"), "damage": dmg_default(),
         "dies_on_any_hit": D(True, "проверяет факт попадания, не жизни"),
         "swim_anim": at(c, "move.l #$001DAEC2,$22(a0)", addr=True),
         "swim_v": at(c, "move.w #$0080,$16(a0)"),
         "patrol_half_px": at(c, "subi.w #$0040,d0"),
         "bob_step_turn": half(at(u, "addi.w #$000C,d0")),
         "bob_amp_px": amp(at(u, "lsl.l #5,d0")),
         "notice_dist_px": at(u, "cmpi.w #$0070,d0", nth=0),
         "open_anim": at(u, "move.l #$001DAECA,$22(a0)", addr=True),
         "death_sound": at(u, "pea ($00007B).w")}
    k.update(core(u))
    k.update(census(c))
    return k


def k_beetle():
    c, u = 0x29DECC, 0x2A9A16
    k = {"kinds": [5, 29], "ctors": ["$29DFC4", "$29DFDA"],
         "update": hexa(u),
         "hp": at(c, "move.w #$0001,$1C(a0)"), "damage": dmg_default(),
         "prog": "$1FEE70", "anim": prog_anim(0x1FEE70),
         "dash_v": pair(cmd(0x1D8010, [0xDC, 0x16]),
                        cmd(0x1D8014, [0xDC, 0x18])),
         "dash_f": D(16, "4 кадра по 4",
                     cmd(0x1D800C, [0xE1, 0x26])),
         "pause_f": cmd(0x1D8028, [0xD8], size=1, signed=False),
         "pause_again_p256": D(129, "DB 80 назад на паузу: переход, если "
                                    "байт жребия не больше $80 ($29714E: "
                                    "cmp.b d0,d1 / bcs) — 129 из 256",
                               cmd(0x1D802C, [0xDB], size=1,
                                   signed=False)),
         "turns": "после каждого рывка по очереди: бит 11, бит 12",
         "bonus_token_variant": at(0x29DFDA, "bset #2,$31(a0)",
                                   value="$29DFDA"),
         "death_sound": at(u, "pea ($000078).w")}
    k.update(core(u))
    k.update(census(0x29DFC4, 0x29DFDA))
    return k


def k_larva():
    c, u = 0x29F47A, 0x29F4BC
    k = {"kinds": [7], "ctors": [hexa(c)], "update": hexa(u),
         "hp": hp_default(), "damage": dmg_default(),
         "anim": at(c, "move.l #$001D9180,$22(a0)", addr=True),
         "patrol_half_px": at(c, "subi.w #$0050,d0"),
         "crawl_v": [cmd(0x1D9188, [0xDC, 0x16]),
                     cmd(0x1D9190, [0xDC, 0x16]),
                     cmd(0x1D9196, [0xDC, 0x16])],
         "crawl_step_f": cmd(0x1D9182, [0xE1, 0x26]),
         "active_margin_px": pair(
             at(u, "move.l #$01000080,d7", part="hi"),
             at(u, "move.l #$01000080,d7", part="lo")),
         "edge_probe_px": at(0x29BA34, "addi.w #$0010,d1", span=0x20),
         "death_sound": at(u, "pea ($000079).w", nth=0)}
    k.update(core(u))
    k.update(census(c))
    return k


def k_fire_spirit():
    c, u, orb, shot, fly = 0x2A144A, 0x2A987E, 0x2A96A8, 0x2A9728, 0x2A97C4
    k = {"kinds": [11], "ctors": [hexa(c)], "update": hexa(u),
         "hp": at(c, "move.w #$0008,$1C(a0)"), "damage": dmg_default(),
         "orbit_step_turn": half(at(orb, "addi.w #$0012,d0")),
         "orbit_radius_px": pair(amp(at(orb, "lsl.l #6,d1")),
                                 amp(at(orb, "lsl.l #5,d1"))),
         "shot": {
             "sound": at(shot, "pea ($000082).w"),
             "spawn_ahead_px": at(shot, "move.w #$000E,d1"),
             "spawn_up_px": at(shot, "subi.w #$001C,d2"),
             "life_f": every(at(shot, "move.w #$00A0,$52(a0)")),
             "damage": bcd(at(shot, "move.b #$10,$43(a0)", signed=False)),
             "start_angle_facing_left_turn": at(shot,
                                                "move.w #$0200,$4C(a0)"),
             "retarget_every_f": every(at(fly, "move.w #$0006,$50(a0)")),
             "turn_per_f_turn": at(fly, "moveq #8,d0"),
             "speed_v": trig_v(at(0x2A9818, "asr.w #5,d1", nth=0)),
             "anim": at(shot, "move.l #$001D8FA6,$22(a0)", addr=True)},
         "hurt_prog": "$1FEDE2", "counter_prog": "$1FEDD6",
         "hit_sound": at(u, "pea ($00000E).w", nth=0),
         "death_sound": at(u, "pea ($000078).w", nth=0)}
    k.update(core(u))
    k.update(census(c))
    return k


def k_flying_insect():
    c, u = 0x2A0E2A, 0x2AB0CC
    k = {"kinds": [12, 14], "ctors": [hexa(c), "$29F448"],
         "update": hexa(u),
         "hp": at(c, "move.w #$0001,$1C(a0)"), "damage": dmg_default(),
         "patrol_v": cmd(0x1DB4B8, [0xDC, 0x16]),
         "notice_dist_px": at(0x2AB074, "cmpi.w #$0080,d1", span=0x10),
         "dive_target_px": pair(at(0x2AB084, "move.w #$FFB0,d2",
                                   span=0x40),
                                at(0x2AB084, "move.w #$FFC0,d2",
                                   span=0x40)),
         "seek_a": pair(at(0x2AAFB4, "move.w #$0050,($FF2204).l"),
                        at(0x2AAFB4, "move.w #$0060,($FF2206).l")),
         "seek_max_v": pair(at(0x2AAFB4, "move.w #$0400,($FF2208).l"),
                            at(0x2AAFB4, "move.w #$0300,($FF220A).l")),
         "climb_target_px": pair(at(0x2AB024, "move.w #$0060,d0"),
                                 at(0x2AB024, "move.w #$FF90,d1")),
         "dive_anim": "$1DB446",
         "dive_sounds": [cmd(0x1DB464, [0xEA], size=1, signed=False),
                         cmd(0x1DB47C, [0xEA], size=1, signed=False)],
         "hit_sound": at(u, "pea ($00000E).w", nth=0),
         "death_sound": at(u, "pea ($000078).w", nth=0)}
    k.update(core(u))
    k.update(census(c, 0x29F448))
    return k


def k_jumping_wedge():
    y, g, u, eat = 0x29F53E, 0x29DCA4, 0x29F58C, 0x29F6E0
    k = {"kinds": [15, 17], "ctors": [hexa(y), hexa(g)],
         "update": {"yellow": hexa(u), "green": "$29DCF2"},
         "hp": {"yellow": at(y, "move.w #$0003,$1C(a0)"),
                "green": at(g, "move.w #$0002,$1C(a0)")},
         "damage": dmg_default(),
         "anim": at(y, "move.l #$001DA514,$22(a0)", addr=True),
         "stand_f": cmd(0x1DA514, [0xD8], size=1, signed=False),
         "jump_v": cmd(0x1DA522, [0xDC, 0x18]),
         "jump_sound": cmd(0x1DA52E, [0xEA], size=1, signed=False),
         "descend_from_v": at(u, "cmpi.w #$0080,$18(a0)"),
         "land_sound": at(u, "pea ($00000D).w", nth=0),
         "hit_sound": at(u, "pea ($000079).w", nth=0),
         "death_sound": at(u, "pea ($000078).w", nth=0),
         "swallow": {
             "only_in_states": [D(1, "cmpi.b #$01 / #$02 в $29F6E0"),
                                D(2, "cmpi.b #$01 / #$02 в $29F6E0")],
             "reach_px": pair(at(eat, "moveq #16,d3"),
                              at(eat, "moveq #24,d4")),
             "damage": bcd(at(eat, "moveq #37,d0")),
             "player_state": at(eat, "move.b #$28,$4(a0)"),
             "chew_anim": {"yellow": at(eat, "move.l #$001DA564,$22(a1)",
                                        addr=True),
                           "green": at(0x29DE46, "move.l #$001DA4F8,$22(a1)",
                                       addr=True)},
             "spit_delay_f": cmd(0x1DA570, [0xD8], size=1, signed=False),
             "rest_after_f": cmd(0x1DA578, [0xD8], size=1, signed=False),
             "spit_v": pair(at(u, "move.l #$0000F800,$16(a1)", span=0x160,
                               part="hi"),
                            at(u, "move.l #$0000F800,$16(a1)", span=0x160,
                               part="lo")),
             "spit_player_state": at(u, "move.b #$0B,$4(a1)", span=0x160)}}
    k.update(core(u))
    k.update(census(y, g))
    return k


def k_fireball_native():
    c, u = 0x2A339C, 0x2AAEF0
    k = {"kinds": [16, 22], "ctors": [hexa(c), "$2A2C02"],
         "update": hexa(u),
         "hp": at(c, "move.w #$0008,$1C(a0)"), "damage": dmg_default(),
         "strike_dist_px": at(0x2AAE62, "cmpi.w #$0068,d1", span=0x10),
         "walk_dist_px": at(0x2AAE72, "cmpi.w #$00D0,d1", span=0x10),
         "strike_prog": "$1FF334", "walk_prog": "$1FF328",
         "walk_v": cmd(0x1DADD4, [0xDC, 0x16]),
         "restrike_p256": p256(cmd(0x1FF33C, [0x86], size=1,
                                   signed=False)),
         "hurt_prog": "$1FF344",
         "hit_sound": at(u, "pea ($000015).w", nth=0),
         "death_anim": at(u, "move.l #$001DAE40,$22(a0)", addr=True),
         "death_sound": at(u, "pea ($000078).w", nth=0)}
    k.update(core(u))
    k.update(census(c, 0x2A2C02))
    return k


def k_dark_fish():
    c, u, m, s = 0x2A27DE, 0x2A281E, 0x2A2A20, 0x2A297E
    k = {"kinds": [18], "ctors": [hexa(c)], "update": hexa(u),
         "hp": at(c, "move.w #$0008,$1C(a0)"), "damage": dmg_default(),
         "wake_dist_px": at(u, "cmpi.w #$00C8,d0"),
         "wake_sound": cmd(0x1DACC0, [0xEA], size=1, signed=False),
         "first_wait_f": every(cmd(0x1DACDA, [0xDC, 0x06])),
         "next_wait_f": every(cmd(0x1DAD18, [0xDC, 0x06])),
         "release_anim": at(u, "move.l #$001DAD44,$22(a0)", addr=True),
         "hit_sound": at(u, "pea ($000079).w", nth=0),
         "death_anim": at(u, "move.l #$001DAD9C,$22(a0)", addr=True),
         "death_sound": at(u, "pea ($000078).w", nth=0),
         "companion": {
             "update": hexa(m),
             "spawn_ahead_px": at(s, "move.w #$002C,d1"),
             "spawn_up_px": at(s, "subi.w #$0012,d1"),
             "target_up_px": at(0x2A29EA, "subi.w #$0010,d2"),
             "seek_a": pair(at(0x2A2B3E, "move.w #$0050,($FF2204).l"),
                            at(0x2A2B3E, "move.w #$0040,($FF2206).l")),
             "seek_max_v": pair(
                 at(0x2A2B3E, "move.w #$0300,($FF2208).l"),
                 at(0x2A2B3E, "move.w #$0200,($FF220A).l")),
             "reach_px": at(m, "cmpi.w #$0020,d1"),
             "hover_f": every(at(m, "move.w #$003C,$6(a0)")),
             "passes": at(m, "cmpi.w #$0004,d0", nth=0),
             "retreat_px": pair(at(0x2A29FC, "move.w #$00A0,d2"),
                                at(0x2A29FC, "moveq #-112,d2")),
             "return_px_per_frame": at(m, "moveq #4,d1", nth=0),
             "return_up_px": at(m, "subi.w #$002C,d2", span=0x120)}}
    k.update(core(u))
    k.update(census(c))
    return k


def k_zombie():
    c, u = 0x2A33DE, 0x2AB1E4
    k = {"kinds": [19, 23, 34], "ctors": ["$2A344A", "$2A33DE", "$2A3438"],
         "update": hexa(u),
         "hp": at(c, "move.w #$0006,$1C(a0)"), "damage": dmg_default(),
         "wake_dist_px": at(0x2AB192, "cmpi.w #$0050,d1", span=0x10),
         "rise_sound": cmd(0x1DB47C, [0xEA], size=1, signed=False),
         "walk_half_px": at(c, "move.w #$0080,$4E(a0)"),
         "walk_v": cmd(0x1DB524, [0xDC, 0x16]),
         "hurt_inv_f": cmd(0x1DB508, [0xDC, 0x0A]),
         "hurt_prog": "$1FF3DC",
         "hit_sound": at(u, "pea ($000079).w", nth=0),
         "death_anim": at(u, "move.l #$001DB566,$22(a0)", addr=True,
                           nth=0)}
    k.update(core(u))
    k.update(census(0x2A344A, 0x2A33DE, 0x2A3438))
    return k


def k_voodoo_mask():
    c, u, t = 0x29E274, 0x29E36C, 0x29E2BA
    k = {"kinds": [20], "ctors": [hexa(c)], "update": hexa(u),
         "hp": hp_default(), "damage": dmg_default(),
         "box_half_px": pair(at(c, "subi.l #$00140018,d0", part="hi"),
                             at(c, "subi.l #$00140018,d0", part="lo")),
         "fly_v": pair(at(c, "move.l #$00800080,$16(a0)", part="hi"),
                       at(c, "move.l #$00800080,$16(a0)", part="lo")),
         "notice_dist_px": at(u, "cmpi.w #$00C0,d0", span=0x120),
         "throw": {
             "sound": at(u, "pea ($00004F).w", span=0x120),
             "spawn_px": pair(at(t, "moveq #18,d1"), at(t, "moveq #13,d2")),
             "vy_v": at(t, "move.w #$FF00,$18(a0)"),
             "vx_base_v": at(t, "move.w #$0280,d0"),
             "vx_from_dist_px": at(t, "subi.w #$0080,d2"),
             "vx_gain_per_px": D(8, "lsl.w #3", at(t, "lsl.w #3,d2")),
             "spark_every_f": D(4, "moveq #3 / and кадровый счётчик",
                                at(0x29E35E, "moveq #3,d0", span=4))},
         "death_sound": at(u, "pea ($000078).w", nth=0)}
    k.update(core(u))
    k.update(census(c))
    return k


def k_small_insect():
    c, u = 0x29F162, 0x29F18E
    tab = 0x1FE952
    k = {"kinds": [21], "ctors": [hexa(c)], "update": hexa(u),
         "hp": hp_default(), "damage": dmg_default(),
         "shard_count": D(8, "moveq #7 и dbf", at(u, "moveq #7,d0")),
         "shards": [{"frame": dw(tab + 6 * i), "v": pair(
             dw(tab + 6 * i + 2), dw(tab + 6 * i + 4))} for i in range(8)]}
    k.update(core(u))
    k.update(census(c))
    return k


def k_butler():
    c, u, srv, puff = 0x29E06E, 0x29E0A0, 0x29E226, 0x29DF1C
    k = {"kinds": [24], "ctors": [hexa(c)], "update": hexa(u),
         "hp": at(c, "move.w #$0004,$1C(a0)"), "damage": dmg_default(),
         "serve_dist_px": at(u, "cmpi.w #$0090,d1"),
         "serve_offset_px": pair(at(srv, "moveq #32,d0"),
                                 neg(at(srv, "subi.w #$0020,d2"))),
         "max_fighters": at(srv, "cmpi.w #$0003,d0"),
         "puff_p256": D(128, "andi.w #$0001 от случайного",
                        at(srv, "andi.w #$0001,d0")),
         "critter": {"prog": "$1FEDEE",
                     "jump_v": pair(cmd(0x1D80E8, [0xDC, 0x16]),
                                    cmd(0x1D80EC, [0xDC, 0x18])),
                     "walk_v": cmd(0x1D80FC, [0xDC, 0x16])},
         "puff": {"anim": at(puff, "move.l #$001DB198,$22(a0)", addr=True),
                  "touch_code": at(puff, "move.w #$00F1,d4",
                                   signed=False),
                  "sound": cmd(0x1DB1AE, [0xEA], size=1, signed=False),
                  "life_f": D(4 * 3 + 6 * 4, "4 кадра по 3 и 6 по 4",
                              cmd(0x1DB19A, [0xE1, 0x26]),
                              cmd(0x1DB1A6, [0xE1, 0x26]))},
         "hit_sound": at(u, "pea ($000081).w", nth=0),
         "death_sound": at(u, "pea ($000078).w", nth=0)}
    k.update(core(u))
    k.update(census(c))
    return k


def destructibles():
    def one(kind, c, u, extra):
        k = {"kinds": [kind], "ctors": [hexa(c)], "update": hexa(u)}
        k.update(core(u))
        k.update(census(c))
        k.update(extra)
        return k
    return {
        "red_drop": one(25, 0x2A0EDE, 0x2A0F3A, {
            "hit_sound": at(0x2A0F3A, "pea ($00006B).w")}),
        "tnt_barrel": one(26, 0x2A1822, 0x2A1850, {}),
        "blue_crate": {"kinds": [27], "ctors": ["$2A1BC4"],
                       "chain_links": at(0x2A1A9A, "moveq #4,d0"),
                       "anchor_px": at(0x2A1A9A, "moveq #40,d6")},
        "mine": {"kinds": [28], "ctors": ["$2A1C06"],
                 "update": "$2A1CB4", "shards_table": "$1FEA4A",
                 "blast_hits_flags": at(0x2A1E0C, "move.w #$1080,d7",
                                        signed=False)},
        "dark_weight": one(32, 0x29FB6A, 0x29FBAE, {
            "flag_after_f": every(at(0x29FBAE, "move.w #$003C,$4C(a0)")),
            "roll_every_f": every(at(0x29FBD2, "move.w #$0014,$6(a0)")),
            "roll_sound": at(0x29FBD2, "pea ($00006F).w")}),
    }


def enemies():
    return {
        "green_spirit": k_green_spirit(),
        "spear_native": k_spear_native(),
        "ninja_duck": k_ninja_duck(),
        "green_fish": k_green_fish(),
        "beetle": k_beetle(),
        "boomerang_native": k_boomerang_native(),
        "weight_native": k_weight_native(),
        "larva": k_larva(),
        "fire_spirit": k_fire_spirit(),
        "flying_insect": k_flying_insect(),
        "jumping_wedge": k_jumping_wedge(),
        "fireball_native": k_fireball_native(),
        "dark_fish": k_dark_fish(),
        "zombie": k_zombie(),
        "voodoo_mask": k_voodoo_mask(),
        "small_insect": k_small_insect(),
        "butler": k_butler(),
        "destructibles": destructibles(),
    }


# ------------------------------------------------------------ боссы

def b_shaman():
    c, u, hit, boom = 0x29E47A, 0x2A6888, 0x2A65F6, 0x2A67FC
    k = {"kind": 30, "ctor": hexa(c), "update": hexa(u), "prog": "$1FF3EC",
         "hp": at(c, "move.w #$005A,$1C(a0)"),
         "damage": bcd(at(c, "move.b #$10,$43(a0)", signed=False)),
         "spawn_sound": at(c, "pea ($000054).w"),
         "arena_x_px": [at(0x2A65C8, "cmpi.w #$0030,d0"),
                        at(0x2A65C8, "cmpi.w #$01E0,d0")],
         "walk": {"anim": "$1DBCCA",
                  "wait_f": cmd(0x1DBCFC, [0xD8], size=1, signed=False),
                  "slide_v": cmd(0x1DBD1C, [0xDC, 0x16])},
         "turn_shift_px": at(0x2A675E, "moveq #29,d0"),
         "strike": {
             "anim": "$1DBC10",
             "sound": cmd(0x1DBC10, [0xEA], size=1, signed=False),
             "point_ahead_px": at(hit, "move.w #$008E,d0"),
             "half_px": pair(at(hit, "cmpi.w #$0018,d0"),
                             at(hit, "cmpi.w #$0018,d1")),
             "y_offset_px": at(hit, "moveq #16,d1"),
             "damage": bcd(at(hit, "moveq #16,d0"))},
         "summon": {
             "anim": "$1DBDAE",
             "shake": at(0x2A66EC, "move.w #$0006,($FF04D2).l"),
             "sound": at(0x2A66EC, "pea ($00000B).w", span=0x40),
             "drops": [
                 {"dx_px": D(0, "над игроком"),
                  "delay_f": at(0x2A66C4, "move.w #$0001,d7")},
                 {"dx_px": at(0x2A66C4, "moveq #64,d1"),
                  "delay_f": at(0x2A66C4, "move.w #$000F,d7")},
                 {"dx_px": at(0x2A66C4, "moveq #-64,d1"),
                  "delay_f": at(0x2A66C4, "move.w #$001E,d7")}],
             "bounce_v": at(0x2A6660, "move.w #$FE80,$18(a0)", span=0x40)},
         "hit_voice": D(0x71, "всегда $71: выбор идёт по d7 = $70, а "
                              "случайное число $296B0C кладёт в d0",
                        at(0x2A6798, "move.w #$0071,d7")),
         "death": {
             "prog": "$1FF474",
             "explosions": at(0x2A6798, "move.w #$000D,$4C(a0)", span=0x80),
             "every_f": every(at(boom, "move.w #$000F,$6(a0)")),
             "spread_px": pair(amp(at(boom, "lsl.l #7,d1")),
                               amp(at(boom, "lsl.l #6,d2"))),
             "y_shift_px": neg(at(boom, "subi.w #$0010,d2")),
             "sound_every_other": at(boom, "pea ($0000A8).w")}}
    k.update(core(u))
    k.update(census(c))
    return k


def b_ninja_school():
    lv, lead = 0x2A61A2, 0x2A410C
    waves = []
    spots = ((0x2A3EC0, "$1FEF8C", "$2AA090"), (0x2A3EEA, "$1FF020",
              "$2AA132"), (0x2A3F18, "$1FF148", "$2AA266"),
             (0x2A3F42, "$1FF0B4", "$2AA1CC"))
    for a, prog, upd in spots:
        waves.append({"prog": prog, "update": upd,
                      "appear_px": pair(at(a, "move.w #", nth=0),
                                        at(a, ",d2", nth=0))})
    return {
        "level_proc": hexa(lv),
        "music": at(lv, "pea ($000054).w"),
        "mentors_px": [pair(at(lv, "move.w #$00F9,d1", nth=0),
                            at(lv, "move.w #$0130,d2", nth=0)),
                       pair(at(lv, "move.w #$0184,d1"),
                            at(lv, "move.w #$0130,d2", nth=1))],
        "leader": {
            "first_turn_f": every(at(lv, "move.w #$005A,$6(a0)")),
            "turn_every_f": every(at(lead, "move.w #$00C8,$6(a0)")),
            "wave_sound": at(lead, "pea ($000074).w"),
            "pattern": [db(0x1FED32 + i) for i in range(16)],
            "throw_split_x_px": at(lead, "cmpi.w #$0140,d0")},
        "critter": {
            "a": {"touch_code": at(0x2A3B04, "move.w #$0003,d4"),
                  "anim": at(0x2A3B04, "move.l #$001D8990,$22(a0)",
                             addr=True)},
            "b": {"touch_code": at(0x2A3B60, "move.w #$0007,d4"),
                  "anim": at(0x2A3B60, "move.l #$001D8C84,$22(a0)",
                             addr=True)},
            "launch_v": pair(at(0x2A3B04, "move.w #$0200,d0"),
                             at(0x2A3B04, "move.w #$FB00,$18(a0)")),
            "life_after_landing_f": every(at(0x2A3B04,
                                             "move.w #$00B4,$6(a0)")),
            "gravity_a": at(0x2A3BBC, "addi.w #$0020,d0")},
        "throw": {
            "vy_v": at(0x2A3C46, "move.w #$FB00,$18(a0)"),
            "arena_mid_px": at(0x2A3C46, "subi.w #$0140,d0"),
            "vx_minus_px": at(0x2A3C46, "subi.w #$0040,d0"),
            "vx_gain": D(4, "lsl.w #2", at(0x2A3C46, "lsl.w #2,d0"))},
        "student": {
            "hp": at(0x2A3E74, "move.w #$0014,$1C(a0)"),
            "spawn_up_px": at(0x2A3E74, "subi.w #$0018,d2"),
            "inv_f": core(0x2AA090)["inv_f"],
            "mask": core(0x2AA090)["mask"]},
        "waves": [
            [waves[0]], [waves[1]], [waves[2]], [waves[3]],
            [{"prog": "$1FF020", "update": "$2AA132",
              "appear_px": pair(at(0x2A3F70, "move.w #$011E,d1"),
                                at(0x2A3F70, "move.w #$00E2,d2"))},
             {"prog": "$1FEF8C", "update": "$2AA090"}],
            [{"prog": "$1FF148", "update": "$2AA266",
              "appear_px": pair(at(0x2A3FB6, "move.w #$0161,d1"),
                                at(0x2A3FB6, "move.w #$00E2,d2"))},
             {"prog": "$1FF0B4", "update": "$2AA1CC"}],
            [{"prog": "$1FF208", "update": "$2AA3A8",
              "appear_px": pair(at(0x2A4000, "move.w #$0140,d1"),
                                at(0x2A4000, "move.w #$00D4,d2"))}]],
        "finale": {
            "at_px": pair(at(0x2A4030, "move.w #$0140,d1"),
                          at(0x2A4030, "move.w #$0118,d2")),
            "explosions": D(16, "счётчик 15 и bpl",
                            at(0x2A4030, "move.w #$000F,$4C(a0)")),
            "sound": at(0x2A4060, "pea ($00000F).w", span=0x60)},
        "student_d_moves": {
            "prog": "$1FF15C",
            "walk_v": cmd(0x1FF164, [0x81, 0x16]),
            "jump_p256": p256(cmd(0x1FF174, [0x86], size=1,
                                  signed=False)),
            "else_dash_p256": p256(cmd(0x1FF178, [0x86], size=1,
                                       signed=False)),
            "bounce_v": pair(cmd(0x1FF1B0, [0x81, 0x16]),
                             cmd(0x1FF1B4, [0x81, 0x18]))},
    }


def serpent_ring(ctor, upd, ring):
    return {
        "ctor": hexa(ctor), "update": hexa(upd),
        "music": at(ctor, "pea ($00008D).w"),
        "head_hp": at(ctor, "move.w #$0030,$1C(a0)"),
        "segment_hp": at(ctor, "move.w #$0010,$1C(a0)"),
        "segments": at(0x2A7B16 if ctor == 0x2A71E0 else 0x2A7B64,
                       "moveq #4,d7", span=0x30),
        "segment_phase_turn": at(ctor, "addi.w #$0100,d1"),
        "ring_spin_turn": at(ctor, "move.w #$0018,$4E(a0)"),
        "ring_grow_to_px": at(ring, "cmpi.w #$0020,d7"),
        "ring_breathe": {"base_px": at(ring, "addi.w #$0020,d7"),
                         "amp_px": amp(at(ring, "lsl.l #6,d7")),
                         "step_turn": at(ring, "addq.w #8,d7")},
        "segment_hit_sound": at(0x2A7136, "pea ($00006E).w"),
        "segment_inv_f": at(0x2A7136, "moveq #16,d1"),
        "patrol": {
            "v": at(ctor, "move.w #$0180,$16(a0)"),
            "first_f": every(at(ctor, "move.w #$00B4,$6(a0)")),
            "center_x_px": at(0x2A72A8, "subi.w #$1240,d1"),
            "half_x_px": at(0x2A72A8, "cmpi.w #$0090,d1"),
            "center_y_px": at(0x2A72A8, "addi.w #$00A0,d0"),
            "sway_amp_px": amp(at(0x2A72A8, "lsl.l #5,d0")),
            "sway_step_turn": at(0x2A72A8, "addq.w #8,d0")},
        "hit_sound": at(upd, "pea ($000018).w", nth=0),
        "death_sound": at(0x2A7618 if upd == 0x2A7796 else upd,
                           "pea ($000078).w", nth=0)}


def b_serpents():
    s1 = 0x2A6FF8
    s2 = serpent_ring(0x2A71E0, 0x2A751A, 0x2A738A)
    s3 = serpent_ring(0x2A7244, 0x2A7796, 0x2A73D0)
    s2.update(core(0x2A751A))
    s3.update(core(0x2A7796))
    s2["lunge"] = {
        "warn_sound": at(0x2A751A, "pea ($000069).w"),
        "pause_f": every(at(0x2A751A, "move.w #$003C,$6(a0)")),
        "speed_major_v": D(4 << 8, "4 шага Брезенхэма << 8",
                           at(0x2A72F4, "move.w #$0004,d7"),
                           at(0x2A72F4, "asl.w #8,d4")),
        "box_half_px": pair(at(0x2A7320, "cmpi.w #$00E0,d0"),
                            at(0x2A7320, "cmpi.w #$0080,d1")),
        "return_tolerance_px": at(0x2A7352, "cmpi.w #$0004,d0"),
        "next_patrol_f": every(at(0x2A7352, "move.w #$0168,$6(a0)"))}
    s3["dive"] = {
        "dive_v": at(0x2A7796, "move.w #$0300,$18(a0)"),
        "gravity_a": at(0x2A7796, "addi.w #$003C,d0"),
        "bottom_y_px": at(0x2A7796, "cmpi.w #$0150,d0"),
        "rise_v": at(0x2A7796, "move.w #$FE00,$18(a0)"),
        "top_y_px": at(0x2A74EE, "cmpi.w #$00A0,d2"),
        "next_patrol_f": every(at(0x2A74EE, "move.w #$0168,$6(a0)")),
        "fireball_touch_code": at(0x2A748A, "move.w #$00ED,d4",
                                  signed=False),
        "fireballs_v": [pair(dw(0x1FF508 + 4 * i), dw(0x1FF50A + 4 * i))
                        for i in range(4)]}
    s3["death"] = {
        "hang_f": every(at(0x2A7618, "move.w #$005A,$6(a0)")),
        "explosions": at(0x2A7670, "move.w #$000F,$4C(a0)"),
        "every_f": every(at(0x2A7698, "move.w #$000F,$6(a0)")),
        "spread_px": pair(amp(at(0x2A7698, "lsl.l #7,d1")),
                          amp(at(0x2A7698, "lsl.l #6,d2"))),
        "y_shift_px": neg(at(0x2A7698, "subi.w #$0010,d2")),
        "explosion_sound": at(0x2A7698, "pea ($000067).w"),
        "fall_v": at(0x2A7742, "move.w #$0100,$18(a0)"),
        "land_sound": at(0x2A7742, "pea ($00000F).w")}
    return {
        "level_cell_ctor": "$2A0E6C",
        "music": at(0x2A0E6C, "pea ($000054).w", span=0x40),
        "trigger_from_left_px": at(0x2A7AAA, "cmpi.w #$0030,d0"),
        "camera_floor_px": at(0x2A7AAA, "move.l #$00000150,d7",
                              span=0x80),
        "rise_v": at(0x2A7AAA, "move.w #$FE00,$18(a2)", span=0x60),
        "rise_until_y_px": at(0x2A78EA, "cmpi.w #$00A0,d2"),
        "first": {
            "update": hexa(s1),
            "segments": at(0x2A7AAA, "moveq #5,d7", span=0x40),
            "head_hp": at(0x2A7930, "move.w #$0008,$1C(a0)"),
            "head_refill_hp": at(s1, "move.w #$0008,$1C(a0)"),
            "inv_f": at(s1, "moveq #16,d1"),
            "hit_sound": at(s1, "pea ($000018).w"),
            "segment_lost_sound": at(s1, "pea ($00006E).w"),
            "hit_turn_turn": at(s1, "move.w #$0140,d1"),
            "steer_every_f": every(at(s1, "move.w #$0002,$6(a0)")),
            "steer_reverse_turn": at(0x2A6FB2, "move.w #$0004,d3"),
            "steer_accel_turn": at(0x2A6FB2, "addi.w #$0004,d2"),
            "steer_max_turn": at(0x2A6FB2, "move.w #$001C,d2"),
            "speed_v": D((0x7FFF >> 6) * 3 // 2,
                         "cos >> 6, затем * 1.5 ($7FFF >> 6 = 511)",
                         at(0x2A6E5C, "asr.w #6,d1", nth=0)),
            "death_sound": at(s1, "pea ($000078).w", nth=0)},
        "second": s2,
        "third": s3,
    }


def b_ship():
    ent, ctl, head = 0x2A7FFE, 0x2A7E6C, 0x2A81C6
    tgt_up, tgt_dn = 0x2A85AE, 0x2A8616
    k = {
        "level_cell_ctor": "$2A7FA0",
        "camera_right_px": at(0x2A7FA0, "move.w #$12B0,($FF1A8E).l",
                              span=0x60),
        "entry": {
            "center_px": pair(at(ent, "subi.w #$1250,d0"),
                              at(ent, "subi.w #$00BC,d1")),
            "half_px": pair(at(ent, "cmpi.w #$0030,d0"),
                            at(ent, "cmpi.w #$0050,d1")),
            "lead_to_px": pair(at(ent, "move.w #$1258,$4C(a0)"),
                               at(ent, "move.w #$00BC,$4E(a0)")),
            "player_state": at(ent, "move.b #$28,$4(a1)"),
            "music": at(ent, "pea ($000054).w"),
            "lead_speed_v": D(4 << 6, "4 шага Брезенхэма << 6",
                              at(0x2A7F64, "moveq #4,d7"),
                              at(0x2A7F64, "asl.w #6,d4")),
            "lead_check_every_f": every(at(0x2A7F64,
                                           "move.w #$0004,$6(a0)"))},
        "platform": {
            "fly_to_px": pair(at(0x2A80DE, "move.w #$1268,$4C(a2)"),
                              at(0x2A80DE, "move.w #$006C,$4E(a2)")),
            "then_x_px": at(0x2A7DD4, "move.w #$13E0,$4C(a0)", span=0x40),
            "camera_left_px": at(0x2A7E1E, "move.w #$12C0,($FF1A8C).l"),
            "camera_bottom_px": at(0x2A7E1E,
                                   "move.w #$0100,($FF1A92).l"),
            "player_state": at(0x2A7E1E, "move.b #$29,$4(a2)"),
            "seat_px": pair(neg(at(0x2A7D32, "subi.w #$0010,d0")),
                            neg(at(0x2A7D32, "subi.w #$0010,d1"))),
            "up_a": neg(at(ctl, "subi.w #$0020,d3")),
            "up_max_v": at(ctl, "cmpi.w #$FE00,d3"),
            "down_a": at(ctl, "addi.w #$0020,d3"),
            "down_max_v": at(ctl, "cmpi.w #$0200,d3"),
            "left_a": neg(at(ctl, "subi.w #$0020,d2")),
            "left_max_v": at(ctl, "cmpi.w #$FE00,d2"),
            "right_a": at(ctl, "addi.w #$0030,d2"),
            "right_max_v": at(ctl, "cmpi.w #$0400,d2"),
            "x_range_px": [at(ctl, "cmpi.w #$1360,d0"),
                           at(ctl, "cmpi.w #$13E0,d0")],
            "y_range_px": [at(ctl, "cmpi.w #$0030,d1"),
                           at(ctl, "cmpi.w #$00E8,d1", span=0x120)]},
        "target": {
            "hp": at(0x2A8456, "move.w #$0050,$1C(a0)"),
            "inv_f": at(tgt_up, "moveq #16,d1"),
            "rise_v": at(0x2A858A, "move.w #$FF00,$18(a0)"),
            "rise_to_y_px": at(tgt_up, "cmpi.w #$0040,d2"),
            "fall_v": at(0x2A8600, "move.w #$0100,$18(a0)"),
            "fall_to_y_px": at(tgt_dn, "cmpi.w #$00BC,d2"),
            "voices": [db(0x1FF52E + i) for i in range(4)],
            "descend_hit_sound": at(tgt_dn, "pea ($000032).w"),
            "killable_only_rising": D(True, "на спуске ветка смерти — nop",
                                      at(tgt_dn, "nop", value=True)),
            "death_sound": at(0x2A8698, "pea ($000066).w"),
            "gone_sound": at(0x2A86C4, "pea ($0000A5).w"),
            "supply_bug": {
                "touch_code": at(0x2A8546, "moveq #23,d4"),
                "v": at(0x2A8546, "move.w #$0400,$16(a0)"),
                "y_from_top_px": [at(0x2A8546, "moveq #96,d2"),
                                  D(96 + 127, "96 + (случайное & $7F)",
                                    at(0x2A8546, "andi.w #$007F,d0"))]}},
        "head": {
            "attack_cycle": [dl(0x1FF532 + 4 * i, addr=True)
                             for i in range(8)],
            "rest_f": every(at(head, "move.w #$003C,$6(a0)")),
            "group_check_every_f": every(at(0x2A8304,
                                            "move.w #$003C,$6(a0)",
                                            nth=1)),
            "group_starts_at_once": D(True, "$2A814E обнуляет +$6 перед "
                                            "атакой", at(0x2A814E,
                                                         "clr.w $6(a0)",
                                                         value=True)),
            "win_delay_f": every(at(head, "move.w #$0078,$6(a0)",
                                    nth=0))},
        "mines": {
            "count": at(head, "cmpi.w #$0004,d0"),
            "every_f": every(at(head, "move.w #$0078,$6(a0)", nth=1)),
            "spawn_left_of_screen_px": at(head, "moveq #-32,d1"),
            "heights_px": [dw(0x1FF552 + 2 * i) for i in range(4)],
            "hp": at(0x2A89CC, "move.w #$0001,$1C(a0)"),
            "damage": bcd(at(0x2A89CC, "move.b #$25,$43(a0)",
                             signed=False)),
            "touch_code": at(0x2A89CC, "move.w #$00E2,d4", signed=False),
            "wave": {"x_px_per_frame": at(0x2A8A08,
                                          "addi.w #$0003,$12(a0)"),
                     "amp_px": amp(at(0x2A8A08, "asl.l #7,d0")),
                     "step_turn": half(at(0x2A8A08, "addi.w #$000C,d1"))},
            "thrown": {"vx_base_v": at(0x2A8254, "addi.w #$0300,d1",
                                       span=0x90),
                       "vx_from_x_px": at(0x2A8254, "subi.w #$1360,d1",
                                          span=0x90),
                       "vy_base_v": at(0x2A8254, "move.w #$FE00,d2",
                                       span=0x90),
                       "gravity_a": at(0x2A8A92, "addi.w #$0010,d0"),
                       "fall_max_v": at(0x2A8A92, "cmpi.w #$0200,d0")},
            "fuse_dist_px": at(0x2A8A08, "cmpi.w #$0020,d0"),
            "blast_sound": at(0x2A8A08, "pea ($00000F).w")},
        "flyers": {
            "hp": at(0x2A8720, "move.w #$0001,$1C(a0)"),
            "inv_f": at(0x2A87D8, "moveq #16,d1"),
            "touch_code": at(0x2A8720, "move.w #$00E2,d4", signed=False),
            "anim": at(0x2A8720, "move.l #$001DAEC2,$22(a0)", addr=True),
            "speed_v": at(0x2A8750, "move.w #$0200,$16(a0)"),
            "dash_v": at(0x2A87D8, "move.w #$0300,$16(a0)"),
            "dash_anim": at(0x2A87D8, "move.l #$001DAECA,$22(a0)",
                            addr=True),
            "gone_right_px": at(0x2A87D8, "cmpi.w #$0160,d0"),
            "wedge": {"spawn_x_shift_px": at(0x2A8750,
                                             "subi.w #$0010,d1"),
                      "split_x_from_screen_px": at(0x2A8750,
                                                   "addi.w #$0040,d1"),
                      "table": [{"dx_px": dw(0x1FF55A + 8 * i),
                                 "dy_px": dw(0x1FF55C + 8 * i),
                                 "vy_v": dw(0x1FF55E + 8 * i),
                                 "shift_y_px": dw(0x1FF560 + 8 * i)}
                                for i in range(5)],
                      "dash_dist_px": at(0x2A87D8, "cmpi.w #$0050,d0",
                                         span=0xE0)},
            "chain": {"table": [{"dx_px": dw(0x1FF582 + 6 * i),
                                 "dy_px": dw(0x1FF584 + 6 * i),
                                 "hover_f": dw(0x1FF586 + 6 * i)}
                                for i in range(5)],
                      "fly_in_f": at(0x2A879C, "move.w #$002D,$6(a0)"),
                      "loop_radius_px": amp(at(0x2A88AA, "asl.l #6,d3",
                                               span=0xE0, nth=0)),
                      "loop_step_turn": half(at(0x2A88AA,
                                                "subi.w #$0020,d2",
                                                span=0xF0)),
                      "drift_v": at(0x2A88AA, "move.w #$0100,$16(a0)"),
                      "dash_dist_px": at(0x2A88AA, "cmpi.w #$0070,d0",
                                         span=0x120)},
            "group_flag": D(0x10, "$29F096 с d7 = $10: бит 4 в +$30",
                            at(0x2A8304, "move.w #$0010,d7"))},
    }
    return k


def b_final():
    arena_rot, lightning, boss = 0x2A3568, 0x2A37E4, 0x2A38C4
    p12, knock, fin, p3 = 0x2A8EA4, 0x2A8F76, 0x2A9166, 0x2A93D0
    return {
        "level_proc": "$2A6156",
        "camera_margin_px": at(0x2A6156, "move.w #$0048,($FF1322).l"),
        "fuel_infinite": at(0x2A6156, "move.w #$FFFF,($FF133E).l",
                            signed=False),
        "hooks": {
            "centers_px": [pair(D(0x1F0 + 8, "$1F0 + 8",
                                  at(0x2A6156, "move.w #$01F0,d1")),
                                D(0xC0 + 8, "$C0 + 8",
                                  at(0x2A6156, "move.w #$00C0,d2",
                                     nth=0))),
                           pair(D(0x590 + 8, "$590 + 8",
                                  at(0x2A6156, "move.w #$0590,d1")),
                                D(0xC0 + 8, "$C0 + 8",
                                  at(0x2A6156, "move.w #$00C0,d2",
                                     nth=1)))],
            "per_wheel": D(4, "moveq #3 и dbf",
                           at(0x2A34C6, "moveq #3,d5")),
            "phase_step_turn": half(at(0x2A34C6, "addi.w #$0200,d6")),
            "spin_turn": [half(at(0x2A34C6, "moveq #2,d7")),
                          half(at(0x2A34F4, "moveq #-2,d7"))],
            "radius_px": D(96, "cos * 64 * 3 >> 16",
                           at(arena_rot, "lsl.l #6,d1", nth=0)),
            "anim": at(0x2A3522, "move.l #$001D8B5A,$22(a0)", addr=True),
            "touch_codes": [at(0x2A34C6, "move.w #$007A,d4"),
                            at(0x2A34F4, "move.w #$007B,d4")],
            "hang_below_px": at(0x29A2BA, "addi.w #$0020,d0"),
            "hang_state": at(0x29A2BA, "move.b #$11,$4(a0)"),
            "grab_sound": at(0x2A35CA, "pea ($000080).w")},
        "supplies": {
            "left_center_px": pair(at(0x2A37A2, "move.w #$00B8,d1",
                                      nth=0),
                                   at(0x2A37A2, "move.w #$0068,d2",
                                      nth=0)),
            "right_center_px": pair(at(0x2A37A2, "move.w #$06D8,d1"),
                                    at(0x2A37A2, "move.w #$0068,d2",
                                       nth=1)),
            "spread_px": at(0x2A36BA, "subi.w #$0020,d1"),
            "codes": {"left": [at(0x2A36BA, "move.w #$0017,d4"),
                               at(0x2A36BA, "move.w #$0017,d4")],
                      "right": [at(0x2A36DE, "move.w #$0019,d4"),
                                at(0x2A36DE, "move.w #$0017,d4")]},
            "check_every_f": every(at(0x2A374E, "move.w #$001E,$6(a0)")),
            "refill_if_stock1_le": bcd(at(0x2A374E, "cmpi.w #$0015,d0"))},
        "lightning": {
            "pos_px": pair(at(0x2A6156, "move.w #$03C8,d1", nth=0),
                           at(0x2A6156, "move.w #$0080,d2", nth=0)),
            "anim": at(lightning, "move.l #$001DAF70,$22(a0)", addr=True),
            "arm_half_x_px": at(lightning, "cmpi.w #$0098,d0", nth=0),
            "arm_below_px": at(lightning, "cmpi.w #$0008,d1", nth=0),
            "recheck_every_f": every(at(lightning, "move.w #$003C,$6(a0)",
                                        nth=0)),
            "hit_half_px": pair(at(0x2A3870, "cmpi.w #$0098,d0"),
                                at(0x2A3870, "cmpi.w #$0018,d1")),
            "damage": bcd(at(0x2A3870, "moveq #37,d0")),
            "knock_v": pair(at(0x2A3870, "move.w #$0400,$16(a1)"),
                            at(0x2A3870, "move.w #$FA00,$18(a1)"))},
        "boss": {
            "ctor": hexa(boss), "touch_code": at(boss, "move.w #$00C8,d4",
                                                 signed=False),
            "pos_px": pair(at(0x2A6156, "move.w #$03C8,d1", nth=1),
                           at(0x2A6156, "move.w #$0080,d2", nth=1)),
            "phase12": {
                "update": hexa(p12),
                "hp": at(boss, "move.w #$003C,$1C(a0)"),
                "rounds": D(2, "+$8 = 1, bpl после вычитания",
                            at(boss, "move.w #$0001,$8(a0)")),
                "inv_f": at(p12, "moveq #16,d1"),
                "shot_max_below_px": at(0x2A8E40, "cmpi.w #$0060,d1"),
                "shot_max_dx_px": at(0x2A8E40, "cmpi.w #$00D8,d0"),
                "shot_from_ahead_px": at(0x2A8E40, "moveq #56,d1"),
                "shot_target_below_player_px": at(p12, "addi.w #$0028,d0",
                                                  span=0xE0),
                "shot_speed_major_v": D(16 << 7, "16 шагов Брезенхэма "
                                                 "<< 7",
                                        at(0x2A8CD8, "moveq #16,d7"),
                                        at(0x2A8CD8, "asl.w #7,d4")),
                "shot_sound": at(0x2A8CD8, "pea ($00000C).w"),
                "shot_burst_dx_px": at(0x2A8D5E, "cmpi.w #$0005,d0"),
                "shot_touch_code": at(0x2A8CD8, "move.w #$00F0,d4",
                                      signed=False),
                "fall_sound": at(p12, "pea ($000010).w"),
                "revive_hp": at(knock, "move.w #$003C,$1C(a0)"),
                "flash_ahead_px": at(0x2A8DBC, "moveq #64,d0"),
                "flash_f": at(0x2A8DBC, "move.w #$0064,$6(a0)")},
            "transition": {
                "sound": at(0x2A8B98, "pea ($00002F).w"),
                "arena_columns": [at(0x2A8B98, "move.w #$0034,d0"),
                                  at(0x2A8B98, "move.w #$0042,d0")],
                "arena_row": at(0x2A8B98, "move.w #$0006,d1", nth=0),
                "spirits": D(21, "+$4C = 20, bpl после вычитания",
                             at(knock, "move.w #$0014,$4C(a0)",
                                span=0xA0)),
                "spirit_every_f": D(2, "and.w #1 с кадровым счётчиком",
                                    at(fin, "moveq #1,d0")),
                "spirit_from_ahead_px": at(0x29AF30, "moveq #70,d0"),
                "spirit_catch_px": pair(at(0x29AF76, "cmpi.w #$0018,d0"),
                                        at(0x29AF76, "cmpi.w #$0008,d0")),
                "spirit_vx_max_v": at(0x29AF76, "move.w #$0800,d0"),
                "spirit_orbit_table": "$1FD806",
                "spirit_release_f": at(0x29B044, "cmpi.w #$0078,d0",
                                       span=0x60),
                "pull_to_px": pair(at(0x2A90BE, "moveq #64,d0"),
                                   at(0x2A90BE, "moveq #-80,d0")),
                "pull_first_gap_f": at(fin, "move.w #$001E,$4C(a0)",
                                       span=0x80),
                "pull_gap_step_f": at(0x2A90BE, "subq.w #2,d0"),
                "ninja_at_gap_f": at(0x2A90BE, "cmpi.w #$0014,d0"),
                "end_at_gap_f": at(0x2A90BE, "cmpi.w #$0004,d0"),
                "drop_sound": at(0x2A90BE, "pea ($000090).w", span=0xC0),
                "drop_v": [pair(dw(0x1FF614 + 4 * i), dw(0x1FF616 + 4 * i))
                           for i in range(4)],
                "drop_anims": [dl(0x1FF604 + 4 * i, addr=True)
                               for i in range(4)]},
            "phase3": {
                "update": hexa(p3),
                "hp": at(0x2A9202, "move.w #$0018,$1C(a0)"),
                "lives": D(3, "+$50 = 2, bpl после вычитания",
                           at(0x2A9202, "move.w #$0002,$50(a0)")),
                "inv_f": at(p3, "moveq #16,d1"),
                "spawn_x_px": [D(0x3C8 - 128, "$3C8 - 128"),
                               D(0x3C8 + 128, "$3C8 + 128",
                                 at(0x2A9202, "move.w #$FF80,d0"),
                                 at(0x2A9202, "addi.w #$03C8,d0"))],
                "ranged_if_dx_ge_px": at(0x2A925A, "cmpi.w #$0080,d0"),
                "melee_wait_f": every(at(0x2A925A, "move.w #$001E,$6(a0)")),
                "melee_now_player_states": [
                    at(0x2A9298, "cmpi.b #$06,d0"),
                    at(0x2A9298, "cmpi.b #$08,d0", nth=0),
                    at(0x2A9298, "cmpi.b #$09,d0", nth=0),
                    at(0x2A9298, "cmpi.b #$0D,d0")],
                "low_attack_anim": at(0x2A9298, "move.l #$001D865A,$22(a0)",
                                      addr=True),
                "high_attack_anim": at(0x2A9298,
                                       "move.l #$001D8668,$22(a0)",
                                       addr=True),
                "second_hit_if_dx_le_px": at(p3, "cmpi.w #$0080,d0",
                                             span=0x140),
                "bolt": {"from_ahead_px": at(0x2A9378, "moveq #72,d1"),
                         "v": at(0x2A9378, "move.w #$0400,$16(a0)",
                                 span=0x40),
                         "anim": at(0x2A9378, "move.l #$001D9FDA,$22(a0)",
                                    span=0x50, addr=True),
                         "sound": at(p3, "pea ($00000F).w")},
                "debris": {"count": D(8, "moveq #7 и dbf",
                                      at(0x2A934C, "moveq #7,d7")),
                           "from_ahead_px": at(0x2A934C, "moveq #88,d1"),
                           "below_px": at(0x2A934C, "moveq #16,d2"),
                           "angle_min_turn": half(at(0x2A92F0,
                                                     "addi.w #$0500,d0")),
                           "angle_range_turn": half(D(0x200,
                                                      "andi.w #$01FE: 0..$1FE",
                                                      at(0x2A92F0,
                                                         "andi.w #$01FE,d0"))),
                           "vx_max_v": trig_v(at(0x2A92F0, "asr.w #5,d1")),
                           "vy_max_v": trig_v(at(0x2A92F0, "asr.w #4,d2"))},
                "death_sound": at(p3, "pea ($000010).w")},
            "touch": {
                "shield_box_bit": D(10, "and.w #$0400 в $2A95AC",
                                    at(0x2A95AC, "move.w #$0400,d1")),
                "clash_sound": at(0x2A95AC, "pea ($00004D).w", nth=0),
                "knock_box_bit": D(9, "andi.w #$0200 в $2A95FE",
                                   at(0x2A95FE, "andi.w #$0200,d1")),
                "knock_v": pair(at(0x2A95FE, "move.l #$0600F900,$16(a0)",
                                   part="hi"),
                                at(0x2A95FE, "move.l #$0600F900,$16(a0)",
                                   part="lo")),
                "hit_sound": at(0x2A95FE, "pea ($000018).w", span=0xB0)}},
    }


def b_guardian():
    """Страж уровня 13: лягушка, которая глотает положенных жуков."""
    c, h, pole = 0x2A0A4A, 0x2A099C, 0x2A0A14
    st1, swal, bite_on, bite = 0x2A6A32, 0x2A6990, 0x2A69D8, 0x2A6B8E
    near, lost, fire = 0x2A68F8, 0x2A6A74, 0x1D9FDA
    fire_f = D(62, u"скрипт $1D9FDA: 12 кадров по +$26 = 5 ($2996E2) и "
                   u"кадр 1086 на 2 такта, потом +$06 = 1 — объект снят",
               at(0x2996C2, "move.b #$05,$26(a0)", signed=False),
               cmd(0x1D9FF2, [0xD8], size=1, signed=False))
    loop = cmd(0x1D87EA, [0xDC, 0x4C])
    return {
        "cell_code": D(160, u"клетка кода 160 -> конструктор $2A0A4A "
                            u"(перепись клеток)"),
        "ctor": hexa(c), "update": "$2A6E40", "states": "$1FF4B8",
        "music": at(c, "pea ($000054).w"),
        "touch_code": at(c, "move.w #$00B4,d4", signed=False),
        "touch": u"код $B4 -> $2A526C (rts): касание головы и шестов "
                 u"ничего не делает; ядра урона $2A2C48 голова не зовёт",
        "hp": at(h, "move.w #$0008,$1C(a0)"),
        "rounds": D(2, u"+$2C = 1: круг проигран — минус один, "
                       u"меньше нуля — поражение",
                    at(h, "move.w #$0001,$2C(a0)")),
        "cell_level13": D([219, 40], u"клетка кода 160 на уровне 13 — "
                                     u"перепись клеток (levels.json)"),
        "home_from_cell_px": pair(at(h, "addq.w #8,d1", value=8),
                        D(18, u"клетка + 16 ($2A0A50) + 2 ($2A09A4)",
                          at(c, "addi.w #$0010,d2"),
                          at(h, "addq.w #2,d2", value=2))),
        "park_dx_px": at(h, "addi.w #$00E0,d1"),
        "vram_bytes": at(h, "move.w #$1480,d0", nth=0, signed=False),
        "show": {
            "hide_below_px": at(0x2A6942, "subi.w #$0100,d0"),
            "rule": u"прячется (состояние 0), когда голова Y − 256 > "
                    u"камера Y, в любом состоянии; появляется, когда "
                    u"голова Y − 256 <= камера Y; утка на шнуре, и "
                    u"лягушка прячется, когда камера уходит вверх за "
                    u"высоким отскоком",
            "side_dx_px": at(0x2A6942, "move.w #$FF18,d1"),
            "sides": u"первый круг — дом − 232, лицом вправо; второй — "
                     u"дом + 232, лицом влево",
            "bug": at(0x2A6C88, "cmpi.w #$0002,$4(a0)", value=u"не "
                      u"срабатывает: слово +$04 при ненулевом состоянии "
                      u"не бывает 2, так что прячется и посреди глотания")},
        "idle": {
            "anim": "$1DAFD0",
            "sound": cmd(0x1DAFD0, [0xEA], size=1, signed=False),
            "spit_every_f": every(at(st1, "move.w #$01E0,$8(a0)")),
            "order": u"каждый кадр: глотание, язык, отсчёт плевка"},
        "swallow": {
            "anim": "$1DB022",
            "point_ahead_px": at(swal, "moveq #20,d1"),
            "point_up_px": neg(at(swal, "moveq #-8,d2")),
            "half_px": pair(at(near, "cmpi.w #$0008,d0", nth=1),
                            at(near, "cmpi.w #$0008,d0", nth=0)),
            "takes_touch_code": at(near, "cmpi.b #$E8,$29(a1)",
                                   signed=False),
            "takes_state_bit": at(near, "andi.w #$0002,d0"),
            "takes": u"снаряд игрока с битом 1 в +$05: наборы 2, 3, 6, 7 — "
                     u"те, что кладут (+$05 = 2, 3, 6, 6); брошенные "
                     u"наборы 0, 1, 4, 5 не глотаются",
            "burst_f": script_mark(0x1DB022, 0x05, 2, 8),
            "damage_hp": at(0x2A6B0A, "subq.w #2,$1C(a0)", value=2),
            "burst_sound": at(0x2A6B0A, "pea ($00000F).w"),
            "flame_f": script_mark(0x1DB022, 0x06, 1, 8),
            "flame": {"ahead_px": at(0x2A6CBA, "moveq #56,d0"),
                      "up_px": at(0x2A6CBA, "subi.w #$0018,d2"),
                      "touch_code": at(0x2A6CBA, "move.w #$00F0,d4",
                                       signed=False),
                      "damage": dmg_default(),
                      "life_f": fire_f, "anim": hexa(fire),
                      "sound": at(0x2A6B0A, "pea ($00007F).w")},
            "then_spit_f": script_mark(0x1DB022, 0x05, 1, 8),
            "no_swallow_while": True},
        "tongue": {
            "anim": "$1DB056",
            "trigger_ahead_px": at(bite_on, "move.w #$0072,d1"),
            "trigger_back_px": at(bite_on, "subi.w #$0008,d1"),
            "trigger_up_px": neg(at(bite_on, "move.w #$FFD4,d1")),
            "trigger_half_px": pair(at(bite_on, "cmpi.w #$0010,d1", nth=0),
                                    at(bite_on, "cmpi.w #$0010,d1",
                                       nth=1)),
            "hit_from_f": script_mark(0x1DB056, 0x06, 1, 8),
            "hit_to_f": D(13, u"+$06 = 1 на такте 11, +$06 = 0 на 14",
                          script_mark(0x1DB056, 0x06, 0, 8)),
            "hit_ahead_px": at(bite, "subi.w #$0072,d0"),
            "hit_up_px": neg(at(bite, "subi.w #$FFCC,d0")),
            "hit_half_px": pair(at(bite, "cmpi.w #$0010,d0", nth=1),
                                at(bite, "cmpi.w #$0010,d0", nth=0)),
            "damage": bcd(at(bite, "moveq #16,d0")),
            "sound": at(bite, "pea ($000083).w"),
            "sound_rule": u"звук и проверка удара — каждый такт языка",
            "total_f": script_mark(0x1DB056, 0x05, 1, 8)},
        "spit": {
            "anim": "$1DB086",
            "shot_f_after_swallow": script_mark(0x1DB086, 0x06, 1, 5),
            "shot_f_from_idle": script_mark(0x1DB086, 0x06, 1, 8),
            "ahead_px": at(0x2A6DE8, "moveq #32,d0"),
            "up_px": at(0x2A6DE8, "subi.w #$0018,d2"),
            "v": at(0x2A6DE8, "move.w #$0400,$16(a0)"),
            "touch_code": at(0x2A6DE8, "move.w #$00F0,d4", signed=False),
            "damage": dmg_default(),
            "life_f": fire_f,
            "sound": at(0x2A6C1E, "pea ($00007F).w"),
            "back_to_idle_f": script_mark(0x1DB086, 0x05, 1, 8)},
        "round_lost": {
            "hp_again": at(lost, "move.w #$0008,$1C(a0)"),
            "explosion_up_px": at(lost, "subi.w #$0040,d2"),
            "explosion_anim": "$1D8810",
            "freeze_anim": "$1D87D2",
            "fireball": {
                "x_from_right_limit_px": neg(at(lost, "subi.w #$00E0,d1")),
                "wait_f": every(at(0x2A6D0C, "move.w #$003C,$4C(a0)")),
                "v": at(0x2A6D0C, "move.w #$0500,$16(a0)"),
                "dir": u"влево: флаги $2801, бит 11",
                "life_f": fire_f,
                "sound": at(0x2A6D50, "pea ($00007F).w")},
            "then": u"ждёт, пока голова спрячется от камеры, и "
                    u"появляется с другой стороны"},
        "defeat": {
            "anim": "$1D87E4",
            "cry_times": loop,
            "cry_sound": cmd(0x1D87EE, [0xEA], size=1, signed=False),
            "cry_every_f": D(26, u"тело петли: 10 + 4 + 8 + 4",
                             cmd(0x1D87F0, [0xD8], size=1, signed=False),
                             cmd(0x1D87F6, [0xD8], size=1, signed=False)),
            "boom_f": D(138, u"4 x 26 + 4 + 30",
                        cmd(0x1D8806, [0xD8], size=1, signed=False)),
            "boom_sound": cmd(0x1D880A, [0xEA], size=1, signed=False),
            "level_done_f": D(200, u"138 + 6 + 14 x 4 кадров взрыва "
                                   u"$1D8810, потом +$06 = 1",
                              cmd(0x1D8814, [0xD8], size=1, signed=False)),
            "level_done": at(0x2A6AF0, "move.w #$0001,($FF1A6C).l")},
        "poles": {
            "anim": "$1DA642", "frame": 1902, "size_px": pair(104, 8),
            "centers_dx_px": [D(0, u"клетка + 8"),
                              at(c, "addi.w #$0050,d1"),
                              neg(at(c, "subi.w #$0050,d1"))],
            "radius_px": [amp(at(pole, "move.w #$0005,$4E(a0)")),
                          amp(at(c, "move.w #$0006,$4E(a0)", nth=0)),
                          amp(at(c, "move.w #$0006,$4E(a0)", nth=1))],
            "phase_turn": [None, at(c, "move.w #$0100,$4C(a0)"),
                           at(c, "move.w #$0300,$4C(a0)")],
            "step_turn": at(0x2A0AC6, "addi.w #$0008,d0"),
            "shelf_bit": at(pole, "move.w #$2000,$30(a0)"),
            "touch": u"урона нет (код $B4 -> rts); бит 13 в +$30 делает "
                     u"шест полкой для утки на шнуре: держа вниз, она "
                     u"встаёт на него и едет (player.bungee)"},
        "refill": {
            "cell_code": D(182, u"клетка кода 182 уровня 13 -> $2A0B14"),
            "shows_when": u"второй запас $FF1A24 пуст ($2A0B40)",
            "ammo2": bcd(at(0x2A0B66, "moveq #5,d0"))},
    }


def bosses():
    return {
        "shaman": b_shaman(),
        "ninja_school": b_ninja_school(),
        "fire_serpents": b_serpents(),
        "flying_ship": b_ship(),
        "guardian": b_guardian(),
        "final": b_final(),
    }


# ------------------------------------------------------------ вывод

def build():
    return {
        "units": units(),
        "player": player(),
        "touch": touch(),
        "enemies": enemies(),
        "bosses": bosses(),
    }


def split(node):
    """Дерево из V -> (значения, происхождения)."""
    if isinstance(node, V):
        return node.v, node.src
    if isinstance(node, dict):
        vals, srcs = {}, {}
        for k, x in node.items():
            vals[k], srcs[k] = split(x)
        return vals, srcs
    if isinstance(node, (list, tuple)):
        pairs = [split(x) for x in node]
        return [p[0] for p in pairs], [p[1] for p in pairs]
    if isinstance(node, (str, int)) or node is None:
        return node, None
    raise SpecError("непонятный узел: %r" % (node,))


def count(node):
    if isinstance(node, V):
        return 1
    if isinstance(node, dict):
        return sum(count(x) for x in node.values())
    if isinstance(node, (list, tuple)):
        return sum(count(x) for x in node)
    return 0


def meta():
    return {
        "game": "Maui Mallard in Cold Shadow (Mega Drive)",
        "rom_sha1": hashlib.sha1(bytes(ROM)).hexdigest().upper(),
        "generator": "tools/specjson.py",
        "spec": "docs/mauimallard/behavior.md",
        "units": {
            "_v": "скорость 8.8: пикселей за кадр * 256; горизонтальная — "
                  "от взгляда (+ вперёд), вертикальная — + вниз",
            "_a": "прибавка к скорости за кадр, 8.8",
            "_f": "кадры, 60 в секунду; у счётчиков — кадров до "
                  "срабатывания (перезарядка n при subq/bpl даёт n + 1)",
            "_px": "пиксели мира; смещение по X — от взгляда (+ вперёд), по "
                   "Y — + вниз, если имя ключа не говорит иначе (_ahead, "
                   "_up, _below)",
            "_turn": "угол в 1/1024 оборота",
            "_p256": "вероятность n/256",
            "health/damage/heal": "обычные числа (в игре двоично-десятичные)",
            "anim/prog": "адрес скрипта анимации или программы +$48",
        },
    }


def main():
    try:
        tree = build()
    except SpecError as e:
        print(u"ошибка: %s" % e)
        return 1
    if ERRORS:
        for e in ERRORS:
            print(u"ошибка: %s" % e)
        print(u"ошибок: %d" % len(ERRORS))
        return 1
    vals, srcs = split(tree)
    n = count(tree)
    if "--check" in sys.argv:
        print(u"проверено чисел: %d" % n)
        return 0
    out = OUT("export")
    if not os.path.isdir(out):
        os.makedirs(out)
    doc = dict(meta=meta(), **vals)
    for name, data in (("behavior.json", doc),
                       ("behavior.sources.json", srcs)):
        p = os.path.join(out, name)
        with io.open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=1))
            f.write(u"\n")
        print(u"%s" % p)
    print(u"чисел: %d" % n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
