#!/usr/bin/env python3
"""Чем заняты окна, которые дизассемблер оставил данными.

    python tools/gaps.py             сводка по видам
    python tools/gaps.py --list      окно за окном, с доказательством
    python tools/gaps.py --code      только те, что похожи на код
    python tools/gaps.py --show data_111   разбор одного окна

Внутри банка обработчиков `$28D000`-`$2AC000` обход по потоку управления не
достаёт около 10 КБ: это не данные, а куски, до которых добираются через
таблицу или сваливаются с середины. Два примера уже стоили отдельного
разбора — таблица опкодов `$2A64AE` (четырнадцать `bra.w` подряд, а не
длинные слова) и `data_125` внутри обработчика противника.

Признак здесь НЕ плотность опкодов (этим занят `findcode.py`), а
структурные улики, каждую из которых видно глазами:

* **таблица `bra.w`** — все слова через четыре байта равны `$6000`;
* **таблица указателей** — подряд идут длинные слова из банка кода;
* **вход снаружи** — какая-то команда ветвится или зовёт адрес ВНУТРИ окна;
* **проваливание** — команда прямо перед окном не `rts` и не `bra`, то
  есть выполнение втекает сюда;
* иначе — **данные**.

Что делать с находкой: поменять в `platformer.yaml` `type: bin` на
`type: m68k`, убрать `subdir`, пересобрать и СВЕРИТЬ ПОБАЙТОВО. Побайтовая
сверка тут и есть доказательство: если кусок на самом деле данные,
ассемблер не воспроизведёт их из декодированных команд.
"""
import os
import re
import struct
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import asm_dir, config_path, rom_bytes            # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM = rom_bytes()
U16 = lambda a: struct.unpack_from(">H", ROM, a)[0]           # noqa: E731
U32 = lambda a: struct.unpack_from(">I", ROM, a)[0]           # noqa: E731
S16 = lambda a: struct.unpack_from(">h", ROM, a)[0]           # noqa: E731

CODE = (0x28D000, 0x2AC000)

A_C = re.compile(r"^; \$([0-9A-F]{6})\s*$")
A_L = re.compile(r"^\w+:\s*;\s*\$([0-9A-F]{6})")
TARGET = re.compile(r"(?:loc_|\$00|\$)([0-9A-F]{6})")
FLOW = re.compile(r"^(?:bsr|jsr|bra|jmp|b(?:hi|ls|cc|cs|ne|eq|vc|vs|pl|mi"
                  r"|ge|lt|gt|le)\b|db)")
STOP = re.compile(r"^(?:rts|rte|rtr|bra|jmp)\b")


def load_asm():
    d = asm_dir()
    if not os.path.isdir(d):
        sys.exit("нет разобранного кода: %s (сделайте `make split`)" % d)
    by = {}
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".asm"):
            continue
        cur = None
        for ln in open(os.path.join(d, fn), encoding="utf-8",
                       errors="replace"):
            s = ln.rstrip()
            m = A_C.match(s.strip())
            if m:
                cur = int(m.group(1), 16)
                continue
            m = A_L.match(s)
            if m:
                cur = int(m.group(1), 16)
            t = s.strip()
            if (t and not t.startswith(";") and cur is not None
                    and not re.match(r"^\w+:", t)):
                by.setdefault(cur, re.sub(r"\s+", " ", t))
    return by


BY = load_asm()
ADDRS = sorted(BY)


def windows():
    """Не-m68k сегменты внутри банка кода, по порядку."""
    import yaml
    cfg = yaml.safe_load(open(config_path(), encoding="utf-8"))
    segs = cfg.get("segments") or cfg.get("sections") or []
    out = []
    for s in segs:
        st, en = s.get("start"), s.get("end")
        if st is None or en is None or s.get("type") == "m68k":
            continue
        if en <= CODE[0] or st >= CODE[1]:
            continue
        out.append((max(st, CODE[0]), min(en, CODE[1]), s.get("name")))
    return sorted(out)


