#!/usr/bin/env python3
"""Карта ОЗУ по дизассемблированному коду: переменные, массивы, структуры.

    python tools/rammap.py [--out docs/ram-map.md]

Что делает.

1. Собирает все обращения к $FFxxxx (ОЗУ Mega Drive) с разбором: чтение или
   запись, размер операнда, адрес инструкции.
2. Отдельно ловит `lea (FFxxxx).l,aN` — взятие БАЗЫ. Дальше в пределах той же
   процедуры смотрит обращения вида `(смещение,aN)` и восстанавливает поля:
   так видно размер структуры и раскладку, чего по одним прямым обращениям
   не увидеть.
3. Склеивает близко лежащие адреса в кластеры — это либо поля одной
   структуры, либо массив.

Вывод — markdown плюс заготовка строк для game_symbols.user.txt.
"""
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT as out_path

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASM = out_path("asm", "m68k")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ADDR_CMT = re.compile(r"^; \$([0-9A-F]{6})$")
ADDR_LBL = re.compile(r"^\S.*;\s*\$([0-9A-F]{6})$")
ADDR_ORG = re.compile(r"^\torg\t\$([0-9A-F]{6})$")
RAM = re.compile(r"\$(FF[0-9A-F]{4})")
# lea ($FFxxxx).l,aN   /   lea (Имя).l,aN
LEA = re.compile(r"^lea\s+\((?:\$(FF[0-9A-F]{4})|(\w+))\)\.l,a(\d)$")
SYMLINE = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*\$?([0-9A-Fa-f]+)\s*(?:;.*)?$")


def load_ram_symbols():
    """имя -> адрес для символов в ОЗУ.

    Без этого карта деградирует по мере работы: как только адресу дают имя,
    дизассемблер печатает `InputState` вместо `$FF003E`, и адрес исчезает из
    карты. То есть чем больше вы разобрали, тем меньше видно — ровно наоборот
    от нужного. Поэтому известные имена распознаём наравне с литералами.
    """
    out = {}
    for name in ("game_symbols.txt", "game_symbols.user.txt"):
        path = os.path.join(HERE, name)
        if not os.path.exists(path):
            continue
        for raw in open(path, encoding="utf-8", errors="replace"):
            line = raw.strip()
            if not line or line[0] in ";#":
                continue
            m = SYMLINE.match(line)
            if not m:
                continue
            a = int(m.group(2), 16)
            if 0xFF0000 <= a <= 0xFFFFFF:
                out.setdefault(m.group(1), a)
    return out
# Поле структуры. sega2asm печатает смещение как `$1870(a4)` / `-$2A(a1)`,
# а НЕ как `($1870,a4)`. Отдельно ловим голое `(aN)` — это смещение 0, но
# только не `-(aN)` и не `(aN)+`: там регистр меняется, это не поле.
FIELD_D = re.compile(r"(-?)\$([0-9A-F]+)\(a(\d)\)")
FIELD_0 = re.compile(r"(?<![-$\w])\(a(\d)\)(?!\+)")
SIZED = re.compile(r"^(\w+)\.([bwl])\b")


def load():
    """[(файл, адрес, текст)] по всем сегментам кода, в порядке адресов."""
    out = []
    if not os.path.isdir(ASM):
        return out
    for fn in sorted(os.listdir(ASM)):
        if not fn.endswith(".asm"):
            continue
        addr = None
        for raw in open(os.path.join(ASM, fn), encoding="utf-8", errors="replace"):
            line = raw.rstrip("\n")
            m = ADDR_CMT.match(line) or ADDR_LBL.match(line) or ADDR_ORG.match(line)
            if m:
                addr = int(m.group(1), 16)
                continue
            if line.startswith("\t") and addr is not None:
                out.append((fn, addr, line.strip()))
                addr = None
    return out


def access_kind(text, token):
    """read / write / lea / test — по положению операнда в инструкции."""
    op = text.split("\t", 1)[0]
    if op.startswith("lea") or op.startswith("pea"):
        return "lea"
    if op.startswith(("tst", "cmp", "btst")):
        return "test"
    if op.startswith(("clr", "st", "sf")):
        return "write"
    parts = text.split("\t", 1)
    if len(parts) < 2:
        return "read"
    args = parts[1].split(",")
    # приёмник — последний операнд
    if len(args) >= 2 and token in args[-1]:
        return "write"
    if len(args) == 1:
        return "write" if op.startswith(("clr", "neg", "not")) else "read"
    return "read"


def opsize(text):
    m = SIZED.match(text)
    return m.group(2) if m else "?"


