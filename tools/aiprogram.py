#!/usr/bin/env python3
u"""ИИ противника как программа для ремейка (dyna #208).

    python tools/aiprogram.py            (нужен свежий `make split`)
    python tools/aiprogram.py --stage 7  (программа одного этапа, текстом)

`AiLoop` `$025282` раз в такт прыгает по `AiScriptTable` `$0252EE` —
256 записей, по байту этапа `+$3` описания миссии, 82 разных скрипта.
Скрипт — это обычный код 68000: правила вызываются `bsr`, результат
смотрится `bne`, между ними регистры, счётчики, тики и деньги. Переносить
его руками — 82 копии без сверки. Поэтому здесь код ИИ выгружается как
есть, инструкция в инструкцию, а ремейк исполняет его маленькой машиной
на узком подмножестве 68000 (`move`, `lea`, `cmp`, ветвления, `movem`,
`dbf` и десяток других форм — ровно то, что в этом коде встречается).

Граница «исполнять / звать нативно» проведена по данным, которые код
трогает:

- **исполняется** всё, что работает только с памятью ИИ — `SessionState`
  `$FFE086`, флаги `$FFE0xx`, записи игроков `Player1State` `$FF9C84` и
  `Player2State` `$FF9CDA`, байт этапа, таблицы ROM. Это сами скрипты,
  их общие тела, цепочки фаз, фазовая машина `AiPhaseStep`, решения
  о яйцах и тела погодных правил;
- **нативно** (ремейк пишет это сам, по разбору) — всё, что читает
  записи юнитов `UnitRecords`, карту юнитов `UnitMap`, местность
  `TerrainMap`, и весь движок за пределами кода ИИ: счёт юнитов в окне,
  выбор цели, эффекты погоды, оплата, кладка яйца, предикаты `a6`.

Список нативных процедур — `NATIVE_IN_AI` и `NATIVE_PRED` ниже плюс всё
вне кода ИИ; он же и есть объём библиотеки ремейка.

Выгрузка — один файл на игру, `out/<имя>/export/ai/opponent.json` (код ИИ
в ROM один; миссия называет только этап, `map.ai.stage`):

- `scripts` — пары [этап, адрес входа] для 219 этапов с непустым скриптом;
- `natives` — имя -> адрес каждой нативной процедуры, которую код зовёт
  или кладёт в регистр;
- `ops` — инструкции по возрастанию адреса: `[адрес, мнемоника, размер,
  операнды…]`; размер 1/2/4 по суффиксу (0 — без суффикса или `.s`);
  операнды — `["d", n]`, `["a", n]`, `["#", v]`, `["abs", адрес]` (и
  `метка(pc)`: адрес известен), `["ind", n]` (an), `["inc", n]` (an)+,
  `["dec", n]` -(an), `["disp", d, n]` d(an), `["idx", d, n, r, long]`
  (d,an,rX) — `n` = −1 значит от pc, тогда `d` — адрес; `r` 0…7 — d0…d7,
  8…15 — a0…a7; `["regs", маска]` для `movem` (биты 0…7 — d0…d7, 8…15 —
  a0…a7); `["to", адрес]` — цель ветвления или вызова;
- `rom` — `[адрес, hex]`: байты ROM, которые код читает, — таблицы фаз,
  таблицы переходов, списки клеток, `AiPlanTable` целиком.

Регистры машины держат настоящие адреса 68000: указатель на таблицу ROM —
её адрес, на код — адрес инструкции или нативной процедуры. Поэтому
`jsr (a0)` по таблице фаз и `lea Предикат,a6` работают без перевода.
"""
import collections
import glob
import io
import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT as out_path, rom_bytes                   # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM = rom_bytes()
SCRIPT_TABLE = 0x0252EE            # AiScriptTable, 256 слов
PLAN_TABLE = 0x02BC3C              # AiPlanTable, 256 слов, записи по $3C
PLAN_SIZE = 0x3C
AI_CODE = (0x024E00, 0x02BD00)     # код ИИ; всё вне — движок, то есть нативно


def u16(a):
    return struct.unpack_from(">H", ROM, a)[0]