def bra_table(lo, hi, least=3):
    """Таблица `bra.w` В НАЧАЛЕ окна: слова через четыре байта равны `$6000`.

    Раньше требовалось, чтобы такими были ВСЕ слова окна, и правило
    промахивалось мимо самого частого случая: таблица и сразу за ней
    её же обработчики в том же окне (`data_43`, `data_44`).
    """
    if hi - lo < 4 * least:
        return None
    n = 0
    while lo + 4 * n + 4 <= hi and U16(lo + n * 4) == 0x6000:
        n += 1
    if n < least:
        return None
    return [lo + k * 4 + 2 + S16(lo + k * 4 + 2) for k in range(n)]


def ptr_table(lo, hi):
    """Подряд идущие длинные слова из банка кода."""
    n = (hi - lo) // 4
    got = []
    for k in range(n):
        v = U32(lo + k * 4)
        if CODE[0] <= v < CODE[1]:
            got.append(v)
        else:
            break
    return got if len(got) >= 4 else None


IMM = re.compile(r"move\.l\s+#\$00([0-9A-F]{6})\s*,")


def all_bra_targets():
    """Цели всех таблиц bra.w, какие найдутся в окнах."""
    got = set()
    for lo, hi, _n in windows():
        br = bra_table(lo, hi)
        if br:
            got |= set(br)
    return got


BRA_TARGETS = None


def rom_pointers():
    """Каждое длинное слово ПЗУ, указывающее в банк кода: адрес -> куда."""
    out = defaultdict(list)
    for a in range(0, len(ROM) - 3, 2):
        v = struct.unpack_from(">I", ROM, a)[0]
        if CODE[0] <= v < CODE[1]:
            out[v].append(a)
    return out


PTRS = None


def entered(lo, hi):
    """Кто ветвится или зовёт адрес внутри окна."""
    out = []
    for a in ADDRS:
        t = BY[a]
        if not FLOW.match(t):
            continue
        for m in TARGET.finditer(t):
            v = int(m.group(1), 16)
            if lo <= v < hi:
                out.append((a, v, t))
    return out


def falls_in(lo):
    """Команда прямо перед окном: втекает ли выполнение внутрь."""
    before = [a for a in ADDRS if a < lo]
    if not before:
        return None
    a = before[-1]
    return None if STOP.match(BY[a]) else (a, BY[a])


def classify(lo, hi, name):
    global BRA_TARGETS, PTRS
    if BRA_TARGETS is None:
        BRA_TARGETS = all_bra_targets()
    if PTRS is None:
        PTRS = rom_pointers()
    ev = []
    br = bra_table(lo, hi)
    if br:
        ev.append(("таблица bra.w", "%d записей -> $%06X..$%06X"
                   % (len(br), min(br), max(br))))
    pt = ptr_table(lo, hi)
    if pt and not br:
        ev.append(("таблица указателей", "%d длинных слов в банке кода"
                   % len(pt)))
    en = entered(lo, hi)
    if en:
        ev.append(("вход снаружи", "%d ссылок, первая $%06X -> $%06X"
                   % (len(en), en[0][0], en[0][1])))
    fi = falls_in(lo)
    if fi and not fi[1].startswith("dc."):
        ev.append(("проваливание", "перед окном $%06X %s" % fi))
    elif fi:
        fi = None
    bt = sorted(v for v in BRA_TARGETS if lo <= v < hi)
    if bt:
        ev.append(("цель таблицы bra.w", "%d входов, первый $%06X"
                   % (len(bt), bt[0])))
    im = []
    for a in ADDRS:
        for m in IMM.finditer(BY[a]):
            v = int(m.group(1), 16)
            if lo <= v < hi:
                im.append((a, v))
    if im:
        ev.append(("ставится процедурой", "%d мест, первое $%06X -> $%06X"
                   % (len(im), im[0][0], im[0][1])))
    rp = []
    for v, places in PTRS.items():
        if lo <= v < hi:
            rp += [(a, v) for a in places]
    outside = [(a, v) for a, v in rp if not (lo <= a < hi)]
    if outside:
        ev.append(("указатель в ПЗУ", "%d мест, первое $%06X -> $%06X"
                   % (len(outside), outside[0][0], outside[0][1])))
    starts = set(v for _a, v, _t in en) | set(bt) | set(v for _a, v in im)
    starts |= set(v for _a, v in outside)
    at_lo = lo in starts
    code = bool(starts or fi)
    kind = ("таблица bra.w" if br else
            "таблица указателей" if pt else
            "код (вход в начало)" if at_lo else
            "код (вход в середину)" if starts else
            "код (проваливание)" if fi else "данные")
    return kind, ev, br, pt, (en + [(a, v, "указатель") for a, v in outside])


