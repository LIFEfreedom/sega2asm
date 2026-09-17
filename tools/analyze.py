#!/usr/bin/env python3
"""Анализ ROM Mega Drive -> game.yaml + game_symbols.gen.txt.

    python tools/analyze.py [--drop <лог сборки>]

Всё выводится из самой ROM, ничего не зашито: таблица векторов, таблица
диспетчера line-F, граница кода. Обход по потоку управления (семена: векторы,
таблица line-F, прологи функций) строит карту «код/данные», по которой
собирается конфиг: в сегменты m68k попадает только подтверждённый код, всё
остальное — bin. Это важно: подсказки НЕ ресинхронизируют дизассемблер,
выравнивание возвращает только начало нового сегмента.

--drop снимает с кода прогоны, в которых ассемблер нашёл нелегальные для 68000
кодировки: это следы ложных срабатываний засева по прологам.

Запускать при смене game.gen.

Декодер ниже считает только ДЛИНЫ инструкций и переходы — для обхода этого
достаточно, полный дизассемблер не нужен.
"""
import collections
import hashlib
import os
import pickle
import re
import struct
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM = open(os.path.join(HERE, "game.gen"), "rb").read()
N = len(ROM)

U16 = lambda o: struct.unpack_from(">H", ROM, o)[0]
S16 = lambda o: struct.unpack_from(">h", ROM, o)[0]
U32 = lambda o: struct.unpack_from(">I", ROM, o)[0]


# ─────────────────────────── декодер длин ────────────────────────────────
class Bad(Exception):
    pass


SZ = {0: 1, 1: 2, 2: 4}


def ea_ext(mode, reg, size):
    """Сколько байт расширения занимает один эффективный адрес."""
    if mode < 5:
        return 0
    if mode in (5, 6):
        return 2
    if mode == 7:
        if reg == 0:
            return 2                       # abs.w
        if reg == 1:
            return 4                       # abs.l
        if reg == 2:
            return 2                       # (d16,PC)
        if reg == 3:
            return 2                       # (d8,PC,Xn)
        if reg == 4:
            return 4 if size == 4 else 2   # непосредственный
    raise Bad()


def ea_target(ext_at, mode, reg):
    """Статически известная цель EA, иначе None."""
    if mode == 7:
        if reg == 0:
            return S16(ext_at) & 0xFFFFFF
        if reg == 1:
            return U32(ext_at)
        if reg == 2:
            return (ext_at + S16(ext_at)) & 0xFFFFFF
    return None


def ctrl_ea_ok(mode, reg):
    """JMP/JSR/LEA/PEA требуют управляющий режим адресации."""
    if mode in (0, 1, 3, 4):
        return False
    if mode == 7 and reg > 3:
        return False
    return True


