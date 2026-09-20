#!/usr/bin/env python3
"""Достаёт сэмплы DAC в WAV.

    make pcm            все девятнадцать сэмплов в out/<имя>/sound/

Кодирование вычитано из главного цикла драйвера Z80 (`$0F26`, разбор в
docs/game-sound.md) и повторено здесь один в один:

* таблица сэмплов лежит в начале окна банка, запись — слово-указатель;
* заголовок сэмпла 5 байт: шаг задержки, длина словом, адрес словом;
* данные — по два отсчёта в байте, старший ниббл первым;
* ниббл индексирует таблицу приращений `$0FC1`, и приращение
  ПРИБАВЛЯЕТСЯ к восьмибитному накопителю по модулю 256;
* накопитель стартует со `$80` (`ld c,$80` на `$0F59`).

Частота считается по такту задержки. Между двумя отсчётами драйвер
крутит `djnz` заданное число раз и делает постоянный набор записей в
порты; это даёт `3.58 МГц / (13·шаг + 117)`. **Оценка, а не измерение**:
в цикле стоит `ei`, и прерывание кадра ворует такты, так что настоящая
частота чуть ниже и слегка плавает.
"""
import os
import struct
import sys
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT as out_path

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

rom = open(os.path.join(HERE, "game.gen"), "rb").read()

Z80_CLOCK = 3579545.0
DELTAS = [0, 1, 2, 4, 8, 16, 32, 64, -128, -1, -2, -4, -8, -16, -32, -64]
# Где сэмпл слышно. Записано только то, что доказано разбором кода:
# остальные привязки к месту в игре не установлены.
WHERE = {
    (7, 3): "дождь, `GfxDraw_00E1EE` `$00E1EE`",
    (6, 4): "тряска экрана, `SoundSfx_00E036` `$00E036`",
}
SFX_TABLE = 0x00201C      # пары (банк, команда) по номеру звука
SFX_NAMES = 0x04C2F6      # звукоподражания, тот же номер


def bank_base(v):
    return 0x1C0000 + v * 0x8000


def rd(v, z):
    return rom[bank_base(v) + (z - 0x8000)]


def wd(v, z):
    return rd(v, z) | (rd(v, z + 1) << 8)


def samples(v):
    """Все сэмплы банка: (номер, шаг, длина, адрес окна, адрес ROM)."""
    first = wd(v, 0x8000)
    n = (first - 0x8000) // 2
    out = []
    for i in range(n):
        p = wd(v, 0x8000 + 2 * i)
        out.append((i, rd(v, p), wd(v, p + 1), wd(v, p + 3)))
    return out


def decode(v, addr, length):
    """Дельты в восьмибитный беззнаковый PCM."""
    out = bytearray()
    c = 0x80
    for k in range(length):
        b = rd(v, addr + k)
        for nib in (b >> 4, b & 15):
            c = (c + DELTAS[nib]) & 0xFF
            out.append(c)
    return bytes(out)


def rate(step):
    return int(round(Z80_CLOCK / (13 * step + 117)))


def sfx_names():
    """Номер звука -> звукоподражание, через charmap проекта."""
    try:
        import dumptext
        return dict(dumptext.sounds(SFX_NAMES))
    except Exception:
        return {}


def dac_sample(img, cmd):
    """Команда драйвера -> номер сэмпла, либо None, если это не DAC.

    Запись команды лежит по указателю из таблицы `$1100`, нотная строка —
    по третьему и четвёртому байту описания канала. Сэмпл заводит
    команда `$EA nn`.
    """
    le = lambda a: img[a] | (img[a + 1] << 8)
    if not 0x90 <= cmd <= 0xCF:
        return None
    rec = le(0x1100 + 2 * (cmd - 0x90))
    for k in range(img[rec + 3]):
        p = le(rec + 4 + 6 * k + 2)
        for _ in range(8):
            if img[p] == 0xEA:
                return img[p + 1] - 1
            p += 1
    return None


