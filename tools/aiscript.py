#!/usr/bin/env python3
"""Скрипты ИИ миссий: что именно делает противник на каждом этапе.

    make aiscripts       (нужен свежий `make split`: читает листинги)

`AiLoop` `$025282` зовётся раз в тик главного цикла. Раз в `$21+1`
вызовов (такт; его ставит фаза, по умолчанию 1 — через тик) он берёт
номер этапа из байта `+$3` описания миссии и прыгает по самоотносительной
таблице `AiScriptTable` `$0252EE` — **256 записей**, как и у
`table_stageframe`. За ними 82 разных скрипта: часть этапов делит один
на всех, у поединка (181…210) и этапов 59…65 скрипт пуст (`rts`).

Скрипт — это список правил по приоритету, той же формы, что и всё
остальное поведение в игре: `bsr` правило, `bne` на общий выход. Правила
почти все сложены по одному шаблону:

    bsr.w   TestPhaseMask           ; работает ли правило в этой фазе
    jsr     (CanAffordXxxP2).l      ; хватает ли денег игроку 2
    jsr     (CountEnemyUnitsNear).l ; сколько чужих в окне подходит под a6
    cmp.b   d5,d7 / bcs мимо        ; меньше d5 — не стоит того
    lea     (loc_0167AA).l,a6       ; предикат «всегда да»
    jsr     (CountOwnUnitsNear).l   ; своих в окне быть не должно
    tst.b   d7 / bne мимо
    jsr     (AiSelectUnitInWindow).l; цель та же, что в прошлый раз?
    ...                             ; эффект и оплата XxxP2

Отсюда и смысл аргументов: `a6` — предикат «чем занят юнит», `d5` —
сколько таких надо набрать, `d7` — **маска фаз**, в которых правило
вообще работает (`TestPhaseMask` `$02AEB8` делает `btst` номера фазы
`$FFE0B3` в этой маске). Окно счёта — 6x6 клеток от угла
`Player2State+$0/+$1`.

Ремейк (dyna #208) исполняет этот код как есть: `tools/aiprogram.py`
выгружает его инструкция в инструкцию. Здесь — разбор для чтения.
"""
import collections
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aiprogram as ap                                        # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BAND = (0x0254EE, 0x0288B6)        # тела скриптов; за ними — библиотека

