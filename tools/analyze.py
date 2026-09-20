#!/usr/bin/env python3
"""Анализ ROM Mega Drive -> <проект>.yaml + <проект>_symbols.gen.txt.

    python tools/analyze.py [--drop <лог сборки>] [--drop-bin <собранный ROM>]
    python tools/analyze.py --report
    SEGA2ASM_CONFIG=platformer.yaml python tools/analyze.py --name mauimallard

Разбираемый ROM и имена файлов берутся из YAML (`SEGA2ASM_CONFIG`, по
умолчанию `game.yaml`), а не зашиты: второй ROM в том же дереве ничего не
затирает. Имя проекта для ПЕРВОГО прогона, когда YAML ещё нет, задаётся
ключом `--name`; дальше оно читается из `name:` самого YAML.

Всё выводится из самой ROM, ничего не зашито: таблица векторов, таблица
диспетчера line-F, граница кода. Обход по потоку управления (семена: векторы,
таблица line-F, прологи функций, указатели из таблиц данных) строит карту
«код/данные», по которой собирается конфиг: в сегменты m68k попадает только
подтверждённый код, всё остальное — bin. Это важно: подсказки НЕ
ресинхронизируют дизассемблер, выравнивание возвращает только начало нового
сегмента.

--drop снимает с кода прогоны, в которых ассемблер нашёл нелегальные для 68000
кодировки: это следы ложных срабатываний засева по прологам. --drop-bin делает
то же по РАСХОЖДЕНИЮ БАЙТ с оригиналом: данные, случайно читающиеся как законная
команда, ассемблер пропускает молча, и видно их только после пересборки.

--report ничего не перезаписывает, а печатает, внутри каких bin-сегментов
ТЕКУЩЕГО game.yaml обход нашёл код. Так и надо пользоваться находками третьего
прохода: game.yaml давно правится руками сегмент за сегментом, и полная
перегенерация стёрла бы эту работу.

Запускать при смене game.gen.

Декодер ниже считает только ДЛИНЫ инструкций и переходы — для обхода этого
достаточно, полный дизассемблер не нужен.
"""
import bisect
import collections
import hashlib
import os
import pickle
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import (config_path, coverage_path, gen_symbols, merged_symbols,
                   project_name, rom_bytes, rom_path)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM = rom_bytes()
N = len(ROM)

# Имя проекта: из `name:` YAML, а на первом прогоне (файла ещё нет) — из
# `--name`, иначе из имени самого YAML.
YAML = config_path()
STEM = os.path.splitext(os.path.basename(YAML))[0]
if "--name" in sys.argv:
    NAME = sys.argv[sys.argv.index("--name") + 1]
else:
    NAME = project_name()
gen_syms = gen_symbols()
merged_syms = merged_symbols()

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

    if hi == 0xA:                                  # line-A
        if not LINEA_TRAP:
            raise Bad()
        return 2, [a + 2], False

    if hi == 0xF:                                  # line-F
        if not LINEF_TRAP:
            raise Bad()
        return 2, [a + 2], False

    raise Bad()


# ────────────────────────────── анализ ───────────────────────────────────
SHA1 = hashlib.sha1(ROM).hexdigest().upper()
print("ROM  : %d байт, SHA-1 %s" % (N, SHA1))

ENTRY = U32(4)
ILLEGAL = U32(4 * 4)


def trap_vector(n):
    """Ловушка это или ошибка.

    Через line-A и line-F процессор уходит по вектору, и по самому слову
    команды не понять, звали ли его нарочно. Признак берём из ROM: вектор
    ведёт в ROM по чётному адресу И не на обработчик недопустимой команды.
    У Dyna Brothers 2 так устроен весь BIOS (line-F), а line-A сведён на
    тот же адрес, что и illegal, то есть ошибка. У Maui Mallard оба
    вектора — мусор, и слово $Axxx/$Fxxx в потоке значит, что разбор ушёл
    не туда.
    """
    v = U32(n * 4)
    return 0x200 <= v < N and not (v & 1) and v != ILLEGAL


LINEA_TRAP = trap_vector(10)
LINEF_TRAP = trap_vector(11)
print("трапы: line-A %s, line-F %s"
      % ("да" if LINEA_TRAP else "нет", "да" if LINEF_TRAP else "нет"))

linef_handler = U32(11 * 4)
tbl, tbl_n = None, 0
if LINEF_TRAP:
    for off in range(linef_handler, min(linef_handler + 0x40, N - 3), 2):
        if U16(off) == 0x303B:             # move.w (d16,pc,d0.w),d0
            tbl = off + 2 + (U16(off + 2) & 0xFF)
            tbl_n = (ENTRY - tbl) // 2
            break
    if tbl is None:
        print("!! диспетчер line-F не найден — продолжаю без его таблицы")
    else:
        print("line-F: обработчик $%06X, таблица $%06X, записей %d"
              % (linef_handler, tbl, tbl_n))


