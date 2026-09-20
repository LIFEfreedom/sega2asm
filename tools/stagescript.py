#!/usr/bin/env python3
"""Сценарий событий каждого этапа: что делает его покадровый обработчик.

    make stages          (нужен свежий `make split`: читает листинги)

Главный цикл `$01631C` сразу после приращения `GameTick` зовёт
`RunStageFrameHook` `$02D090`. Тот берёт номер этапа из байта `+$3`
описания миссии и прыгает по самоотносительной таблице
`table_stageframe` `$02D0B8` — 256 записей. Соседняя `$02CE68` делает то
же один раз при входе на карту по таблице `table_stagestart` `$02CE90`.

Сами сценарии формульны: задать пару порогов в `d6`/`d7` и позвать общую
процедуру, либо сверить `GameTick` с точным числом и что-то сделать —
сменить музыку, подсыпать юнитов, включить отсчёт. `d7` — тик, на котором
событие начинается, `d6` — период повторения; счётчик живёт в `$FFE0BC`.
"""
import glob
import io
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT as out_path

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

rom = open(os.path.join(HERE, "game.gen"), "rb").read()
w = lambda a: (rom[a] << 8) | rom[a + 1]

TABLE = 0x02D0B8          # table_stageframe
START_TABLE = 0x02CE90    # table_stagestart
STUB = 0x02E8FA


def listing_index():
    """Адрес -> текст инструкции, из всех листингов m68k."""
    code = {}
    for f in glob.glob(out_path("asm", "m68k", "*.asm")):
        cur = None
        for ln in open(f, encoding="utf-8", errors="replace"):
            ln = ln.rstrip("\n")
            m = (re.match(r"^\s*org\s+\$([0-9A-F]{6})", ln)
                 or re.match(r"^; \$([0-9A-F]{6})$", ln.strip())
                 or re.match(r"^\S+:\s+; \$([0-9A-F]{6})", ln))
            if m:
                cur = int(m.group(1), 16)
                continue
            if ln.startswith("\t") and cur is not None:
                code[cur] = ln.strip()
                cur = None
    return code


def label_index():
    """Имя метки -> адрес, из всех листингов."""
    out = {}
    for f in glob.glob(out_path("asm", "m68k", "*.asm")):
        for ln in open(f, encoding="utf-8", errors="replace"):
            m = re.match(r"^([A-Za-z_]\w*):\s+; \$([0-9A-F]{6})", ln)
            if m:
                out[m.group(1)] = int(m.group(2), 16)
    return out


def body(code, a, limit=80):
    """Инструкции от a до первого rts."""
    out, cur, addrs = [], a, sorted(code)
    import bisect
    for _ in range(limit):
        if cur not in code:
            out.append("??? $%06X" % cur)
            break
        out.append(code[cur])
        if code[cur] == "rts":
            break
        i = bisect.bisect_right(addrs, cur)
        if i >= len(addrs):
            break
        # Через дыру не прыгаем: за ней уже другой сегмент, и его текст
        # к этому обработчику отношения не имеет.
        if addrs[i] - cur > 10:
            out.append("…дальше bin")
            break
        cur = addrs[i]
    return out


def digest(ins):
    d6 = d7 = None
    ticks, music, calls, arg7 = [], [], [], []
    for t in ins:
        m = re.match(r"move\.w\s+#\$([0-9A-F]+),d6", t)
        if m:
            d6 = int(m.group(1), 16)
        m = re.match(r"move\.w\s+#\$([0-9A-F]+),d7", t)
        if m:
            d7 = int(m.group(1), 16)
        m = re.match(r"cmpi\.l\s+#\$([0-9A-F]+),d0", t)
        if m:
            ticks.append(int(m.group(1), 16))
        m = re.match(r"move\.b\s+#\$([0-9A-F]+),d0", t)
        if m:
            music.append(int(m.group(1), 16))
        # У тел-условий d7 значит не тик, а тип или число — и тогда его
        # кладут байтом, а не словом.
        m = re.match(r"move\.b\s+#\$([0-9A-F]+),d7", t)
        if m:
            arg7.append(int(m.group(1), 16))
        m = re.match(r"(?:bsr\.w|jsr)\s+\(?([A-Za-z_]\w*)", t)
        if m:
            calls.append(m.group(1))
    return d6, d7, ticks, music, calls, arg7


SWEEPS = {"SpreadTerrainRandom": "38x38, шанс 10%",
          "ConvertTerrainInner": "38x38, все клетки",
          "ConvertTerrainAll": "40x40, все клетки",
          "SeedEmptyTerrain": "только пустые, шанс 25%"}


