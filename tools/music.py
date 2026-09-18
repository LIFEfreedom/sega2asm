#!/usr/bin/env python3
"""Выгружает партитуры: нотные строки всех песен в читаемый вид.

    make music                 docs/game-music.md и out/sound/music/*.txt

Формат вычитан из драйвера Z80 (docs/game-sound.md). Запись песни лежит
в музыкальном банке по таблице `$8004`, и из неё берутся указатели на
нотные строки каналов. Байт строки:

| байт | что |
|---|---|
| `$00`–`$7F` | пауза; длительность = байт × множитель из записи песни |
| `$80` | снять ноту |
| `$81`–`$DF` | нота: номер в таблице частот `$08AA` плюс транспонирование |
| `$E0`–`$FF` | команда, таблица `$0ADB` |

Разбор самой строки общий со звуковыми эффектами и живёт в
`tools/notestring.py`; там же сказано, откуда взято число операндов
каждой команды.

После ноты может идти байт длительности (тоже `< $80`); если следующий
байт `≥ $80`, берётся длительность предыдущей ноты.

Высота: таблица `$08AA` хроматическая — каждые двенадцать шагов фнум
ровно вдвое, — но **убывает** с номером: меньший номер выше. Поэтому
ноты названы по положению в таблице (октава и ступень), а не абсолютной
высотой: блок YM у всех записей нулевой, и переводить фнум в герцы без
разбора инструментов было бы натяжкой.
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

import notestring  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

rom = open(os.path.join(HERE, "game.gen"), "rb").read()

STEPS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

def bank_base(v):
    return 0x1C0000 + v * 0x8000


def rd(v, z):
    return rom[bank_base(v) + (z - 0x8000)]


def wd(v, z):
    return rd(v, z) | (rd(v, z + 1) << 8)


def note_name(i):
    """Номер в таблице частот -> ступень и октава.

    Отсчёт от номера 9 — первой незажатой записи, самой высокой. Номера
    0..8 таблица зажимает в один и тот же фнум $3FF: ударным каналам это
    и нужно, мелодии — нет. Октава РАСТЁТ ВНИЗ, потому что фнум убывает.
    """
    if i >= 84:
        return "psg%d" % (i - 84)
    if i < 9:
        return "зажата%d" % i
    return "%s%d" % (STEPS[(9 - i) % 12], (i - 9) // 12)


def song(v, n):
    """Запись песни n ($81+n) банка v."""
    table = wd(v, 0x8004)
    p = wd(v, table + 2 * n)
    patches = wd(v, p)
    fm, psg, mul, tempo = rd(v, p + 2), rd(v, p + 3), rd(v, p + 4), rd(v, p + 5)
    chans = []
    q = p + 6
    for _ in range(fm):
        chans.append(("FM", wd(v, q), rd(v, q + 2), rd(v, q + 3)))
        q += 4
    for _ in range(psg):
        chans.append(("PSG", wd(v, q), rd(v, q + 2), rd(v, q + 3)))
        q += 6
    return dict(addr=p, patches=patches, mul=mul, tempo=tempo, chans=chans)


def walk(v, start, mul, limit=4000):
    """Обёртка над общим разбором: подставляет чтение из банка v."""
    out = []
    for at, what, arg, _dur in notestring.walk(lambda a: rd(v, a), start, mul,
                                               limit):
        if what.startswith("\u043d\u043e\u0442\u0430 \u2116"):
            i = int(what.split("\u2116")[1])
            what = "\u043d\u043e\u0442\u0430 %s (\u2116%d)" % (note_name(i), i)
        out.append((at, what, arg))
    return out


def main():
    d = os.path.join(HERE, "out", "sound", "music")
    os.makedirs(d, exist_ok=True)
    doc = os.path.join(HERE, "docs", "game-music.md")
    f = open(doc, "w", encoding="utf-8", newline="\n")
    p = f.write
    p("# Партитуры\n\n")
    p("СГЕНЕРИРОВАНО `tools/music.py` (`make music`) — правки затираются,\n"
      "меняйте инструмент.\n\n")
    p(__doc__.split("\n", 2)[2].strip().replace("    make music", "`make music`"))
    p("\n\n")

    # названия дорожек: номер музыки -> (банк, песня)
    names = {}
    NT = 0x4BF5E
    w16 = lambda a: (rom[a] << 8) | rom[a + 1]
    for i in range(w16(NT) // 2):
        a = NT + w16(NT + 2 * i)
        e = a + 4
        while rom[e]:
            e += 1
        mid = w16(0x4B314 + 2 * rom[a])
        b, c = rom[0x1F36 + 2 * mid], rom[0x1F37 + 2 * mid]
        if b <= 0x7F:
            names[(b, c)] = rom[a + 4:e].decode("latin1")

    total = 0
    p("| банк | песня | название | FM | PSG | темп | множитель | событий |\n")
    p("|---|---|---|---|---|---|---|---|\n")
    for v in (2, 3, 4):
        for n in range(15):
            cmd = 0x81 + n
            s = song(v, n)
            ev = 0
            path = os.path.join(d, "bank%d_song%02X.txt" % (v, cmd))
            g = open(path, "w", encoding="utf-8", newline="\n")
            g.write("банк %d, песня $%02X, запись $%04X\n" % (v, cmd, s["addr"]))
            g.write("инструменты $%04X, темп $%02X, множитель длительности %d\n\n"
                    % (s["patches"], s["tempo"], s["mul"]))
            for ci, (kind, seq, tr, vol) in enumerate(s["chans"]):
                g.write("-- канал %d (%s), строка $%04X, транспонирование %d, "
                        "громкость $%02X\n" % (ci, kind, seq, tr, vol))
                for at, what, arg in walk(v, seq, s["mul"]):
                    ev += 1
                    g.write("   $%04X  %-26s %s\n" % (at, what, arg or ""))
                g.write("\n")
            g.close()
            total += ev
            p("| %d | `$%02X` | %s | %d | %d | $%02X | %d | %d |\n"
              % (v, cmd, names.get((v, cmd), "—"),
                 sum(1 for c in s["chans"] if c[0] == "FM"),
                 sum(1 for c in s["chans"] if c[0] == "PSG"),
                 s["tempo"], s["mul"], ev))
    p("\nСобытий разобрано всего: %d.\n" % total)
    p("\nПолные строки — в `out/sound/music/bank<N>_song<XX>.txt`.\n")
    f.close()
    print("записано: docs/game-music.md и %d файлов в %s"
          % (45, os.path.relpath(d, HERE)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