def decode(a):
    """-> (длина, список преемников, обрывает ли поток)"""
    if a + 1 >= N:
        raise Bad()
    op = U16(a)
    hi = op >> 12
    mode, reg = (op >> 3) & 7, op & 7

    if hi == 6:                                    # Bcc / BSR / BRA
        cond, d8 = (op >> 8) & 0xF, op & 0xFF
        if d8 == 0x00:
            ln, tgt = 4, (a + 2 + S16(a + 2)) & 0xFFFFFF
        elif d8 == 0xFF:
            raise Bad()                            # длинное смещение — не 68000
        else:
            ln = 2
            tgt = (a + 2 + (d8 - 256 if d8 > 127 else d8)) & 0xFFFFFF
        if cond == 0:
            return ln, [tgt], True
        return ln, [tgt, a + ln], False

    if hi == 7:                                    # MOVEQ
        if op & 0x0100:
            raise Bad()
        return 2, [a + 2], False

    if hi in (1, 2, 3):                            # MOVE
        size = {1: 1, 3: 2, 2: 4}[hi]
        dmode, dreg = (op >> 6) & 7, (op >> 9) & 7
        if size == 1 and (mode == 1 or dmode == 1):
            raise Bad()
        if dmode == 7 and dreg > 1:
            raise Bad()
        s = ea_ext(mode, reg, size)
        d = ea_ext(dmode, dreg, size)
        return 2 + s + d, [a + 2 + s + d], False

    if hi == 4:                                    # разное
        if op in (0x4E75, 0x4E73, 0x4E77):
            return 2, [], True                     # RTS / RTE / RTR
        if op in (0x4E71, 0x4E70, 0x4E76):
            return 2, [a + 2], False               # NOP / RESET / TRAPV
        if op == 0x4E72:
            return 4, [], True                     # STOP
        if 0x4E40 <= op <= 0x4E4F:
            return 2, [a + 2], False               # TRAP
        if 0x4E50 <= op <= 0x4E57:
            return 4, [a + 4], False               # LINK
        if 0x4E58 <= op <= 0x4E6F:
            return 2, [a + 2], False               # UNLK / MOVE USP
        if op & 0xFFC0 == 0x4EC0:                  # JMP
            if not ctrl_ea_ok(mode, reg):
                raise Bad()
            e = ea_ext(mode, reg, 4)
            t = ea_target(a + 2, mode, reg)
            return 2 + e, ([t] if t is not None else []), True
        if op & 0xFFC0 == 0x4E80:                  # JSR
            if not ctrl_ea_ok(mode, reg):
                raise Bad()
            e = ea_ext(mode, reg, 4)
            t = ea_target(a + 2, mode, reg)
            return 2 + e, [a + 2 + e] + ([t] if t is not None else []), False
        if op & 0xF1C0 == 0x41C0:                  # LEA
            if not ctrl_ea_ok(mode, reg):
                raise Bad()
            e = ea_ext(mode, reg, 4)
            return 2 + e, [a + 2 + e], False
        if op & 0xF1C0 == 0x4180:                  # CHK
            e = ea_ext(mode, reg, 2)
            return 2 + e, [a + 2 + e], False
        if op & 0xFFF8 == 0x4840:                  # SWAP
            return 2, [a + 2], False
        if op & 0xFFB8 == 0x4880:                  # EXT
            return 2, [a + 2], False
        if op & 0xFB80 == 0x4880:                  # MOVEM
            size = 4 if op & 0x40 else 2
            e = ea_ext(mode, reg, size)
            return 4 + e, [a + 4 + e], False
        if op & 0xFFC0 == 0x4840:                  # PEA
            if not ctrl_ea_ok(mode, reg):
                raise Bad()
            e = ea_ext(mode, reg, 4)
            return 2 + e, [a + 2 + e], False
        if op & 0xFFC0 == 0x4800:                  # NBCD
            e = ea_ext(mode, reg, 1)
            return 2 + e, [a + 2 + e], False
        if op & 0xFFC0 == 0x4AC0:                  # TAS
            e = ea_ext(mode, reg, 1)
            return 2 + e, [a + 2 + e], False
        if op & 0xFFC0 in (0x40C0, 0x44C0, 0x46C0):    # MOVE SR / CCR
            e = ea_ext(mode, reg, 2)
            return 2 + e, [a + 2 + e], False
        if op & 0xFF00 in (0x4000, 0x4200, 0x4400, 0x4600, 0x4A00):
            size = (op >> 6) & 3                   # NEGX/CLR/NEG/NOT/TST
            if size == 3:
                raise Bad()
            e = ea_ext(mode, reg, SZ[size])
            return 2 + e, [a + 2 + e], False
        raise Bad()

    if hi == 5:                                    # ADDQ/SUBQ/Scc/DBcc
        if op & 0xF0F8 == 0x50C8:
            return 4, [(a + 2 + S16(a + 2)) & 0xFFFFFF, a + 4], False
        if op & 0xF0C0 == 0x50C0:
            e = ea_ext(mode, reg, 1)
            return 2 + e, [a + 2 + e], False
        size = (op >> 6) & 3
        if size == 3:
            raise Bad()
        e = ea_ext(mode, reg, SZ[size])
        return 2 + e, [a + 2 + e], False

    if hi == 0:                                    # непосредственные / битовые
        if op & 0xF138 == 0x0108:
            return 4, [a + 4], False               # MOVEP
        if op & 0xF100 == 0x0100:
            e = ea_ext(mode, reg, 1)
            return 2 + e, [a + 2 + e], False       # динамические битовые
        if op & 0xFF00 == 0x0800:
            e = ea_ext(mode, reg, 1)
            return 4 + e, [a + 4 + e], False       # статические битовые
        size = (op >> 6) & 3
        if size == 3:
            raise Bad()
        if (op >> 9) & 7 > 6:
            raise Bad()
        imm = 4 if size == 2 else 2
        if mode == 7 and reg == 4:                 # ... в CCR / SR
            return 2 + imm, [a + 2 + imm], False
        e = ea_ext(mode, reg, SZ[size])
        return 2 + imm + e, [a + 2 + imm + e], False

    if hi in (8, 9, 0xB, 0xC, 0xD):                # OR SUB CMP AND ADD
        opmode = (op >> 6) & 7
        if opmode in (3, 7):
            e = ea_ext(mode, reg, 2 if opmode == 3 else 4)
            return 2 + e, [a + 2 + e], False
        if hi in (9, 0xD) and opmode in (4, 5, 6) and mode in (0, 1):
            return 2, [a + 2], False               # SUBX / ADDX
        if hi in (8, 0xC) and opmode == 4 and mode in (0, 1):
            return 2, [a + 2], False               # SBCD / ABCD
        if hi == 0xC and opmode in (5, 6) and mode in (0, 1):
            return 2, [a + 2], False               # EXG
        if hi == 0xB and opmode in (4, 5, 6) and mode == 1:
            return 2, [a + 2], False               # CMPM
        e = ea_ext(mode, reg, SZ[opmode & 3])
        return 2 + e, [a + 2 + e], False

    if hi == 0xE:                                  # сдвиги / вращения
        if (op >> 6) & 3 == 3:
            e = ea_ext(mode, reg, 2)
            return 2 + e, [a + 2 + e], False
        return 2, [a + 2], False

    if hi == 0xA:                                  # line-A: в этой ROM ошибка
        raise Bad()

    if hi == 0xF:                                  # line-F: трап BIOS, +2
        return 2, [a + 2], False

    raise Bad()