def collect():
    rows = []
    for lo, hi, name in windows():
        kind, ev, br, pt, en = classify(lo, hi, name)
        rows.append({"lo": lo, "hi": hi, "name": name, "kind": kind,
                     "ev": ev, "bra": br, "ptr": pt, "in": en})
    return rows


def do_summary():
    rows = collect()
    tot = sum(r["hi"] - r["lo"] for r in rows)
    print("окон в банке кода: %d, всего %d байт" % (len(rows), tot))
    print()
    tally = defaultdict(lambda: [0, 0])
    for r in rows:
        t = tally[r["kind"]]
        t[0] += 1
        t[1] += r["hi"] - r["lo"]
    for k, (n, b) in sorted(tally.items(), key=lambda kv: -kv[1][1]):
        print("   %-20s окон %3d, байт %5d (%.0f %%)"
              % (k, n, b, 100.0 * b / tot))
    print()
    big = sorted(rows, key=lambda r: -(r["hi"] - r["lo"]))[:8]
    print("самые большие:")
    for r in big:
        print("   %-10s $%06X..$%06X  %5d  %s"
              % (r["name"], r["lo"], r["hi"], r["hi"] - r["lo"], r["kind"]))


def do_list(only=None):
    for r in collect():
        if only and r["kind"] != only:
            continue
        print("%-10s $%06X..$%06X  %5d  %s"
              % (r["name"], r["lo"], r["hi"], r["hi"] - r["lo"], r["kind"]))
        for what, detail in r["ev"]:
            print("     %-20s %s" % (what, detail))


def do_show(name):
    for r in collect():
        if r["name"] != name and "$%06X" % r["lo"] != name.upper():
            continue
        print("%s  $%06X..$%06X  %d байт  ->  %s"
              % (r["name"], r["lo"], r["hi"], r["hi"] - r["lo"], r["kind"]))
        for what, detail in r["ev"]:
            print("   %-20s %s" % (what, detail))
        if r["bra"]:
            print("   цели:")
            for k, t in enumerate(r["bra"]):
                print("     %2d -> $%06X" % (k, t))
        if r["ptr"]:
            print("   указатели:")
            for k, t in enumerate(r["ptr"][:24]):
                print("     %2d -> $%06X" % (k, t))
        if r["in"]:
            print("   входы:")
            for a, v, t in r["in"][:12]:
                print("     $%06X -> $%06X   %s" % (a, v, t))
        print()
        print("   байты:")
        for off in range(r["lo"], min(r["hi"], r["lo"] + 256), 16):
            print("     $%06X  %s"
                  % (off, " ".join("%02X" % b for b in ROM[off:off + 16])))
        return
    print("окна %s нет" % name)


def main():
    a = sys.argv[1:]
    if not a:
        do_summary()
    elif a[0] == "--list":
        do_list()
    elif a[0] == "--code":
        do_list("код")
    elif a[0] == "--show" and len(a) > 1:
        do_show(a[1])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
