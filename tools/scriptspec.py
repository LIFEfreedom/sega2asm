#!/usr/bin/env python3
"""Байт-код скриптов анимации для ремейка Maui Mallard.

    SEGA2ASM_CONFIG=platformer.yaml python tools/scriptspec.py          выгрузка
    SEGA2ASM_CONFIG=platformer.yaml python tools/scriptspec.py --check  только проверка

Ремейк исполняет скрипты сам, тем же порядком, что `AnimStep` (`$297010`) и
`$297074`, поэтому получает их **как есть** — байтами ROM, без перевода:

* `anim/scripts.bin` — область скриптов `$1D6000`-`$1DE000` (уровни и, за `$1DC000`,
  экраны вне уровня);
* `anim/frame_slots.bin` — таблица кадров `$0200`-`$3898`: длинное слово на
  слот; слово кадра в скрипте — адрес слота, кадр объекта `+$C` — длинное
  слово из него;
* `anim/scripts.json` — где что лежит, формы игрока, все найденные входы
  (адрес и откуда взят) и итог проверки;
* `anim/scripts.txt` — разбор всех найденных скриптов для чтения.

Проверка: скрипты ищутся в таблицах форм игрока (`$1FCC64`, `$1FCC90`,
`$1FCCB8`), в каждой команде `move.l #адрес,$22(An)` банка кода, в записи
`$22` игрока по абсолютному адресу (`$FFFFE1EC`) и в программах порождения
(`$84 $00` + адрес). От каждого входа обход идёт по всем веткам (`$D9`, `$DB`,
`$E5`, `$E6`): каждый шаг обязан лежать в области, команда — в таблице
`$2970D6`, слово кадра — указывать на слот таблицы кадров.
"""
import io
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT, rom_bytes  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM = rom_bytes()
U16 = lambda o: struct.unpack_from(">H", ROM, o)[0]
S16 = lambda o: struct.unpack_from(">h", ROM, o)[0]
U32 = lambda o: struct.unpack_from(">I", ROM, o)[0]

SCRIPTS = (0x1D6000, 0x1DE000)
SLOTS = (0x000200, 0x003898)
CODE = (0x28D000, 0x2AC000)
SPAWN_PROGRAMS = (0x1FEDCA, 0x1FF3EC)
PLAYER_SCRIPT_ABS = 0xE1EC          # $FFFFE1CA + $22, адрес .w
FORMS = ((0, 0x1FCC64, 0x1FCC90), (1, 0x1FCC90, 0x1FCCB8), (2, 0x1FCCB8, 0x1FCCE0))

# $2970D6: команда -> длина в байтах (по обработчикам с $297126; $E9 с $2972EE)
LENGTH = {0xD8: 2, 0xD9: 4, 0xDA: 2, 0xDB: 4, 0xDC: 4, 0xDD: 6, 0xDE: 4,
          0xDF: 2, 0xE0: 2, 0xE1: 4, 0xE2: 4, 0xE3: 4, 0xE4: 4, 0xE5: 4,
          0xE6: 6, 0xE7: 6, 0xE8: 6, 0xE9: 6, 0xEA: 2, 0xEB: 2}
NAMES = {0xD8: "hold", 0xD9: "jump", 0xDA: "flip", 0xDB: "random-branch",
         0xDC: "set.w", 0xDD: "set.l", 0xDE: "add.w", 0xDF: "load $8",
         0xE0: "store $8", 0xE1: "set.b", 0xE2: "or.w", 0xE3: "and.w",
         0xE4: "eor.w", 0xE5: "branch-if-byte", 0xE6: "branch-if-byte-eq",
         0xE7: "spawn 1", 0xE8: "spawn 2", 0xE9: "spawn 3", 0xEA: "sound",
         0xEB: "sound-stop"}


class Bad(Exception):
    pass


