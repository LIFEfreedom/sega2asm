#!/usr/bin/env python3
"""Факты для спецификации поведения: что процедура делает с числами.

    python tools/spec.py --proc 2A9A16         одна процедура, своё тело
    python tools/spec.py --table 1FF6EA 4      автомат: состояние -> факты
    python tools/spec.py --kinds               все клеточные виды противников
    python tools/spec.py --prog 1FF070         программа поведения `+$48`
    python tools/spec.py --kind 29DFC4         досье вида по конструктору
    python tools/spec.py --dump 29DFC4         то же, сами команды
    python tools/spec.py --boxes 1D8720        коробки кадров скрипта

Это не пересказ, а выписка. Обход берёт СВОЁ тело процедуры — ветвления и
проваливание, без входа в `bsr`/`jsr` (тот же обход, что в `states.py`), — и
из каждой команды достаёт то, что годится в спецификацию:

* переходы: `move.b #N,$4(a0)` (состояние) и `$5(a0)` (подсостояние);
* скорости: непосредственные записи и прибавки в `+$16`/`+$18`;
* таймеры и поля: записи непосредственных чисел в поля записи;
* пороги: `cmpi` с непосредственным числом;
* звуки: `pea ($0000NN).w` перед `SoundStart`;
* вызовы: куда зовёт, и имя, если помощник известен.

Скорости записаны в 8.8 — пикселей за кадр, умноженных на 256, — и
горизонтальная считается ОТ ВЗГЛЯДА: `loc_29A982` переворачивает её по
биту 11 флагов. Отсюда и знак в выводе: `+$0200` у `+$16` значит «вперёд».
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import enemies as E                                          # noqa: E402
import states as S                                           # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

U32 = S.U32

# Помощники, которые уже прочитаны; имена — из enemies.md, player.md,
# engine.md и objects.md.
HELPERS = {
    0x2A2C48: u"ядро урона",
    0x29974C: u"завести объект",
    0x2997B2: u"снять объект",
    0x299CF8: u"общая смерть",
    0x2918BA: u"уборка, если клетка уехала",
    0x29192A: u"уборка сейчас",
    0x29A982: u"шаг движения",
    0x29A6A6: u"тяготение",
    0x29A6C8: u"тяготение с трением",
    0x29A700: u"падать до земли",
    0x2919A2: u"есть ли земля в точке",
    0x2A516A: u"код клетки в точке",
    0x2AB40A: u"расстояние до игрока по X",
    0x2AB41A: u"расстояние до игрока по Y",
    0x2AB4B8: u"шаг патрулирования",
    0x2AB4FC: u"щуп края и стены",
    0x2AB514: u"щуп земли",
    0x2AB380: u"запустить цепочку",
    0x29AA6A: u"я в кадре?",
    0x296B0C: u"случайное число",
    0x2A7C4E: u"направление на точку",
    0x2A9FDE: u"повернуться к игроку",
    0x2A9F56: u"пол позади?",
    0x2A9F78: u"стоит ли прыгать",
    0x2A9FA6: u"влезет ли рывок",
    0x29562C: u"куда доворачивать",
    0x2A1F7C: u"выстрел в пяти направлениях",
    0x299920: u"урон игроку",
    0x29997E: u"урон игроку",
    0x299A00: u"урон игроку",
    0x296822: u"в длинный список кадра",
    0x2967FE: u"в короткий список кадра",
    0x2A5830: u"заплатка CRAM",
    0x297780: u"зажим камерой",
}

FIELD = {
    0x4: u"состояние", 0x5: u"подсостояние", 0x6: u"таймер +6",
    0xA: u"неуязвимость", 0x16: u"скорость X", 0x18: u"скорость Y",
    0x1C: u"жизни", 0x26: u"длит. кадра", 0x28: u"счёт кадра",
    0x42: u"удар", 0x43: u"урон", 0x44: u"тип удара",
}

MOVE_IMM = re.compile(
    r"^move\.([bwl])\s+#\$([0-9A-F]+),\$([0-9A-F]+)\(a0\)$")
MOVEQ = re.compile(r"^moveq\s+#(-?\d+),d(\d)$")
ADD_IMM = re.compile(
    r"^(addi|subi|addq|subq)\.([bwl])\s+#\$?([0-9A-F]+),\$([0-9A-F]+)\(a0\)$")
CMP_IMM = re.compile(r"^cmpi\.([bwl])\s+#\$([0-9A-F]+),(.+)$")
CALL = re.compile(r"^(?:bsr(?:\.[sw])?|jsr)\s+\(?(?:loc_|\$00)([0-9A-F]{6})")
SND = re.compile(r"pea\s+\(\$0000([0-9A-F]{2})\)\.w")
TABLE = re.compile(r"lea\s+\(\$(1F[0-9A-F]{4})\)\.l,a\d")
PLAYER = re.compile(r"\(\$FFFFE1DC\)|\(\$FFFFE1DE\)|\(\$FF220C\)"
                    r"|\(\$FFFFE1CA\)")


def signed(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >= 1 << (bits - 1) else v


def show(v, bits):
    s = signed(v, bits)
    return ("-$%X" % -s) if s < 0 else ("$%X" % s)


def facts(at):
    """Своё тело процедуры -> словарь выписок."""
    out = {"states": set(), "subs": set(), "vel": [], "fields": [],
           "adds": [], "cmps": [], "sounds": set(), "calls": {},
           "player": False, "size": 0, "tables": set()}
    b = S.body(at, cap=400)
    out["size"] = len(b)
    for a in b:
        t = E.BY[a]
        m = MOVE_IMM.match(t)
        if m:
            w, v, off = m.group(1), int(m.group(2), 16), int(m.group(3), 16)
            bits = {"b": 8, "w": 16, "l": 32}[w]
            if off == 0x4 and w == "b":
                out["states"].add(v)
            elif off == 0x5 and w == "b":
                out["subs"].add(v)
            elif off == 0x16 and w == "l":
                out["vel"].append((a, u"X,Y", "%s,%s" % (
                    show(v >> 16, 16), show(v, 16))))
            elif off in (0x16, 0x18) and w == "w":
                out["vel"].append((a, FIELD[off], show(v, 16)))
            elif off not in (0x1E, 0x22, 0x48):
                out["fields"].append((a, off, show(v, bits)))
        m = ADD_IMM.match(t)
        if m:
            op, w, v, off = m.groups()
            v, off = int(v, 16), int(off, 16)
            sgn = -1 if op.startswith("sub") else 1
            out["adds"].append((a, off, sgn * v))
        m = CMP_IMM.match(t)
        if m:
            w, v, what = m.group(1), int(m.group(2), 16), m.group(3)
            bits = {"b": 8, "w": 16, "l": 32}[w]
            out["cmps"].append((a, what, show(v, bits)))
        m = SND.search(t)
        if m:
            out["sounds"].add(int(m.group(1), 16))
        m = CALL.match(t)
        if m:
            tgt = int(m.group(1), 16)
            out["calls"][tgt] = out["calls"].get(tgt, 0) + 1
        if PLAYER.search(t):
            out["player"] = True
        m = TABLE.search(t)
        if m:
            out["tables"].add(int(m.group(1), 16))
    return out


def fmt_field(off):
    return FIELD.get(off, u"+$%X" % off)


def print_facts(at, indent=u"  "):
    f = facts(at)
    p = indent
    print(u"%sкоманд в своём теле: %d%s" % (
        p, f["size"], u", читает игрока" if f["player"] else u""))
    if f["states"]:
        print(u"%sсостояние ->  %s" % (
            p, u", ".join(str(x) for x in sorted(f["states"]))))
    if f["subs"]:
        print(u"%sподсост.  ->  %s" % (
            p, u", ".join(str(x) for x in sorted(f["subs"]))))
    for a, what, v in f["vel"]:
        print(u"%s$%06X  %s = %s" % (p, a, what, v))
    for a, off, v in f["adds"]:
        print(u"%s$%06X  %s += %d" % (p, a, fmt_field(off), v))
    for a, off, v in f["fields"]:
        print(u"%s$%06X  %s = %s" % (p, a, fmt_field(off), v))
    for a, what, v in f["cmps"]:
        print(u"%s$%06X  сравнить %s с %s" % (p, a, what, v))
    if f["tables"]:
        print(u"%sтаблицы: %s" % (
            p, u", ".join("$%06X" % x for x in sorted(f["tables"]))))
    if f["sounds"]:
        print(u"%sзвуки: %s" % (
            p, u", ".join("$%02X" % s for s in sorted(f["sounds"]))))
    if f["calls"]:
        named = []
        for tgt in sorted(f["calls"]):
            nm = HELPERS.get(tgt)
            named.append(u"$%06X%s" % (tgt, u" (%s)" % nm if nm else u""))
        print(u"%sзовёт: %s" % (p, u"; ".join(named)))


# Программа поведения `+$48`. Базы переходов сняты с обработчиков в
# `$2A64E6`-`$2A65C4` побайтово, и они РАЗНЫЕ: у `$85` смещение считается
# от самой команды (`adda.w $2(a1),a1`, a1 ещё на коде), у `$86` и `$8C` —
# от операнда (`adda.w (a1),a1` после `(a1)+`), у `$8D` — от второго
# операнда.
PLEN = {0x80: 4, 0x81: 4, 0x82: 6, 0x83: 4, 0x84: 6, 0x85: 4, 0x86: 4,
        0x87: 4, 0x88: 4, 0x89: 4, 0x8A: 4, 0x8B: 4, 0x8C: 4, 0x8D: 6}


def U16(a):
    return int.from_bytes(S.ROM[a:a + 2], "big")


def prog_step(at):
    """Одна команда программы -> (текст, длина, куда ещё может пойти, конец)."""
    op, ff = S.ROM[at], S.ROM[at + 1]
    if op < 0x80:
        w = U16(at)
        lo = w & 0xFF
        if lo == 0x7E:
            txt = u"конец шага: остаться в состоянии"
        elif lo > 0x7E:
            txt = u"конец шага: подсостояние 2 (цепочка)"
        else:
            txt = u"конец шага: состояние %d" % lo
        return txt, 2, [], False
    if op not in PLEN:
        return u"?? $%02X — не команда" % op, 0, [], True
    n = PLEN[op]
    w1 = U16(at + 2)
    fld = fmt_field(ff)
    if op == 0x80:
        return u"%s (байт) = %s" % (fld, show(w1 & 0xFF, 8)), n, [], False
    if op == 0x81:
        return u"%s = %s" % (fld, show(w1, 16)), n, [], False
    if op == 0x82:
        v = U32(at + 2)
        if ff == 0x16:
            return u"скорость X,Y = %s,%s" % (
                show(v >> 16, 16), show(v, 16)), n, [], False
        return u"%s (длинное) = $%08X" % (fld, v), n, [], False
    if op == 0x83:
        return u"%s = %s" % (fmt_field(w1), fld), n, [], False
    if op == 0x84:
        return u"скрипт анимации $%06X" % U32(at + 2), n, [], False
    if op == 0x85:
        t = at + signed(w1, 16)
        return u"перейти на $%06X" % t, n, [t], True
    if op == 0x86:
        t = at + 2 + signed(w1, 16)
        return (u"с вероятностью %d/256 перейти на $%06X" % (ff + 1, t),
                n, [t], False)
    if op == 0x87:
        return u"%s += %d" % (fld, signed(w1, 16)), n, [], False
    if op == 0x88:
        return (u"%s += %d по взгляду" % (fld, signed(w1, 16)), n, [],
                False)
    if op in (0x89, 0x8A, 0x8B):
        sym = {0x89: u"|=", 0x8A: u"&=", 0x8B: u"^="}[op]
        return u"%s %s $%04X" % (fld, sym, w1), n, [], False
    if op == 0x8C:
        t = at + 2 + signed(w1, 16)
        return u"если %s не ноль — на $%06X" % (fld, t), n, [t], False
    if op == 0x8D:
        t = at + 4 + signed(U16(at + 4), 16)
        return (u"если %s == %d — на $%06X" % (fld, w1 & 0xFF, t), n, [t],
                False)
    return u"?", n, [], True


def prog(start, cap=600):
    """Обход программы по всем путям -> {адрес: (текст, длина)}."""
    got, q = {}, [start]
    while q and len(got) < cap:
        at = q.pop()
        while at not in got and len(got) < cap:
            txt, n, more, stop = prog_step(at)
            got[at] = (txt, n)
            q.extend(more)
            if stop or n == 0:
                break
            at += n
            # Конец шага, за которым лежит указатель на код, — это уже не
            # программа, а соседняя таблица состояний: у программы смерти
            # шамана `$1FF474` сразу за последним шагом стоит `$1FF47C`.
            if S.ROM[at - n] < 0x80 and U32(at) in E.BY:
                break
    return got


def do_prog(start):
    got = prog(start)
    targets = set()
    for a in got:
        _t, _n, more, _s = prog_step(a)
        targets.update(more)
    for a in sorted(got):
        txt, n = got[a]
        raw = " ".join("%02X" % b for b in S.ROM[a:a + max(n, 2)])
        mark = u"->" if a in targets else u"  "
        print(u"%s $%06X  %-20s %s" % (mark, a, raw, txt))


def table_len(base, cap=24):
    """Сколько подряд длинных слов таблицы указывают на код."""
    n = 0
    while n < cap and U32(base + 4 * n) in E.BY:
        n += 1
    return n


def do_kind(ctor):
    """Досье вида: конструктор, обновление, автомат, программы."""
    d = E.describe(ctor)
    print(u"### конструктор $%06X" % ctor)
    print(u"  жизни %s, неуязвимость %s, маска %s, урон %s" % (
        ",".join(str(x) for x in sorted(d["hp"])) or u"0 (по умолчанию)",
        ",".join(str(x) for x in sorted(d["inv"])) or u"-",
        ",".join("$%04X" % x for x in sorted(d["mask"])) or u"-",
        ",".join("$%02X" % x for x in sorted(d["dmg"])) or
        u"$10 (по умолчанию)"))
    print(u"  скрипты %s; программы %s" % (
        ", ".join("$%06X" % x for x in sorted(d["scr"])) or u"-",
        ", ".join("$%06X" % x for x in sorted(d["prog"])) or u"-"))
    print_facts(ctor)
    tabs = set(d["tbl"])
    for u in sorted(d["upd"]):
        print(u"### обновление $%06X" % u)
        print_facts(u)
        tabs |= facts(u)["tables"]
    for t in sorted(tabs):
        n = table_len(t)
        if not n:
            continue
        print(u"### таблица $%06X, состояний %d" % (t, n))
        do_table(t, n)
    for pg in sorted(d["prog"]):
        print(u"### программа $%06X" % pg)
        do_prog(pg)


PROGW = re.compile(r"move\.l\s+#\$00(1F[0-9A-F]{4}),\$48\(a0\)")
UPDW = re.compile(r"move\.l\s+#\$00(2[89A][0-9A-F]{4}),\$(?:1E|50)\(a\d\)"
                  r"|lea\s+\(loc_(2[89A][0-9A-F]{4})\)\.l,a0")
LOCAL = re.compile(r"^bsr(?:\.[sw])?\s+loc_([0-9A-F]{6})")


def own(at, depth=1):
    """Тело процедуры и её прямых `bsr`-помощников, кроме известных."""
    seen, order = set(), []

    def go(a, d):
        if a in seen:
            return
        seen.add(a)
        order.append(a)
        if d == 0:
            return
        for x in S.body(a, cap=400):
            m = LOCAL.match(E.BY[x])
            if m:
                t = int(m.group(1), 16)
                if t not in HELPERS and t in E.BY:
                    go(t, d - 1)
    go(at, depth)
    return order


def listing(at, indent=u"    "):
    for a in S.body(at, cap=400):
        print(u"%s$%06X  %s" % (indent, a, E.BY[a]))


def prog_states(pg):
    got = set()
    for a in prog(pg):
        if S.ROM[a] < 0x80:
            lo = U16(a) & 0xFF
            if lo < 0x7E:
                got.add(lo)
    return got


def do_dump(ctor):
    """Досье для ручного чтения: сами команды, а не выписка.

    Обход идёт до замыкания: конструктор даёт обновление и программу,
    программа назначает состояния, состояние через таблицу даёт
    обработчик, обработчик — цепочку, действие цепочки — новую программу.
    """
    procs = own(ctor, 2)
    progs, upds, tabs, used = [], [], [], set()
    shown, chains_seen = set(), set()

    def scan(p):
        for x in S.body(p, cap=400):
            t = E.BY[x]
            m = PROGW.search(t)
            if m and int(m.group(1), 16) not in progs:
                progs.append(int(m.group(1), 16))
            m = UPDW.search(t)
            if m:
                v = int(m.group(1) or m.group(2), 16)
                if v not in upds and v in E.BY:
                    upds.append(v)

    def show_proc(title, p):
        if p in shown or p not in E.BY:
            return
        shown.add(p)
        print(u"### %s $%06X" % (title, p))
        listing(p)
        scan(p)
        for q in own(p, 1)[1:]:
            if q not in shown:
                shown.add(q)
                print(u"    ... помощник $%06X" % q)
                listing(q, u"      ")
                scan(q)
                for c in chains_in(q):
                    if c not in chains_seen:
                        chains_seen.add(c)
                        do_chain(c, u"      ")
                        for cond, act in chain(c):
                            for r in (cond, act):
                                if r in E.BY:
                                    shown.add(r)
                                    scan(r)
        for t in sorted(facts(p)["tables"]):
            if t not in tabs and table_len(t):
                tabs.append(t)
        for c in chains_in(p):
            if c in chains_seen:
                continue
            chains_seen.add(c)
            do_chain(c, u"    ")
            for cond, act in chain(c):
                for q in (cond, act):
                    if q in E.BY:
                        shown.add(q)
                        scan(q)

    for p in procs:
        show_proc(u"конструктор/помощник", p)
    done_p, done_u, done_s = set(), set(), set()
    scripts = []
    while True:
        work = False
        for u in list(upds):
            if u in done_u:
                continue
            done_u.add(u)
            work = True
            for p in own(u, 1):
                show_proc(u"обновление/помощник", p)
        for pg in list(progs):
            if pg in done_p:
                continue
            done_p.add(pg)
            work = True
            print(u"### программа $%06X" % pg)
            do_prog(pg)
            used |= prog_states(pg)
            for a in sorted(prog(pg)):
                if S.ROM[a] == 0x84:
                    v = U32(a + 2)
                    if v not in scripts:
                        scripts.append(v)
        for t in list(tabs):
            for i in sorted(used):
                if (t, i) in done_s:
                    continue
                done_s.add((t, i))
                work = True
                h = U32(t + 4 * i)
                if h in E.BY:
                    show_proc(u"состояние %d таблицы $%06X:" % (i, t), h)
                    for q in own(h, 1):
                        used |= {x for x in facts(q)["states"] if x < 0x40}
        if not work:
            break
    import anim as AN
    for sc in scripts:
        print(u"### скрипт $%06X" % sc)
        for a, _raw, txt, _fr in AN.walk(sc, 80):
            print(u"    $%06X  %s" % (a, txt))


def chain(at):
    """Цепочка решений `loc_2AB380`: слово N, затем N пар (условие, действие).

    Перед обходом `loc_2AB3AE` кладёт положение игрока относительно себя:
    `d0` — по X от взгляда, `d1` — по Y. Срабатывает первое условие,
    вернувшее `d7 = 0`; если ни одно — ничего.
    """
    n = U16(at)
    return [(U32(at + 2 + 8 * i), U32(at + 6 + 8 * i)) for i in range(n)]


def do_chain(at, indent=u"  "):
    pairs = chain(at)
    print(u"%sцепочка $%06X, пар %d" % (indent, at, len(pairs)))
    for i, (cond, act) in enumerate(pairs):
        print(u"%s  пара %d: условие $%06X -> действие $%06X" % (
            indent, i, cond, act))
        for a in (cond, act):
            if a in E.BY:
                listing(a, indent + u"      ")


CHAINLEA = re.compile(r"lea\s+\(\$(1F[0-9A-F]{4})\)\.l,a1")


def is_chain(at):
    """Похожа ли таблица на цепочку: счётчик 1..10, дальше только код."""
    n = U16(at)
    if not 1 <= n <= 10:
        return False
    return all(U32(at + 2 + 4 * k) in E.BY for k in range(2 * n))


def chains_in(proc):
    """Цепочки, которые процедура грузит в a1 — сама или для помощника."""
    got = []
    for x in S.body(proc, cap=400):
        m = CHAINLEA.search(E.BY[x])
        if m:
            t = int(m.group(1), 16)
            if is_chain(t) and t not in got:
                got.append(t)
    return got


def do_table(base, n):
    for i in range(n):
        h = U32(base + 4 * i)
        print(u"--- состояние %d: $%06X" % (i, h))
        if h in E.BY:
            print_facts(h, u"    ")
        else:
            print(u"    (не код)")


# Номер коробки — номер бита; смысл снят с обработчиков касания
# (`$299AD0`, `$2A95AC`, `$2A35CA`), см. behavior.md, раздел 2.2.
BOXBIT = {14: u"тело", 8: u"удар", 9: u"удар", 10: u"удар", 11: u"удар",
          15: u"зацеп"}


def do_boxes(script):
    """Коробки всех кадров скрипта: общая (`+4` кадра) и подробные."""
    import anim as AN
    import frames as F
    seen = []
    for _a, _raw, _txt, fr in AN.walk(script, 120):
        if fr is None or fr in seen:
            continue
        seen.append(fr)
        v = F.U32(F.BASE + 4 * fr)
        items = F.parse(v)
        if items is None:
            print(u"кадр %4d  не кадр" % fr)
            continue
        print(u"кадр %4d  общая x %+d..%+d, y %+d..%+d" % (
            fr, F.S8(v + 4), F.S8(v + 5), F.S8(v + 6), F.S8(v + 7)))
        for x0, x1, y0, y1, num in F.boxes(v, len(items)):
            print(u"           %-5s (бит %2d) x %+d..%+d, y %+d..%+d" % (
                BOXBIT.get(num, u"-"), num, x0, x1, y0, y1))


def do_kinds():
    cells, where = E.census()
    by_upd = {}
    for (code, ctor), n in cells.items():
        d = E.describe(ctor)
        if not (d["upd"] & E.HITS if isinstance(E.HITS, set)
                else any(u in E.HITS for u in d["upd"])):
            continue
        for u in d["upd"]:
            by_upd.setdefault(u, []).append((ctor, code, n, d))
    for u in sorted(by_upd):
        rows = by_upd[u]
        total = sum(r[2] for r in rows)
        print(u"=== обновление $%06X, клеток %d" % (u, total))
        for ctor, code, n, d in sorted(rows, key=lambda r: -r[2]):
            print(u"    конструктор $%06X код %d клеток %d жизни %s неуяз %s "
                  u"маска %s урон %s" % (
                      ctor, code, n,
                      ",".join(str(x) for x in sorted(d["hp"])) or u"0",
                      ",".join(str(x) for x in sorted(d["inv"])) or u"-",
                      ",".join("$%04X" % x for x in sorted(d["mask"])) or u"-",
                      ",".join("$%02X" % x for x in sorted(d["dmg"])) or
                      u"$10"))
        print_facts(u, u"    ")
        print()


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return
    if a[0] == "--proc":
        print_facts(int(a[1], 16))
    elif a[0] == "--dump":
        do_dump(int(a[1], 16))
    elif a[0] == "--kind":
        do_kind(int(a[1], 16))
    elif a[0] == "--prog":
        do_prog(int(a[1], 16))
    elif a[0] == "--table":
        do_table(int(a[1], 16), int(a[2]))
    elif a[0] == "--kinds":
        do_kinds()
    elif a[0] == "--boxes":
        do_boxes(int(a[1], 16))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
