#!/usr/bin/env python3
"""Скрипты ИИ миссий: что именно делает противник на каждом этапе.

    make aiscripts       (нужен свежий `make split`: читает листинги)

`AiLoop` `$025282` каждый кадр уменьшает такт `$21(a5)`, и когда тот
дошёл до нуля, берёт номер этапа из байта `+$3` описания миссии и
прыгает по самоотносительной таблице `AiScriptTable` `$0252EE` —
64 записи. За ними 35 разных скриптов: часть этапов делит один на всех.

Скрипт — это список правил по приоритету, той же формы, что и всё
остальное поведение в игре: `bsr` правило, `bne` на общий выход. Правила
почти все сложены по одному шаблону:

    bsr.w   TestPhaseMask           ; работает ли правило в этой фазе
    jsr     (Player_024Fxx).l       ; можно ли её применить сейчас
    jsr     (CountEnemyUnitsNear).l ; сколько чужих рядом подходит под a6
    cmp.b   d5,d7 / bcs мимо        ; меньше d5 — не стоит того
    lea     (data_131).l,a6
    jsr     (CountOwnUnitsNear).l   ; своих под удар не подставлять
    tst.b   d7 / bne мимо
    ...                             ; анимация и оплата

Отсюда и смысл аргументов: `a6` — предикат «чем занят юнит», `d5` —
сколько таких надо набрать, `d7` — **маска фаз**, в которых правило
вообще работает (`TestPhaseMask` `$02AEB8` делает `btst` номера фазы
`$FFE0B3` в этой маске). Окно счёта — 12x6 клеток от курсора ИИ.
"""
import bisect
import collections
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

ROM = open(os.path.join(HERE, "game.gen"), "rb").read()
S16 = lambda o: struct.unpack_from(">h", ROM, o)[0]

TABLE = 0x0252EE           # AiScriptTable
BAND = (0x025000, 0x0288B6)  # полоса скриптов: сюда bsr — это общее тело

# Что делает правило. Адрес -> (имя, пояснение). Пустое пояснение значит
# «зовётся, но не разобрано» — такие печатаются как есть.
RULES = {
    0x02AF46: "открыть панель d6",
    0x0239B0: "ЯЙЦО у гнезда 1: тип из ростера миссии +$0E по d0",
    0x0239E8: "ЯЙЦО у гнезда 2: то же",
    0x02AF56: "выполнить команду d0",
    0x02AF70: "МОЛНИЯ по юниту: наборы действий d0/d1, вероятность d2",
    0x02AFF0: "в фазе 5 открыть панель ｼｾﾞﾝ",
    0x02A1FA: "фаза 1 -> 2, если рядом виден юнит нужного вида",
    0x02A478: "БУРЯ, если рядом не меньше d5 чужих по предикату a6",
    0x02A708: "ЗЕМЛЕТРЯСЕНИЕ, если рядом не меньше d5 чужих по a6",
    0x02A772: "ЗЕМЛЕТРЯСЕНИЕ, вариант со своей проверкой применимости",
    0x02A7E6: "ЗЕМЛЕТРЯСЕНИЕ, вариант с другой анимацией",
    0x02A854: "ПЕРЕДЕЛКА юнита: вариант d5, фильтр d4",
    0x02A8F2: "пауза: молчать, пока тик меньше $46(a5)",
    0x02A94E: "РАСТЕНИЕ, если вокруг набралось клеток нужного типа",
    0x02AA46: "загнать курсор ИИ обратно в карту",
    0x02AA6C: "ЗАСУХА по маскам типов местности",
    0x02AC12: "МЕТЕОРИТ",
    0x02A4EE: "ЗАСУХА, если рядом не меньше d5 чужих по a6",
    0x02B010: "РАСТЕНИЕ по типу клетки под курсором",
    0x02B044: "МОЛНИЯ по клетке под курсором",
    0x02B120: "вызвать процедуру из a0",
    0x02B1D6: "МЕТЕОРИТ по чужим, предикат $01E4A6",
    0x02B2C6: "раздать юнитам действие из набора $016854",
    0x02B2E6: "пересчитать маску запрещённых команд $FFE0DD",
    0x02B382: "снять запрет, когда денег больше порога",
}
COMMANDS = {
    "ClampMapCoords": "загнать координаты в границы карты",
    "TestIndexBitThenCall": "шлюз яиц: проверить запрет и положить вид d0",
    "AiChainP1": "цепочка фазы 1 напрямую, мимо AiPhaseStep",
    "Random": "бросок кубика",
    "Player_0248CE": "оплатить ЗАСУХУ из кошелька второго",
    "AiSetPanelAfterTick": "после тика d0 поставить панель d1",
    "AiScriptDefault": "общее тело: фаза, курсор и вся погодная лестница",
    "AiTimedEgg3": "раз в $800 тиков после $1C20 — яйцо вида 3",
    "AiTimedEgg4": "раз в $800 тиков — яйцо вида 4",
    "AiTimedEgg5": "раз в $400 тиков — яйцо вида 5",
    "DemoRandomCommands": "демо: обоим игрокам случайная команда",
    "AiHeavyRainWet": "ЛИВЕНЬ по сырым клеткам",
    "AiHeavyRainPair": "ЛИВЕНЬ, две проверки подряд",
    "AiHeavyRainP2": "ЛИВЕНЬ",
    "AiDroughtBare": "ЗАСУХА по голой земле",
    "AiDroughtGrowth": "ЗАСУХА по заросшим клеткам",
    "AiPhaseStep": "выбрать фазу и запустить её цепочку",
    "AiSweepMapCursor": "прогулка курсора по карте",
    "AiAdvanceMapCursor": "сдвинуть курсор",
    "AiPlanForPhase": "взять план текущей фазы",
}