def s16(a):
    return struct.unpack_from(">h", ROM, a)[0]


def u32(a):
    return struct.unpack_from(">I", ROM, a)[0]


def symbols():
    u"""Имя -> адрес и адрес -> имя из `game_symbols.txt`."""
    sym, name = {}, {}
    for ln in io.open(os.path.join(HERE, "game_symbols.txt"), encoding="utf-8"):
        m = re.match(r"^([A-Za-z_]\w*)\s*=\s*\$([0-9A-Fa-f]+)", ln)
        if m:
            a = int(m.group(2), 16)
            sym[m.group(1)] = a
            name.setdefault(a, m.group(1))
    return sym, name


SYM, NAME = symbols()


def segments():
    u"""Сегменты `game.yaml`: имя -> (тип, начало, конец). Таблицы ROM в коде
    ИИ — сегменты `bin`, и их границы — ровно границы таблицы."""
    seg, cur = {}, None
    for ln in io.open(os.path.join(HERE, "game.yaml"), encoding="utf-8"):
        m = re.match(r"^\s*- name:\s*(\S+)", ln)
        if m:
            cur = [m.group(1), None, None, None]
            continue
        m = re.match(r"^\s+(type|start|end):\s*(\S+)", ln)
        if m and cur is not None:
            k = {"type": 1, "start": 2, "end": 3}[m.group(1)]
            cur[k] = m.group(2) if k == 1 else int(m.group(2), 0)
            if all(v is not None for v in cur):
                seg[cur[0]] = (cur[1], cur[2], cur[3])
                cur = None
    return seg


SEG = segments()
BIN_AT = {}                        # начало bin-сегмента -> конец
for _n, (_t, _s, _e) in SEG.items():
    SYM.setdefault(_n, _s)
    NAME.setdefault(_s, _n)
    if _t == "bin":
        BIN_AT[_s] = _e


def listing():
    u"""Адрес -> текст инструкции из всех листингов m68k."""
    code = {}
    for f in glob.glob(out_path("asm", "m68k", "*.asm")):
        cur = None
        for ln in io.open(f, encoding="utf-8", errors="replace"):
            ln = ln.rstrip("\n")
            m = (re.match(r"^\s*org\s+\$([0-9A-F]{6})", ln)
                 or re.match(r"^; \$([0-9A-F]{6})$", ln.strip())
                 or re.match(r"^\S+:\s+; \$([0-9A-F]{6})", ln))
            if m:
                cur = int(m.group(1), 16)
                continue
            if ln.startswith("\t") and cur is not None:
                code[cur] = ln.strip()
                cur = None
    return code


CODE = listing()
ADDRS = sorted(CODE)
_POS = {a: i for i, a in enumerate(ADDRS)}


def after(a):
    i = _POS[a] + 1
    return ADDRS[i] if i < len(ADDRS) else None


def name_of(a):
    return NAME.get(a, "$%06X" % a)


