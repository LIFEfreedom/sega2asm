#!/usr/bin/env python3
"""Программы поведения `+$48`, таблицы состояний и цепочки решений для ремейка Maui Mallard.

    SEGA2ASM_CONFIG=platformer.yaml python tools/programspec.py          выгрузка
    SEGA2ASM_CONFIG=platformer.yaml python tools/programspec.py --check  только проверка

Ремейк исполняет программы сам, как толкователь `$2AB346`, поэтому получает их **как
есть** — байтами ROM, без перевода (решение 2a ремейка, mauimallard #16):

* `programs/programs.bin` — окно данных от первой программы до конца последней таблицы
  состояний: программы и таблицы лежат в нём по своим адресам, так что номер состояния за
  концом среза читает, как и ROM, соседний срез;
* `programs/programs.json` — где окно лежит, все найденные входы программ (адрес и
  откуда взят), таблицы состояний (адрес, откуда, поле-номер, обработчики) и цепочки
  (адрес, откуда, пары «условие, действие» — цепочка `$2AB150` лежит в банке кода, вне
  окна, поэтому ремейк берёт пары отсюда), итог проверки;
* `programs/programs.txt` — разбор всех программ для чтения.

Толкователь (`engine.md`, «Программы поведения `+$48`»): байт `$80`-`$8D` — команда из
таблицы `$2A64AE` (четырнадцать `bra.w` на обработчики `$2A64E6`-`$2A65C2`), байт меньше
`$80` — конец шага: слово, чей МЛАДШИЙ байт сравнивается с `$7E` знаково (`cmpi.b`,
`blt`): меньше — номер состояния в `+$4`, `$7E` — остаться, `$7F` — подсостояние 2.

Где ищутся входы: в банке кода `$28D000`-`$2AC000` побайтно (как `scriptspec.py`) —
`move.l #адрес,$48(An)`, `move.l #адрес,d7` с адресом в окне (вызывающие кладут
программу в `d7`, а `$2AB7BC`, `$29E714` пишут её в `+$48`), и `$82 48` внутри самих
программ. Таблицы состояний — `lea (адрес).l,An`, за которым `movea.l (0,An,Dn.w),Am`
и `jsr (Am)`, с номером из поля объекта (`move.b $nn(a0),d0` рядом; таблица `$1FEC38`
уровня 6 берёт номер из счётчика `$FF2148` и сюда не входит); цепочки — `lea (адрес).l,a1`
и вызов `$2AB380` или обёртки `$2AA476` (щуп впереди, затем та же цепочка по подсостоянию 2).

Проверка: от каждого входа обход идёт по всем веткам (`$85`, `$86`, `$8C`, `$8D`, конец
шага продолжает следующим словом); каждая команда обязана быть из четырнадцати, каждый
скрипт `$84` — проходить обход `scriptspec.py` без ошибки, указатель таблицы или цепочки —
вести в банк кода на чётный адрес.
"""
import io
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT, rom_bytes  # noqa: E402
import scriptspec  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM = rom_bytes()
U16 = lambda o: struct.unpack_from(">H", ROM, o)[0]
S16 = lambda o: struct.unpack_from(">h", ROM, o)[0]
U32 = lambda o: struct.unpack_from(">I", ROM, o)[0]

CODE = (0x28D000, 0x2AC000)
# Где ищутся адреса программ, таблиц и цепочек: банк данных за таблицами уровней.
DATA = (0x1FE000, 0x200000)
CHAIN_WALKER = 0x2AB380
# Кто передаёт a1 в $2AB380: сам обход и $2AA476 (jsr (loc_2AB380).l в $2AA4B8).
CHAIN_CALLERS = (CHAIN_WALKER, 0x2AA476)
INTERPRETER = 0x2AB346
PROGRAM_FIELD = 0x48

# $2A64AE: команда -> длина в байтах (обработчики $2A64E6-$2A65C2; у переходов длина -
# это продолжение, когда переход не взят)
LENGTH = {0x80: 4, 0x81: 4, 0x82: 6, 0x83: 4, 0x84: 6, 0x85: 4, 0x86: 4, 0x87: 4,
          0x88: 4, 0x89: 4, 0x8A: 4, 0x8B: 4, 0x8C: 4, 0x8D: 6}
NAMES = {0x80: "set.b", 0x81: "set.w", 0x82: "set.l", 0x83: "copy.w", 0x84: "script",
         0x85: "jump", 0x86: "random", 0x87: "add.w", 0x88: "add.w facing", 0x89: "or.w",
         0x8A: "and.w", 0x8B: "eor.w", 0x8C: "if byte", 0x8D: "if byte =="}


class Bad(Exception):
    pass