# Слова, которые в коде встречаются постоянно, а в графике и таблицах —
# случайно: возвраты, сохранение регистров, вызовы по длинному адресу.
MARKERS = frozenset((0x4E75, 0x4E71, 0x4E73, 0x4E77,     # rts nop rte rtr
                     0x48E7, 0x4CDF,                     # movem -(a7) / (a7)+
                     0x4E56, 0x4E5E,                     # link / unlk
                     0x4EB9, 0x4EF9))                    # jsr.l / jmp.l


def code_windows(blk=0x1000, thr=6, gap=0x4000):
    """Где в ROM вообще лежит код — по плотности маркеров.

    Раньше граница бралась как первая большая заливка одним байтом: у Dyna
    Brothers 2 код идёт с $000200 подряд, и заливка $FF за ним честно его
    закрывала. У Maui Mallard код лежит В КОНЦЕ картриджа ($28D000) двумя
    кусками, а перед ним 2,6 МБ графики — заливки там нет, и приём даёт
    границу на первой же случайной строке одинаковых байт.

    Порог 6 маркеров на 4 КБ разделяет оба ROM'а: у Dyna Brothers он даёт
    ровно один кусок $000200-$05F000, у Maui Mallard — $28D000-$2AC000 и
    $2F8000-$2F9000 (второй — помощники, которых зовут больше 300 раз).

    Окна нужны не для красоты: засев по прологам и поиск таблиц идут
    сплошным перебором, и без окон 2,6 МБ графики превратились бы в тысячи
    ложных «процедур».
    """
    hot = []
    for base in range(0, N, blk):
        end = min(base + blk, N) - 1
        if sum(1 for o in range(base, end, 2) if U16(o) in MARKERS) >= thr:
            hot.append([base, min(base + blk, N)])
    if not hot:
        return [(0x200, N)]
    out = [hot[0]]
    for lo, hi in hot[1:]:
        if lo - out[-1][1] <= gap:
            out[-1][1] = hi
        else:
            out.append([lo, hi])
    return [(max(lo, 0x200), hi) for lo, hi in out]


WINDOWS = code_windows()
CODE_LO = WINDOWS[0][0]
CODE_HI = WINDOWS[-1][1]
print("окна кода: %s (всего %d байт из %d)"
      % (" ".join("$%06X-$%06X" % w for w in WINDOWS),
         sum(hi - lo for lo, hi in WINDOWS), N))


def in_code(a):
    """Внутри ли адрес какого-нибудь окна кода."""
    for lo, hi in WINDOWS:
        if lo <= a < hi:
            return True
    return False

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
for lo, hi in WINDOWS:
    for a in range(lo, hi - 3, 2):
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


# ─────────────── проход 3: указатели из таблиц данных ────────────────────
# Часть процедур недостижима обходом по потоку: адрес лежит в таблице, а не
# в команде, и пролога `movem` у таких процедур нет. Так спрятан, например,
# весь слой фаз компьютерного противника (docs/game-ai-player.md).
#
# Таблицы ищутся по самой ROM, двумя признаками, и оба самопроверяемые:
# кандидат принимается, только если с указанного адреса декодируется
# связный кусок кода до первой остановки.

def flows_ok(a, limit=0x400):
    """Декодируется ли с адреса связный кусок кода до первой остановки."""
    end = a + limit
    while a < end:
        if a & 1 or a < 0x200 or a + 1 >= N:
            return False
        try:
            ln, _, stop = decode(a)
        except Bad:
            return False
        if stop:
            return True
        a += ln
    return False


def code_start_ok(v):
    """Годится ли значение в указатель на процедуру.

    Попадать оно обязано на ГРАНИЦУ команды: адрес внутри уже разобранной
    команды — верный признак, что это не указатель, а совпадение.
    """
    if v & 1 or not in_code(v):
        return False
    if covered[v] and v not in starts:
        return False
    return flows_ok(v)