# ────────────────────────────── анализ ───────────────────────────────────
SHA1 = hashlib.sha1(ROM).hexdigest().upper()
print("ROM  : %d байт, SHA-1 %s" % (N, SHA1))

ENTRY = U32(4)
linef_handler = U32(11 * 4)
tbl, tbl_n = None, 0
for off in range(linef_handler, linef_handler + 0x40, 2):
    if U16(off) == 0x303B:                 # move.w (d16,pc,d0.w),d0
        tbl = off + 2 + (U16(off + 2) & 0xFF)
        tbl_n = (ENTRY - tbl) // 2
        break
if tbl is None:
    print("!! диспетчер line-F не найден — продолжаю без его таблицы")
else:
    print("line-F: обработчик $%06X, таблица $%06X, записей %d"
          % (linef_handler, tbl, tbl_n))


def first_big_fill(lo, min_len=0x1000):
    i = lo
    while i < N:
        j = i + 1
        while j < N and ROM[j] == ROM[i]:
            j += 1
        if j - i >= min_len:
            return i, j
        i = j
    return N, N


CODE_HI, PAD_HI = first_big_fill(0x200)
print("код кончается не позже $%06X (далее %d байт 0x%02X до $%06X)"
      % (CODE_HI, PAD_HI - CODE_HI, ROM[CODE_HI], PAD_HI))