# Что делает процедура, которую скрипт зовёт сам. ЗАГЛАВНЫМИ — команда
# игрока 2 (погода, яйцо, растение, наведение, приказ).
DESC = {
    # ход, фазы, курсор
    "AiPhaseStep": u"пересчитать фазу по переписи и деньгам, запустить цепочку фазы из таблицы a0",
    "AiPlanForPhase": u"a3 = подзапись плана для текущей фазы, без перехода",
    "AiPhase1To2OnSight": u"фаза 1 -> 2, если в окне юнит игрока 1 видов 3, 4, 5, 6, 8, 9, 10",
    "AiSweepMapCursor": u"пройти курсором столько шагов, сколько в бюджете фазы, только высматривая",
    "AiAdvanceMapCursor": u"то же без высматривания",
    "AiCursorToOwnNest": u"окно на своё гнездо",
    "AiAimAtEnemyNest": u"окно на первое гнездо игрока 1",
    "AiOnCooldown": u"пауза после пометки цели: «сработал», пока GameTick < $46",
    "ClampMapCoords": u"клетка -> угол окна: x >= 35 даёт 33, иначе max(x-2, 1)",
    "TestPhaseMask": u"фаза в маске d7?",
    "Random": u"бросок",
    "CountEnemyUnitsNear": u"сколько чужих в окне под предикатом a6 (в d7)",
    "CensusTotalP1": u"d7 = сколько юнитов у игрока 1",
    "ScanUnitsInRect": u"юниты в прямоугольнике",
    "FindEnemyInWindow": u"чужой юнит вида из маски d7 в окне, в действии из набора a5",
    "AiPickLine": u"строка реплики ИИ в a6 (косметика)",
    "DebugTrapStub": u"заглушка",
    # приказы
    "AiSetOrder": u"ПРИКАЗ игрока 2 := d6",
    "AiBrawlOnPhase5": u"в фазе 5 ПРИКАЗ := $C ﾗﾝﾄｳ",
    "AiSetOrderAfterTick": u"с тика d0 ПРИКАЗ := d1",
    "AiPickWatchedTarget": u"ближайший к своему гнезду юнит игрока 1 — цель, ПРИКАЗ := $B ﾄﾂｹﾞｷ",
    # яйца
    "AiLayEggSlot": u"ЯЙЦО слота d0 (если не под запретом); шаг не останавливает",
    "AiEggUnlessBanned": u"ЯЙЦО слота d0, если фаза 0 или платные яйца не под запретом",
    "AiHatchNest1": u"БЕСПЛАТНОЕ ЯЙЦО слота d0 у второго гнезда",
    "AiHatchNest2": u"БЕСПЛАТНОЕ ЯЙЦО слота d0 у третьего гнезда",
    "AiLayEggPreferBig": u"ЯЙЦА по нормам фазы 1 в порядке 3, 2, 1, 4, 5, 6",
    "AiEggBare4": u"ЯЙЦО слота 4 без условий",
    "AiEggBare5": u"ЯЙЦО слота 5 без условий",
    "AiLayEggIfBehind3": u"ЯЙЦО слота 3, пока своих вида 3 не больше, чем у игрока 1",
    "AiLayEggIfBehind4": u"ЯЙЦО слота 4, пока своих вида 4 не больше, чем у игрока 1",
    "AiLayEggIfBehind5": u"ЯЙЦО слота 5, пока своих вида 5 не больше, чем у игрока 1",
    "AiLayEgg3IfUnderD5": u"ЯЙЦО слота 3, пока своих вида 3 не больше d5",
    "AiLayEgg4IfUnderD5": u"ЯЙЦО слота 4, пока своих вида 4 не больше d5",
    "AiLayEgg5IfUnderD5": u"ЯЙЦО слота 5, пока своих вида 5 не больше d5",
    "AiTimedEgg3": u"приказ 9; с тика 7200 приказ 6 и раз в $800 тиков ЯЙЦО слота 3",
    "AiTimedEgg4": u"с тика 5400 приказ 8; раз в $800 тиков приказ 9 и ЯЙЦО слота 4",
    "AiTimedEgg5": u"раз в $400 тиков приказ 9 и ЯЙЦО слота 5; с тика 7200 приказ $C",
    "AiLatchPichanNear": u"защёлка $FFE0DE, если в окне ﾋﾟｰﾁｬﾝ игрока 1",
    "AiUpdateEggBan": u"запрет всех платных яиц, пока ﾋﾟｰﾁｬﾝ игрока 1 в ±4 от гнезда",
    "AiReserveMoneyEgg3": u"фаза 1: отложить на ход min(деньги игрока 1, 773, свои)",
    "AiReserveMoneyEgg4": u"фаза 1: отложить на ход min(деньги игрока 1, 1236, свои)",
    "AiUpgradeUnit": u"ПЕРЕДЕЛКА своего зреющего яйца вида из маски d4 в слот d5 (0 — УСИЛЕНИЕ)",
    # погода
    "AiHeavyRainWet": u"ЛИВЕНЬ: чужих под a6 >= d5, своих нет, зрелых трав и цветов (типы 3…7) >= 18",
    "AiHeavyRainPair": u"ДВОЙНОЙ ЛИВЕНЬ: то же, клеток типов 8, 9 меньше двух; оплата x2",
    "AiStormNearEnemies": u"БУРЯ: воды ($53) в окне 8x8 больше 23, чужих под a6 >= d5, своих нет",
    "AiStormNoOwnNear": u"БУРЯ: своих нет, клеток типов 24…26 (деревья) >= d5",
    "AiDroughtNearEnemies": u"ЗАСУХА: чужих под a6 >= d5, своих нет, клеток типов 1 и 5 >= 18",
    "AiDroughtBare": u"ДВОЙНАЯ ЗАСУХА: чужих под a6 >= d5, своих нет, типов 0…7 >= 29; оплата x2",
    "AiDroughtTypes": u"ЗАСУХА по колючкам (типы 21…23) против порога d5, без прицела",
    "AiDroughtGrowth": u"ЗАСУХА: денег >= d5 (BCD), типов 1…7 >= 8, в окне гнездо игрока 1",
    "AiDroughtType14": u"ЗАСУХА: своих под a6 >= d5, клеток типа 14 >= 18",
    "AiDroughtType16Anyway": u"ЗАСУХА: клеток типа 16 >= 21",
    "EffectDrought": u"ЗАСУХА по окну (только эффект)",
    "DroughtP2": u"оплата засухи 824, если хватает",
    "EffectStorm": u"БУРЯ по окну (только эффект)",
    "AiQuakeNearEnemies": u"ЗЕМЛЕТРЯСЕНИЕ: чужих под a6 >= d5, своих нет",
    "AiQuakeNearEnemies2": u"ЗЕМЛЕТРЯСЕНИЕ, если в окне больше 10 клеток жерла ($54)",
    "AiQuakeNearEnemies3": u"ДВОЙНОЕ ЗЕМЛЕТРЯСЕНИЕ (трещины); оплата x2",
    "AiLightningAtUnit": u"МОЛНИЯ по чужому вида d0 у своего зреющего яйца вида d1; Random <= d2 — в юнита",
    "AiLightningInList": u"МОЛНИЯ в первую клетку списка a6 с типом из маски d5",
    "AiFreeLightningInList": u"БЕСПЛАТНАЯ МОЛНИЯ в первую клетку списка a6 с типом из маски d5",
    "AiMeteorNearEnemies": u"МЕТЕОРИТ по самому плотному скоплению игрока 1 в полосе обхода",
    "AiMeteorOnEnemyUnits": u"раз за игру БЕСПЛАТНЫЙ МЕТЕОРИТ, если у ИИ <= 5 юнитов, а у игрока 1 >= 25",
    "AiMeteorChain": u"раз за игру МЕТЕОРИТ по окну",
    "AiRunChainAfterTick": u"с тика d7 раз за игру вызвать a0 (бесплатный эффект или правило)",
    "AiCallIfPhase": u"по парам клеток a1: окно туда и вызвать a0, до первого «сработал»",
    # растения, наведение
    "AiPlantOnTerrain": u"РАСТЕНИЕ колючка у гнезда игрока 1, случайное направление",
    "AiPlantInList": u"РАСТЕНИЕ d6 в первую клетку списка a6 с типом из маски d5",
    "AiGuideUnitAt": u"НАВЕДЕНИЕ юнита клетки (d2,d3) под a6 в (d0,d1), если не ранен",
    # общие тела
    "AiScriptDefault": u"общее тело: фаза, запрет яиц, погодная лестница, бесплатные яйца",
    "AiChainP1": u"цепочка фазы 1 напрямую",
    "AiChainP3": u"цепочка фазы 3 напрямую",
    "DemoRandomCommands": u"демо-бой: случайные бесплатные яйца обоим",
    "CheckSpeciesGone": u"демо-бой: вид исчез — бесплатное яйцо",
}

