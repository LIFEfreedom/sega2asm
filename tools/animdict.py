#!/usr/bin/env python3
u"""Словарь анимаций юнита: кто ставит каждый номер байта `+$7` и что он показывает.

    make animdict

Пишет `docs/game-animations.md` и листы `out/<имя>/anim/dict_<вид>.png` —
по строке на номер, кадры стороны 4 (морда) слева направо.

## Как собрано

Номер анимации лежит в байте `+$7` записи юнита. Его ставят обычные
`move.b #$XX,$7(aN)`, и почти всегда рядом, в тех же нескольких командах,
ставится и действие `+$15`. Инструмент проходит листинг банков `$01` и
`$02` (там вся логика юнитов; две записи в `+$7` за их пределами —
экраны банков `$03` и `$04`, чужие структуры) и собирает для каждого
номера: адрес записи, ближайшую именованную процедуру выше неё и
действие, записанное в тот же регистр в пределах четырнадцати строк.

Имя процедуры — ближайшая метка без `loc_`. Где процедура не названа,
запись приписывается соседу сверху; адрес при этом всегда точный.

Номера `$00`…`$03` берутся из общей таблицы `CommonFrameTable` и
одинаковы у всех видов, `$04`…`$20` — из набора вида. Поэтому смысл
номера здесь — смысл у шести видов игрока: у гнезда или падали те же
номера значат своё.
"""
import collections
import glob
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import gfx                                                   # noqa: E402
import unitgfx                                               # noqa: E402
import unitanim                                              # noqa: E402
from paths import OUT as out_path                            # noqa: E402

FRAME = unitanim.FRAME
UNIT_BANKS = (0x010000, 0x030000)
SPECIES = ((5, "pacific", u"ｽﾃｺﾞ"), (6, "fat", u"ﾄﾘｹﾗ"),
           (7, "defender", u"ｱﾛ"), (8, "hunter", u"ﾃｨﾗﾉ"),
           (9, "scout", u"ﾌﾟﾃﾗ"), (10, "egg_eater", u"ﾋﾟｰﾁｬﾝ"))
SAMPLE = 7                 # ｱﾛ: по нему в таблице кадры и длительности
FACE = 4                   # сторона 4 — морда

# что номер значит у шести видов; только то, что подтверждено кодом
READ = {
    0x00: u"пусто: общий кадр 0 без точек — яйцо, ещё не вышедшее из родителя",
    0x01: u"горит: пламя общего банка. Смерть на лаве и в огне "
          u"(`UnitDieFlame`), от бедствий",
    0x02: u"исчезает всплеском (общий банк): смерть на плитках `$53`/`$54` "
          u"(`UnitDieSplash`), смерть гнезда",
    0x03: u"хлопок «POW» (общий банк), дальше `$00`: вылупление и смерть на "
          u"клетке с битом 5 плитки (`UnitDiePop`)",
    0x04: u"кладка: яйцо переливается (общий банк); у гнезда — покой "
          u"(`EnterNestIdle`)",
    0x05: u"яйцо лежит, стадия 1 (общий банк); у декораций — поза покоя",
    0x06: u"яйцо шевелится, стадия 2; у гнезда — искра",
    0x07: u"яйцо вот-вот вылупится, стадия 3",
    0x08: u"яйцо летит: бросок `TossUnitToCell` и роды",
    0x0A: u"**покой**, прямые стороны",
    0x0B: u"**покой**, диагонали (вид в три четверти)",
    0x0C: u"смерть декорации; падаль доедена",
    0x0D: u"**еда**: пастись, доедать падаль, съесть соседа",
    0x0E: u"реакция на рану, паника",
    0x0F: u"жертва удара, отброшена (по таблице нападающего)",
    0x10: u"жертва удара, отброшена в другую сторону",
    0x11: u"жертва удара, крутится в воздухе; оглушение бедствием",
    0x12: u"кружится на месте: после броска",
    0x13: u"**удар**, степень 1; топтание",
    0x14: u"**удар**, степень 2 — самая частая",
    0x15: u"**удар**, степень 3",
    0x16: u"**удар**, редкий исход; её же ставят полное лечение "
          u"`GrazeHealFull` и `EnterWalkPause`",
    0x17: u"оглушён, лежит",
    0x18: u"**шаг** в соседнюю клетку, прямые стороны",
    0x19: u"**шаг**, диагонали",
    0x1A: u"**смерть** — обычная для ящеров",
    0x1B: u"поза раны: кадров нет, сразу перетекает в `$0A`",
    0x1C: u"роды: родитель стоит, пока яйцо рядом",
    0x1D: u"превращение в другой вид",
    0x1E: u"ожидание взросления",
    0x1F: u"пара: двое встают друг к другу",
    0x20: u"лежит мёртвый",
}


