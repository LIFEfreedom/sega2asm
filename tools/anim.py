#!/usr/bin/env python3
"""Скрипты анимации объектов Maui Mallard.

    python tools/anim.py 1D8980        разобрать скрипт по адресу
    python tools/anim.py --frame 1D8980  только первый кадр
    python tools/anim.py --forms         три формы игрока и их скрипты
    make anim ANIM=1D8980

Скрипт лежит в `$22(a0)` и исполняется `$297074`, когда счётчик `$28(a0)`
дошёл до нуля. Читается он **словами**:

* старший байт меньше `$D8` — это слово-адрес слота таблицы кадров
  (`$0200`-`$3898`), он и становится новым кадром `$C(a0)`; значения 0, 1 и
  2 — короткие команды `$296FAE`;
* старший байт `$D8`-`$EB` — команда, младший байт всегда её первый
  операнд. Переход идёт через таблицу `$2970D6`, двадцать записей по
  `bra.w`.

Обработчики команд лежат в `$297126`-`$2972EE`. Обход по потоку управления
туда не попадает — только через таблицу, — поэтому анализатор считал этот
кусок данными, пока его не перевели в код руками.

**Прикрепить скрипт можно ДВУМЯ способами**, и это видно по обработчикам
порождения. Прямой — `move.l #adr,$22(a0)`; так делают 231 обработчик из
298. Остальные кладут в `$48(a0)` адрес ПРОГРАММЫ ПОРОЖДЕНИЯ в банке
данных, а уже её команда `$84 $00` несёт адрес скрипта (`script_in_prog`).
Не путать с `$1E(a0)`: там лежит процедура обновления объекта, все 314
значений внутри банка кода, и к анимации она отношения не имеет —
декодер скрипта на ней даёт ложные кадры.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import rom_bytes

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM = rom_bytes()
TABLE = 0x2970D6        # таблица переходов, 20 записей по bra.w
FRAMES = 0x000200
FRAMES_END = 0x003898

# Окно, в котором лежат сами скрипты. Границы сняты с 264 значений `$22(a0)`
# по всем обработчикам порождения: от $1D6E38 до $1DB600. Нужно, чтобы
# отличать адрес скрипта от прочих длинных слов в программе порождения.
SCRIPTS = (0x1D6000, 0x1DC000)
HANDLERS = (0x28D000, 0x2AC000)     # банк обработчиков порождения

# команда -> (сколько байт всего, как показать)
CMDS = {
    0xD8: (2, "держать кадр %(n)d"),
    0xD9: (4, "переход на %(d)+d"),
    0xDA: (2, "отразить по %(flip)s"),
    0xDB: (4, "случайно: если меньше %(n)d — дальше, иначе переход на %(d)+d"),
    0xDC: (4, "поле +$%(n)02X (слово) = $%(w)04X"),
    0xDD: (6, "поле +$%(n)02X (длинное) = $%(l)08X"),
    0xDE: (4, "поле +$%(n)02X += $%(w)04X"),
    0xDF: (2, "$8 = поле +$%(n)02X"),
    0xE0: (2, "поле +$%(n)02X = $8"),
    0xE1: (4, "поле +$%(n)02X (байт) = $%(b)02X"),
    0xE2: (4, "поле +$%(n)02X |= $%(w)04X"),
    0xE3: (4, "поле +$%(n)02X &= $%(w)04X"),
    0xE4: (4, "поле +$%(n)02X ^= $%(w)04X"),
    0xE5: (4, "если поле +$%(n)02X не ноль — переход на %(d)+d"),
    0xE6: (6, "если поле +$%(n)02X == $%(w)04X — переход на %(d2)+d"),
    0xE7: (6, "породить $%(l)08X"),
    0xE8: (6, "породить $%(l)08X (вариант 2)"),
    0xE9: (6, "породить $%(l)08X (вариант 3)"),
    0xEA: (2, "начать звук %(n)d"),
    0xEB: (2, "остановить звук %(n)d"),
}
U16 = lambda o: struct.unpack_from(">H", ROM, o)[0]
S16 = lambda o: struct.unpack_from(">h", ROM, o)[0]
U32 = lambda o: struct.unpack_from(">I", ROM, o)[0]


def step(a):
    """Один шаг скрипта -> (длина, текст, номер кадра либо None)."""
    hi = ROM[a]
    if hi < 0xD8:
        w = U16(a)
        if w < 3:
            return 2, "короткая команда %d" % w, None
        if FRAMES <= w < FRAMES_END and w % 4 == 0:
            return 2, "кадр %d" % ((w - FRAMES) // 4), (w - FRAMES) // 4
        return 2, "слово $%04X (не кадр)" % w, None
    ln, fmt = CMDS.get(hi, (2, "неизвестная команда $%02X" % hi))
    v = {"n": ROM[a + 1], "b": ROM[a + 3] if ln > 2 else 0,
         "w": U16(a + 2) if ln > 2 else 0,
         "l": U32(a + 2) if ln > 4 else 0,
         "d": S16(a + 2) if ln > 2 else 0,
         "d2": S16(a + 4) if ln > 4 else 0,
         "flip": "горизонтали" if ROM[a + 1] == 0 else "вертикали"}
    return ln, fmt % v, None


def walk(a, limit=64):
    """Линейный проход: переходы не исполняются, только показываются."""
    out, seen = [], set()
    for _ in range(limit):
        if a in seen or not (0x1000 <= a < len(ROM) - 8):
            break
        seen.add(a)
        ln, txt, fr = step(a)
        out.append((a, ROM[a:a + ln], txt, fr))
        if ROM[a] == 0xD9:      # безусловный переход — дальше линейно нечего
            break
        a += ln
    return out


def first_frame(a, limit=64):
    for _at, _raw, _txt, fr in walk(a, limit):
        if fr is not None:
            return fr
    return None


def field_imm(at, field, depth=0, seen=None):
    """Длинное слово из `move.l #adr,<field>(a0)` в теле обработчика.

    В байтах это `21 7C adr 00 ff`, где `ff` — смещение поля. Если до него
    встретился `bsr.w` или `jsr .l`, заходит внутрь: половина обработчиков
    делегирует соседу.
    """
    seen = set() if seen is None else seen
    if at in seen or depth > 2 or not (HANDLERS[0] <= at < HANDLERS[1]):
        return None
    seen.add(at)
    calls, a = [], at
    for _ in range(80):
        if a + 8 > len(ROM):
            break
        if ROM[a] == 0x21 and ROM[a + 1] == 0x7C and U16(a + 6) == field:
            return U32(a + 2)
        w = U16(a)
        if w == 0x4E75:                       # rts
            break
        if w == 0x6100:                       # bsr.w
            calls.append(a + 2 + S16(a + 2))
        if w == 0x4EB9:                       # jsr xxx.l
            calls.append(U32(a + 2))
        a += 2
    for c in calls:
        r = field_imm(c, field, depth + 1, seen)
        if r:
            return r
    return None


def script_of(at, depth=0, seen=None):
    """Адрес скрипта, который обработчик порождения кладёт в `$22(a0)`."""
    return field_imm(at, 0x0022, depth, seen)


def script_in_prog(at, span=32):
    """Скрипт внутри ПРОГРАММЫ ПОРОЖДЕНИЯ, на которую смотрит `$48(a0)`.

    Второй способ прикрепить анимацию: обработчик не пишет `$22(a0)` сам, а
    кладёт в `$48(a0)` адрес программы в банке данных (`$1FEDCA`-`$1FF3EC`).
    Программа — поток команд по два байта с операндами; `$84 $00` несёт
    длинным словом адрес скрипта, и он нам и нужен:

        $1FF226:  84 00  00 1D 94 20  00 00  85 00 FF F8
                         ^^^^^^^^^^^ скрипт $1D9420

    Остальные команды (`$81 nn` — поле записи, `$85 $00` — смещение)
    пропускаются: разбирать их целиком, чтобы достать первый кадр, незачем.
    Смещение `$84 $00` у всех девяти известных программ чётное и не дальше
    четвёртого байта, поэтому окна в 32 байта хватает с запасом.
    """
    if at is None or at + span + 6 > len(ROM):
        return None
    for i in range(0, span, 2):
        if ROM[at + i] == 0x84 and ROM[at + i + 1] == 0x00:
            v = U32(at + i + 2)
            if SCRIPTS[0] <= v < SCRIPTS[1]:
                return v
    return None


def script_of_any(at):
    """Скрипт анимации, как бы обработчик его ни прикреплял.

    Сначала прямой `$22(a0)`, затем программа порождения из `$48(a0)`.
    Порядок важен: у кого есть `$22`, тот берёт его, и поведение для таких
    обработчиков не меняется.
    """
    sc = script_of(at)
    if sc is not None:
        return sc
    return script_in_prog(field_imm(at, 0x0048))


def show(a):
    print("скрипт $%06X:" % a)
    for at, raw, txt, _fr in walk(a):
        print("  $%06X  %-12s %s"
              % (at, " ".join("%02X" % b for b in raw), txt))


# Форма игрока: значение `$FF133A` -> (скрипты, обработчики, высота, имя)
FORMS = [
    (0, 0x1FCC64, 0x1FCCE0, 0x20, "Maui Mallard, утка"),
    (1, 0x1FCC90, 0x1FCD98, 0x20, "Cold Shadow, ниндзя"),
    (2, 0x1FCCB8, 0x1FCE50, 0x10, "уменьшенный"),
]


def show_forms():
    """Три формы игрока: у каждой свои скрипты и свои обработчики действий.

    Ставят их `$291B60` (утка), `$291B84` (ниндзя) и `$29A8A0` (переключает
    между обычной и уменьшенной, проигрывая превращение `$1D7EE4` или
    `$1D7E8E`). Высота `$FF133C` участвует в пробе земли (`$2A4F...`).
    """
    print("формы игрока, значение `$FF133A`:")
    print()
    print(" знач  скрипты   обработчики  высота  кто")
    for v, sc, hd, ht, name in FORMS:
        print("   %d   $%06X   $%06X     $%02X   %s" % (v, sc, hd, ht, name))
    for v, sc, _hd, _ht, name in FORMS:
        end = {0: 0x1FCC90, 1: 0x1FCCB8, 2: 0x1FCCE0}[v]
        print()
        print("форма %d (%s), %d скриптов:" % (v, name, (end - sc) // 4))
        for i in range((end - sc) // 4):
            a = U32(sc + i * 4)
            fr = first_frame(a)
            print("   %2d -> $%06X  первый кадр %s"
                  % (i, a, fr if fr is not None else "—"))


def main():
    args = [x for x in sys.argv[1:] if not x.startswith("-")]
    if "--forms" in sys.argv:
        show_forms()
        return 0
    if not args:
        print(__doc__)
        return 2
    a = int(args[0], 16)
    if "--frame" in sys.argv:
        print(first_frame(a))
        return 0
    show(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