# Какие регистры процедура читает (порядок печати — как в ARG_ORDER).
ARGS = {
    "AiPhaseStep": ("a0",), "AiSetOrder": ("d6", "d7"), "AiLayEggSlot": ("d0", "d7"),
    "AiSetOrderAfterTick": ("d0", "d1"), "AiEggUnlessBanned": ("d0",),
    "AiHatchNest1": ("d0",), "AiHatchNest2": ("d0",), "AiPickWatchedTarget": ("d7",),
    "AiUpgradeUnit": ("d4", "d5", "d7"), "AiGuideUnitAt": ("a6", "d0", "d1", "d2", "d3", "d7"),
    "AiLightningAtUnit": ("d0", "d1", "d2", "d7"), "AiPlantInList": ("a6", "d5", "d6", "d7"),
    "AiLightningInList": ("a6", "d5", "d7"), "AiFreeLightningInList": ("a6", "d5", "d7"),
    "AiCallIfPhase": ("a0", "a1", "d7"), "AiRunChainAfterTick": ("a0", "d7"),
    "AiDroughtTypes": ("d5", "d7"), "AiDroughtGrowth": ("d5", "d7"),
    "AiDroughtType14": ("a6", "d5", "d7"), "AiDroughtType16Anyway": ("d7",),
    "AiStormNoOwnNear": ("d5", "d7"), "AiLayEgg3IfUnderD5": ("d5", "d7"),
    "AiLayEgg4IfUnderD5": ("d5", "d7"), "AiLayEgg5IfUnderD5": ("d5", "d7"),
    "FindEnemyInWindow": ("a5", "d7"), "CountEnemyUnitsNear": ("a6",),
    "ClampMapCoords": ("d0", "d1"), "TestPhaseMask": ("d7",),
}
for _n in ("AiHeavyRainWet", "AiHeavyRainPair", "AiStormNearEnemies", "AiDroughtNearEnemies",
           "AiDroughtBare", "AiQuakeNearEnemies", "AiQuakeNearEnemies2", "AiQuakeNearEnemies3"):
    ARGS[_n] = ("a6", "d5", "d7")