def terrain_ops(ins):
    """Пары «маска типов -> тип» из тела: d4 маска, d5 тип, затем проход.

    Значений `d5` до вызова может быть несколько — тогда тип выбирается
    броском, как в `$02F30A`; собираем их все.
    """
    d4 = None
    cand = []
    out = []
    for t in ins:
        m = re.match(r"move\.l\s+#\$([0-9A-F]+),d4", t)
        if m:
            d4 = int(m.group(1), 16)
        if re.match(r"moveq\s+#1,d4", t):
            d4 = 1
        m = re.match(r"move\.w\s+#\$([0-9A-F]+),d5", t)
        if m:
            cand.append(int(m.group(1), 16))
        m = re.match(r"(?:bsr\.w|jsr)\s+\(?(\w+)", t)
        if m and m.group(1) in SWEEPS:
            types = [b for b in range(32) if d4 and d4 >> b & 1]
            if not cand and out:
                cand = list(out[-1][2])       # повтор того же прохода
            op = (m.group(1), tuple(types), tuple(cand))
            if not out or out[-1] != op:
                out.append(op)
            cand = []
    return out


def stage_to_missions():
    """Номер этапа -> подписи миссий, которые его берут."""
    from unpack import unpack
    out = {}
    for c in range(9):
        p = struct.unpack(">I", rom[0x060400 + c * 4:0x060404 + c * 4])[0]
        if not (0 < p < 0x280000):
            continue
        _m, size, d, _e = unpack(rom, p)
        for i in range(size // 92):
            r = d[i * 92:(i + 1) * 92]
            out.setdefault(r[3], []).append("гл.%d м.%d" % (c, i + 1))
    return out


def music_target(mid):
    b, c = rom[0x1F36 + 2 * mid], rom[0x1F37 + 2 * mid]
    return ("—" if b > 0x7F else str(b)), c


def main():
    code = listing_index()
    miss = stage_to_missions()
    tgt = [TABLE + w(TABLE + 2 * i) for i in range(256)]
    start = [START_TABLE + w(START_TABLE + 2 * i) for i in range(256)]

    out_path = os.path.join(HERE, "docs", "game-events.md")
    f = io.open(out_path, "w", encoding="utf-8", newline="\n")
    p = f.write

    live = [i for i, t in enumerate(tgt) if t != STUB]
    p("# Сценарии событий этапов\n\n")
    p("СГЕНЕРИРОВАНО `tools/stagescript.py` (`make stages`) — правки\n"
      "затираются, меняйте инструмент.\n\n")
    p("Главный цикл `$01631C` сразу после приращения `GameTick` зовёт\n"
      "`RunStageFrameHook` `$02D090`. Тот берёт номер этапа из байта `+$3`\n"
      "описания миссии и прыгает по самоотносительной таблице\n"
      "`table_stageframe` `$02D0B8` — 256 записей. Соседняя\n"
      "`RunStageStartHook` `$02CE68` делает то же один раз при входе на\n"
      "карту, по таблице `table_stagestart` `$02CE90`.\n\n")
    p("Сценарии формульны: задать пару порогов в `d6`/`d7` и позвать общую\n"
      "процедуру, либо сверить `GameTick` с точным числом и что-то\n"
      "сделать — сменить музыку, подсыпать юнитов, включить отсчёт.\n"
      "**`d7` — тик, на котором событие начинается, `d6` — период\n"
      "повторения**; счётчик живёт в `$FFE0BC`. При 60 кадрах в секунду\n"
      "`$0708` это полминуты, `$2A30` — три минуты.\n\n")
    p("Из 256 этапов на собственный сценарий указывают %d, остальные ведут\n"
      "на общую заглушку `$%06X`.\n\n" % (len(live), STUB))
    rows = []
    for i in live:
        ins = body(code, tgt[i])
        d6, d7, ticks, music, calls, arg7 = digest(ins)
        if len(ins) <= 1:
            continue
        bits = []
        if d7 is not None:
            bits.append("старт на тике $%04X" % d7)
        if d6 is not None:
            bits.append("повтор каждые $%04X" % d6)
        for x in arg7:
            bits.append("параметр d7 = %d" % x)
        for t in ticks:
            bits.append("на тике %d" % t)
        for m in music:
            b, c = music_target(m)
            bits.append("музыка %d = банк %s песня $%02X" % (m, b, c))
        seen = []
        for c in calls:
            if c not in seen:
                seen.append(c)
        if seen:
            bits.append("зовёт " + ", ".join(seen[:4]))
        rows.append((i, tgt[i], start[i], "; ".join(bits)))
    p("Из них непустых — %d; прочие это один `rts`.\n\n" % len(rows))
    p("| этап | миссии | сценарий | что делает |\n|---|---|---|---|\n")
    for i, t, _s, what in rows:
        p("| %d | %s | `$%06X` | %s |\n"
          % (i, ", ".join(miss.get(i, [])) or "—", t, what))

    # ── вход на карту ────────────────────────────────────────────────
    p("\n## Что делается при входе на карту\n\n")
    p("Таблица `table_stagestart` `$02CE90` устроена так же, но тела у неё\n")
    p("короткие: почти все сводятся к одному вызову. Смысл вызова виден из\n")
    p("`$0166B2`, который каждый кадр решает, кончилась ли миссия: после\n")
    p("первых `$200` тиков он смотрит перепись обоих игроков, и если у\n")
    p("второго не осталось юнитов, ставит победу — **но перед этим\n")
    p("умножает её на байт `WipeoutWinAllowed`**. Поэтому обработчик входа\n")
    p("фактически задаёт цель миссии: `EnableWipeoutWin` — «перебей всех и\n")
    p("победил», `DisableWipeoutWin` — «этого мало».\n\n")
    bodies = {}
    for t in sorted(set(start)):
        bodies[t] = body(code, t)
    plain = [t for t in bodies
             if bodies[t] == ["jsr\t(EnableWipeoutWin).l", "rts"]]
    n_plain = sum(1 for t in start if t in plain)
    p("Из 256 этапов %d обходятся ровно этим вызовом и ничем больше.\n"
      "Различных адресов %d, но различных тел всего %d: одинаковые\n"
      "восьмибайтовые кусочки размножены, а не разделены.\n\n"
      % (n_plain, len(set(start)),
         len(set(tuple(v) for v in bodies.values()))))
    p("| этап | миссии | вход | тело |\n|---|---|---|---|\n")
    for i, t in enumerate(start):
        if t in plain:
            continue
        p("| %d | %s | `$%06X` | %s |\n"
          % (i, ", ".join(miss.get(i, [])) or "—", t,
             " / ".join(x.replace("\t", " ") for x in bodies[t])))

    # ── общие тела ───────────────────────────────────────────────────
    p("\n## Общие тела: что именно происходит\n\n")
    p("Сценарий сам почти ничего не делает — он задаёт `d6` и `d7` и зовёт\n")
    p("тело из библиотеки около `$02F1D2`. У всех тел один скелет:\n\n")
    p("```\n")
    p("    d0 = StageEventTimer\n")
    p("    если d0 == 0:  сработать, когда GameTick дорастёт до d7\n")
    p("    иначе:         d0 -= 1; сработать на нуле\n")
    p("    сработав:      <действие>; StageEventTimer = d6\n")
    p("```\n\n")
    p("Действие почти всегда — **проход по карте местности**. Соглашение у\n")
    p("всех четырёх проходов одно: `d4` — маска типов, которые можно\n")
    p("менять (бит по номеру типа), `d5` — тип, в который менять.\n\n")
    p("| проход | охват |\n|---|---|\n")
    for k, v in sorted(SWEEPS.items()):
        p("| `%s` | %s |\n" % (k, v))
    p("\nНесколько тел местность не трогают, а **проверяют цель миссии**.\n"
      "У них `d7` значит не тик, а тип или число, и кладут его байтом:\n\n")
    p("| тело | смысл | где |\n|---|---|---|\n")
    p("| `LoseIfNeutralTypeGone` | не осталось нейтрального юнита типа "
      "`d7` — поражение | этапы 29, 30, 34, 36, всюду тип 50 |\n")
    p("| `AllowWinIfNeutralTypeGone` | не осталось типа `d7` — победу "
      "разрешить | этап 222, тип 68 |\n")
    p("| `WinIfHerbivoresReach` | травоядных у игрока 1 стало `>= d7` — "
      "победа | этап 51, восемь |\n")
    p("\nПоследние два стоят на картах, где обработчик входа победу\n"
      "запретил, — так и получаются цели, отличные от «перебей всех».\n")
    p("\nТела, которые зовут сценарии:\n\n")
    users = {}
    for i in live:
        for c in digest(body(code, tgt[i]))[4]:
            users.setdefault(c, []).append(i)
    p("| тело | этапы | действие |\n|---|---|---|\n")
    labels = label_index()
    for name in sorted(users, key=lambda n: -len(users[n])):
        # только библиотека сценариев, не общие процедуры движка
        if not (0x02EA00 <= labels.get(name, 0) < 0x030060):
            continue
        ins = body(code, labels[name], limit=120)
        ops = terrain_ops(ins)
        if ops:
            what = "; ".join(
                "%s -> %s (`%s`)"
                % ("типы " + ", ".join(str(t) for t in ts) if ts else "пусто",
                   " либо ".join(str(x) for x in d5) or "?", fn)
                for fn, ts, d5 in ops)
        else:
            seen = []
            for c in digest(ins)[4]:
                if c not in seen and c not in SWEEPS:
                    seen.append(c)
            what = "местность не трогает; зовёт " + ", ".join(seen[:5])
        p("| `%s` | %s | %s |\n"
          % (name, ", ".join(str(x) for x in sorted(set(users[name]))), what))
    f.close()
    print("записано: %s" % os.path.relpath(out_path, HERE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