def step(a):
    """-> (длина, текст, [следующие адреса]) одного шага скрипта в `a`."""
    if not SCRIPTS[0] <= a < SCRIPTS[1] - 1:
        raise Bad("шаг $%06X вне области скриптов" % a)
    hi = ROM[a]
    if hi < 0xD8:
        w = U16(a)
        if w < 3:
            return 2, "short %d" % w, [a + 2]
        if not (SLOTS[0] <= w < SLOTS[1] and w % 4 == 0):
            raise Bad("слово кадра $%04X в $%06X не слот таблицы" % (w, a))
        return 2, "frame %d (slot $%04X)" % ((w - SLOTS[0]) // 4, w), [a + 2]
    if hi not in LENGTH:
        raise Bad("команда $%02X в $%06X вне таблицы $2970D6" % (hi, a))
    n = ROM[a + 1]
    ln = LENGTH[hi]
    if a + ln > SCRIPTS[1]:
        raise Bad("команда в $%06X выходит за область" % a)
    txt = "%s $%02X" % (NAMES[hi], n)
    if hi == 0xD9:
        # adda.w $2(a1),a1 - от начала команды
        return ln, txt + " -> $%06X" % (a + S16(a + 2)), [a + S16(a + 2)]
    if hi in (0xDB, 0xE5):
        # слово смещения сразу за командой, отсчёт от него
        t = a + 2 + S16(a + 2)
        return ln, txt + " -> $%06X" % t, [t, a + 4]
    if hi == 0xE6:
        t = a + 4 + S16(a + 4)
        return ln, txt + " == $%04X -> $%06X" % (U16(a + 2), t), [t, a + 6]
    if ln == 4:
        txt += ", $%04X" % U16(a + 2)
    elif ln == 6:
        txt += ", $%08X" % U32(a + 2)
    return ln, txt, [a + ln]


def walk(entry, seen):
    """Обход всех веток от `entry`; -> адреса шагов, которые встретились впервые."""
    todo, found = [entry], []
    while todo:
        a = todo.pop()
        if a in seen:
            continue
        seen.add(a)
        found.append(a)
        _ln, _txt, nxt = step(a)
        todo.extend(nxt)
    return found


def entries():
    """Известные входы -> {адрес: откуда}."""
    out = {}
    for form, lo, hi in FORMS:
        for i in range((hi - lo) // 4):
            out.setdefault(U32(lo + 4 * i), "form %d script %d" % (form, i))
    a = CODE[0]
    while a < CODE[1] - 8:
        op = U16(a)
        # move.l #imm,$22(An): 0x217C | An << 9
        if op & 0xF1FF == 0x217C and U16(a + 6) == 0x0022:
            v = U32(a + 2)
            if SCRIPTS[0] <= v < SCRIPTS[1]:
                out.setdefault(v, "move.l at $%06X" % a)
        # move.l #imm,($FFFFE1EC).w - $22 игрока
        if op == 0x21FC and U16(a + 6) == PLAYER_SCRIPT_ABS:
            v = U32(a + 2)
            if SCRIPTS[0] <= v < SCRIPTS[1]:
                out.setdefault(v, "move.l at $%06X" % a)
        a += 2
    a = SPAWN_PROGRAMS[0]
    while a < SPAWN_PROGRAMS[1] - 6:
        if ROM[a] == 0x84 and ROM[a + 1] == 0x00:
            v = U32(a + 2)
            if SCRIPTS[0] <= v < SCRIPTS[1]:
                out.setdefault(v, "spawn program at $%06X" % a)
        a += 2
    return out


def listing(known, seen_order):
    lines = []
    for a in sorted(seen_order):
        ln, txt, _ = step(a)
        mark = "  <- %s" % known[a] if a in known else ""
        raw = " ".join("%02X" % b for b in ROM[a:a + ln])
        lines.append("$%06X  %-17s %s%s" % (a, raw, txt, mark))
    return lines


def main():
    known = entries()
    seen = set()
    errors = []
    for a in sorted(known):
        try:
            walk(a, seen)
        except Bad as e:
            errors.append("%s (вход $%06X, %s)" % (e, a, known[a]))
    print(u"входов: %d, шагов: %d, ошибок: %d" % (len(known), len(seen), len(errors)))
    for e in errors:
        print(u"ошибка: %s" % e)
    if errors:
        return 1
    if "--check" in sys.argv:
        return 0

    out = OUT("export", "anim")
    if not os.path.isdir(out):
        os.makedirs(out)
    with open(os.path.join(out, "scripts.bin"), "wb") as f:
        f.write(ROM[SCRIPTS[0]:SCRIPTS[1]])
    with open(os.path.join(out, "frame_slots.bin"), "wb") as f:
        f.write(ROM[SLOTS[0]:SLOTS[1]])
    doc = {
        "meta": {
            "game": "Maui Mallard in Cold Shadow (Mega Drive)",
            "generator": "tools/scriptspec.py",
            "executor": "AnimStep $297010, AnimScript $297074, AnimCommand $296FAE, "
                        "commands $2970D6 -> $297126-$2972EE",
        },
        "scripts": {"file": "scripts.bin", "base": "$%06X" % SCRIPTS[0],
                    "length": SCRIPTS[1] - SCRIPTS[0]},
        "frame_slots": {"file": "frame_slots.bin", "base": "$%06X" % SLOTS[0],
                        "count": (SLOTS[1] - SLOTS[0]) // 4},
        "forms": [{"form": form, "table": "$%06X" % lo,
                   "scripts": ["$%06X" % U32(lo + 4 * i) for i in range((hi - lo) // 4)]}
                  for form, lo, hi in FORMS],
        "checked": {"entries": len(known), "steps": len(seen)},
        "entries": [{"at": "$%06X" % a, "from": known[a]} for a in sorted(known)],
    }
    with io.open(os.path.join(out, "scripts.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(doc, ensure_ascii=False, indent=1))
        f.write("\n")
    with io.open(os.path.join(out, "scripts.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(listing(known, seen)))
        f.write("\n")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