for _n in ("AiPlantOnTerrain", "AiMeteorNearEnemies", "AiMeteorChain", "AiLayEggIfBehind3",
           "AiLayEggIfBehind4", "AiLayEggIfBehind5"):
    ARGS[_n] = ("d7",)
PHASED = {n for n, a in ARGS.items() if "d7" in a} - {
    "AiPickWatchedTarget", "AiRunChainAfterTick", "FindEnemyInWindow"}
PHASED.add("AiPickWatchedTarget")
ARG_ORDER = ("a0", "a1", "a5", "a6", "d0", "d1", "d2", "d3", "d4", "d5", "d6", "d7")
# d5 у этих правил — маска типов местности, а не порог
TYPE_MASK_D5 = {"AiPlantInList", "AiLightningInList", "AiFreeLightningInList"}
# d0/d1/d4 у этих — маска видов (бит n — вид n)
SPECIES_MASK = {("AiLightningAtUnit", "d0"), ("AiLightningAtUnit", "d1"),
                ("AiUpgradeUnit", "d4"), ("FindEnemyInWindow", "d7")}

# Что таблица шагов не передаёт: особые скрипты, разобранные по коду.
SPECIAL = {
    0x025F9E: u"Приказ 9 (ﾊﾝｼｮｸ) навсегда; ни яиц, ни погоды.",
    0x0260AC: u"**Зеркальный противник.** Каждый ход деньги ИИ := 199999; приказ "
              u"игрока 1 зеркалится ((d + 4) & 7, $B -> $C), точка сбора -> 39 − x, окно -> "
              u"34 − x. Команда игрока 1 из `ActiveEffectCode` `$FFE0E3` (2…7 погода, 8…13 "
              u"яйца, 14…17 растения) бесплатно повторяется в зеркальной клетке по таблице "
              u"переходов `data_187b`; полив (код 1) не повторяется. Без команды — обычный "
              u"`AiPhaseStep`.",
    0x02583A: u"На тике 1 — засуха на своём гнезде (`DroughtP2` платит, только если "
              u"хватает), дальше обычный скрипт.",
    0x0262D0: u"Приказ 9, деньги 199999. Молния по первой клетке-дереву (типы 24…26) "
              u"из `data_187d`; начало списка сдвигается на 2 x (ｱﾛ + ﾃｨﾗﾉ у ИИ). Ударила — "
              u"трава (тип 1) на первую клетку типа 18 того же списка; `StageEventTimer` := 30.",
    0x025C1C: u"Без фазовой машины: до тика 10800 цепочка фазы 1, потом фазы 3; нормы — "
              u"из подзаписи текущей фазы.",
    0x02652C: u"`$FFE11E` := Random & 1 — платные яйца идут к первому или второму гнезду.",
    0x02832A: u"Демо-бой: `DemoRandomCommands` — бесплатные случайные яйца обоим игрокам.",
    0x028330: u"Демо-бой: `CheckSpeciesGone` — вид исчез у игрока, бесплатное яйцо ему.",
}

# Числа в ОЗУ, которые скрипты сравнивают, — по-человечески.
RAM = {0xFFE05C: u"GameTick", 0xFF9CDC: u"деньги ИИ", 0xFF9C86: u"деньги игрока 1",
       0xFFE0D8: u"$FFE0D8"}
for _i in range(6):
    RAM[0xFFE086 + _i] = u"видов %d у игрока 1" % (_i + 1)
    RAM[0xFFE096 + _i] = u"своих вида %d" % (_i + 1)