def listing():
    return sorted(glob.glob(out_path("asm", "m68k", "*.asm")))


LABEL = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s+;\s+\$([0-9A-F]{6})")
ADDR = re.compile(r"^; \$([0-9A-F]{6})")
WRITE = re.compile(r"move\.b\s+(\S+),\$7\((a[0-6])\)")


def setters():
    u"""({номер: [(адрес, процедура, действие)]}, [(адрес, процедура, источник)])."""
    direct, indirect = collections.defaultdict(list), []
    for path in listing():
        lines = io.open(path, encoding="utf-8", errors="replace").read()
        lines = lines.split("\n")
        proc, addr = "?", None
        for i, l in enumerate(lines):
            m = LABEL.match(l)
            if m:
                addr = int(m.group(2), 16)
                if not m.group(1).startswith("loc_"):
                    proc = m.group(1)
                continue
            m = ADDR.match(l)
            if m:
                addr = int(m.group(1), 16)
                continue
            m = WRITE.search(l)
            if not m or addr is None:
                continue
            if not UNIT_BANKS[0] <= addr < UNIT_BANKS[1]:
                continue
            src, reg = m.group(1), m.group(2)
            if not src.startswith("#$"):
                indirect.append((addr, proc, src))
                continue
            act = None
            pat = re.compile(r"move\.b\s+#\$([0-9A-F]{2}),\$15\(" + reg + r"\)")
            best = None
            for j in range(max(0, i - 14), min(len(lines), i + 14)):
                mm = pat.search(lines[j])
                if mm and (best is None or abs(j - i) < best):
                    best, act = abs(j - i), int(mm.group(1), 16)
            direct[int(src[2:], 16)].append((addr, proc, act))
    return direct, indirect


def anim_steps(t, an, side=FACE):
    try:
        seq, loop, ok, nxt = unitanim.steps(unitgfx.script_addr(t, an, side),
                                            unitanim.entry_map(t))
        ok = ok and unitanim.frames_fit(t, seq)
    except Exception:
        return None
    return (seq, loop, nxt) if ok else None


def contact_sheet(t, path, cols=16):
    u"""Строка — номер `$00`…`$20`, кадры стороны 4 без повторов подряд."""
    pal = unitgfx.row_palette(unitgfx.palette_row(t))
    rows = []
    for an in range(0x21):
        got = anim_steps(t, an)
        words = []
        for w, _d in (got[0] if got else []):
            if not words or words[-1] != w:
                words.append(w)
        rows.append(words[:cols])
    w, h = cols * FRAME, len(rows) * FRAME
    img = [[(40, 40, 48, 255)] * w for _ in range(h)]
    cache = {}
    for r, words in enumerate(rows):
        for c, word in enumerate(words):
            if word not in cache:
                cache[word] = unitanim.frame_pixels(t, word, pal)
            f = cache[word]
            if f is None:
                continue
            for y in range(FRAME):
                row = img[r * FRAME + y]
                for x in range(FRAME):
                    if f[y][x] is not None:
                        row[c * FRAME + x] = f[y][x] + (255,)
    gfx.png(path, w, h, img, alpha=True)


def frames_brief(t, an):
    got = anim_steps(t, an)
    if got is None:
        return u"—"
    seq, loop, nxt = got
    if not seq:
        return u"кадров нет, дальше `$%02X`" % nxt[0] if nxt else u"кадров нет"
    durs = u", ".join(u"%d" % d for _w, d in seq[:8])
    more = u"…" if len(seq) > 8 else u""
    tail = (u", дальше `$%02X`" % nxt[0]) if nxt else \
        (u", петля" if loop is not None else u"")
    return u"%d: %s%s%s" % (len(seq), durs, more, tail)