# ── Нативные процедуры ──────────────────────────────────────────────────
# Внутри кода ИИ — те, что трогают юнитов, карту юнитов и местность.
# Всё за пределами AI_CODE нативно само собой. Пояснение — что ремейк
# должен сделать; порядок бросков `Random` важен так же, как результат.
NATIVE_IN_AI = {
    "AiScanUnitsP0": u"полив по своим юнитам, фаза 0: пороги по деньгам",
    "AiScanUnitsP1": u"полив по своим юнитам, фаза 1",
    "AiScanUnitsP2": u"полив по своим юнитам, фаза 2",
    "AiScanUnitsP3": u"полив по своим юнитам, фаза 3",
    "AiScanUnitsP45": u"полив по своим юнитам, фазы 4 и 5",
    "AiScanOwnForFire": u"тушение огня у своих, счётчик $2C",
    "AiWaterBareNearOwn": u"полив голой земли у своего юнита",
    "AiWaterScorchedNearOwn": u"полив выжженной земли у своего юнита",
    "AiExtinguishFire": u"потушить огонь в окне 3x3",
    "AiWaterScorchedAroundB": u"полив выжженной земли в окне 3x3",
    "AiWaterGrass": u"полив травы в окне 3x3",
    "AiWaterBareAround": u"полив голой земли в окне",
    "AiWaterScorchedAround": u"полив выжженной земли в окне",
    "AiWaterYoungPlantAround": u"полив ростков в окне",
    "AiGuideUnitAt": u"наведение юнита из клетки (d2,d3) в (d0,d1)",
    "AiUpgradeUnit": u"переделка или усиление своего яйца в окне",
    "AiSelectAndMarkUnit": u"выбор цели метеорита в полосе обхода",
    "AiSelectUnitInWindow": u"выбор цели в окне 6x6, иначе пометка",
    "AiClearSelection": u"снять выбор P2+$A",
    "AiSelectionInTargetBand": u"выбранный юнит в полосе обхода",
    "AiSelectionStillInWindow": u"выбранный юнит в окне 6x6",
    "AiPickWatchedTarget": u"ближайший юнит игрока 1 к гнезду — цель атаки",
    "AiLightningAtUnit": u"молния по чужому юниту у своего зреющего яйца",
    "ScanUnitsAroundAiTarget": u"юниты вокруг цели ИИ",
    "ScanUnitsInRect": u"юниты в прямоугольнике",
    "ForEachCellAroundAiTarget": u"обход клеток 4x4 от угла",
    "ForEachCellAround3x3": u"обход клеток 3x3",
    "FindEnemyInWindow": u"чужой юнит вида из маски d7 в окне 6x6",
    "FindOwnInWindow": u"свой юнит вида из маски в окне 6x6",
    "CheckSpeciesGone": u"демо-бой: вид исчез — бесплатное яйцо",
    "DemoRandomCommands": u"демо-бой: случайные яйца обоим",
}

# Предикаты юнитов (их кладут в a6 и зовут изнутри нативного счёта) —
# тоже нативные: читают запись юнита. Список пополняется сам, когда адрес
# кода попадает в `lea` и лежит в NATIVE_PRED; неизвестный адрес кода в
# `lea` — ошибка разбора.
NATIVE_PRED = {
    "AiBusyRoaming", "AiBusyIdle", "AiBusyBroad", "AiBusyRoamingNotSpecies",
    "TestSpeciesAndAction", "FilterCarnivoreBroad", "FilterIdlePredator",
    "FilterP1GrazerIdle", "FilterMeatEaterOrPtera", "AiUnitOfP1Idle",
    "FilterOwnIdle", "FilterOwnHerbivore", "FilterP2HunterIdle",
    "FilterLiveMeatEater", "RuleIsPichanOfP1", "loc_0167AA",
}


def is_native(a):
    if not (AI_CODE[0] <= a < AI_CODE[1]):
        return True
    n = NAME.get(a)
    return n in NATIVE_IN_AI or n in NATIVE_PRED


# ── Разбор операндов листинга ───────────────────────────────────────────
SIZES = {"b": 1, "w": 2, "l": 4, "s": 0}
REG = re.compile(r"^([ad])([0-7])$")


class Bad(Exception):
    pass


def num(t):
    t = t.strip()
    neg = t.startswith("-")
    t = t.lstrip("-")
    v = int(t[1:], 16) if t.startswith("$") else int(t)
    return -v if neg else v


def addr_of(t):
    u"""Метка, символ или `$адрес` -> адрес."""
    t = t.strip()
    if t.startswith("$"):
        return int(t[1:], 16)
    if t in SYM:
        return SYM[t]
    m = re.match(r"^(?:loc|sub|data|code)_([0-9A-Fa-f]{6})", t)
    if m:
        return int(m.group(1), 16)
    raise Bad(u"неизвестная метка %s" % t)


def reglist(t):
    u"""`a5/d7/d0` или `d0-d3/a2` -> маска: биты 0..7 — d0..d7, 8..15 — a0..a7."""
    mask = 0
    for part in t.split("/"):
        m = re.match(r"^([ad])([0-7])(?:-([ad])([0-7]))?$", part)
        if not m:
            raise Bad(u"список регистров %s" % t)
        lo = (8 if m.group(1) == "a" else 0) + int(m.group(2))
        hi = lo if not m.group(3) else (8 if m.group(3) == "a" else 0) + int(m.group(4))
        for r in range(lo, hi + 1):
            mask |= 1 << r
    return mask