def listing_index():
    """Адрес -> текст команды и имя метки -> адрес, из всех листингов."""
    code, lab, rlab = {}, {}, {}
    for f in glob.glob(os.path.join(HERE, "out", "asm", "m68k", "*.asm")):
        cur = None
        for ln in open(f, encoding="utf-8", errors="replace"):
            ln = ln.rstrip("\n")
            m = re.match(r"^([A-Za-z_]\w*):\s+; \$([0-9A-F]{6})", ln)
            if m:
                a = int(m.group(2), 16)
                lab[m.group(1)] = a
                rlab[a] = m.group(1)
                cur = a
                continue
            m = (re.match(r"^\s*org\s+\$([0-9A-F]{6})", ln)
                 or re.match(r"^; \$([0-9A-F]{6})$", ln.strip()))
            if m:
                cur = int(m.group(1), 16)
                continue
            if ln.startswith("\t") and cur is not None:
                code[cur] = ln.strip()
                cur = None
    return code, lab, rlab


CODE, LAB, RLAB = listing_index()
ADDRS = sorted(CODE)
CALL = re.compile(r"(?:bsr\.[wsb]|jsr)\s+\(?([A-Za-z_$][\w$]*)")
PHASED = {}


def resolve(name):
    if name in LAB:
        return LAB[name]
    m = re.match(r"^\$?([0-9A-F]{6})$", name.lstrip("$"))
    return int(m.group(1), 16) if m else None


def flow(a, seen=None, depth=0):
    """Тело скрипта по потоку: через bra, с подстановкой общих тел."""
    if seen is None:
        seen = set()
    out, cur = [], a
    while len(out) < 400:
        if cur in seen or cur not in CODE:
            break
        seen.add(cur)
        t = CODE[cur]
        m = CALL.match(t)
        if m:
            tgt = resolve(m.group(1))
            if tgt is not None and BAND[0] <= tgt < BAND[1] and depth < 4:
                out.append((cur, t, True))
                out.extend(flow(tgt, seen, depth + 1))
                # После общего тела скрипт обычно только `rts`.
            else:
                out.append((cur, t, False))
        else:
            out.append((cur, t, False))
        if t in ("rts", "rte"):
            break
        m = re.match(r"bra\.[wsb]\s+(\S+)", t)
        if m:
            nxt = resolve(m.group(1))
            if nxt is None:
                break
            cur = nxt
            continue
        i = bisect.bisect_right(ADDRS, cur)
        if i >= len(ADDRS) or ADDRS[i] - cur > 12:
            break
        cur = ADDRS[i]
    return out


IMM = re.compile(r"(?:moveq|move\.[bwl])\s+#\$?(-?[0-9A-F]+),(d[0-7])")
LEA = re.compile(r"lea\s+\(?([A-Za-z_$][\w$]*)[^,]*,a6$")
TICK = re.compile(r"andi\.l\s+#\$([0-9A-F]+),d[0-7]")