def step(a):
    """-> (длина, текст, [следующие адреса], [новые входы программ]) одного шага в `a`."""
    if not DATA[0] <= a < DATA[1] - 1:
        raise Bad("шаг $%06X вне банка данных" % a)
    hi = ROM[a]
    if hi < 0x80:
        # $2AB364: move.w (a1)+,d0; cmpi.b #$7E,d0; blt/beq
        low = ROM[a + 1]
        signed = low - 0x100 if low >= 0x80 else low
        if signed < 0x7E:
            txt = "end: state %d" % low
        elif signed == 0x7E:
            txt = "end: stay"
        else:
            txt = "end: substate 2"
        return 2, txt, [a + 2], []
    if hi not in LENGTH:
        raise Bad("команда $%02X в $%06X вне таблицы $2A64AE" % (hi, a))
    ln = LENGTH[hi]
    field = ROM[a + 1]
    txt = "%s $%02X" % (NAMES[hi], field)
    if hi == 0x84:
        target = U32(a + 2)
        try:
            scriptspec.walk(target, set())
        except scriptspec.Bad as e:
            raise Bad("скрипт $%06X программы в $%06X: %s" % (target, a, e))
        return ln, "script $%06X" % target, [a + ln], []
    if hi == 0x85:
        # $2A6530 adda.w $2(a1),a1: от самой команды
        t = a + S16(a + 2)
        return ln, "jump -> $%06X" % t, [t], []
    if hi == 0x86:
        # $2A6536: cmp.b d0,d1 / bcs - порог меньше броска: дальше, иначе adda.w (a1),a1 от операнда
        t = a + 2 + S16(a + 2)
        return ln, "random %d/256 -> $%06X" % (field + 1, t), [a + ln, t], []
    if hi == 0x8C:
        t = a + 2 + S16(a + 2)
        return ln, "if byte $%02X != 0 -> $%06X" % (field, t), [a + ln, t], []
    if hi == 0x8D:
        t = a + 4 + S16(a + 4)
        return ln, "if byte $%02X == $%02X -> $%06X" % (field, U16(a + 2) & 0xFF, t), [a + ln, t], []
    entries = []
    if ln == 6:
        value = U32(a + 2)
        txt += ", $%08X" % value
        if hi == 0x82 and field == PROGRAM_FIELD:
            entries.append(value)
    else:
        txt += ", $%04X" % U16(a + 2)
    if hi in (0x80, 0x81, 0x83, 0x87, 0x88, 0x89, 0x8A, 0x8B) and PROGRAM_FIELD - 3 <= field < PROGRAM_FIELD + 4:
        raise Bad("команда в $%06X пишет в указатель программы +$%02X не целиком" % (a, field))
    return ln, txt, [a + ln], entries


def walk(entry, seen, found, stops):
    """Обход всех веток от `entry`; новые входы программ — в `found`. Программа может кончиться
    концом шага, за которым лежит таблица или цепочка (`$1FF474` перед `$1FF47C`): туда обход не идёт."""
    todo = [entry]
    while todo:
        a = todo.pop()
        if a in seen or (a != entry and a in stops):
            continue
        _ln, _txt, nxt, more = step(a)
        seen.add(a)
        todo.extend(nxt)
        for e in more:
            found.setdefault(e, "set.l +$48 at $%06X" % a)


def in_data(v):
    return DATA[0] <= v < DATA[1]


def code_pointer(v):
    return CODE[0] <= v < CODE[1] and v % 2 == 0


def calls_walker(a):
    """jsr (адрес).l или bsr.w на обход цепочки или его обёртку в `a`."""
    if U16(a) == 0x4EB9 and U32(a + 2) in CHAIN_CALLERS:
        return True
    return U16(a) == 0x6100 and a + 2 + S16(a + 2) in CHAIN_CALLERS


def scan():
    """Банк кода -> (программы {адрес: откуда}, таблицы {адрес: (откуда, поле)}, цепочки {адрес: откуда})."""
    programs, tables, chains = {}, {}, {}
    a = CODE[0]
    while a < CODE[1] - 8:
        op = U16(a)
        # move.l #imm,$48(An): 0x217C | An << 9
        if op & 0xF1FF == 0x217C and U16(a + 6) == PROGRAM_FIELD and in_data(U32(a + 2)):
            programs.setdefault(U32(a + 2), "move.l at $%06X" % a)
        # move.l #imm,d7: 0x2E3C
        if op == 0x2E3C and in_data(U32(a + 2)):
            programs.setdefault(U32(a + 2), "move.l d7 at $%06X" % a)
        # lea (abs).l,An: 0x41F9 | An << 9
        if op & 0xF1FF == 0x41F9:
            target = U32(a + 2)
            reg = (op >> 9) & 7
            # move.b $nn(a0),d0 (0x1028) до lea или после
            field = next((U16(b + 2) for b in range(a - 8, a + 24, 2) if U16(b) == 0x1028), None)
            b = a + 6
            while b < a + 24:
                w = U16(b)
                # movea.l (0,An,Dn.w),Am: 0x2070 | Am << 9 | An, расширение Dn.w без сдвига
                if w & 0xF1FF == 0x2070 | reg and U16(b + 2) & 0x8FFF == 0x0000:
                    to = (w >> 9) & 7
                    if U16(b + 4) == 0x4E90 | to and in_data(target) and field is not None:
                        tables.setdefault(target, ("lea at $%06X" % a, field))
                    break
                if calls_walker(b):
                    chains.setdefault(target, "lea at $%06X" % a)
                    break
                b += 2
        a += 2
    return programs, tables, chains