def detect_stride(offsets):
    """Шаг массива записей, если смещения повторяются группами.

    Массив структур выдаёт себя тем, что набор смещений самоподобен: если
    есть поля +$00,+$04,+$08 и рядом +$42,+$46,+$4A, то шаг записи — $42.
    Берём шаг с наибольшим числом совпадений, требуя хотя бы три пары,
    иначе это просто одна большая структура.
    """
    offs = set(offsets)
    if len(offs) < 6:
        return None
    span = max(offs)
    # Идём от БОЛЬШЕГО шага к меньшему и берём первый подходящий. Иначе
    # побеждает тривиальный шаг $02: при плотных смещениях он «совпадает»
    # всегда, но ничего не объясняет. Крупный шаг — более сильное
    # утверждение, и если он замощает смещения, то он и есть настоящий.
    # только чётные шаги: записи на 68000 выравниваются по слову, нечётный
    # размер записи практически не встречается и почти всегда означает
    # случайное совпадение
    for s in range(span // 2 & ~1, 3, -2):
        residues = {o % s for o in offs}
        records = {o // s for o in offs}
        if len(records) < 3:                 # видно меньше трёх записей
            continue
        if len(residues) > len(offs) / 2:    # смещения не повторяются
            continue
        if len(offs) / len(residues) < 2.0:  # на остаток меньше двух записей
            continue
        return s, len(records), sorted(residues)
    return None


def main():
    code = load()
    if not code:
        print("[--] нет out/<имя>/asm/m68k — сначала make split")
        return 1

    refs = collections.defaultdict(lambda: {"read": 0, "write": 0, "test": 0,
                                            "lea": 0, "sizes": collections.Counter(),
                                            "sites": []})
    names = load_ram_symbols()
    addr2name = {}
    for nm, a in names.items():
        addr2name.setdefault(a, nm)
    sym_re = (re.compile(r"\b(%s)\b" % "|".join(sorted(map(re.escape, names),
                                                       key=len, reverse=True)))
              if names else None)
    if names:
        print("известных имён в ОЗУ: %d (учитываются наравне с $FFxxxx)"
              % len(names))

    # ── прямые обращения ────────────────────────────────────────────────
    for fn, addr, text in code:
        seen_here = []
        for m in RAM.finditer(text):
            seen_here.append((int(m.group(1), 16) | 0xFF0000, m.group(0)))
        if sym_re:
            for m in sym_re.finditer(text):
                seen_here.append((names[m.group(1)], m.group(1)))
        for a, token in seen_here:
            r = refs[a]
            r[access_kind(text, token)] += 1
            r["sizes"][opsize(text)] += 1
            if len(r["sites"]) < 4:
                r["sites"].append((addr, text))

    # ── структуры: lea базы + поля через (смещение,aN) ──────────────────
    structs = collections.defaultdict(lambda: collections.Counter())
    for i, (fn, addr, text) in enumerate(code):
        m = LEA.match(text)
        if not m:
            continue
        if m.group(1):
            base = int(m.group(1), 16) | 0xFF0000
        elif m.group(2) in names:          # база уже названа вами
            base = names[m.group(2)]
        else:
            continue
        reg = m.group(3)
        # смотрим вперёд, пока регистр не переопределят
        for fn2, a2, t2 in code[i + 1:i + 45]:
            if fn2 != fn:
                break
            mm = LEA.match(t2)
            if mm and mm.group(3) == reg:
                break
            if t2.startswith(("rts", "rte", "jmp")):
                break
            for f in FIELD_D.finditer(t2):
                if f.group(3) != reg:
                    continue
                off = int(f.group(2), 16) * (-1 if f.group(1) else 1)
                if 0 <= off < 0x400:
                    structs[base][off] += 1
            for f in FIELD_0.finditer(t2):
                if f.group(1) == reg:
                    structs[base][0] += 1

    total = sum(r["read"] + r["write"] + r["test"] + r["lea"]
                for r in refs.values())
    print("адресов ОЗУ: %d, обращений: %d, баз структур: %d"
          % (len(refs), total, len(structs)))

    # ── кластеризация: близкие адреса = одна структура/массив ───────────
    addrs = sorted(refs)
    clusters, cur = [], [addrs[0]] if addrs else []
    for a in addrs[1:]:
        if a - cur[-1] <= 0x10:
            cur.append(a)
        else:
            clusters.append(cur)
            cur = [a]
    if cur:
        clusters.append(cur)
    clusters.sort(key=lambda c: -sum(refs[a]["read"] + refs[a]["write"] for a in c))

    def lbl(a):
        """Подпись адреса: с вашим именем, если оно уже есть."""
        return ("`%s` (`$%06X`)" % (addr2name[a], a)) if a in addr2name else "`$%06X`" % a

    out_path = os.path.join(HERE, "docs", "ram-map.md")
    if "--out" in sys.argv:
        out_path = os.path.join(HERE, sys.argv[sys.argv.index("--out") + 1])
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Карта ОЗУ\n\n")
        f.write("Построено `tools/rammap.py` по дизассемблированному коду. ")
        f.write("ОЗУ Mega Drive — `$FF0000-$FFFFFF`.\n\n")
        f.write("Всего адресов: **%d**, обращений: **%d**, "
                "баз структур (через `lea`): **%d**.\n\n" % (len(refs), total, len(structs)))

        f.write("## Структуры: база и раскладка полей\n\n")
        f.write("Найдены по `lea ($FFxxxx).l,aN` с последующими `(смещение,aN)`. ")
        f.write("Максимальное смещение даёт нижнюю оценку размера структуры.\n\n")
        ranked = sorted(structs.items(), key=lambda kv: -sum(kv[1].values()))
        for base, fields in ranked[:20]:
            span = max(fields) if fields else 0
            st = detect_stride(fields)
            if st:
                stride, hits, inner = st
                f.write("### %s — похоже на МАССИВ, шаг записи $%02X (%d байт)\n\n"
                        % (lbl(base), stride, stride))
                f.write("Смещения замощаются периодом `$%02X`: видно %d записей, "
                        "до `$%06X`. Это гипотеза — сверьтесь с таблицей ниже "
                        "и с кодом, прежде чем закладываться на неё.\n\n"
                        % (stride, hits, base + span))
                f.write("Поля внутри записи: %s\n\n"
                        % ", ".join("`+$%02X`" % o for o in inner[:14]))
            else:
                f.write("### %s — структура, не менее %d байт, %d полей\n\n"
                        % (lbl(base), span + 1, len(fields)))
            f.write("| смещение | обращений |\n|---|---|\n")
            for off in sorted(fields)[:16]:
                f.write("| `+$%02X` | %d |\n" % (off, fields[off]))
            if len(fields) > 16:
                f.write("| … | ещё %d полей |\n" % (len(fields) - 16))
            f.write("\n")

        f.write("## Кластеры прямых обращений\n\n")
        f.write("Адреса, отстоящие не более чем на 16 байт, собраны вместе: ")
        f.write("это поля одной структуры либо элементы массива.\n\n")
        for c in clusters[:30]:
            rw = sum(refs[a]["read"] + refs[a]["write"] + refs[a]["test"] for a in c)
            if len(c) == 1:
                a = c[0]
                r = refs[a]
                sz = r["sizes"].most_common(1)[0][0]
                f.write("### %s (.%s) — чтений %d, записей %d\n\n"
                        % (lbl(a), sz, r["read"] + r["test"], r["write"]))
            else:
                f.write("### %s-`$%06X` — %d адресов, %d обращений\n\n"
                        % (lbl(c[0]), c[-1], len(c), rw))
                f.write("| адрес | имя | разм. | чт. | зап. |\n|---|---|---|---|---|\n")
                for a in c[:12]:
                    r = refs[a]
                    f.write("| `$%06X` | %s | .%s | %d | %d |\n"
                            % (a, ("`%s`" % addr2name[a]) if a in addr2name else "",
                               r["sizes"].most_common(1)[0][0],
                               r["read"] + r["test"], r["write"]))
                if len(c) > 12:
                    f.write("| … | | | | ещё %d |\n" % (len(c) - 12))
                f.write("\n")
            for site, text in refs[c[0]]["sites"][:2]:
                f.write("    $%06X  %s\n" % (site, text))
            f.write("\n")

        f.write("## Заготовка для game_symbols.user.txt\n\n")
        f.write("Скопируйте нужные строки, замените имена на осмысленные.\n\n```\n")
        for c in clusters[:40]:
            a = c[0]
            if a in addr2name:        # уже названо вами — предлагать нечего
                continue
            r = refs[a]
            tag = "Base" if a in structs else ("Ptr" if r["lea"] else "Var")
            f.write("%s_%04X = $%06X\t; чт %d зап %d%s\n"
                    % (tag, a & 0xFFFF, a, r["read"] + r["test"], r["write"],
                       ", структура" if a in structs else ""))
        f.write("```\n")

    print("записано: %s" % os.path.relpath(out_path, HERE))

    print("\n═══ Крупнейшие структуры ═══")
    for base, fields in ranked[:8]:
        print("  $%06X  полей %2d  размер >= %3d байт  обращений %d"
              % (base, len(fields), max(fields) + 1, sum(fields.values())))

    print("\n═══ Самые горячие адреса ═══")
    hot = sorted(refs.items(), key=lambda kv: -(kv[1]["read"] + kv[1]["write"] + kv[1]["test"]))
    for a, r in hot[:10]:
        print("  $%06X  .%s  чт %4d  зап %4d"
              % (a, r["sizes"].most_common(1)[0][0], r["read"] + r["test"], r["write"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