def operand(t):
    u"""Операнд листинга -> список для JSON.

    ["d", n] / ["a", n]      — регистр;
    ["#", v]                 — непосредственное;
    ["abs", адрес]           — абсолютный адрес (и `метка(pc)` тоже: он известен);
    ["ind", n]               — (an);   ["inc", n] — (an)+;   ["dec", n] — -(an);
    ["disp", d, n]           — d(an);
    ["idx", d, n, r, long]   — (d,an,rX.w|l); n = -1 — от pc, тогда d — адрес;
    ["regs", маска]          — список `movem`;
    ["sr"] / ["ccr"].
    """
    t = t.strip()
    m = REG.match(t)
    if m:
        return [m.group(1), int(m.group(2))]
    if t in ("sr", "ccr"):
        return [t]
    if t.startswith("#"):
        return ["#", num(t[1:])]
    m = re.match(r"^\((a[0-7])\)$", t)
    if m:
        return ["ind", int(m.group(1)[1])]
    m = re.match(r"^\((a[0-7])\)\+$", t)
    if m:
        return ["inc", int(m.group(1)[1])]
    m = re.match(r"^-\((a[0-7])\)$", t)
    if m:
        return ["dec", int(m.group(1)[1])]
    m = re.match(r"^(-?\$?[0-9A-Fa-f]+)\((a[0-7])\)$", t)
    if m:
        return ["disp", num(m.group(1)), int(m.group(2)[1])]
    m = re.match(r"^\((-?\$?[0-9A-Fa-f]+),(a[0-7]),([ad][0-7])\.([wl])\)$", t)
    if m:
        r = m.group(3)
        return ["idx", num(m.group(1)), int(m.group(2)[1]),
                (8 if r[0] == "a" else 0) + int(r[1]), m.group(4) == "l"]
    m = re.match(r"^\(([^,()]+),pc,([ad][0-7])\.([wl])\)$", t)
    if m:
        r = m.group(2)
        return ["idx", addr_of(m.group(1)), -1,
                (8 if r[0] == "a" else 0) + int(r[1]), m.group(3) == "l"]
    m = re.match(r"^\(([^,()]+),pc\)$", t) or re.match(r"^([^,()]+)\(pc\)$", t)
    if m:
        return ["abs", addr_of(m.group(1))]
    m = re.match(r"^\(([^,()]+)\)\.[wl]$", t)
    if m:
        return ["abs", addr_of(m.group(1))]
    if re.match(r"^[ad][0-7](?:-[ad][0-7])?(?:/[ad][0-7](?:-[ad][0-7])?)*$", t):
        return ["regs", reglist(t)]
    raise Bad(u"операнд %s" % t)


def split_ops(s):
    u"""Операнды через запятую, не разрывая скобки."""
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return [x.strip() for x in out]


BRANCH = {"bra", "bsr", "beq", "bne", "bcs", "bcc", "bhi", "bls", "bge", "blt",
          "bgt", "ble", "bmi", "bpl", "bvs", "bvc"}
END = {"rts", "rte", "bra", "jmp"}


class Ins(object):
    __slots__ = ("a", "mn", "size", "ops", "text")

    def __init__(self, a):
        self.a = a
        self.text = CODE[a]
        parts = self.text.split(None, 1)
        mn = parts[0]
        m = re.match(r"^(\w+)\.([bwls])$", mn)
        if m:
            mn, sz = m.group(1), SIZES[m.group(2)]
        else:
            sz = 0
        self.mn = mn
        self.size = sz
        args = parts[1] if len(parts) > 1 else ""
        raw = split_ops(args)
        if mn in BRANCH or mn in ("dbf", "dbra"):
            # цель ветвления — адрес; операнд-регистр у dbf первый
            tgt = addr_of(raw[-1])
            self.ops = [operand(x) for x in raw[:-1]] + [["to", tgt]]
        elif mn in ("jsr", "jmp"):
            m = re.match(r"^\(([^,()]+)\)\.[wl]$", raw[0]) or re.match(r"^([A-Za-z_]\w*)$", raw[0])
            if m:
                self.ops = [["to", addr_of(m.group(1))]]
            else:
                self.ops = [operand(raw[0])]
        else:
            self.ops = [operand(x) for x in raw]
        if mn == "moveq" or mn in ("lea", "pea", "swap", "exg"):
            self.size = 4
        if mn == "dbra":
            self.mn = "dbf"