NEG = {"bcs": u">=", "bcc": u"<", "bhi": u"<=", "bls": u">", "beq": u"!=", "bne": u"==",
       "blt": u">=", "bge": u"<", "bgt": u"<=", "ble": u">"}
POS = {"bcs": u"<", "bcc": u">=", "bhi": u">", "bls": u"<=", "beq": u"==", "bne": u"!=",
       "blt": u"<", "bge": u">=", "bgt": u">", "ble": u"<="}


def body(entry):
    u"""Инструкции самого скрипта: по ветвлениям внутри полосы, без вызовов."""
    seen, work = {}, [entry]
    while work:
        a = work.pop()
        while a is not None and a not in seen:
            x = ap.Ins(a)
            seen[a] = x
            for o in x.ops:
                if o[0] == "to" and x.mn not in ("bsr", "jsr"):
                    if BAND[0] <= o[1] < BAND[1] and not ap.is_native(o[1]):
                        work.append(o[1])
            if x.mn in ap.END:
                break
            a = ap.after(a)
    return [seen[a] for a in sorted(seen)]


def callee(x):
    if x.mn in ("bsr", "jsr") and x.ops[0][0] == "to":
        return ap.name_of(x.ops[0][1])
    return None


def value_name(o, src):
    u"""Что сравнивается: имя ячейки ОЗУ, регистр с известным источником."""
    if o[0] == "abs":
        return RAM.get(o[1], u"$%06X" % o[1])
    if o[0] == "#":
        return u"%d" % o[1] if abs(o[1]) < 10 else u"$%X" % o[1]
    if o[0] == "d":
        return src.get(o[1], u"d%d" % o[1])
    return None


def guard_text(ins, i, src):
    u"""Условие ветвления ins[i] (b<cc>) как «истина — переход»; None — не умею."""
    br = ins[i]
    j = i - 1
    if j < 0:
        return None
    p = ins[j]
    if p.mn in ("andi",) and p.ops[1][0] == "d":
        what = src.get(p.ops[1][1], u"d%d" % p.ops[1][1])
        rel = {"bne": u"!= 0", "beq": u"== 0"}.get(br.mn)
        return rel and u"%s & $%X %s" % (what, p.ops[0][1], rel)
    if p.mn in ("cmpi", "cmp") and br.mn in POS:
        a, b = value_name(p.ops[1], src), value_name(p.ops[0], src)
        if a and a.startswith(u"деньги") and p.ops[0][0] == "#":
            b = u"%X" % p.ops[0][1]           # деньги — BCD: цифры как есть
        return a and b and u"%s %s %s" % (a, POS[br.mn], b)
    if p.mn == "btst" and p.ops[0][0] == "#":
        what = value_name(p.ops[1], src) or u"?"
        rel = {"bne": u"взведён", "beq": u"снят"}.get(br.mn)
        return rel and u"бит %d %s %s" % (p.ops[0][1], what, rel)
    if p.mn == "tst":
        what = value_name(p.ops[0], src) or u"?"
        rel = {"bne": u"!= 0", "beq": u"== 0"}.get(br.mn)
        return rel and u"%s %s" % (what, rel)
    return None


def negate(t):
    for a, b in ((u" != ", u" == "), (u" == ", u" != "), (u" >= ", u" < "), (u" <= ", u" > "),
                 (u" < ", u" >= "), (u" > ", u" <= "), (u"взведён", u"снят"), (u"снят", u"взведён")):
        if a in t:
            return t.replace(a, b, 1)
    return u"не (%s)" % t