def word_tables():
    """`jmp/jsr (d8,pc,Xn.w)` — диспетчер по самоотносительным словам.

    Смещение в самой команде задаёт адрес таблицы точно, гадать не о чем;
    длина — пока слова разрешаются в код. Тем же приёмом выше снята
    таблица line-F, здесь он распространён на все найденные диспетчеры.
    """
    found = {}
    for a in starts:
        if U16(a) not in (0x4EBB, 0x4EFB):         # JSR / JMP (d8,pc,Xn)
            continue
        ext = U16(a + 2)
        if ext & 0x0800:                           # длинный индекс — не наш
            continue
        d8 = ext & 0xFF
        t = a + 2 + (d8 - 256 if d8 > 127 else d8)
        if t in found:
            continue
        run, limit = [], N
        for i in range(0x400):
            e = t + i * 2
            if e + 1 >= N or e >= limit:
                break
            if covered[e] or covered[e + 1]:   # пошёл код, лежащий за таблицей
                break
            v = (t + S16(e)) & 0xFFFFFF
            if not code_start_ok(v):
                break
            if v > t:
                limit = min(limit, v)          # таблица не залезает на свою цель
            run.append(v)
        if run:
            found[t] = run
    return found


def long_tables(min_run=4):
    """Прогон длинных слов, указывающих в код, в НЕ покрытых байтах.

    Покрытые байты не смотрим вовсе: там такой прогон — это сам код.
    Четыре подряд — уже не совпадение: случайное длинное слово попадает в
    диапазон кода примерно раз на четыре тысячи.
    """
    found = {}
    for lo, hi in WINDOWS:
        a = lo
        while a + 4 * min_run <= hi:
            run, b = [], a
            while b + 4 <= hi and not (covered[b] or covered[b + 1]
                                       or covered[b + 2] or covered[b + 3]):
                v = U32(b)
                if v & 1 or not in_code(v):
                    break
                run.append(v)
                b += 4
            if len(run) >= min_run and all(code_start_ok(v) for v in run):
                found[a] = run
                a = b
            else:
                a += 2
    return found


# ─────────────── проход 3: одиночные указатели из всей ROM ───────────────
# Прогон из четырёх подряд (выше) ловит только таблицы. У Maui Mallard код
# зовут из СТРУКТУР: в записи объекта лежит один указатель на обработчик, и
# соседние длинные слова — координаты и номера кадров, а не адреса. Прогона
# нет, и таблица не находится.
#
# Почему одиночному указателю здесь можно верить. Окно кода узкое: 131 КБ
# из 3 МБ. Случайное длинное слово попадает в него примерно раз на тридцать
# тысяч, то есть на полтора миллиона чётных смещений ждём десятки ложных, а
# не тысячи — и каждое ещё обязано разобраться в связный кусок кода
# (`code_start_ok`). У Dyna Brothers 2 окно занимает пятую часть картриджа,
# и там этот проход почти ничего не даёт: указателей в код из данных мало.
def stray_pointers():
    found = []
    for o in range(0, N - 3, 2):
        v = U32(o)
        if v & 1 or not in_code(v) or v in starts:
            continue
        if code_start_ok(v):
            found.append(v)
    return sorted(set(found))


fresh = stray_pointers()
targets.update(fresh)
walk(fresh)
print("проход 3 (+%d указателей из данных): %d инструкций, %d байт"
      % (len(fresh), len(starts), sum(covered)))

for rnd in range(1, 9):
    tabs = {}
    tabs.update(word_tables())
    tabs.update(long_tables())
    fresh = sorted({v for run in tabs.values() for v in run} - starts)
    if not fresh:
        break
    targets.update(fresh)
    walk(fresh)
    print("проход 4.%d (+%d таблиц, %d новых адресов): %d инструкций, %d байт"
          % (rnd, len(tabs), len(fresh), len(starts), sum(covered)))

# Таблица переходов диспетчера — данные, но лежит вплотную за его концом, и
# поток в неё затекает. Снимаем явно: иначе она даёт нелегальные инструкции,
# а снятие всего прогона целиком утащило бы вместе с ней сам обработчик.
if tbl is not None:
    for k in range(tbl, tbl + tbl_n * 2):
        covered[k] = 0
    print("таблица line-F $%06X-$%06X помечена данными" % (tbl, tbl + tbl_n * 2))

