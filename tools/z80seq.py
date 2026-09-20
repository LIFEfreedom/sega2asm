#!/usr/bin/env python3
"""Разбор скриптов дорожек звукового драйвера (Maui Mallard).

    python tools/z80seq.py            сводка по всем 169 звукам
    python tools/z80seq.py 0          звук 0 целиком, дорожка за дорожкой
    python tools/z80seq.py 0 2        только дорожка 2
    make z80seq SOUND=0

Откуда взялась грамматика. Драйвер Z80 читает дорожку побайтно
(`$04B4`, разбор `$050E`), и разбор здесь повторяет его один в один:

* байт `< $60` — **нота**; играется процедурой `$11DF`, после чего дорожка
  засыпает на текущий шаг;
* `$60..$72` — команды, у каждой своё число аргументов (см. таблицу ниже);
* `$73..$7F` — драйвер пропускает молча;
* `$80..$BF` — **длительность звучания** ноты (gate), шесть бит на байт,
  несколько байт подряд наращивают число;
* `$C0..$FF` — **шаг до следующего события**, так же по шесть бит.

Числа накапливаются, пока идут байты с тем же старшим двубитным признаком
(`$04E6`), и хранятся в драйвере со знаком минус: счётчик `+$7/+$8` слота
считает ВВЕРХ до нуля.

Адреса внутри дорожки — 24-битные, считаются от начала таблицы звуков.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT as out_path
from paths import rom_bytes

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM = rom_bytes()
# Третий из четырёх адресов, которые 68000 отдаёт драйверу при старте
# ($2F8D7C). Он же — база всех смещений внутри таблицы звуков.
TABLE = int(os.environ.get("MM_SOUND_TABLE", "2AECB7"), 16)
# Первая из четырёх таблиц — тембры. Первый байт записи задаёт, чем
# играется нота, и от этого зависит, что номер ноты вообще значит.
VOICES = int(os.environ.get("MM_VOICE_TABLE", "2AD33C"), 16)
VOICE_KIND = {0: "FM", 1: "ударные", 2: "PSG", 3: "PSG-2"}

# код: (имя, сколько байт аргументов)
CMD = {
    0x60: ("конец дорожки", 0),
    0x61: ("тембр", 1),
    0x62: ("набор из таблицы 2", 1),
    0x63: ("пауза", 0),
    0x64: ("начало цикла", 1),
    0x65: ("конец цикла", 0),
    0x66: ("флаг 6", 1),
    0x67: ("флаг 7", 1),
    0x68: ("темп", 1),
    0x69: ("глушить дорожку", 1),
    0x6A: ("громкость", 1),
    0x6B: ("запустить звук", 1),
    0x6C: ("пара в $0F4F", 2),
    0x6D: ("второй темп", 0),
    0x6E: ("правка тембра", 1),
    0x6F: ("переход", 2),
    0x70: ("параметр :=", 2),
    0x71: ("если параметр", 3),     # индекс, режим, значение (+ смещение)
    0x72: ("управление", 2),
}

# Подкоманды $72 ($076D). Пятая — самая ходовая во всей игре: она правит
# поле +$1E слота, а его `$11DF` складывает с общей громкостью $15A8.
SUB72 = {
    0x00: "остановить звук $%02X",
    0x01: "приглушить звук $%02X",
    0x02: "продолжить все ($%02X)",
    0x03: "приглушить звук из параметра[0] ($%02X)",
    0x04: "общая громкость := $%02X",
    0x05: "громкость дорожки := $%02X",
}

# Режимы сравнения из цепочки `dec d` в $0720. Сравнивается ЗНАЧЕНИЕ из
# скрипта (в аккумуляторе) с параметром, при истине — переход. Всё, что не
# попало в пятёрку — включая 0, — уходит в последнюю ветку $074C, а там
# переход делается при НЕравенстве.
COND = {1: "==", 2: ">=", 3: ">", 4: "<=", 5: "<"}


def u16le(o):
    return ROM[o] | (ROM[o + 1] << 8)


def voice_kind(n):
    """Тип тембра n: FM, ударные или PSG."""
    d = VOICES + u16le(VOICES + n * 2)
    return VOICE_KIND.get(ROM[d], "тип %d" % ROM[d])


def sound_count():
    """Первое смещение в таблице — она же её длина в байтах."""
    return u16le(TABLE) // 2


def tracks(n):
    """-> [адрес скрипта дорожки] для звука n."""
    d = TABLE + u16le(TABLE + n * 2)
    cnt = ROM[d]
    out = []
    for t in range(cnt):
        b = ROM[d + 1 + t * 3: d + 4 + t * 3]
        out.append(TABLE + (b[0] | (b[1] << 8) | (b[2] << 16)))
    return d, cnt, out


def number(a, tag):
    """Число из байт с признаком `tag`: шесть бит на байт. -> (значение, адрес)."""
    v = ROM[a] & 0x3F
    a += 1
    while a < len(ROM) and (ROM[a] & 0xC0) == tag:
        v = (v << 6) | (ROM[a] & 0x3F)
        a += 1
    return v, a


def dump(addr, limit=4000):
    """Печать одной дорожки. Останавливается на `конец дорожки`."""
    a = addr
    end = addr + limit
    while a < end:
        b = ROM[a]
        if b < 0x60:
            # Что значит номер ноты, решает ТИП тембра: у ударного канала
            # (тип 0) это сэмпл `нота-$30`, у FM и PSG — высота.
            print("  $%06X  %-14s нота $%02X%s"
                  % (a, "%02X" % b, b,
                     "  (для ударных — сэмпл %d)" % (b - 0x30)
                     if b >= 0x30 else ""))
            a += 1
        elif b < 0x73:
            name, n = CMD[b]
            args = ROM[a + 1:a + 1 + n]
            # у `если параметр` за тремя аргументами всегда идёт байт
            # смещения: драйвер читает его в обеих ветках, просто в одной
            # выбрасывает ($074F против $0759).
            extra = ROM[a + 4:a + 5] if b == 0x71 else b""
            raw = " ".join("%02X" % x for x in ROM[a:a + 1 + n + len(extra)])
            if b == 0x71:
                txt = ("если $%02X %s параметр[$%02X] -> $%06X"
                       % (args[2], COND.get(args[1], "!="),
                          args[0], a + 5 + extra[0]))
            elif b == 0x6F:
                off = args[0] | (args[1] << 8)
                if off >= 0x8000:
                    off -= 0x10000
                txt = "переход -> $%06X" % (a + 3 + off)
            elif b == 0x70:
                txt = "параметр[$%02X] := $%02X" % (args[0], args[1])
            elif b == 0x72:
                txt = SUB72.get(args[0], "управление $%02X := $%%02X" % args[0]) % args[1]
            elif b == 0x61:
                txt = "тембр $%02X (%s)" % (args[0], voice_kind(args[0]))
            elif n:
                txt = name + " " + " ".join("$%02X" % x for x in args)
            else:
                txt = name
            print("  $%06X  %-14s %s" % (a, raw, txt))
            a += 1 + n + len(extra)
            if b == 0x60:
                return a
        elif b < 0x80:
            print("  $%06X  %-14s (пропуск $%02X)" % (a, "%02X" % b, b))
            a += 1
        else:
            tag = b & 0xC0
            v, nxt = number(a, tag)
            raw = " ".join("%02X" % x for x in ROM[a:nxt])
            what = "звучание" if tag == 0x80 else "шаг"
            print("  $%06X  %-14s %s %d" % (a, raw, what, v))
            a = nxt
    print("  … оборвано на $%06X" % a)
    return a


def summary():
    n = sound_count()
    print("таблица звуков $%06X, звуков %d\n" % (TABLE, n))
    print("| звук | дорожек | первая дорожка | длина, байт |")
    print("|---|---|---|---|")
    multi = 0
    for i in range(n):
        d, cnt, addrs = tracks(i)
        if cnt > 1:
            multi += 1
        ln = "—"
        if addrs:
            a = addrs[0]
            e = a
            while e < len(ROM) and ROM[e] != 0x60 and e - a < 4000:
                e += 1
            ln = e - a + 1
        print("| %d | %d | $%06X | %s |"
              % (i, cnt, addrs[0] if addrs else 0, ln))
        if i > 40:
            print("| … | | | |")
            break
    print("\nмногодорожечных звуков (музыка): %d из %d"
          % (sum(1 for i in range(n) if tracks(i)[1] > 1), n))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        summary()
        return 0
    n = int(args[0], 0)
    d, cnt, addrs = tracks(n)
    print("звук %d: описатель $%06X, дорожек %d" % (n, d, cnt))
    want = [int(args[1], 0)] if len(args) > 1 else range(cnt)
    for t in want:
        print("\n— дорожка %d, $%06X —" % (t, addrs[t]))
        dump(addrs[t])
    return 0


if __name__ == "__main__":
    sys.exit(main())
