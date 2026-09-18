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
    for f in glob.glob(os.path.join(HERE, "out", "asm", "m68k", "*.asm")):
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
        cur = addrs[i]
    return out


def digest(ins):
    d6 = d7 = None
    ticks, music, calls = [], [], []
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
        m = re.match(r"(?:bsr\.w|jsr)\s+\(?([A-Za-z_]\w*)", t)
        if m:
            calls.append(m.group(1))
    return d6, d7, ticks, music, calls


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
        d6, d7, ticks, music, calls = digest(ins)
        if len(ins) <= 1:
            continue
        bits = []
        if d7 is not None:
            bits.append("старт на тике $%04X" % d7)
        if d6 is not None:
            bits.append("повтор каждые $%04X" % d6)
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
    f.close()
    print("записано: %s" % os.path.relpath(out_path, HERE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