covered = bytearray(N)
starts, targets = set(), set()


def walk(seeds):
    work, seen = list(seeds), set(seeds)
    while work:
        a = work.pop()
        while True:
            if a < 0x200 or a >= N or a & 1 or a in starts:
                break
            try:
                ln, succ, stop = decode(a)
            except Exception:
                break
            if a + ln > N:
                break
            starts.add(a)
            for k in range(a, a + ln):
                covered[k] = 1
            nxt = None
            for t in succ:
                if t == a + ln and not stop:
                    nxt = t
                    continue
                if 0x200 <= t < N and not (t & 1):
                    targets.add(t)
                    if t not in seen:
                        seen.add(t)
                        work.append(t)
            if stop or nxt is None:
                break
            a = nxt


seeds = []
for i in range(1, 64):
    v = U32(i * 4)
    if 0x200 <= v < N:
        seeds.append(v)
        targets.add(v)
for i in range(tbl_n):
    t = (tbl + S16(tbl + i * 2)) & 0xFFFFFF
    if 0x200 <= t < N:
        seeds.append(t)
        targets.add(t)
walk(seeds)
print("проход 1: %d инструкций, %d байт" % (len(starts), sum(covered)))

prologues = []
for a in range(0x200, CODE_HI, 2):
    op = U16(a)
    if op == 0x48E7 and U16(a + 2) not in (0x0000, 0xFFFF):
        prologues.append(a)
    elif op == 0x4E56 and -0x2000 <= S16(a + 2) <= 0:
        prologues.append(a)
walk([a for a in prologues if a not in starts])
for a in prologues:
    if a in starts:
        targets.add(a)
print("проход 2 (+%d прологов): %d инструкций, %d байт"
      % (len(prologues), len(starts), sum(covered)))

# Таблица переходов диспетчера — данные, но лежит вплотную за его концом, и
# поток в неё затекает. Снимаем явно: иначе она даёт нелегальные инструкции,
# а снятие всего прогона целиком утащило бы вместе с ней сам обработчик.
if tbl is not None:
    for k in range(tbl, tbl + tbl_n * 2):
        covered[k] = 0
    print("таблица line-F $%06X-$%06X помечена данными" % (tbl, tbl + tbl_n * 2))

COV = os.path.join(HERE, "tools", ".coverage.pkl")
if "--drop" in sys.argv:
    log = open(sys.argv[sys.argv.index("--drop") + 1],
               encoding="utf-8", errors="replace").read()
    covered = bytearray(pickle.load(open(COV, "rb")))
    bad = set()
    # Между "Error:" и "On line" ассемблер иногда печатает многострочное
    # пояснение, поэтому пропускаем произвольные строки до первой ссылки.
    for m in re.finditer(r"^Error:(?:.*\n)*?^On line (\d+) of '([^']*code_\d+\.asm)'",
                         log, re.M):
        path = os.path.join(HERE, m.group(2).replace("\\", "/"))
        if not os.path.exists(path):
            continue
        src = open(path, encoding="utf-8", errors="replace").read().split("\n")
        for k in range(int(m.group(1)) - 1, max(-1, int(m.group(1)) - 40), -1):
            mm = (re.match(r"^; \$([0-9A-F]{6})$", src[k])
                  or re.match(r"^\S.*;\s*\$([0-9A-F]{6})$", src[k])
                  or re.match(r"^\torg\t\$([0-9A-F]{6})$", src[k]))
            if mm:
                bad.add(int(mm.group(1), 16))
                break
    n = 0
    for a in bad:
        s = a
        while s > 0x200 and covered[s - 1]:
            s -= 1
        e = a
        while e < N and covered[e]:
            e += 1
        for k in range(s, e):
            if covered[k]:
                covered[k] = 0
                n += 1
    print("снято прогонов: %d, байт: %d" % (len(bad), n))

pickle.dump(bytes(covered), open(COV, "wb"))