def digest(entry):
    u"""Шаги скрипта: (вызов, условие, аргументы, в обходе ли)."""
    ins = body(entry)
    pos = {x.a: i for i, x in enumerate(ins)}
    guards = collections.defaultdict(list)       # адрес -> условия
    loops = []
    src = {}                                     # dN -> что в нём лежит
    for i, x in enumerate(ins):
        if x.mn == "move" and x.ops[0][0] == "abs" and x.ops[1][0] == "d":
            src[x.ops[1][1]] = RAM.get(x.ops[0][1], u"$%06X" % x.ops[0][1])
        elif x.mn in ("moveq", "move") and x.ops[1][0] == "d":
            src.pop(x.ops[1][1], None)
        if x.mn == "dbf":
            loops.append((x.ops[1][1], x.a))
            continue
        if x.mn not in POS or x.ops[0][0] != "to":
            continue
        prev = ins[i - 1] if i else None
        prev2 = ins[i - 2] if i > 1 else None
        if prev is not None and (callee(prev) or prev.mn == "movem" and prev2 is not None
                                 and callee(prev2)):
            continue                              # «сработало — выход»
        t = x.ops[0][1]
        if t <= x.a:
            continue
        cond = guard_text(ins, i, src)
        if not cond:
            p = ins[i - 1]
            cond = u"`%s` / `%s`" % (p.text, x.mn)
        for y in ins[i + 1:]:
            if y.a >= t:
                break
            guards[y.a].append(negate(cond) if not cond.startswith(u"`") else u"не " + cond)
        # «иначе»: перед целью стоит bra дальше — там условие истинно
        k = pos.get(t)
        if k and ins[k - 1].mn == "bra" and ins[k - 1].ops[0][1] > t:
            for y in ins[k:]:
                if y.a >= ins[k - 1].ops[0][1]:
                    break
                guards[y.a].append(cond)
    steps, regs = [], {}
    for x in ins:
        if x.mn in ("moveq", "move") and x.ops[0][0] == "#" and x.ops[1][0] == "d":
            regs["d%d" % x.ops[1][1]] = x.ops[0][1] & 0xFFFFFFFF
        elif x.mn == "move" and x.ops[0][0] == "abs" and x.ops[1][0] == "d":
            regs["d%d" % x.ops[1][1]] = RAM.get(x.ops[0][1], u"$%06X" % x.ops[0][1])
        elif x.mn == "lea" and x.ops[1][0] == "a":
            regs["a%d" % x.ops[1][1]] = ap.name_of(x.ops[0][1]) if x.ops[0][0] == "abs" else "?"
        n = callee(x)
        if n is None:
            if x.mn == "move" and x.ops[1] in (["disp", 15, 4], ["abs", 0xFF9CE9]) \
                    and x.ops[0][0] == "#":
                steps.append((u"приказ := $%X" % x.ops[0][1], u"ПРИКАЗ игрока 2 прямо", {},
                              guards.get(x.a, []), in_loop(x.a, loops)))
            elif x.mn == "move" and x.ops[1] in (["disp", 2, 4], ["disp", 2, 1],
                                                 ["abs", 0xFF9CDC]) and x.ops[0][0] == "#":
                steps.append((u"деньги := %X" % x.ops[0][1], u"деньги ИИ прямо (BCD)", {},
                              guards.get(x.a, []), in_loop(x.a, loops)))
            continue
        args = {k: regs[k] for k in ARGS.get(n, ()) if k in regs}
        steps.append((n, DESC.get(n, u""), args, guards.get(x.a, []), in_loop(x.a, loops)))
    return steps


def in_loop(a, loops):
    return any(lo <= a < hi for lo, hi in loops)


def fmt_args(name, args):
    out = []
    for k in ARG_ORDER:
        if k not in args:
            continue
        v = args[k]
        if k == "d7" and name in PHASED and isinstance(v, int):
            if v & 0x3F == 0x3F:
                out.append(u"любая фаза")
                continue
            ph = [str(b) for b in range(6) if v >> b & 1]
            out.append((u"фаза " if len(ph) == 1 else u"фазы ")
                       + (u", ".join(ph) if ph else u"никакие"))
            continue
        if isinstance(v, int) and k == "d5" and name in TYPE_MASK_D5:
            out.append(u"типы " + u", ".join(str(b) for b in range(32) if v >> b & 1))
            continue
        if isinstance(v, int) and (name, k) in SPECIES_MASK:
            out.append(u"%s: виды %s" % (k, u", ".join(str(b) for b in range(32) if v >> b & 1)))
            continue
        if isinstance(v, int):
            v = u"$%X" % v if v > 9 else u"%d" % v
        out.append(u"%s=%s" % (k, v))
    return u", ".join(out)


