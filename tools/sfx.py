#!/usr/bin/env python3
"""Разбирает звуковые эффекты: 50 записей драйвера Z80.

    make sfx        docs/game-sfx.md и out/sound/sfx/*.txt

Сэмплы DAC вынуты отдельно (`make pcm`), но они — меньшая часть: из
пятидесяти команд `$90`–`$C1` сэмпл заводят семнадцать, а остальные
**тридцать три** целиком синтезируются на YM2612 и PSG. Здесь разобраны
все, и данные для этого лежат не в картридже, а в ОЗУ Z80: таблица
записей `$1100`, описания каналов и нотные строки — часть самого
драйвера, одна и та же при любом банке.

Запись звука:

| смещение | что |
|---|---|
| `+0`, `+1` | указатель на таблицу инструментов |
| `+2` | байт, попадающий в `+2` каждого слота |
| `+3` | число каналов |
| `+4`… | по 6 байт на канал |

Канал: флаги, адрес канала, слово — нотная строка, транспонирование,
громкость. Порядок проверен по коду запуска `$05E4`, где эти шесть байт
переносятся в слот командами `ldi`.

**Длительности здесь — кадры.** Счётчик `+11` слота уменьшается раз в
кадр (`$02DA`), а темповая прибавка `$0845` достаётся только десяти
музыкальным слотам; эффектным — нет. Поэтому пауза `$0C` в эффекте это
ровно 12 кадров, пятая доля секунды, и никакой темп на это не влияет.

## Тембры эффектов: «песня `$81`» — не заглушка

Каждый FM-эффект просит инструмент командой `$EF` с отрицательным
номером, и второй байт при этом — номер песни, откуда брать патч
(`$0C12`). Таких эффектов двадцать девять — остальные четыре сидят на
одном PSG, и тембр им не нужен, — и у всех двадцати девяти там стоит
`$81` и только `$81`.

Раньше эта песня считалась заглушкой: она побайтно одинакова в банках 2,
3 и 4, и её никто не заводит. Разгадка в её записи. Все девять каналов
указывают на один и тот же адрес `$822D`, а там лежит единственный байт
`$E3` — «заглушить и кончить». Музыки в ней нет вовсе. Зато сразу за
этим байтом, с `$822E`, идёт таблица инструментов, и она кончается ровно
там, где начинается следующая песня `$85CB`: **37 патчей по 25 байт, без
остатка**. Эффекты просят 17 из них, старший номер 36 — последний в
таблице.

Значит запись `$81` существует не ради музыки: это **общий банк тембров
для звуковых эффектов**. Одинакова она в трёх банках именно потому, что
звук удара должен звучать одинаково, какая бы музыка ни играла.

## Кому какие каналы

Эффектам отданы не все каналы: `$066D` раздаёт слоты по трём таблицам, и
FM 1, FM 2 и слот DAC в них не попадают. На деле занято ещё меньше:
FM3 в двадцати девяти записях, FM4 в двадцати восьми, FM5 в двадцати
одной (из них семнадцать — запуск сэмпла), PSG3 в семи, PSG2 в трёх,
PSG1 в двух. Пока играет эффект, музыкальный слот того же канала
помечается битом 2 и молчит.

Шум PSG встречается трижды. `$AA` `ｻﾞｱｯ` — единственная запись во всём
драйвере, где занят ровно один канал и тот шумовой: `$F3 $E4` кладёт в
порт `$7F11` белый шум на самой быстрой скорости сдвига. `$AB` и `$B8`
подмешивают шум к другим каналам.
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

SFX_TABLE = 0x00201C      # пары (банк, команда) по номеру звука
SFX_NAMES = 0x04C2F6      # звукоподражания, тот же номер
TABLE = 0x1100            # 64 указателя на записи звуков, ОЗУ Z80
FIRST, LAST = 0x90, 0xC1  # команды, которые игра действительно просит

# Адрес канала -> имя. Значения взяты из таблиц `$06C6`/`$06D6`/`$06E6`:
# эффектам достаются только эти семь, FM 1 и 2 и слот DAC для них закрыты.
CHAN = {
    0x00: "FM1", 0x01: "FM2", 0x02: "FM3", 0x04: "FM4",
    0x05: "FM5", 0x06: "FM6", 0x80: "PSG1", 0xA0: "PSG2", 0xC0: "PSG3",
}

# Назначение тех команд, у которых нет звукоподражания, но есть
# доказанный вызов. Больше в список не добавлять без разбора кода.
NOTE = {
    0xBF: "предсмертный крик, игрок 1 (`PlayDeathSfx` `$01D168`)",
    0xC0: "предсмертный крик, игрок 2 (тот же разбор знака `+$9`)",
}


def image():
    from z80dis import load
    return load()


def record(img, cmd):
    """Запись команды: инструменты, общий байт и список каналов."""
    le = lambda a: img[a] | (img[a + 1] << 8)
    p = le(TABLE + 2 * (cmd - 0x90))
    n = img[p + 3]
    chans = []
    for k in range(n):
        b = img[p + 4 + 6 * k:p + 10 + 6 * k]
        chans.append(dict(flags=b[0], chan=b[1], seq=b[2] | (b[3] << 8),
                          transpose=b[4], volume=b[5]))
    return dict(addr=p, patches=le(p), common=img[p + 2], chans=chans)


def names():
    """Команда -> звукоподражания из списка `$04C2F6`."""
    try:
        import dumptext
        by_num = dict(dumptext.sounds(SFX_NAMES))
    except Exception:
        by_num = {}
    out = {}
    for i in range((0x207E - SFX_TABLE) // 2):
        c = rom[SFX_TABLE + 2 * i + 1]
        if i in by_num:
            out.setdefault(c, []).append(by_num[i])
    return out


def callers():
    """Команда -> адреса вызовов из кода 68000, оба пути.

    `$FF38` кладёт номер звука и берёт команду из `table_sfx`, `$FF2F`
    кладёт саму команду. Считаются только площадки с константой: где
    номер приходит в регистре, из статики он не виден.
    """
    out = {}
    for i in range(0, len(rom) - 6, 2):
        if (rom[i], rom[i + 1], rom[i + 4]) != (0x3F, 0x3C, 0xFF):
            continue
        v = rom[i + 2] << 8 | rom[i + 3]
        if rom[i + 5] == 0x2F:
            cmd = v
        elif rom[i + 5] == 0x38 and 2 * v < 0x207E - SFX_TABLE:
            cmd = rom[SFX_TABLE + 2 * v + 1]
        else:
            continue
        if FIRST <= cmd <= LAST:
            out.setdefault(cmd, []).append(i + 4)
    return out


def kind(img, chans):
    """Чем звук сделан: сэмплом, FM, PSG, шумом."""
    tags = []
    body = b""
    for c in chans:
        ev = notestring.walk(lambda a: img[a], c["seq"])
        body += bytes(img[e[0]] for e in ev)
        if any(e[1].startswith("СЭМПЛ") for e in ev):
            tags.append("DAC")
        elif any(e[1].startswith("шум") for e in ev):
            tags.append("шум")
        elif CHAN.get(c["chan"], "").startswith("PSG"):
            tags.append("PSG")
        else:
            tags.append("FM")
    order = ["DAC", "FM", "PSG", "шум"]
    return "+".join(sorted(set(tags), key=order.index))


def patches(img, chans):
    """Инструменты, которые звук просит командой `$EF`."""
    out = []
    for c in chans:
        for at, what, _ops, _d in notestring.walk(lambda a: img[a], c["seq"]):
            if not what.startswith("ИНСТРУМЕНТ"):
                continue
            n = img[at + 1]
            if n >= 0x80:
                out.append("%d из песни $%02X" % (n & 0x7F, img[at + 2]))
            else:
                out.append("%d" % n)
    seen = []
    for x in out:
        if x not in seen:
            seen.append(x)
    return ", ".join(seen) or "—"


SEQ_LO, SEQ_HI = 0x1466, 0x1BEE   # область нотных строк в ОЗУ Z80


def coverage(img):
    """Сколько байт области нотных строк обход действительно проходит.

    Проверка того же рода, что с блоками и записями: если разбор верен,
    строки должны покрыть область без дыр. Считаются байты, а не события,
    и повторное покрытие не страшно — несколько команд делят одну строку.
    """
    hit = bytearray(SEQ_HI - SEQ_LO)
    rd = lambda a: img[a]
    for cmd in range(FIRST, LAST + 1):
        for c in record(img, cmd)["chans"]:
            for at, _what, _ops, _d in notestring.walk(rd, c["seq"]):
                b = img[at]
                if b >= 0xE0:
                    n = 1 + notestring.nops(rd, at)
                elif 0x81 <= b <= 0xDF:
                    n = 2 if img[at + 1] < 0x80 else 1
                else:
                    n = 1
                for k in range(n):
                    if SEQ_LO <= at + k < SEQ_HI:
                        hit[at + k - SEQ_LO] = 1
    holes = []
    for i, v in enumerate(hit):
        a = SEQ_LO + i
        if v:
            continue
        if holes and holes[-1][1] + 1 == a:
            holes[-1][1] = a
        else:
            holes.append([a, a])
    return sum(hit), len(hit), holes


def main():
    img = image()
    d = os.path.join(HERE, "out", "sound", "sfx")
    os.makedirs(d, exist_ok=True)
    nm, cl = names(), callers()

    doc = os.path.join(HERE, "docs", "game-sfx.md")
    f = open(doc, "w", encoding="utf-8", newline="\n")
    p = f.write
    p("# Звуковые эффекты\n\n")
    p("СГЕНЕРИРОВАНО `tools/sfx.py` (`make sfx`) — правки затираются,\n"
      "меняйте инструмент.\n\n")
    p(__doc__.split("\n", 2)[2].strip().replace("make sfx", "`make sfx`", 1))
    p("\n\n## Все пятьдесят\n\n")
    p("Столбец «зовут» — площадки с константой: `$FF38` через `table_sfx`\n"
      "и `$FF2F` напрямую. Пусто значит, что команду просят только из\n"
      "экрана звука либо номером в регистре.\n\n")
    p("| команда | звукоподражание | чем | каналы | кадров | инструменты | "
      "зовут |\n")
    p("|---|---|---|---|---|---|---|\n")

    seen = {}
    for cmd in range(FIRST, LAST + 1):
        r = record(img, cmd)
        if r["addr"] in seen:
            continue
        seen[r["addr"]] = cmd
        chans = r["chans"]
        frames = 0
        path = os.path.join(d, "cmd_%02X.txt" % cmd)
        g = open(path, "w", encoding="utf-8", newline="\n")
        g.write("команда $%02X, запись $%04X, инструменты $%04X, общий байт "
                "$%02X\n\n" % (cmd, r["addr"], r["patches"], r["common"]))
        for ci, c in enumerate(chans):
            ev = notestring.walk(lambda a: img[a], c["seq"])
            frames = max(frames, notestring.ticks(ev))
            g.write("-- канал %d: %s, строка $%04X, флаги $%02X, "
                    "транспонирование $%02X, громкость $%02X\n"
                    % (ci, CHAN.get(c["chan"], "$%02X" % c["chan"]),
                       c["seq"], c["flags"], c["transpose"], c["volume"]))
            for at, what, ops, _dur in ev:
                g.write("   $%04X  %-30s %s\n" % (at, what, ops or ""))
            g.write("\n")
        g.close()
        p("| `$%02X` | %s | %s | %s | %s | %s | %s |\n"
          % (cmd,
             ", ".join(nm.get(cmd, [])) or NOTE.get(cmd, "—"),
             kind(img, chans),
             " ".join(CHAN.get(c["chan"], "$%02X" % c["chan"]) for c in chans),
             "—" if frames == 0 else "%d" % frames,
             patches(img, chans),
             ", ".join("`$%06X`" % a for a in cl.get(cmd, [])) or "—"))

    p("\nРазличных записей: %d.\n" % len(seen))

    got, total, holes = coverage(img)
    p("\n## Сходится ли разбор\n\n")
    p("Нотные строки занимают `$%04X`–`$%04X`. Обход по всем пятидесяти\n"
      "записям доходит до **%d байт из %d**.\n\n" % (SEQ_LO, SEQ_HI - 1,
                                                       got, total))
    if holes:
        p("Не достаётся до: %s. Это хвост `$E1 $FF`, «снять», пауза и\n"
          "переход назад в тело `ﾋﾟﾁｬﾋﾟﾁｬ` — то есть заготовка повтора,\n"
          "на которую во всём образе драйвера нет ни одной ссылки.\n"
          % ", ".join("`$%04X`–`$%04X`" % (a, b) if a != b
                      else "`$%04X`" % a for a, b in holes))
    else:
        p("Дыр нет.\n")
    p("\nПолные строки — в `out/sound/sfx/cmd_<XX>.txt`.\n")
    f.close()
    print("записано: docs/game-sfx.md и %d файлов в %s"
          % (len(seen), os.path.relpath(d, HERE)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