# ── Программа этапа ─────────────────────────────────────────────────────
def script_entry(stage):
    return (SCRIPT_TABLE + s16(SCRIPT_TABLE + 2 * stage)) & 0xFFFFFF


def plan_record(stage):
    return (PLAN_TABLE + s16(PLAN_TABLE + 2 * stage)) & 0xFFFFFF


_BINS = sorted((s, e) for s, e in BIN_AT.items())
_BIN_STARTS = [s for s, _e in _BINS]


def bin_segment(a):
    u"""Сегмент `bin`, в котором лежит адрес, или None."""
    import bisect
    i = bisect.bisect_right(_BIN_STARTS, a) - 1
    if i >= 0 and _BINS[i][0] <= a < _BINS[i][1]:
        return _BINS[i]
    return None


def is_code_start(a):
    return a in CODE or NAME.get(a) in NATIVE_PRED


def plan_end():
    u"""Конец последней записи `AiPlanTable`: таблица слов и все записи."""
    return max(plan_record(st) for st in range(256)) + PLAN_SIZE


class Program(object):
    u"""Достижимый код этапов, его нативные вызовы и чтения ROM.

    `ins` — инструкции машины; `natives` — имя -> адрес; `rom` — начало ->
    байты читаемых таблиц ROM. `AiPlanTable` выгружается целиком: 256 слов
    и все записи — фазовая машина берёт запись по байту этапа.
    """

    def __init__(self, stages):
        self.stages = list(stages)
        self.ins = {}
        self.natives = {}
        self.rom = {}
        self.errors = []
        self._work = [script_entry(st) for st in self.stages]
        self._walk()

    def native(self, a):
        n = name_of(a)
        self.natives[n] = a
        return n

    def code(self, a):
        u"""Адрес кода: нативный — в список, свой — в обход."""
        if is_native(a):
            self.native(a)
        else:
            self._work.append(a)

    def _walk(self):
        while self._work:
            a = self._work.pop()
            while a is not None and a not in self.ins:
                if a not in CODE:
                    self.errors.append(u"нет кода по $%06X" % a)
                    break
                try:
                    x = Ins(a)
                except Bad as e:
                    self.errors.append(u"$%06X %s: %s" % (a, CODE[a], e))
                    break
                self.ins[a] = x
                for o in x.ops:
                    if o[0] == "to":
                        if x.mn in ("bsr", "jsr", "jmp"):
                            self.code(o[1])
                        elif is_native(o[1]):
                            self.errors.append(u"$%06X: ветвление в нативную %s"
                                               % (a, name_of(o[1])))
                        else:
                            self._work.append(o[1])
                    elif o[0] == "abs" or (o[0] == "idx" and o[2] == -1):
                        self._ref(x, o)
                if x.mn in END:
                    break
                a = after(a)

    def _ref(self, x, o):
        u"""Адрес в операнде: код, таблица ROM или ОЗУ."""
        t = o[1]
        if t >= 0xFF0000:
            return                          # ОЗУ: её проверяет машина ремейка
        if o[0] == "abs" and is_code_start(t) and not bin_segment(t)                 or NAME.get(t) in NATIVE_PRED:
            self.code(t)
            return
        if t == PLAN_TABLE:
            self.rom[PLAN_TABLE] = ROM[PLAN_TABLE:plan_end()]
            return
        if x.mn == "pea":
            return                          # указатель на строку реплики: не читается
        if o[0] == "abs" and x.mn not in ("lea", "jmp", "jsr") and x.size:
            self.rom[t] = ROM[t:t + x.size]  # одно значение из большой таблицы
            return
        seg = bin_segment(t)
        if seg is None:
            self.errors.append(u"$%06X: адрес $%06X не код и не таблица" % (x.a, t))
            return
        s, e = seg
        if e - s > 0x400:
            self.errors.append(u"$%06X: таблица $%06X…$%06X велика" % (x.a, s, e))
            return
        self.rom[s] = ROM[s:e]
        if x.mn == "jmp" or (o[0] == "idx" and self._jump_table(x)):
            # таблица переходов: слова от её начала
            for w in range(s, e - 1, 2):
                tgt = (s + s16(w)) & 0xFFFFFF
                if tgt in CODE:
                    self.code(tgt)
            return
        # таблицы фаз и прочие: длинные слова, указывающие в код ИИ
        for w in range(s, e - 3, 2):
            v = u32(w)
            if AI_CODE[0] <= v < AI_CODE[1] and v in CODE:
                self.code(v)

    def _jump_table(self, x):
        nxt = after(x.a)
        return nxt is not None and CODE[nxt].startswith("jmp") and "pc," in CODE[nxt]


