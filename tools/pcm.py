#!/usr/bin/env python3
"""Достаёт сэмплы DAC в WAV.

    make pcm            все девятнадцать сэмплов в out/sound/

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

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

rom = open(os.path.join(HERE, "game.gen"), "rb").read()

Z80_CLOCK = 3579545.0
DELTAS = [0, 1, 2, 4, 8, 16, 32, 64, -128, -1, -2, -4, -8, -16, -32, -64]
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


def commands():
    """(банк, сэмпл) -> номера звуковых команд, которые его заводят."""
    import gfx  # noqa: F401  (только ради общего пути)
    from z80dis import load
    img = load()
    le = lambda a: img[a] | (img[a + 1] << 8)
    out = {}
    for i in range((0x207E - SFX_TABLE) // 2):
        b, c = rom[SFX_TABLE + 2 * i], rom[SFX_TABLE + 2 * i + 1]
        if b > 0x7F or not (0x90 <= c <= 0xCF):
            continue
        rec = le(0x1100 + 2 * (c - 0x90))
        for k in range(img[rec + 3]):
            seq = le(rec + 4 + 6 * k + 2)
            p = seq
            for _ in range(8):
                if img[p] == 0xEA:
                    out.setdefault((b, img[p + 1] - 1), []).append(i)
                    break
                p += 1
    return out


def main():
    d = os.path.join(HERE, "out", "sound")
    os.makedirs(d, exist_ok=True)
    names = sfx_names()
    try:
        used = commands()
    except Exception:
        used = {}
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
    idx.write("Частота — **оценка**: `3.58 МГц / (13·шаг + 117)`. В цикле "
              "задержки\nстоит `ei`, и прерывание кадра ворует такты, так "
              "что настоящая\nчастота чуть ниже и слегка плавает.\n\n")
    lines = []
    print("| банк | сэмпл | шаг | отсчётов | Гц | звук | файл |")
    print("|---|---|---|---|---|---|---|")
    lines.append("| банк | сэмпл | шаг | отсчётов | Гц | звук | файл |")
    lines.append("|---|---|---|---|---|---|---|")
    for v in (5, 6, 7):
        for i, step, length, addr in samples(v):
            if length < 2:
                continue
            pcm = decode(v, addr, length)
            hz = rate(step)
            who = used.get((v, i), [])
            label = ", ".join(names.get(x, "№%02X" % x) for x in who) or "—"
            name = "bank%d_sample%d.wav" % (v, i)
            with wave.open(os.path.join(d, name), "wb") as f:
                f.setnchannels(1)
                f.setsampwidth(1)
                f.setframerate(hz)
                f.writeframes(pcm)
            total += 1
            row = ("| %d | %d | %d | %d | %d | %s | `%s` |"
                   % (v, i, step, len(pcm), hz, label, name))
            print(row)
            lines.append(row)
    idx.write("\n".join(lines))
    idx.write("\n\nБанк 6, сэмплы 1 и 2 стоят особняком: у них 38 и 62 "
              "процента\nприращений нулевые, огибающей нет, и уровень "
              "гуляет во весь размах.\nОстальные при том же декодере дают "
              "правильную огибающую, так что\nдело не в разборе. Имени у "
              "их команд в списке звукоподражаний тоже\nнет — похоже на "
              "неиспользованное.\n")
    idx.close()
    print()
    print("записано %d файлов в %s" % (total, os.path.relpath(d, HERE)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