# Какие регистры правило читает. Ставятся они заранее и НЕ сбрасываются:
# соседние правила часто пользуются одним и тем же `d7`, поэтому состояние
# копится по всему скрипту, а печатается только то, что нужно этому шагу.
ARGS = {
    0x02AF46: ("d6", "d7"),
    0x02AF56: ("d0", "d7"),
    0x02AF70: ("d0", "d1", "d2", "d7"),
    0x02A478: ("a", "d5", "d7"),
    0x02A4EE: ("a", "d5", "d7"),
    0x02A708: ("a", "d5", "d7"),
    0x02A772: ("a", "d5", "d7"),
    0x02A7E6: ("a", "d5", "d7"),
    0x02A854: ("d4", "d5", "d7"),
    0x02A94E: ("d7",),
    0x02AA6C: ("d5", "d7"),
    0x02AC12: ("d7",),
    0x02B010: ("d7",),
    0x02B044: ("d7",),
    0x02B120: ("d7",),
    0x02B1D6: ("d7",),
}
ARGS_BY_NAME = {
    "AiHeavyRainWet": ("a", "d5", "d7"),
    "AiHeavyRainPair": ("a", "d5", "d7"),
    "AiHeavyRainP2": ("a", "d5", "d7"),
    "AiDroughtBare": ("a", "d5", "d7"),
    "AiDroughtGrowth": ("a", "d5", "d7"),
}


def digest(ins):
    """Шаги скрипта: вызов, пояснение, его аргументы из текущего состояния."""
    steps, st, gate = [], {}, None
    for _a, t, inlined in ins:
        if inlined:
            continue
        m = TICK.match(t)
        if m:
            gate = int(m.group(1), 16)
            continue
        m = IMM.match(t)
        if m:
            v = m.group(1)
            st[m.group(2)] = int(v, 16) if "$" in t else int(v)
            continue
        m = LEA.match(t)
        if m:
            st["a"] = m.group(1)
            continue
        m = CALL.match(t)
        if not m:
            continue
        nm = m.group(1)
        tgt = resolve(nm)
        note = RULES.get(tgt) or COMMANDS.get(nm) or ""
        keys = ARGS.get(tgt) or ARGS_BY_NAME.get(nm) or ()
        args = {k: st[k] for k in keys if k in st}
        steps.append((nm, note, args, gate, phase_gated(tgt)))
        gate = None
    return steps


def phase_gated(tgt):
    """Зовёт ли правило TestPhaseMask — тогда его d7 это маска фаз."""
    if tgt in PHASED:
        return PHASED[tgt]
    PHASED[tgt] = False
    cur, n = tgt, 0
    while cur in CODE and n < 60:
        m = CALL.match(CODE[cur])
        if m and m.group(1) == "TestPhaseMask":
            PHASED[tgt] = True
            break
        if CODE[cur] == "rts":
            break
        i = bisect.bisect_right(ADDRS, cur)
        if i >= len(ADDRS) or ADDRS[i] - cur > 12:
            break
        cur, n = ADDRS[i], n + 1
    return PHASED[tgt]


def fmt_args(args, phases):
    out = []
    for k in ("a", "d0", "d1", "d2", "d3", "d4", "d5", "d6", "d7"):
        if k not in args:
            continue
        v = args[k]
        if k == "d7" and phases and isinstance(v, int):
            ph = [str(b) for b in range(8) if v >> b & 1]
            out.append(("фаза " if len(ph) == 1 else "фазы ")
                       + (", ".join(ph) if ph else "никакие"))
            continue
        out.append("%s=%s" % ("a6" if k == "a" else k,
                              v if isinstance(v, str) else "$%X" % v))
    return ", ".join(out)