def named():
    """(банк, сэмпл) -> номера звуков из table_sfx, у которых есть имя."""
    from z80dis import load
    img = load()
    out = {}
    for i in range((0x207E - SFX_TABLE) // 2):
        b, c = rom[SFX_TABLE + 2 * i], rom[SFX_TABLE + 2 * i + 1]
        if b > 0x7F:
            continue
        s = dac_sample(img, c)
        if s is not None:
            out.setdefault((b, s), []).append(i)
    return out


def raw():
    """(банк, сэмпл) -> адреса площадок трапа `$FF2F` с константой.

    `$FF2F` отдаёт драйверу КОМАНДУ как есть, мимо `table_sfx`, и таких
    вызовов 95 против 13. Банк при этом не передаётся — остаётся тот, что
    выбран раньше, поэтому одна и та же команда в разных банках звучит
    по-разному. Банк ищется назад по ближайшему `$FF36` (всегда 5) или
    `$FF2D` с константой; где рядом нет ни того, ни другого, банк
    неизвестен и такая площадка в счёт не идёт.
    """
    from z80dis import load
    img = load()
    out = {}
    for i in range(0, len(rom) - 6, 2):
        if (rom[i], rom[i + 1], rom[i + 4], rom[i + 5]) != (0x3F, 0x3C, 0xFF, 0x2F):
            continue
        s = dac_sample(img, rom[i + 2] << 8 | rom[i + 3])
        if s is None:
            continue
        bank = None
        for j in range(i + 4, max(0, i - 0x600), -2):
            if rom[j] == 0xFF and rom[j + 1] == 0x36:
                bank = 5
                break
            if (rom[j], rom[j + 1], rom[j - 4], rom[j - 3]) == (0xFF, 0x2D, 0x3F, 0x3C):
                bank = rom[j - 1]
                break
        if bank in (5, 6, 7):
            out.setdefault((bank, s), []).append(i + 4)
    return out


def main():
    d = out_path("sound")
    os.makedirs(d, exist_ok=True)
    names = sfx_names()
    try:
        by_name, by_raw = named(), raw()
    except Exception:
        by_name, by_raw = {}, {}
    total = 0
    idx = open(os.path.join(d, "index.md"), "w", encoding="utf-8",
               newline="\n")
    idx.write("# Сэмплы DAC\n\n")
    idx.write("СГЕНЕРИРОВАНО `tools/pcm.py` (`make pcm`).\n\n")
    idx.write("Кодирование — четырёхбитная дельта: ниббл индексирует таблицу\n"
              "приращений, приращение прибавляется к восьмибитному "
              "накопителю\n**по модулю 256**. Обёртывание не ошибка, а "
              "замысел: так устроен\n`add a,` в драйвере, и один сэмпл "
              "(банк 5, №5) уложен в диапазон\nровно, со сносом в ноль.\n\n")
    idx.write("Частота — **верхняя граница**: `3.58 МГц / (13·шаг + 117)`. В цикле\n"
              "задержки стоит `ei`, и прерывание кадра ворует такты, так что\n"
              "настоящая ниже на 7–13 процентов и зависит от того, сколько\n"
              "каналов звучит. Измеренные значения — в `out/<имя>/sound/render/index.md`\n"
              "(`make render`), там драйвер исполняется на эмуляторе.\n\n")
    idx.write("Столбец «звук» — звукоподражание из списка `$04C2F6`; оно есть\n"
              "только у сэмплов, которые заводят через `table_sfx`. Столбец\n"
              "«зовут» перечисляет площадки трапа `$FF2F`, который отдаёт\n"
              "команду драйверу напрямую: имени у такого вызова нет, зато\n"
              "видно место в коде.\n\n")
    lines = []
    head = "| банк | сэмпл | шаг | отсчётов | Гц | звук | зовут | файл |"
    rule = "|---|---|---|---|---|---|---|---|"
    print(head)
    print(rule)
    lines.append(head)
    lines.append(rule)
    for v in (5, 6, 7):
        for i, step, length, addr in samples(v):
            if length < 2:
                continue
            pcm = decode(v, addr, length)
            hz = rate(step)
            who = by_name.get((v, i), [])
            label = ", ".join(names.get(x, "№%02X" % x) for x in who) or "—"
            part = ["`$%06X`" % a for a in by_raw.get((v, i), [])]
            if (v, i) in WHERE:
                part.insert(0, WHERE[(v, i)])
            place = ", ".join(part) or "—"
            name = "bank%d_sample%d.wav" % (v, i)
            with wave.open(os.path.join(d, name), "wb") as f:
                f.setnchannels(1)
                f.setsampwidth(1)
                f.setframerate(hz)
                f.writeframes(pcm)
            total += 1
            row = ("| %d | %d | %d | %d | %d | %s | %s | `%s` |"
                   % (v, i, step, len(pcm), hz, label, place, name))
            print(row)
            lines.append(row)
    idx.write("\n".join(lines))
    idx.write("\n\nБанк 6, сэмплы 1 и 2 стоят особняком: у них 38 и 62 "
              "процента\nприращений нулевые, огибающей нет, и уровень "
              "гуляет во весь размах.\nОстальные при том же декодере дают "
              "правильную огибающую, так что\nдело не в разборе. Имени в "
              "списке звукоподражаний у них нет, но играются\n"
              "они оба — трапом `$FF2F`.\n\n")
    idx.write("Ни одного вызова не нашлось только у банка 5 сэмпла 4 "
              "и банка 6\nсэмпла 3.\n")
    idx.close()
    print()
    print("записано %d файлов в %s" % (total, os.path.relpath(d, HERE)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