def silent(stage):
    u"""Скрипт этапа — голый `rts`: поединок (181…210) и 59…65."""
    return CODE.get(script_entry(stage)) == "rts"


def merged(rom):
    u"""Байты ROM одним списком отрезков без перекрытий."""
    out = []
    for a in sorted(rom):
        b = bytes(rom[a])
        if out and a <= out[-1][0] + len(out[-1][1]):
            s0, bb = out[-1]
            end = max(s0 + len(bb), a + len(b))
            out[-1] = (s0, ROM[s0:end])
        else:
            out.append((a, b))
    return out


def library():
    u"""Вся программа ИИ: код всех этапов, у которых скрипт не пуст."""
    stages = [st for st in range(256) if not silent(st)]
    p = Program(stages)
    if p.errors:
        raise AssertionError(u"\n".join(p.errors))
    ops = []
    for a in sorted(p.ins):
        x = p.ins[a]
        ops.append([a, x.mn, x.size] + x.ops)
    return collections.OrderedDict([
        ("format", 1),
        ("scripts", [[st, script_entry(st)] for st in stages]),
        ("natives", collections.OrderedDict(sorted(p.natives.items()))),
        ("ops", ops),
        ("rom", [[a, b.hex()] for a, b in merged(p.rom)]),
    ])


def write_library(path):
    u"""Пишет программу: по инструкции на строку, чтобы diff был читаем."""
    lib = library()
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    compact = dict(separators=(",", ":"))
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(u"{\n")
        f.write(u'"format": %d,\n' % lib["format"])
        f.write(u'"scripts": %s,\n' % json.dumps(lib["scripts"], **compact))
        f.write(u'"natives": %s,\n' % json.dumps(lib["natives"], **compact))
        f.write(u'"ops": [\n')
        f.write(u",\n".join(json.dumps(o, **compact) for o in lib["ops"]))
        f.write(u'\n],\n"rom": [\n')
        f.write(u",\n".join(json.dumps(r, **compact) for r in lib["rom"]))
        f.write(u"\n]\n}\n")
    return lib


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=int, help=u"текст программы одного этапа")
    ap.add_argument("--out", default=out_path("export", "ai", "opponent.json"))
    args = ap.parse_args()
    if args.stage is not None:
        p = Program([args.stage])
        for err in p.errors:
            print(u"ошибка: %s" % err)
        for a in sorted(p.ins):
            label = NAME.get(a, "")
            if label.startswith("loc_"):
                label = ""
            print(u"%06X  %-24s %s" % (a, label, CODE[a]))
        print(u"\nнативные: %s" % ", ".join(sorted(p.natives)))
        return 0
    lib = write_library(args.out)
    print(u"записано: %s — %d этапов, %d инструкций, %d нативных, %d байт ROM"
          % (os.path.relpath(args.out, HERE), len(lib["scripts"]), len(lib["ops"]),
             len(lib["natives"]), sum(len(r[1]) // 2 for r in lib["rom"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
