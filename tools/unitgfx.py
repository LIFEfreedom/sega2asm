#!/usr/bin/env python3
u"""Как выглядит каждый ТИП юнита: от номера типа до готового PNG.

    make unitgfx                 сводка: какой тип какими кадрами рисуется
    make unitgfx UARGS=32        кадры типа 32 в out/<имя>/gfx/type_032.png
    make unitgfx UARGS="32 10"   только анимация 10 этого типа

Цепочка разобрана по `InitAnimRecord` `$014EDA` и `MakeUnitNameWord`
`$014660`:

1. `AssetIndexTable` `$0150FA` по «номер типа минус один» даёт номер банка;
   банк — запись в `$078818`, то есть таблица указателей на кадры по 512
   байт (спрайт 4x4 тайла).
2. `UnitAnimScriptIndex` `$01509E` по тому же индексу даёт набор анимаций:
   запись в таблице `[$078814]`. Внутри набора смещение считается как
   `(анимация - 4) * 8 + направление & ~1` — то есть четыре стороны, а не
   восемь: восьмая берётся отражением. Анимации 0…3 у всех общие, их корень
   `[$078804]`.
3. Скрипт анимации читает `RunAnimScript` `$014F80`. Он состоит из ЗАПИСЕЙ
   ПО ТРИ БАЙТА `{слово кадра, длительность}` и восьми команд от `$F0`:

   | байт | что делает |
   |---|---|
   | `$FF` | два операнда: счётчик и знаковое смещение — цикл с повторами |
   | `$FE` | операнд: безусловный относительный переход |
   | `$FD` | операнд пропускается |
   | `$FC` | выровнять на чётный и прыгнуть по ДЛИННОМУ СЛОВУ |
   | `$FB` | шесть операндов: кадр сразу для двух слоёв плюс длительность |
   | `$FA` | операнд в `+$1E` записи анимации |
   | `$F9` | операнд в `+$1F` |
   | `$F8` | ничего |

   Почти каждая анимация начинается с `$FC`: сама таблица короткая, а тела
   скриптов лежат далеко, около `$1626xx`.

4. Слово кадра разбирает `MakeUnitNameWord`: **младший байт — номер кадра**,
   **бит 8 — брать не свой банк, а ОБЩИЙ** `[$078800]`, остальные биты идут
   в слово имени спрайта VDP (бит 11 — отражение по горизонтали).

Общий банк — это ЯЙЦА и эффекты: три размера яйца на каждый из шести видов
каждой стороны, потом раскол скорлупы. Поэтому у анимаций 4…9 (стадии
дозревания) своих кадров нет вовсе, а тело существа появляется с анимации
10.
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import struct                                                # noqa: E402
import gfx                                                   # noqa: E402
from paths import OUT as out_path                            # noqa: E402

rom = gfx.rom

ASSET_IDX = 0x0150FA        # номер типа - 1 -> номер банка кадров
ANIM_IDX = 0x01509E         # он же -> номер набора анимаций
FRAME_ROOT = 0x078818       # банки кадров
ANIM_ROOT = 0x078814        # указатель на таблицу наборов анимаций
COMMON_ANIM = 0x078804      # указатель на таблицу анимаций 0..3
COMMON_FRAMES = 0x078800    # указатель на ОБЩИЙ банк кадров (яйца, эффекты)

N_TYPES = 91
# Набор анимаций — 232 байта, то есть 29 записей по 8 байт: номера $04…$20.
# До этого здесь стояло range(4, 20), и signature() не видела разницы в
# анимациях $14…$20 — типы 32/33 и 34/35/91 из-за этого считались клонами.
ANIMS = range(4, 33)
FACINGS = (0, 2, 4, 6)

L = gfx.L
W = lambda a: struct.unpack(">H", rom[a:a + 2])[0]

OPERANDS = {0xFF: 2, 0xFE: 1, 0xFD: 1, 0xFC: 0, 0xFB: 6, 0xFA: 1, 0xF9: 1,
            0xF8: 0}


def frame_table(t):
    return L(FRAME_ROOT + 4 * rom[ASSET_IDX + t - 1])


def script_addr(t, anim, facing=0):
    base = (L(COMMON_ANIM) if anim <= 3
            else L(L(ANIM_ROOT) + 4 * rom[ANIM_IDX + t - 1]))
    return base + W(base + (anim if anim <= 3 else anim - 4) * 8
                    + (facing & ~1))


def walk(a, steps=400):
    u"""Пройти скрипт; вернуть слова кадров в порядке показа."""
    out, seen = [], set()
    for _ in range(steps):
        if a in seen or not (0 < a < len(rom) - 8):
            break
        seen.add(a)
        b = rom[a]
        if b < 0xF0:
            out.append(W(a))
            a += 3
        elif b == 0xFB:
            out.append(W(a + 2))      # первый слой; второй на +$4
            a += 7
        elif b == 0xFE:
            d = rom[a + 1]
            a += 2 + (d - 256 if d > 127 else d)
        elif b == 0xFF:
            # Смещение — ПЕРВЫЙ операнд, второй это счётчик повторов.
            # Раньше здесь стоял rom[a + 2], и обход уезжал в чужой скрипт:
            # ленты набирали кадры соседних анимаций (разбор в unitanim.py).
            d = rom[a + 1]
            a += 3 + (d - 256 if d > 127 else d)
        elif b == 0xFC:
            p = a + 1 + ((a + 1) & 1)
            a = L(p)
        else:
            a += 1 + OPERANDS.get(b, 0)
    return out


def anim_frames(t, anim, facing=0):
    u"""(свои кадры, кадры общего банка) для одной анимации."""
    own, com = [], []
    try:
        words = walk(script_addr(t, anim, facing))
    except Exception:
        return own, com
    for w in words:
        (com if w & 0x100 else own).append(w & 0xFF)
    return own, com


def body_frames(t, anims=(10, 11)):
    u"""Кадры тела: анимации стойки и ходьбы, четыре стороны."""
    out = []
    for an in anims:
        for f in FACINGS:
            for k in anim_frames(t, an, f)[0]:
                if k not in out:
                    out.append(k)
    return out


def signature(t):
    u"""Чем тип отличим от другого: банк плюс кадры всех анимаций."""
    return (frame_table(t),
            tuple(tuple(anim_frames(t, an, f)[0])
                  for an in ANIMS for f in FACINGS))


PALETTE_ROW = 0x015156      # тип минус один -> ряд CRAM 0..3


def palette_row(t):
    u"""Ряд CRAM, которым рисуется тип.

    Выбирает его `MakeUnitNameWord` на `$014BDA`: берёт тип из `+$14`
    записи анимации, минус один, идёт в эту таблицу и `ror.b #3`
    укладывает результат в биты 13-14 слова имени спрайта.
    """
    return rom[PALETTE_ROW + t - 1]


def row_palette(row, stage_rec=0, stage_pal=0):
    u"""Ряд CRAM -> цвета, по `BuildStagePalettes` `$005384`.

    Ряд 0 всегда `data_99[0]`, ряды 1 и 2 — `data_99` по байтам `+$28`
    и `+$29` описания миссии (1 у всех 123 миссий и 3 у 119 из 123),
    ряд 3 — палитра `+$4C` из записи графики этапа.
    """
    if row == 3:
        return gfx.stage_records()[stage_rec][0][stage_pal]
    return gfx.read_palette(gfx.PAL_ARRAY + 32 * (0, 1, 3)[row])


def render_type(t, anims=None, path=None, pal=None, scale=4):
    tbl = frame_table(t)
    n = gfx.table_len(tbl)
    keys = []
    for an in (anims if anims is not None else ANIMS):
        for f in FACINGS:
            for k in anim_frames(t, an, f)[0]:
                if k < n and k not in keys:
                    keys.append(k)
    frames = []
    for k in keys:
        p = L(tbl + 4 * k)
        if not (0 < p < 0x200000):
            continue
        _m, _s, d, _e = gfx.unpack(rom, p)
        frames.append(gfx.columnwise(bytes(d)))
    if not frames:
        print("тип %d: своих кадров нет" % t)
        return None
    d = out_path("gfx")
    os.makedirs(d, exist_ok=True)
    path = path or os.path.join(d, "type_%03d.png" % t)
    row = palette_row(t)
    gfx.render_frames(frames, path, per_row=8, pal=pal or row_palette(row),
                      scale=scale, cut=gfx.SPRITE_CUT)
    print("тип %3d: банк $%06X, ряд палитры %d, кадры %s -> %s"
          % (t, tbl, row, keys, os.path.relpath(path, HERE)))
    return path


def main():
    args = sys.argv[1:]
    if args:
        t = int(args[0])
        anims = [int(x) for x in args[1:]] or None
        render_type(t, anims)
        return 0

    print("Общий банк кадров: $%06X (%d записей) — яйца и эффекты"
          % (L(COMMON_FRAMES), gfx.table_len(L(COMMON_FRAMES))))
    print()
    print("тип  банк      тело (анимации 10 и 11)      совпадает с")
    sigs = {}
    for t in range(1, N_TYPES + 1):
        try:
            s = signature(t)
        except Exception:
            continue
        same = sigs.setdefault(s, t)
        body = body_frames(t)
        print("%3d  $%06X  %-28s %s"
              % (t, frame_table(t), str(body[:8]),
                 "" if same == t else "тип %d" % same))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