def table_handlers(at, stops):
    """Обработчики таблицы с `at`: до первого негодного указателя или до начала другой таблицы."""
    out = []
    a = at
    while True:
        if a != at and a in stops:
            break
        v = U32(a)
        if not code_pointer(v):
            break
        out.append(v)
        a += 4
    return out


def chain_rules(at):
    """$2AB38C: слово-счётчик, дальше столько пар длинных слов «условие, действие»."""
    count = U16(at)
    rules = []
    for i in range(count):
        cond, act = U32(at + 2 + 8 * i), U32(at + 6 + 8 * i)
        if not (code_pointer(cond) and code_pointer(act)):
            raise Bad("цепочка $%06X: пара %d ($%08X, $%08X) не в банке кода" % (at, i, cond, act))
        rules.append((cond, act))
    return rules


def listing(programs, seen):
    lines = []
    for a in sorted(seen):
        ln, txt, _, _ = step(a)
        mark = "  <- %s" % programs[a] if a in programs else ""
        raw = " ".join("%02X" % b for b in ROM[a:a + ln])
        lines.append("$%06X  %-17s %s%s" % (a, raw, txt, mark))
    return lines


def main():
    programs, tables, chains = scan()
    structures = set(tables) | set(chains)
    seen = set()
    errors = []
    done = set()
    while True:
        todo = sorted(set(programs) - done)
        if not todo:
            break
        for a in todo:
            done.add(a)
            try:
                walk(a, seen, programs, structures)
            except Bad as e:
                errors.append("%s (вход $%06X, %s)" % (e, a, programs[a]))

    stops = set(tables) | set(chains) | set(programs)
    table_rows = []
    for at in sorted(tables):
        handlers = table_handlers(at, stops)
        if not handlers:
            errors.append("таблица $%06X (%s): ни одного указателя в код" % (at, tables[at][0]))
        table_rows.append((at, handlers))
    chain_rows = []
    for at in sorted(chains):
        try:
            chain_rows.append((at, chain_rules(at)))
        except Bad as e:
            errors.append(str(e))

    ends = [a + step(a)[0] for a in seen]
    ends += [at + 4 * len(h) for at, h in table_rows]
    starts = sorted(seen) + [at for at, _ in table_rows]
    base, end = min(starts), max(ends)
    print(u"программ: %d, шагов: %d, таблиц: %d, цепочек: %d, окно $%06X-$%06X (%d байт), ошибок: %d"
          % (len(programs), len(seen), len(table_rows), len(chain_rows), base, end, end - base, len(errors)))
    for e in errors:
        print(u"ошибка: %s" % e)
    if errors:
        return 1
    if "--check" in sys.argv:
        return 0

    out = OUT("export", "programs")
    if not os.path.isdir(out):
        os.makedirs(out)
    with open(os.path.join(out, "programs.bin"), "wb") as f:
        f.write(ROM[base:end])
    doc = {
        "meta": {
            "game": "Maui Mallard in Cold Shadow (Mega Drive)",
            "generator": "tools/programspec.py",
            "interpreter": "$2AB346, commands $2A64AE -> $2A64E6-$2A65C2; state tables: "
                           "lea table, move.b $4(a0),d0, movea.l (0,a1,d0.w),a1, jsr (a1); "
                           "chains $2AB380 (word count, then pairs of condition and action)",
        },
        "image": {"file": "programs.bin", "base": "$%06X" % base, "length": end - base},
        "checked": {"programs": len(programs), "steps": len(seen), "tables": len(table_rows),
                    "chains": len(chain_rows)},
        "programs": [{"at": "$%06X" % a, "from": programs[a]} for a in sorted(programs)],
        "tables": [{"at": "$%06X" % at, "from": tables[at][0],
                    "field": None if tables[at][1] is None else "$%02X" % tables[at][1],
                    "handlers": ["$%06X" % h for h in handlers]}
                   for at, handlers in table_rows],
        "chains": [{"at": "$%06X" % at, "from": chains[at],
                    "rules": [["$%06X" % c, "$%06X" % d] for c, d in rules]}
                   for at, rules in chain_rows],
    }
    with io.open(os.path.join(out, "programs.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(doc, ensure_ascii=False, indent=1))
        f.write("\n")
    with io.open(os.path.join(out, "programs.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(listing(programs, seen)))
        f.write("\n")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