def main():
    import stagescript
    miss = stagescript.stage_to_missions()
    users = collections.defaultdict(list)
    for st in range(256):
        users[ap.script_entry(st)].append(st)

    out = os.path.join(HERE, "docs", "game-ai-missions.md")
    f = io.open(out, "w", encoding="utf-8", newline="\n")
    p = f.write
    p(u"# Скрипты ИИ миссий\n\n")
    p(u"Собрано `tools/aiscript.py` (`make aiscripts`) по листингам.\n\n")
    p(u"СГЕНЕРИРОВАНО — правки затираются, меняйте инструмент.\n"
      u"Вывод, который надо сохранить, пишите в соседний, ручной файл.\n\n")
    p(__doc__[__doc__.index("`AiLoop`"):].strip() + u"\n\n")
    p(u"## Чем меряется «рядом»\n\n"
      u"`CountEnemyUnitsNear` `$05DF6E` и `CountOwnUnitsNear` `$05E060` —\n"
      u"один и тот же обход окна **6x6 клеток**, различаются только границей по\n"
      u"номеру слота: первый считает слоты до 107 (`UnitSlotsP1Nest`…`UnitSlotsP1`),\n"
      u"второй — от 148 (`UnitSlotsP2`). То есть правило требует набрать рядом\n"
      u"**чужих** и не задеть **своих**. Шесть на шесть **клеток**: внутренний цикл\n"
      u"делает шесть шагов по два байта, потому что в карте юнитов два байта на\n"
      u"клетку, а в конце ряда прибавляет `$44`, что вместе с пройденными\n"
      u"двенадцатью даёт ровно 80 — ширину ряда. Угол окна — `Player2State+$0/+$1`,\n"
      u"его ставит `ClampMapCoords` `$006ABE`: x >= 35 даёт 33, иначе max(x-2, 1).\n\n")
    p(u"## Поправки к прежнему разбору (dyna #208)\n\n"
      u"- Таблиц **по 256 записей**, не по 64: `AiScriptTable` и `AiPlanTable`, как\n"
      u"  `table_stageframe`. Разных скриптов 82, записей плана 69. Прежний разбор\n"
      u"  покрывал только этапы 0…63 — сюжет и тренировку.\n"
      u"- `$F(Player2State)` (`$FF9CE9`) — не «панель», а **приказ игрока 2**: его\n"
      u"  читает поведение юнитов через `GetPlayerOrder` `$018CD6`. 0…7 — направление,\n"
      u"  8 ｼﾝｹﾞｷ, 9 ﾊﾝｼｮｸ, $A ｼｭｳｺﾞｳ, $B ﾄﾂｹﾞｷ, $C ﾗﾝﾄｳ. Отсюда `AiSetOrder`\n"
      u"  (было `AiOpenPanel`), `AiSetOrderAfterTick`, `AiBrawlOnPhase5` (в фазе 5 —\n"
      u"  $C, а не «ｼｾﾞﾝ»).\n"
      u"- `AiLayEggSlot` (было `AiRunCommand`) — яйцо слота ростера d0. Все правила\n"
      u"  яиц возвращают Z: яйцо ход не занимает, скрипт идёт дальше.\n"
      u"- `AiPickLine`/`AiCurrentLine` (были `AiPickChain`/`AiCurrentChain`) выбирают\n"
      u"  **строку реплики** ИИ по соотношению сил, а не цепочку правил.\n"
      u"- `AiHeavyRainPair` срабатывает, когда клеток типов 8, 9 **меньше** двух.\n"
      u"- Бесплатные `AiHatchNest1/2` кладут у **второго и третьего** гнезда\n"
      u"  (`Player2State+$12/+$14`); платные яйца — у первого (`+$10`).\n"
      u"- `$FFE0DD` — флаг «все платные яйца под запретом», а не маска команд\n"
      u"  (`AiUpdateEggBan`, было `AiUpdateBanMask`; `AiEggUnlessBanned`, было\n"
      u"  `TestIndexBitThenCall`). Разрешённые команды миссии ИИ не смотрит.\n"
      u"- `AiReserveMoneyEgg3/4` (были `AiSpendMatchingPlayer1`/`AiUnbanOnMoney`) в\n"
      u"  фазе 1 откладывают на ход часть денег ИИ; `AiLoop` возвращает их в конце\n"
      u"  кадра.\n"
      u"- `AiLightningInList`, `AiFreeLightningInList`, `AiPlantInList` (были\n"
      u"  `...AtCursor`) идут по списку клеток a6, а не бьют под курсор; вторая\n"
      u"  молния не платит.\n"
      u"- Стартовая фаза — 1 (`InitAiState` ставит `$2D`=1).\n\n")

    byname = collections.defaultdict(lambda: [0, set(), set()])
    for a in users:
        for n, note, args, _g, _l in digest(a):
            r = byname[(n, note)]
            r[0] += 1
            r[1].add(a)
            if n in PHASED and isinstance(args.get("d7"), int):
                r[2] |= {b for b in range(8) if args["d7"] >> b & 1}
    p(u"## Что противник умеет, по всем скриптам сразу\n\n"
      u"Считаются вызовы из самих скриптов; общее тело `AiScriptDefault` — один\n"
      u"скрипт, хотя его зовут многие.\n\n")
    p(u"| шаг | вызовов | в скольких скриптах | фазы |\n|---|---|---|---|\n")
    for (n, note), (c, scr, ph) in sorted(byname.items(), key=lambda kv: (-kv[1][0], kv[0][0])):
        p(u"| `%s` — %s | %d | %d | %s |\n"
          % (n, note or u"не разобрано", c, len(scr),
             u", ".join(str(x) for x in sorted(ph)) or u"любая"))

    byphase = collections.defaultdict(set)
    for a in users:
        for n, note, args, _g, _l in digest(a):
            head = note.split(u":")[0].split(u",")[0]
            if not note or not any(ch.isupper() for ch in head[:6]):
                continue
            kind = re.sub(u"^(ДВОЙН\\w+ |БЕСПЛАТН\\w+ )", u"", head).split(u" ")[0]
            if n in PHASED and isinstance(args.get("d7"), int):
                for b in range(6):
                    if args["d7"] >> b & 1:
                        byphase[b].add(kind)
            else:
                byphase[u"любая"].add(kind)
    p(u"\n## Что противнику открыто в какой фазе\n\n| фаза | команды |\n|---|---|\n")
    for k in list(range(6)) + [u"любая"]:
        if k in byphase:
            p(u"| %s | %s |\n" % (k, u", ".join(sorted(byphase[k]))))

    p(u"\n## Скрипты\n\n"
      u"Этапы, которые делят один скрипт, перечислены вместе; подписи миссий — по\n"
      u"байту `+$3` их описаний. «Условие» — ветвление в самом скрипте, под которым\n"
      u"стоит шаг (без него шаг идёт всегда, пока выше ничего не сработало);\n"
      u"«обход» — шаг внутри цикла `dbf` по клеткам карты.\n\n")
    for a in sorted(users, key=lambda x: (-len(users[x]), x)):
        st = users[a]
        names = []
        for s in st:
            names += miss.get(s, [])
        steps = digest(a)
        stages = u", ".join(str(x) for x in st) if len(st) < 12 else \
            u"%s … %s (%d)" % (u", ".join(str(x) for x in st[:6]), st[-1], len(st))
        p(u"### `$%06X` — этап%s %s\n\n" % (a, u"ы" if len(st) > 1 else u"", stages))
        if names:
            p(u"Миссии: %s.\n\n" % u", ".join(sorted(set(names))))
        else:
            p(u"Ни одна миссия на этих этапах не стоит.\n\n")
        if not steps:
            if ap.CODE.get(a) == "rts":
                p(u"Пусто: сразу `rts`, ИИ на этих этапах не делает ничего.\n\n")
            else:
                p(u"Вызовов нет, только правка состояния:\n\n```asm\n%s\n```\n\n"
                  % u"\n".join(u"\t" + x.text for x in body(a)[:14]))
            if a in SPECIAL:
                p(SPECIAL[a] + u"\n\n")
            continue
        if a in SPECIAL:
            p(SPECIAL[a] + u"\n\n")
        p(u"| шаг | что | условие | аргументы |\n|---|---|---|---|\n")
        for n, note, args, g, loop in steps:
            cond = u"; ".join(g)
            if loop:
                cond = (cond + u"; " if cond else u"") + u"обход"
            p(u"| `%s` | %s | %s | %s |\n" % (n, note or u"—", cond or u"—",
                                             fmt_args(n, args) or u"—"))
        p(u"\n")
    f.close()
    print(u"записано: %s (%d скриптов на 256 этапов)" % (os.path.relpath(out, HERE), len(users)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