# ─────────────────────────── game.yaml ───────────────────────────────────
holes, run = [], None
for i in range(0x200, CODE_HI):
    if not covered[i]:
        if run is None:
            run = i
    elif run is not None:
        holes.append((run, i))
        run = None
if run is not None:
    holes.append((run, CODE_HI))
sel = [(s + (s & 1), e + (e & 1)) for s, e in holes if e > s]

body, cur, ci, di = [], 0x200, 0, 0


def emit(kind, s, e):
    global ci, di
    if kind == "m68k":
        ci += 1
        nm, sub = "code_%02d" % ci, ""
    else:
        di += 1
        nm, sub = "data_%02d" % di, "\n    subdir: code_data"
    body.append("  - name: %s\n    type: %s\n    start: 0x%06X\n    end:   0x%06X%s"
                % (nm, kind, s, e, sub))


for s, e in sel:
    if s > cur:
        emit("m68k", cur, s)
    emit("bin", s, e)
    cur = e
if cur < CODE_HI:
    emit("m68k", cur, CODE_HI)

head = """# Dyna Brothers 2 (Japan) — CRI
# СГЕНЕРИРОВАНО tools/analyze.py — правки затираются, меняйте анализатор.
# Границы кода получены обходом по потоку управления (векторы + таблица
# line-F $%06X + прологи функций), а не разметкой на глаз. В m68k попадает
# только подтверждённый код, всё непокрытое вынесено в bin: только начало
# нового сегмента возвращает дизассемблеру выравнивание.
name: dynabrothers2
sha1: "%s"

options:
  platform: megadrive
  region: ntsc
  basename: dynabrothers2
  base_path: ./out
  target_path: ./game.gen
  asm_path: asm
  asset_path: assets
  build_path: build
  symbols_path: ./game_symbols.txt
  charmap_path: ./game_charmap.tbl
  header_output: true
  incbin: true

segments:
  # Тип `header` непригоден для побайтовой пересборки: NUL-байты полей
  # заголовка рвут лексер, а InitialSSP выводится как метка в ОЗУ, которую
  # никто не определяет.
  - name: header
    type: bin
    start: 0x000000
    end:   0x000200

""" % (tbl or 0, SHA1)

tail = ("\n\n  - name: rest\n    type: bin\n    start: 0x%06X\n    end:   0x%06X\n"
        % (CODE_HI, N))
open(os.path.join(HERE, "game.yaml"), "w", encoding="utf-8").write(
    head + "\n\n".join(body) + tail)

# ───────────────────── game_symbols.gen.txt ──────────────────────────────
named = {ENTRY: "EntryPoint", U32(2 * 4): "BusError", U32(3 * 4): "AddressError",
         U32(4 * 4): "IllegalInstruction", U32(5 * 4): "DivideByZero",
         U32(30 * 4): "VBlankHandler", U32(28 * 4): "HBlankHandler"}
good = sorted(t for t in targets if t in starts and covered[t])
out = ["; СГЕНЕРИРОВАНО tools/analyze.py — правки затираются.",
       "; Свои имена держите в game_symbols.user.txt: они идут первыми при",
       "; склейке и побеждают, потому что types/symbol.go запоминает первое",
       "; вхождение адреса.", ""]
seen_names = set()
for a in good:
    nm = named.get(a, "loc_%06X" % a)
    if nm in seen_names:
        nm = "loc_%06X" % a
    seen_names.add(nm)
    out.append("%s = $%06X" % (nm, a))
open(os.path.join(HERE, "game_symbols.gen.txt"), "w", encoding="utf-8").write(
    "\n".join(out) + "\n")

m = sum(1 for l in body if "m68k" in l)
print("\ngame.yaml: %d сегментов (m68k %d, bin %d), кода %d байт"
      % (len(body) + 2, m, len(body) - m + 2, sum(covered)))
print("game_symbols.gen.txt: %d символов" % len(good))