def main():
    import stagescript
    miss = stagescript.stage_to_missions()

    stages = [(TABLE + S16(TABLE + 2 * i)) & 0xFFFFFF for i in range(64)]
    users = collections.defaultdict(list)
    for i, a in enumerate(stages):
        users[a].append(i)

    out = os.path.join(HERE, "docs", "game-ai-missions.md")
    f = io.open(out, "w", encoding="utf-8", newline="\n")
    p = f.write
    p("# Скрипты ИИ миссий\n\n")
    p("Собрано `tools/aiscript.py` (`make aiscripts`) по листингам.\n\n")
    p(__doc__[__doc__.index("`AiLoop`"):].strip() + "\n\n")
    p("## Чем меряется «рядом»\n\n")
    p("`CountEnemyUnitsNear` `$05DF6E` и `CountOwnUnitsNear` `$05E060` —\n"
      "один и тот же обход окна **12x6 клеток** от курсора ИИ, различаются\n"
      "только границей по номеру слота: первый считает слоты до 107\n"
      "(`UnitSlotsP1Nest`…`UnitSlotsP1`), второй — от 148 (`UnitSlotsP2`).\n"
      "То есть правило требует набрать рядом **чужих** и не задеть\n"
      "**своих**.\n\n")
    # ── Сводка: что и в каких фазах противник вообще делает ──────────────
    byname = collections.defaultdict(lambda: [0, set(), set()])
    for a in users:
        for nm, note, args, _g, ph in digest(flow(a)):
            r = byname[(nm, note)]
            r[0] += 1
            r[1].add(a)
            if ph and "d7" in args and isinstance(args["d7"], int):
                r[2] |= {b for b in range(8) if args["d7"] >> b & 1}
    p("## Что противник умеет, по всем скриптам сразу\n\n")
    p("| шаг | вызовов | в скольких скриптах | фазы |\n|---|---|---|---|\n")
    for (nm, note), (n, scr, ph) in sorted(
            byname.items(), key=lambda kv: (-kv[1][0], kv[0][0])):
        p("| `%s` — %s | %d | %d | %s |\n"
          % (nm, note or "не разобрано", n, len(scr),
             ", ".join(str(x) for x in sorted(ph)) or "любая"))
    # ── Что из этого следует ────────────────────────────────────────────
    byphase = collections.defaultdict(set)
    thresh = collections.Counter()
    for a in users:
        for nm, note, args, _g, ph in digest(flow(a)):
            if not note or not note[0].isupper():
                continue
            if isinstance(args.get("d5"), int) and args["d5"] < 0x100:
                thresh[args["d5"]] += 1
            if ph and "d7" in args and isinstance(args["d7"], int):
                for b in range(6):
                    if args["d7"] >> b & 1:
                        byphase[b].add(note.split(",")[0].split(" по ")[0])
            else:
                byphase["любая"].add(note.split(",")[0].split(" по ")[0])
    p("\n## Что противнику открыто в какой фазе\n\n")
    p("| фаза | команды |\n|---|---|\n")
    for k in list(range(6)) + ["любая"]:
        if k in byphase:
            p("| %s | %s |\n" % (k, ", ".join(sorted(byphase[k]))))
    p("\nПорог `d5` — сколько чужих надо насчитать рядом: %s.\n\n"
      % ", ".join("%d раз%s при d5=%d"
                  % (n, "" if n % 10 == 1 and n % 100 != 11 else "а"
                     if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "",
                     v)
                  for v, n in sorted(thresh.items(), key=lambda kv: -kv[1])))
    p("## Скрипты\n\n")
    p("Этапы, которые делят один скрипт, перечислены вместе. Подписи\n"
      "миссий — по байту `+$3` их описаний.\n\n")

    for a in sorted(users, key=lambda x: (-len(users[x]), x)):
        st = users[a]
        names = []
        for s in st:
            names += miss.get(s, [])
        steps = digest(flow(a))
        p("### `$%06X` — этап%s %s\n\n"
          % (a, "ы" if len(st) > 1 else "", ", ".join(str(x) for x in st)))
        if names:
            p("Миссии: %s.\n\n" % ", ".join(sorted(set(names))))
        else:
            p("Ни одна миссия кампании на этих этапах не стоит.\n\n")
        if not steps:
            ins = [t for _a, t, _i in flow(a)]
            if len(ins) <= 1:
                p("Пусто: сразу `rts`, ИИ на этих этапах не делает ничего.\n\n")
            else:
                p("Правил нет — скрипт ничего не вызывает, только правит\n"
                  "состояние:\n\n```asm\n%s\n```\n\n"
                  % "\n".join("\t" + t for t in ins[:14]))
            continue
        p("| шаг | что | аргументы |\n|---|---|---|\n")
        for nm, note, args, gate, phases in steps:
            g = " *(по маске тика $%X)*" % gate if gate else ""
            p("| `%s` | %s%s | %s |\n"
              % (nm, note or "—", g, fmt_args(args, phases) or "—"))
        p("\n")
    f.close()
    print("записано: %s (%d скриптов на 64 этапа)"
          % (os.path.relpath(out, HERE), len(users)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