def main():
    direct, indirect = setters()
    out = out_path("anim")
    os.makedirs(out, exist_ok=True)
    for t, folder, _name in SPECIES:
        contact_sheet(t, os.path.join(out, "dict_%s.png" % folder))

    doc = os.path.join(HERE, "docs", "game-animations.md")
    f = io.open(doc, "w", encoding="utf-8", newline="\n")
    p = f.write
    p(u"# Анимации юнита: словарь байта `+$7`\n\n")
    p(u"Собрано `tools/animdict.py` (`make animdict`).\n\n")
    p(u"СГЕНЕРИРОВАНО — правки затираются, меняйте инструмент.\n\n")
    p(u"Номер анимации лежит в байте `+$7` записи юнита. В банках `$01` и\n"
      u"`$02` его пишут **%d раз константой** и %d раз из регистра или\n"
      u"таблицы; различных констант %d. Кадры по номерам —\n"
      u"`out/<имя>/anim/dict_<вид>.png`.\n\n"
      % (sum(len(v) for v in direct.values()), len(indirect), len(direct)))
    p(u"Смысл дан для шести видов игрока. `$00`…`$03` общие для всех видов,\n"
      u"с `$04` начинается набор вида, и у гнезда или падали тот же номер\n"
      u"значит своё — это видно по тому, КТО его ставит.\n\n")

    p(u"## Все номера\n\n")
    p(u"«Кадры» — у ｱﾛ на стороне 4: сколько и длительности в тактах.\n"
      u"«Действие» — что пишется в `+$15` рядом.\n\n")
    p(u"| номер | что это | кто ставит | кадры |\n|---|---|---|---|\n")
    for an in range(0x21):
        who = []
        for addr, proc, act in direct.get(an, []):
            who.append(u"`%s` `$%06X`%s"
                       % (proc, addr,
                          (u", действие `$%02X`" % act) if act is not None
                          else u""))
        p(u"| `$%02X` | %s | %s | %s |\n"
          % (an, READ.get(an, u"—"), u"; ".join(who) or u"только косвенно",
             frames_brief(SAMPLE, an)))

    p(u"\n## Покой и шаг\n\n")
    p(u"Вернуть юнита в покой — это `EnterWalkState` `$01A404`. Он выбирает\n"
      u"позу по байту `+$C`: гнездо (вид 0) получает `$04`, декорации и\n"
      u"неигровые виды (бит 5) — `EnterIdleFacing` с `$05`, все прочие —\n"
      u"`EnterWalkStateNormal` `$01A454`: действие `$0B` и анимация `$0A` на\n"
      u"чётной стороне, `$0B` на нечётной. Шаг в соседнюю клетку ставит\n"
      u"`EnterStepState` `$01A238`: действие `$0E` и `$18` или `$19` по той же\n"
      u"чётности. Так у покоя и шага появляются диагонали — отдельными\n"
      u"номерами, а не ячейками внутри одной анимации.\n\n")

    p(u"## Удар\n\n")
    p(u"Анимацию удара выбирает `ResolveCombat` `$01B1AE`, и степеней у неё\n"
      u"четыре. Сначала бросок против байта `+$AC` блока параметров\n"
      u"(`+$AD`, если у юнита взведён бит 5 `+$11`): выпало меньше — редкий\n"
      u"исход, `$16`. Иначе второй бросок из 256:\n\n")
    p(u"| бросок | анимация нападающего | его действие | действие жертвы "
      u"| доля |\n"
      u"|---|---|---|---|---|\n"
      u"| 0…`$60` | `$13` | `$10` | `$14` | 97/256, 38%% |\n"
      u"| `$61`…`$DC` | `$14` | `$11` | `$15` | 124/256, 48%% |\n"
      u"| `$DD`…`$FF` | `$15` | `$12` | `$16` | 35/256, 14%% |\n"
      u"| редкий исход | `$16` | `$13` | `$17` | по `+$AC` вида |\n\n")
    p(u"Анимацию жертвы берут из дескриптора вида НАПАДАЮЩЕГО: байт\n"
      u"`+4 + степень`, и ещё `+4`, если жертва смотрит на сторону 2, 3, 6\n"
      u"или 7; к нему прибавляется `$0F`. Выходит `$0F`, `$10` или `$11` —\n"
      u"то есть как далеко и куда отлетит жертва, решает тот, кто бьёт.\n\n")

    p(u"## Смерть\n\n")
    p(u"`UnitDie` `$01A8AE` ставит `$1A` — это и есть смерть ящера. Иначе\n"
      u"только в трёх случаях: гнездо и юнит в действии из списка\n"
      u"`$016894` исчезают всплеском `$02`, декорации (бит 5 `+$C`) —\n"
      u"`$0C`. Юнит в действии из списка `$01688C` не трогается вовсе: он\n"
      u"уже умирает.\n\n")
    p(u"Первые шесть шагов `$1A` — кадры общего банка: 61, потом 37…40 и\n"
      u"снова 37, то есть те же кадры, что у всплеска `$02`. Затем кадры\n"
      u"самого вида, лежащее тело, и на них петля. Поэтому обычная смерть\n"
      u"начинается с белого облака, похожего на всплеск воды.\n\n")
    p(u"Смерть от местности идёт мимо `UnitDie`, у каждой своя процедура и\n"
      u"своя анимация общего банка — `CheckLethalTerrain` `$019DF4` смотрит\n"
      u"клетку под ногами:\n\n"
      u"| клетка | процедура | действие | анимация |\n|---|---|---|---|\n"
      u"| бит 5 плитки | `UnitDiePop` `$01BADC` | `$29` | `$03`, хлопок |\n"
      u"| лава, огонь (типы 11, 12) | `UnitDieFlame` `$01AAE4` | `$27` | "
      u"`$01`, пламя |\n"
      u"| плитки `$53`, `$54` | `UnitDieSplash` `$01BAA4` | `$28` | "
      u"`$02`, всплеск |\n\n"
      u"`UnitDieFlame` зовут ещё шесть мест, в том числе оба бедствия\n"
      u"(`DisasterKnockDown`, `DisasterKillOrWound`). Анимаций смерти у ящера\n"
      u"поэтому четыре, и три из них — общие для всех видов.\n\n")

    p(u"### Бедствия\n\n")
    p(u"Погода проходит по юнитам окна и для каждого зовёт один из девяти\n"
      u"обработчиков бедствия. Убивают четыре, и убивают двумя способами:\n"
      u"`UnitDieFlame` — действие `$27`, пламя `$01`, тело горит; или\n"
      u"`$01BB42` и `KillUnit` — действие `$2B`, анимация `$00`, юнит\n"
      u"исчезает без трупа.\n\n"
      u"| погода | где | обработчик | что с юнитом |\n|---|---|---|---|\n"
      u"| метеорит | `EventAnim7`: сначала `WalkUnitsOffInArea`, в конце "
      u"`QuakeReshapeArea` | `DisasterWalkOff`, потом `DisasterKnockDown` | "
      u"сначала уходит; потом виды маски `$0730FFFE` с шансом 255/256 "
      u"гибнут **в пламени**; `IgniteCell` поджигает клетки окна |\n"
      u"| землетрясение, ветка `EventAnim5` | `QuakeAreaToRock`, "
      u"`QuakeAreaUnitsOnly` | `DisasterKillOrWound`, `DisasterKillAlways` | "
      u"первый: действие из `$01689C` — исчезает, прочие — **пламя**; "
      u"второй убирает без трупа |\n"
      u"| землетрясение, ветка `EventAnim6` | `QuakeAreaTo16` | "
      u"`DisasterKillCharged` | действие из `$01689C` — исчезает, прочие "
      u"исчезают с шансом 100/256 |\n"
      u"| буря, фаза `EventAnim3` | `RainAreaThenPanicOrKill` | "
      u"`DisasterPanicOrKill` | действие из `$016884` или идущий — исчезает, "
      u"прочие исчезают с шансом 200/256, иначе паника |\n"
      u"| молния | `LightningStrikeArea` | `LightningHitUnit`, "
      u"`DisasterStunUnit` | ранит и оглушает; гибнут только яйца |\n"
      u"| засуха | `DroughtAreaCurrent`, `DroughtAreaP2`; усиленная — "
      u"`HeavyDroughtArea` | `DisasterWoundUnit`; `DisasterPanicOnly` | "
      u"ранит; усиленная только пугает |\n"
      u"| ливень | `HeavyRainArea` | — | юнитов не трогает |\n\n"
      u"Кроме того, буря (`EventAnim1`, `EventAnim2`) и метеорит поджигают\n"
      u"клетки, а на горящей клетке юнит гибнет в пламени сам, через\n"
      u"`CheckLethalTerrain`. Какую ветку землетрясения выбрать, решает `d1`\n"
      u"из `$0093D4` перед драйвером `$009362`: единица ведёт на\n"
      u"`EventAnim6`, иначе `EventAnim5`; что это за счётчик, не установлено.\n\n")

    p(u"## Выгрузка для ремейка\n\n")
    p(u"`tools/exportanim.py` выводит по этому словарю одиннадцать листов\n"
      u"на вид. Где игра выбирает между несколькими анимациями, выводятся\n"
      u"все, а правило выбора ложится в `animations.json`, поле `select`:\n\n"
      u"| ремейк | номер | как выбирается |\n|---|---|---|\n"
      u"| `idle` | `$0A`, `$0B` | покой; `$0B` на нечётной стороне |\n"
      u"| `walking` | `$18`, `$19` | шаг; `$19` на нечётной стороне |\n"
      u"| `kicking_1`…`kicking_4` | `$13`…`$16` | два броска "
      u"`ResolveCombat`, см. «Удар» |\n"
      u"| `dying`, `dying_flame`, `dying_splash`, `dying_pop` | `$1A`, "
      u"`$01`, `$02`, `$03` | по местности и действию, см. «Смерть» |\n"
      u"| `eat` | `$0D` | все пять мест еды |\n\n")

    p(u"## Косвенные записи\n\n")
    p(u"| адрес | процедура | источник |\n|---|---|---|\n")
    for addr, proc, src in indirect:
        p(u"| `$%06X` | `%s` | `%s` |\n" % (addr, proc, src))
    f.close()
    print(u"записей константой %d, косвенных %d, различных номеров %d"
          % (sum(len(v) for v in direct.values()), len(indirect), len(direct)))
    print(u"без прямой записи: %s"
          % ", ".join("$%02X" % a for a in range(0x21) if a not in direct))
    print(u"листы: %s" % os.path.relpath(out, HERE))
    print(u"сводка: %s" % os.path.relpath(doc, HERE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
