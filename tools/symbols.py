#!/usr/bin/env python3
"""Развязка пользовательских и сгенерированных символов.

    python tools/symbols.py --merge     # user + gen -> game_symbols.txt
    python tools/symbols.py --equates   # после split: дописать equ в ports.asm

Зачем две части.

1. --merge. `game_symbols.gen.txt` перезаписывается анализатором при каждой
   смене ROM, поэтому вписывать туда найденные имена нельзя. Имена живут в
   `game_symbols.user.txt` (под git), а сборочный `game_symbols.txt`
   склеивается из обоих. Пользовательский идёт ПЕРВЫМ: в types/symbol.go
   побеждает первое вхождение адреса, так что ваши имена перекрывают
   автоматические loc_XXXXXX.

2. --equates. sega2asm определяет метку только там, где реально печатает её
   в сегменте кода. Если назвать адрес вне кода — переменную в ОЗУ, таблицу
   внутри bin-сегмента, регистр — имя подставится в ссылку, а определения не
   будет, и ассемблер упадёт на "Symbol does not exist". Поэтому после split
   мы смотрим, какие имена НЕ определены в выводе, и дописываем им `equ` в
   out/asm/include/ports.asm, который подключается первым.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER = os.path.join(HERE, "game_symbols.user.txt")
GEN = os.path.join(HERE, "game_symbols.gen.txt")
OUT = os.path.join(HERE, "game_symbols.txt")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LINE = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*\$?([0-9A-Fa-f]+)\s*(?:;.*)?$")


def read(path):
    """-> [(name, addr)] в порядке файла"""
    out = []
    if not os.path.exists(path):
        return out
    for raw in open(path, encoding="utf-8"):
        line = raw.strip()
        if not line or line[0] in ";#" or line.startswith("//"):
            continue
        m = LINE.match(line)
        if m:
            out.append((m.group(1), int(m.group(2), 16)))
    return out


def merge():
    user, gen = read(USER), read(GEN)
    taken_addr = {a for _, a in user}
    taken_name = {n for n, _ in user}

    kept, shadowed, renamed = [], 0, 0
    for name, addr in gen:
        if addr in taken_addr:
            shadowed += 1
            continue
        if name in taken_name:
            renamed += 1          # имя занято пользователем под другой адрес
            continue
        kept.append((name, addr))

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("; СГЕНЕРИРОВАННЫЙ ФАЙЛ — не редактировать.\n")
        f.write("; Собран tools/symbols.py из game_symbols.user.txt (первым,\n")
        f.write("; поэтому побеждает) и game_symbols.gen.txt.\n\n")
        f.write("; ── ваши имена ──────────────────────────────────────────\n")
        for name, addr in user:
            f.write("%s = $%06X\n" % (name, addr))
        f.write("\n; ── автоматические ─────────────────────────────────────\n")
        for name, addr in kept:
            f.write("%s = $%06X\n" % (name, addr))

    print("символы: ваших %d, автоматических %d" % (len(user), len(kept)))
    if shadowed:
        print("  перекрыто вашими именами: %d" % shadowed)
    if renamed:
        print("  пропущено из-за занятого имени: %d" % renamed)
    return 0


def equates():
    syms = read(OUT)
    if not syms:
        print("[--] %s пуст — сначала --merge" % os.path.basename(OUT))
        return 1

    asm_dir = os.path.join(HERE, "out", "asm")
    if not os.path.isdir(asm_dir):
        print("[--] нет out/asm — сначала make split")
        return 1

    defined = set()
    ports = None
    for root, _, files in os.walk(asm_dir):
        for fn in files:
            if not fn.endswith(".asm"):
                continue
            path = os.path.join(root, fn)
            if fn == "ports.asm":
                ports = path
            for line in open(path, encoding="utf-8", errors="replace"):
                m = re.match(r"^([A-Za-z_]\w*):", line)
                if m:
                    defined.add(m.group(1))
                m = re.match(r"^([A-Za-z_]\w*)\s+equ\s", line)
                if m:
                    defined.add(m.group(1))

    missing = [(n, a) for n, a in syms if n not in defined]
    if not missing:
        print("equ не требуются: все %d символов определены в выводе" % len(syms))
        return 0
    if ports is None:
        print("[FAIL] не найден out/asm/include/ports.asm")
        return 1

    with open(ports, "a", encoding="utf-8") as f:
        f.write("\n; ── символы вне сегментов кода ─────────────────────────\n")
        f.write("; Дописано tools/symbols.py: на эти адреса есть ссылки, но\n")
        f.write("; метку там никто не печатает (ОЗУ, данные, регистры).\n")
        for name, addr in missing:
            f.write("%s\tequ\t$%06X\n" % (name, addr))

    print("дописано equ в ports.asm: %d" % len(missing))
    for name, addr in missing[:8]:
        print("    %-22s $%06X" % (name, addr))
    if len(missing) > 8:
        print("    … ещё %d" % (len(missing) - 8))
    return 0


if __name__ == "__main__":
    if "--merge" in sys.argv:
        sys.exit(merge())
    if "--equates" in sys.argv:
        sys.exit(equates())
    print(__doc__)
    sys.exit(2)