# ─────────────────────────── --report ────────────────────────────────────
# game.yaml давно правится руками: 53 сегмента переведены в m68k по одному,
# арбитром — побайтовая пересборка. Перезаписать его целиком значит стереть
# эту работу, поэтому находки нового прохода печатаются списком, а перевод
# остаётся ручным, как и раньше.
if "--report" in sys.argv:
    def yaml_segments(path):
        cur = {}
        for line in open(path, encoding="utf-8"):
            m = re.match(r"\s*-?\s*name:\s*(\S+)", line)
            if m:
                cur = {"name": m.group(1)}
            m = re.match(r"\s*type:\s*(\S+)", line)
            if m and cur:
                cur["type"] = m.group(1)
            m = re.match(r"\s*start:\s*0x([0-9A-Fa-f]+)", line)
            if m and cur:
                cur["start"] = int(m.group(1), 16)
            m = re.match(r"\s*end:\s*0x([0-9A-Fa-f]+)", line)
            if m and cur:
                cur["end"] = int(m.group(1), 16)
                yield cur
                cur = {}

    # Две байта — самая короткая команда 68000, и короткие прогоны бывают
    # настоящими: хвост скрипта из `bsr`+`moveq` или пустой обработчик из
    # одного `rts`. Но они же чаще всего и ложные — внутри таблицы слов
    # или графики. Прогон в два-шесть байт обязательно смотреть глазами.
    MIN_RUN = 2
    rows, total = [], 0
    for sg in yaml_segments(YAML):
        if sg.get("type") != "bin":
            continue
        runs, run = [], None
        for i in range(sg["start"], sg["end"]):
            if covered[i]:
                if run is None:
                    run = i
            elif run is not None:
                runs.append((run, i))
                run = None
        if run is not None:
            runs.append((run, sg["end"]))
        runs = [r for r in runs if r[1] - r[0] >= MIN_RUN]
        if runs:
            n = sum(b - a for a, b in runs)
            total += n
            rows.append((n, sg, runs))
    rows.sort(key=lambda r: -r[0])
    print("\nbin-сегменты, внутри которых обход нашёл код.")
    print("Переводить по одному, арбитр — `make rebuild`.\n")
    for n, sg, runs in rows:
        whole = len(runs) == 1 and runs[0] == (sg["start"], sg["end"])
        print("  %-14s $%06X-$%06X  +%5d байт%s" % (
            sg["name"], sg["start"], sg["end"], n,
            "   ЦЕЛИКОМ" if whole else ""))
        if not whole:
            for a, b in runs:
                print("%36s$%06X-$%06X" % ("", a, b))
    print("\nсегментов %d, байт %d" % (len(rows), total))
    sys.exit(0)

COV = coverage_path()
if "--drop-bin" in sys.argv:
    # Второй арбитр, после ассемблера: собранный ROM. Ассемблер ругается
    # только на невозможные кодировки, а данные, которые СЛУЧАЙНО читаются
    # как законная команда, проходят молча и всплывают расхождением байт.
    # Так ловится, например, `ori.b #$42` поверх таблицы: старший байт
    # непосредственного операнда в байтовой команде не хранится нигде, и
    # обратно печатается ноль.
    # Снимаем ОДНУ команду, а не весь прогон. Прогон — это сотни настоящих
    # команд, среди которых затесалась таблица; снятие целиком стоило здесь
    # 10 КБ разобранного кода при двенадцати разошедшихся байтах. Границы
    # команд берём из `starts` текущего обхода: карта покрытия из pickle им
    # не противоречит, потому что обход тот же.
    built = open(sys.argv[sys.argv.index("--drop-bin") + 1], "rb").read()
    covered = bytearray(pickle.load(open(COV, "rb")))
    bad = {i for i in range(min(len(built), N)) if built[i] != ROM[i]}
    bounds = sorted(starts)
    n, hit = 0, 0
    for a in bad:
        if not covered[a]:
            continue
        i = bisect.bisect_right(bounds, a) - 1
        if i >= 0 and bounds[i] <= a:
            s = bounds[i]
            e = bounds[i + 1] if i + 1 < len(bounds) else a + 1
            # Команда не может тянуться дальше конца прогона покрытия.
            while e > s and not covered[e - 1]:
                e -= 1
        else:                                  # границы нет — снимаем прогон
            s = a
            while s > 0x200 and covered[s - 1]:
                s -= 1
            e = a
            while e < N and covered[e]:
                e += 1
        hit += 1
        for k in range(s, e):
            if covered[k]:
                covered[k] = 0
                n += 1
    print("расхождений байт: %d, снято команд %d, байт %d" % (len(bad), hit, n))

if "--drop" in sys.argv:
    log = open(sys.argv[sys.argv.index("--drop") + 1],
               encoding="utf-8", errors="replace").read()
    if "--drop-bin" not in sys.argv:      # иначе затёрли бы его работу
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
body, ci, di, bi = [], 0, 0, 0


def emit(kind, s, e, blob=False):
    """Один сегмент конфига. `blob` — данные ВНЕ окон кода (графика, звук)."""
    global ci, di, bi
    if kind == "m68k":
        ci += 1
        nm, sub = "code_%02d" % ci, ""
    elif blob:
        bi += 1
        nm, sub = "blob_%02d" % bi, ""
    else:
        di += 1
        nm, sub = "data_%02d" % di, "\n    subdir: code_data"
    body.append("  - name: %s\n    type: %s\n    start: 0x%06X\n    end:   0x%06X%s"
                % (nm, kind, s, e, sub))


cur = 0x200
for lo, hi in WINDOWS:
    if cur < lo:
        emit("bin", cur, lo, blob=True)
    holes, run = [], None
    for i in range(lo, hi):
        if not covered[i]:
            if run is None:
                run = i
        elif run is not None:
            holes.append((run, i))
            run = None
    if run is not None:
        holes.append((run, hi))
    cur = lo
    for a, b in [(a + (a & 1), b + (b & 1)) for a, b in holes if b > a]:
        if a > cur:
            emit("m68k", cur, a)
        emit("bin", a, b)
        cur = b
    if cur < hi:
        emit("m68k", cur, hi)
    cur = hi
if cur < N:
    emit("bin", cur, N, blob=True)

charmap = os.path.join(HERE, "%s_charmap.tbl" % STEM)
head = """# %s — %s
# СГЕНЕРИРОВАНО tools/analyze.py — правки затираются, меняйте анализатор.
# Границы кода получены обходом по потоку управления (векторы%s + прологи
# функций) внутри окон %s, а не разметкой на глаз. В m68k попадает только
# подтверждённый код, всё непокрытое вынесено в bin: только начало нового
# сегмента возвращает дизассемблеру выравнивание.
name: %s
sha1: "%s"

options:
  platform: megadrive
  region: ntsc
  basename: %s
  base_path: ./out/%s
  target_path: ./%s
  asm_path: asm
  asset_path: assets
  build_path: build
  symbols_path: ./%s
%s  header_output: true
  incbin: true

segments:
  # Тип `header` непригоден для побайтовой пересборки: NUL-байты полей
  # заголовка рвут лексер, а InitialSSP выводится как метка в ОЗУ, которую
  # никто не определяет.
  - name: header
    type: bin
    start: 0x000000
    end:   0x000200

""" % (NAME, ROM[0x120:0x150].decode("latin1").strip() or NAME,
       " + таблица line-F $%06X" % tbl if tbl else "",
       " ".join("$%06X-$%06X" % w for w in WINDOWS),
       NAME, SHA1, NAME, NAME, os.path.basename(rom_path()),
       os.path.basename(merged_syms),
       ("  charmap_path: ./%s\n" % os.path.basename(charmap)
        if os.path.exists(charmap) else ""))

tail = "\n"
# ОСТОРОЖНО: game.yaml давно не чисто производный файл. Поверх первого
# прогона в нём руками переведены десятки сегментов, разрезаны свалки и
# расставлены имена, на которые ссылаются документы. Перезапись стирает всё
# это, поэтому существующий файл трогаем только по явному --write, а находки
# смотрим через --report.
if os.path.exists(YAML) and "--write" not in sys.argv:
    print("%s оставлен как есть (перезапись — только с --write);"
          " находки: --report" % os.path.basename(YAML))
else:
    open(YAML, "w", encoding="utf-8").write(head + "\n\n".join(body) + tail)

# ───────────────────── game_symbols.gen.txt ──────────────────────────────
named = {ENTRY: "EntryPoint", U32(2 * 4): "BusError", U32(3 * 4): "AddressError",
         U32(4 * 4): "IllegalInstruction", U32(5 * 4): "DivideByZero",
         U32(30 * 4): "VBlankHandler", U32(28 * 4): "HBlankHandler"}
good = sorted(t for t in targets if t in starts and covered[t])
out = ["; СГЕНЕРИРОВАНО tools/analyze.py — правки затираются.",
       "; Свои имена держите в %s: они идут первыми при"
       % os.path.basename(gen_syms).replace(".gen.txt", ".user.txt"),
       "; склейке и побеждают, потому что types/symbol.go запоминает первое",
       "; вхождение адреса.", ""]
seen_names = set()
for a in good:
    nm = named.get(a, "loc_%06X" % a)
    if nm in seen_names:
        nm = "loc_%06X" % a
    seen_names.add(nm)
    out.append("%s = $%06X" % (nm, a))
open(gen_syms, "w", encoding="utf-8").write("\n".join(out) + "\n")

m = sum(1 for l in body if "m68k" in l)
print("\nразметка обходом: %d сегментов (m68k %d, bin %d), кода %d байт"
      % (len(body) + 2, m, len(body) - m + 2, sum(covered)))
print("%s: %d символов" % (os.path.basename(gen_syms), len(good)))
