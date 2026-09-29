#!/usr/bin/env python3
"""Перепись мест звука Dyna Brothers 2: где ROM запускает звук и зачем.

    make soundsites                       проверка и выгрузка
    python tools/soundsites.py --check    только проверка
    python tools/soundsites.py --sites    список мест (после проверки)
    python tools/soundsites.py --raw      места с окрестностью, без проверки

Место — команда в коде игры, которая отдаёт звуку приказ: слово line-F
звукового трапа (`$FF2D` `$FF2F` `$FF30` `$FF31` `$FF33` `$FF35` `$FF36`
`$FF37` `$FF38`) или `trap #0`. Места ищутся по дизассемблеру
(`make split`), а не по байтам ROM: в данных слово `$FF2F` встречается и
просто так. Помощник — процедура, которая получает номер от вызывающего и
сама зовёт трап; тогда местом становится и каждый вызов помощника.

Описания — таблицы `tools/soundevents.py` (`SITES`, `DYNAMIC`, `BANKS`),
помощники — `HELPERS` ниже. Номер звука в описании не пишется: он
читается из ROM на месте (`move.w #n,-(a7)` перед трапом,
`moveq`/`move.b #n,d0` перед `trap #0` и вызовом помощника). Место без
описания, описание без места и константа, записанная как вычисляемая (и
наоборот), — ошибка, и тогда инструмент ничего не выгружает.

Выгрузка для ремейка (dyna #231): `export/sounds.json` и
`sounds.sources.json` (у каждого числа — адрес и текст команды),
`export/sound/z80.bin` (ОЗУ Z80 после загрузчика `$00093C`) и `banks.bin`
(`$1C0000`–`$1FFFFF`), документ `docs/game-sound-events.md`. Эталон по
кадрам — `tools/render.py --reference`.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT, asm_dir, rom_path  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ─────────────────────────────── трапы ───────────────────────────────────
# Что делает каждый — docs/game-engine.md, docs/game-sound.md «Трапы».
TRAPS = {
    0xFF2D: "bank_main",      # банк главного цикла ($1C04/$1C05), команда $A0
    0xFF2F: "sound",          # команда драйвера как есть, в SoundRequest
    0xFF30: "music",          # номер table_music
    0xFF31: "fade_wait",      # затухание и ожидание его конца
    0xFF33: "fade",           # затухание без ожидания
    0xFF35: "bank_music",     # банк прерывания ($1C06/$1C07), команда $E1
    0xFF36: "bank_main5",     # банк главного цикла, как $FF2D
    0xFF37: "stop",           # $1F в $1C14, команда $E1, ожидание
    0xFF38: "sfx",            # номер table_sfx
}
# Трапы со словом-аргументом на стеке. $FF36 — тот же $FF2D с банком 5
# внутри, а затухания и стоп аргумента не берут.
WITH_ARG = {0xFF2D, 0xFF2F, 0xFF30, 0xFF35, 0xFF38, 0}


# ─────────────────────────── чтение листинга ─────────────────────────────
class Ins:
    __slots__ = ("addr", "text", "proc", "label", "file")

    def __init__(self, addr, text, proc, label, file):
        self.addr, self.text, self.proc, self.label, self.file = \
            addr, text, proc, label, file


def load_listing():
    """-> список команд в порядке адресов.

    Каждая команда в выводе sega2asm стоит под строкой `; $XXXXXX` или
    под меткой с тем же комментарием. `proc` — ближайшая выше метка, не
    `loc_` и не имя сегмента (`code_59b:` в начале файла — это сегмент, а
    не процедура): имя процедуры, в которой лежит команда. `label` —
    метка, стоящая ровно на этой команде, иначе None.
    """
    out = []
    d = asm_dir()
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".asm"):
            continue
        segment = fn[:-4]
        cur, proc, label = None, None, None
        for line in open(os.path.join(d, fn), encoding="utf-8", errors="replace"):
            m = re.match(r"^([A-Za-z_]\w*):\s*;\s*\$([0-9A-F]{6})", line)
            if m:
                label, cur = m.group(1), int(m.group(2), 16)
                if not label.startswith("loc_") and label != segment:
                    proc = label
                continue
            m = re.match(r"^;\s*\$([0-9A-F]{6})\s*$", line)
            if m:
                cur, label = int(m.group(1), 16), None
                continue
            if line.startswith("\t") and cur is not None:
                text = line.strip().split(";")[0].strip()
                if text and not text.startswith(("org", "even", "include")):
                    out.append(Ins(cur, text, proc, label, fn))
                    cur, label = None, None
    out.sort(key=lambda i: i.addr)
    # Файл может начинаться с loc_: тогда процедура — последняя именованная
    # метка выше по адресам, в каком бы файле она ни стояла.
    last = None
    for ins in out:
        if ins.proc is None:
            ins.proc = last
        last = ins.proc
    return out


def trap_of(ins):
    m = re.match(r"dc\.w\s+\$(FF[0-9A-F]{2})$", ins.text)
    if m and int(m.group(1), 16) in TRAPS:
        return int(m.group(1), 16)
    if re.match(r"trap\s+#0$", ins.text):
        return 0
    return None


def argument(prev, trap):
    """Номер, который видно в предыдущей команде, или None (вычисляется)."""
    if prev is None:
        return None
    t = prev.text
    if trap:
        # `-(a7)` — новое слово на стеке; `(a7)` — то же слово второй раз
        # подряд (`$00DB80`: банк, потом номер).
        m = re.match(r"move\.w\s+#\$([0-9A-F]+),-?\(a7\)$", t)
        return int(m.group(1), 16) if m else None
    m = re.match(r"(?:moveq\s+#(\d+)|move\.[bw]\s+#\$([0-9A-F]+)),d0$", t)
    if m:
        return int(m.group(1)) if m.group(1) else int(m.group(2), 16)
    return None


def sites(listing=None):
    """-> [(addr, trap, n, ins, prev)] — все места звука.

    n — константа, None (номер вычисляется) или False (трап без аргумента).
    """
    listing = listing or load_listing()
    found = []
    for k, ins in enumerate(listing):
        trap = trap_of(ins)
        if trap is None:
            continue
        prev = listing[k - 1] if k and listing[k - 1].addr < ins.addr else None
        n = argument(prev, trap) if trap in WITH_ARG else False
        found.append((ins.addr, trap, n, ins, prev))
    return found


def trap_name(trap):
    return "trap #0" if trap == 0 else "$%04X" % trap


def shown(n):
    """Номер места для печати: константа, «вычисл.» или «—» (без аргумента)."""
    if n is False:
        return "—"
    return "вычисл." if n is None else "$%02X" % n


def raw_report():
    listing = load_listing()
    index = {ins.addr: k for k, ins in enumerate(listing)}
    for addr, trap, n, ins, prev in sites(listing):
        k = index[addr]
        print("== $%06X %-7s %-6s %s (%s)" % (
            addr, trap_name(trap), shown(n),
            ins.proc or "?", ins.file))
        for j in range(max(0, k - 6), min(len(listing), k + 3)):
            c = listing[j]
            print("   %s $%06X  %s" % (">" if j == k else " ", c.addr, c.text))


# ─────────────────────────────── помощники ───────────────────────────────
# Процедура, которая получает номер в d0 от вызывающего и сама зовёт трап.
# Её собственный трап описан как место «помощника», а событие — у каждого
# вызова: вызов тоже место переписи, номер читается перед ним.
HELPERS = {
    0x006BDC: "PlaySfxRemembered",     # $FF30 d0, d0 -> $FF2A78; музыка, не звук
    0x00BEC0: "PlaySfxWithCallback",   # $FF2F d0, повтор каждые d1 кадров из VBlank
    0x00DFEE: "PlaySound",             # $FF30 d0, MusicId := d0 + 1; музыка этапа
}


def helper_calls(listing):
    """-> [(addr, helper, n, ins, src)] — все вызовы помощников.

    Номер — ближайшая выше `moveq #n,d0` / `move.b|w #n,d0` в пределах
    четырёх команд подряд, без меток и вызовов между; `src` — команда,
    давшая номер. Любая другая запись в d0 (`move ...,d0`, `clr.b d0`,
    `swap d0`) — номер вычисляется.
    """
    names = {v: k for k, v in HELPERS.items()}
    pat = re.compile(r"(?:bsr\.[sw]|jsr)\s+\(?(\w+)\)?(?:\.l)?$")
    out = []
    for k, ins in enumerate(listing):
        m = pat.match(ins.text)
        if not m or m.group(1) not in names:
            continue
        n, src = None, None
        for j in range(k - 1, max(k - 5, -1), -1):
            p = listing[j]
            if listing[j + 1].label or \
                    re.match(r"(?:bsr|jsr|bra|jmp|rts|rte)\b", p.text):
                break
            n = argument(p, 0)
            if n is not None:
                src = p
                break
            if re.search(r"[\s,]d0$", p.text):
                break
        out.append((ins.addr, names[m.group(1)], n, ins, src))
    return out


def stage_music_calls():
    """Вызов PlaySound -> (этапы, тик, номер) по разбору сценариев этапов."""
    import stageevents as se
    out = {}
    for st in range(256):
        try:
            ins = se.decode(se.entry(st))
        except AssertionError:
            continue
        blocks = se.tick_blocks(ins)
        for i, x in enumerate(ins):
            if se.call_target(x) != se.PLAY_SOUND:
                continue
            blk = [b for b in blocks if b[1] <= x.a < b[2]]
            tick = blk[0][0] if blk else None
            out.setdefault(x.a, [[], tick])[0].append(st)
    for st, addrs in se.MUSIC_EXTRA.items():
        for a in addrs:
            ev = se.music_block(a)
            stages = out.setdefault(a + 20, [[], ev["tick"]])[0]
            if st not in stages:
                stages.append(st)
    return out


# ──────────────────────────────── перепись ────────────────────────────────
def census(listing):
    """-> список мест с описаниями; ошибки — в ERRORS.

    Место: адрес, трап (или помощник), номер, описание. Сверка:
    каждое найденное место описано, каждое описание стоит на месте;
    вычисляемый номер описан в DYNAMIC, константа — нет; банк для
    `$FF2F` — только у мест `$FF2F`.
    """
    import soundevents as E
    rows = []
    found = set()
    # Метки, на которые есть ссылки: если такая стоит на самом трапе, сюда
    # приходят и другим путём, и константа перед трапом — не весь ответ
    # (место обязано быть в DYNAMIC со списком значений).
    labelled = {i.label for i in listing if i.label}
    referenced = {w for i in listing for w in re.findall(r"\w+", i.text)
                  if w in labelled}
    for addr, trap, n, ins, prev in sites(listing):
        found.add(addr)
        d = E.SITES.get(addr)
        if d is None:
            ERRORS.append("$%06X %s: нет описания" % (addr, trap_name(trap)))
            continue
        if n not in (None, False) and addr not in E.DYNAMIC and \
                ins.label in referenced:
            ERRORS.append("$%06X: на трап переходят (%s) — номер может прийти "
                          "другим путём, место для DYNAMIC" % (addr, ins.label))
        rows.append({"addr": addr, "trap": trap, "helper": None, "n": n,
                     "domain": d[0], "side": d[1], "event": d[2],
                     "proc": ins.proc, "src": prev})
    music = stage_music_calls()
    for addr, helper, n, ins, src in helper_calls(listing):
        found.add(addr)
        if HELPERS[helper] == "PlaySound" and addr in music:
            stages, tick = music[addr]
            d = ("сценарий", "сим",
                 "этап %s, тик %s: смена музыки" % (
                     ", ".join(map(str, stages)),
                     tick if tick is not None else "?"))
            if addr in E.SITES:
                ERRORS.append("$%06X: вызов PlaySound описан вручную" % addr)
        else:
            d = E.SITES.get(addr)
        if d is None:
            ERRORS.append("$%06X вызов %s: нет описания" % (addr, HELPERS[helper]))
            continue
        rows.append({"addr": addr, "trap": None, "helper": helper, "n": n,
                     "domain": d[0], "side": d[1], "event": d[2],
                     "proc": ins.proc, "src": src})
    for addr in sorted(set(E.SITES) - found):
        ERRORS.append("$%06X: описано, но в ROM такого места нет" % addr)
    for r in rows:
        a = r["addr"]
        if r["n"] is None and a not in E.DYNAMIC:
            ERRORS.append("$%06X: номер вычисляется — место для DYNAMIC" % a)
        # Номер выбран веткой из нескольких констант: перед трапом видна
        # одна из них, и она обязана быть в списке DYNAMIC.
        if r["n"] is not None and a in E.DYNAMIC and \
                r["n"] not in (E.DYNAMIC[a][0] or ()):
            ERRORS.append("$%06X: номер $%02X виден в ROM, а записан в DYNAMIC"
                          % (a, r["n"]))
        # Банк — у команды драйвера: `$FF2F` и вызовы PlaySfxWithCallback.
        sends = r["trap"] == 0xFF2F or r["helper"] is not None and \
            HELPERS[r["helper"]] == "PlaySfxWithCallback"
        if a in E.BANKS and not sends:
            ERRORS.append("$%06X: банк записан не у команды драйвера" % a)
        if r["domain"] not in DOMAINS or r["side"] not in SIDES:
            ERRORS.append("$%06X: область «%s» или сторона «%s» не из списка"
                          % (a, r["domain"], r["side"]))
    for a in set(E.DYNAMIC) - {r["addr"] for r in rows}:
        ERRORS.append("$%06X: в DYNAMIC, но такого места нет" % a)
    for a in set(E.BANKS) - {r["addr"] for r in rows}:
        ERRORS.append("$%06X: в BANKS, но такого места нет" % a)
    rows.sort(key=lambda r: r["addr"])
    return rows


DOMAINS = ("музыка", "погода", "меню", "симуляция", "сценарий", "миссия",
           "анимация", "экран", "биос")
SIDES = ("сим", "меню", "модально", "экран", "биос", "помощник")


# ─────────────────────────── происхождение чисел ─────────────────────────
# Каждое выгруженное число — V(значение, откуда). `откуда` — адрес и текст
# команды, из которой число прочитано, взятые из листинга, а не
# переписанные руками: `at()` сверяет команду с ожидаемым образцом, и
# расхождение — ошибка выгрузки. Дерево с V раскладывается на два файла
# с одинаковыми ключами: sounds.json (значения) и sounds.sources.json.
ERRORS = []


class V:
    __slots__ = ("value", "src")

    def __init__(self, value, src):
        self.value, self.src = value, src


_BY_ADDR = {}


def at(addr, pattern):
    """'$ADDR: команда' — если команда по адресу подходит под образец."""
    ins = _BY_ADDR.get(addr)
    if ins is None:
        ERRORS.append("$%06X: в листинге нет команды" % addr)
        return "$%06X: ?" % addr
    if not re.search(pattern, ins.text):
        ERRORS.append("$%06X: ждали /%s/, а там «%s»" % (addr, pattern, ins.text))
    return "$%06X: %s" % (addr, " ".join(ins.text.split()))


def data(addr, what):
    """Число из данных ROM, а не из команды."""
    return "$%06X: данные, %s" % (addr, what)


def split(tree):
    """-> (значения, источники) с одинаковыми ключами."""
    if isinstance(tree, V):
        return tree.value, tree.src
    if isinstance(tree, dict):
        a, b = {}, {}
        for k, v in tree.items():
            a[k], b[k] = split(v)
        return a, b
    if isinstance(tree, (list, tuple)):
        pairs = [split(v) for v in tree]
        return [p[0] for p in pairs], [p[1] for p in pairs]
    return tree, None


# ─────────────────────────────── драйвер ─────────────────────────────────
Z80_DRIVER = 0x00207E          # сжатый блок драйвера (метод 3)
TABLE_MUSIC = 0x001F36         # пары (банк, команда) по номеру музыки
TABLE_SFX = 0x00201C           # пары (банк, команда) по номеру эффекта
BANKS_ROM = 0x1C0000           # окно банков: адрес = $1C0000 + номер * $8000
BANKS_LEN = 0x040000           # банки 0-7; 0 и 1 не используются, но окно
                               # отдаётся целиком, как render.c отдаёт весь ROM
BANK_SIZE = 0x8000
Z80_RAM = 0x2000


def rom():
    return open(rom_path(), "rb").read()


def driver_image(r, image):
    """ОЗУ Z80 сразу после загрузчика $00093C: 8 КБ, всё прочее — нули.

    Раскладка берётся из `image` — тех чисел, что прочитаны из команд
    загрузчика: распакованный блок двумя кусками и ящик отдельно.
    Остальное ОЗУ загрузчик не трогает (у приставки оно при включении не
    задано, эмуляторы и render.c начинают с нулей).
    """
    from unpack import unpack
    _, _, d, _ = unpack(r, image["packed"]["rom"].value)
    img = bytearray(image["size"].value)
    for p in image["pieces"]:
        z, n = p["z80"].value, p["length"].value
        if "rom" in p:
            img[z:z + n] = r[p["rom"].value:p["rom"].value + n]
        else:
            img[z:z + n] = d[p["from"].value:p["from"].value + n]
    return bytes(img)


def driver(r):
    from unpack import unpack
    method, size, _, _ = unpack(r, Z80_DRIVER)
    music = [[V(r[TABLE_MUSIC + 2 * i], data(TABLE_MUSIC + 2 * i, "банк")),
              V(r[TABLE_MUSIC + 2 * i + 1], data(TABLE_MUSIC + 2 * i + 1, "команда"))]
             for i in range((TABLE_SFX - TABLE_MUSIC) // 2)]
    sfx = [[V(r[TABLE_SFX + 2 * i], data(TABLE_SFX + 2 * i, "банк")),
            V(r[TABLE_SFX + 2 * i + 1], data(TABLE_SFX + 2 * i + 1, "команда"))]
           for i in range((Z80_DRIVER - TABLE_SFX) // 2)]
    return {
        "image": {
            "file": "sound/z80.bin",
            "size": V(Z80_RAM, "ОЗУ Z80 целиком, $0000-$1FFF"),
            "packed": {
                "rom": V(Z80_DRIVER, at(0x00092A, r"pea\s+z80_driver\(pc\)")),
                "method": V(method, data(Z80_DRIVER + 2, "метод сжатия")),
                "length": V(size, data(Z80_DRIVER, "длина распакованного")),
            },
            "pieces": [
                {"z80": V(0x0000, at(0x000960, r"lea\s+\(Z80_RAM\)\.l,a2")),
                 "from": V(0x0000, at(0x000966, r"lea\s+\(GameState\)\.l,a3")),
                 "length": V(0x0FD2, at(0x00096C, r"move\.w\s+#\$0FD1,d7"))},
                {"z80": V(0x1100, at(0x000976, r"lea\s+\(\$A01100\)\.l,a2")),
                 "from": V(0x0FD2, "продолжение того же a3"),
                 "length": V(0x0AEE, at(0x00097C, r"move\.w\s+#\$0AED,d7"))},
                {"z80": V(0x1C00, at(0x000986, r"lea\s+\(\$A01C00\)\.l,a0")),
                 "rom": V(0x000AA8, at(0x00098C, r"lea\s+Z80MailboxInit\(pc\),a1")),
                 "length": V(13, at(0x000990, r"moveq\s+#12,d0"))},
            ],
        },
        "banks": {
            "file": "sound/banks.bin",
            "rom": V(BANKS_ROM, "номер 0 по формуле ниже"),
            "length": V(BANKS_LEN, "банки 0-7"),
            "size": V(BANK_SIZE, "окно Z80 $8000-$FFFF"),
            # x = номер * 8 + $1C0; в ящик (x >> 4, x << 4); адрес = x << 12
            "mul": V(8, at(0x001D68, r"lsl\.b\s+#3,d0")),
            "add": V(0x1C0, at(0x001D6A, r"addi\.w\s+#\$01C0,d0")),
            "hi_shift": V(4, at(0x001D70, r"lsr\.w\s+#4,d0")),
            "lo_shift": V(4, at(0x001D72, r"lsl\.w\s+#4,d1")),
            "waits": V(3, at(0x001D54, r"bsr\.w\s+VDPWaitVBlank")),
        },
        "mailbox": {
            "command": V(0x1C0A, at(0x00061C, r"move\.b\s+\(SoundRequest\)\.l,\(Z80SoundCommand\)\.l")),
            "status": V(0x1C08, at(0x0005D8, r"move\.b\s+\(Z80SoundStatus\)\.l,d0")),
            "taken": V(0x1C09, at(0x001DCE, r"move\.b\s+\(Z80CommandTaken\)\.l,d0")),
            "idle": V(0x8000, at(0x001DF6, r"cmpi\.w\s+#\$8000,d0")),
            "bank_main": V(0x1C04, at(0x001CF0, r"lea\s+\(Z80BankMain\)\.l,a0")),
            "bank_music": V(0x1C06, at(0x001D12, r"lea\s+\(Z80BankMusic\)\.l,a0")),
            "pause": V(0x1C10, at(0x000416, r"move\.b\s+d0,\(Z80PauseRequest\)\.l")),
            "fade": V(0x1C0D, at(0x001F12, r"move\.b\s+#\$28,\(Z80FadeCounter\)\.l")),
            "fade_steps": [V(0x1C0E, at(0x001F02, r"#\$02,\(\$A01C0E\)")),
                           V(0x1C0F, at(0x001F0A, r"#\$02,\(\$A01C0F\)"))],
            "stop": V(0x1C14, at(0x001EFA, r"#\$1F,\(\$A01C14\)")),
        },
        "ram": {
            "request": V(0xFF0282, at(0x001E1A, r"move\.b\s+d0,\(SoundRequest\)\.l")),
            "music_id": V(0xFF0281, at(0x001E24, r"move\.b\s+d0,\(MusicId\)\.l")),
            "bank_main_cache": V(0xFF0280, at(0x001CF6, r"lea\s+\(SoundBankCache\)\.l,a1")),
            "bank_music_cache": V(0xFF027F, at(0x001D18, r"lea\s+\(MusicBankCache\)\.l,a1")),
            "mute_bit": V(4, at(0x001E04, r"btst\s+#4,\(GlobalFlags\)\.l")),
        },
        "init": {
            "music_id": V(0xFF, at(0x0009BC, r"st\s+\(MusicId\)\.l")),
            "bank_music": V(2, at(0x0009C2, r"move\.b\s+#\$02,\(MusicBankCache\)\.l")),
            "bank_main": V(5, at(0x0009CA, r"move\.b\s+#\$05,\(SoundBankCache\)\.l")),
            "vblanks": V(10, at(0x0009B0, r"moveq\s+#9,d0")),
        },
        "traps": {
            # $FF2F: номер как есть; не глушится ли и не служебный ли
            "sound_limit": V(0xE0, at(0x001E12, r"cmpi\.b\s+#\$E0,d0")),
            # $FF2D/$FF36 шлют $A0, $FF35 и $FF37 — $E1
            "bank_main_command": V(0xA0, at(0x001CE8, r"move\.w\s+#\$00A0,d0")),
            "bank_music_command": V(0xE1, at(0x001D0A, r"move\.w\s+#\$00E1,d0")),
            "bank5": V(5, at(0x001D32, r"move\.b\s+#\$05,d0")),
            "stop_value": V(0x1F, at(0x001C7E, r"#\$1F,\(\$A01C14\)")),
            "stop_command": V(0xE1, at(0x001C90, r"move\.b\s+#\$E1,d0")),
            "fade_value": V(0x1F, at(0x001EFA, r"#\$1F,\(\$A01C14\)")),
            "fade_step": V(2, at(0x001F02, r"#\$02,\(\$A01C0E\)")),
            "fade_count": V(0x28, at(0x001F12, r"#\$28,\(Z80FadeCounter\)")),
            # trap #0: $FF пропускается, при затухании младше $E0 — отбрасываются,
            # младше $81 — в $1C10 (пауза), остальные — в SoundRequest
            "z80_skip": V(0xFF, at(0x000392, r"cmpi\.b\s+#\$FF,d0")),
            "z80_fade_floor": V(0xE0, at(0x0003D2, r"cmpi\.b\s+#\$E0,d0")),
            "z80_pause_below": V(0x81, at(0x0003DA, r"cmpi\.b\s+#\$81,d0")),
        },
        "tables": {
            "music": music,
            "sfx": sfx,
            "music_rom": V(TABLE_MUSIC, at(0x001E2E, r"lea\s+table_music\(pc\),a0")),
            "sfx_rom": V(TABLE_SFX, at(0x001E5C, r"lea\s+table_sfx\(pc\),a0")),
            "keep_bank": V(0x80, at(0x001E36, r"bmi\.w")),
        },
    }


def write_json(path, obj):
    import json
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")


def export(r, tree):
    values, sources = split(tree)
    write_json(OUT("export", "sounds.json"), values)
    write_json(OUT("export", "sounds.sources.json"), sources)
    img = driver_image(r, tree["driver"]["image"])
    os.makedirs(OUT("export", "sound"), exist_ok=True)
    open(OUT("export", "sound", "z80.bin"), "wb").write(img)
    open(OUT("export", "sound", "banks.bin"), "wb").write(
        r[BANKS_ROM:BANKS_ROM + BANKS_LEN])


# ───────────────────────────── что звучит ────────────────────────────────
class Names:
    """Подписи номеров: звукоподражания эффектов и названия песен."""

    def __init__(self, r):
        import sfx
        import render
        self.r = r
        self.sfx = sfx.names()
        self.note = getattr(sfx, "NOTE", {})
        self.songs = render.song_titles()

    def command(self, c):
        if c == 0x01:
            return "$01 пауза"
        if c == 0x80:
            return "$80 снятие паузы"
        if c == 0xE1:
            return "$E1 стоп"
        if c == 0xE0:
            return "$E0 затухание"
        if 0x81 <= c <= 0x8F:
            return "$%02X песня" % c
        n = self.sfx.get(c)
        return "$%02X %s" % (c, " ".join(n[0].split()) if n else "")

    def music(self, n):
        b, c = self.r[TABLE_MUSIC + 2 * n], self.r[TABLE_MUSIC + 2 * n + 1]
        if b == 0xFF:
            return "м.%d = %s" % (n, self.command(c))
        t = self.songs.get((b, c))
        return "м.%d = б%d $%02X%s" % (n, b, c, " «%s»" % " ".join(t.split()) if t else "")

    def sfx_index(self, n):
        b, c = self.r[TABLE_SFX + 2 * n], self.r[TABLE_SFX + 2 * n + 1]
        return "э.%d = %s%s" % (n, self.command(c), "" if b == 0xFF else ", банк %d" % b)

    def of(self, kind, n):
        """kind — трап, 0 (trap #0) или имя помощника; n — номер."""
        if kind in (0xFF30, "PlaySound", "PlaySfxRemembered"):
            return self.music(n)
        if kind == 0xFF38:
            return self.sfx_index(n)
        if kind in (0xFF2D, 0xFF35):
            return "банк %d" % n
        return self.command(n)


FIXED = {0xFF36: "банк 5", 0xFF37: "стоп всего", 0xFF31: "затухание, ждать",
         0xFF33: "затухание"}


def sound_text(names, row):
    import soundevents as E
    kind = row["helper"] and HELPERS[row["helper"]] or row["trap"]
    if row["n"] is False:
        return FIXED[row["trap"]]
    dyn = E.DYNAMIC.get(row["addr"])
    if dyn and dyn[0]:
        return " / ".join(names.of(kind, v) for v in dyn[0])
    if row["n"] is None:
        return "вычисл."
    return names.of(kind, row["n"])


def kind_name(row):
    return row["helper"] and HELPERS[row["helper"]] or trap_name(row["trap"])


def sites_tree(rows):
    """Места для sounds.json; источник номера — команда, давшая номер."""
    import soundevents as E
    out = []
    for r in rows:
        a = r["addr"]
        prev = r["src"]
        dyn = E.DYNAMIC.get(a)
        if r["n"] is False:
            num = V(None, None)
        elif a in E.DYNAMIC:
            num = V(None, dyn[1] if isinstance(dyn[1], str) else None)
        else:
            num = V(r["n"], "$%06X: %s" % (prev.addr, " ".join(prev.text.split())))
        bank = E.BANKS.get(a)
        out.append({
            "addr": a,
            "kind": kind_name(r),
            "number": num,
            "values": list(dyn[0]) if dyn and dyn[0] else None,
            "domain": r["domain"],
            "side": r["side"],
            "event": r["event"],
            "bank": V(bank[0], bank[1]) if bank else None,
            "proc": r["proc"],
        })
    return out


def commands_by_site(r):
    """Команда драйвера -> адреса мест переписи, где она звучит.

    Константа или список значений из DYNAMIC; `$FF38` — через table_sfx,
    `PlaySfxWithCallback` и `trap #0` — как есть. Для game-sfx.md."""
    import soundevents as E
    del ERRORS[:]
    listing = load_listing()
    rows = census(listing)
    out = {}
    for row in rows:
        kind = row["helper"] and HELPERS[row["helper"]] or row["trap"]
        if kind not in (0xFF2F, 0xFF38, 0, "PlaySfxWithCallback"):
            continue
        dyn = E.DYNAMIC.get(row["addr"])
        vals = list(dyn[0]) if dyn and dyn[0] else (
            [row["n"]] if row["n"] not in (None, False) else [])
        for v in vals:
            c = r[TABLE_SFX + 2 * v + 1] if kind == 0xFF38 else v
            out.setdefault(c, []).append(row["addr"])
    return out


# Чей канал сейчас — для двух шин ремейка (dyna #232, решение 3b #230).
# Адреса — ОЗУ Z80, разбор драйвера — docs/game-sound.md «Чей канал сейчас».
# Канал с эффектным слотом — эффект, пока у слота +0 бит 7; FM1, FM2 —
# всегда музыка; FM6 — эффект, пока $1C3C ≠ 0 (DAC); шум PSG — эффект,
# пока у слота $1F40 биты 7 и 0.
OWNER_SLOTS = [("FM3", 0x1E20, 0x1CD0), ("FM4", 0x1E50, 0x1D00),
               ("FM5", 0x1E80, 0x1D30), ("FM6", 0x1EB0, 0x1D60),
               ("PSG1", 0x1EE0, 0x1D90), ("PSG2", 0x1F10, 0x1DC0),
               ("PSG3", 0x1F40, 0x1DF0)]


def owners():
    src = "Z80 $066D: таблицы $06D6 (эффект) и $06E6 (музыка)"
    return {
        "music_only": ["FM1", "FM2"],
        "active_bit": V(0x80, "Z80 $0C55: res 7,(ix+0) на $F2; бит 7 +0 — слот занят"),
        "channels": [{"channel": c, "effect_slot": V(e, src), "music_slot": V(m, src)}
                     for c, e, m in OWNER_SLOTS],
        "dac": {"channel": "FM6",
                "flag": V(0x1C3C, "Z80 $0B29: ld ($1C3C),a по $EA; $0FAF обнуляет")},
        "noise": {"slot": V(0x1F40, "Z80 $0CFD: бит 0 +0 по $F3 у слота PSG3"),
                  "bits": V(0x81, "+0 бит 7 (занят) и бит 0 (шум)")},
    }


def weather():
    import soundevents as E
    return [{"weather": w, "who": who, "path": path,
             "steps": [{"frame": f, "op": op, "addr": a, "note": n}
                       for f, op, a, n in rows]}
            for w, who, path, rows in E.WEATHER]


def bank_by_command(r):
    """Команда эффекта -> банк главного цикла, который застаёт её в игре.

    Берётся самый частый банк из `BANKS` среди мест переписи, где звучит
    команда; команды без известного банка в ответ не входят. Для эталона
    `render.py --reference`."""
    import collections
    import soundevents as E
    by_cmd = commands_by_site(r)
    out = {}
    for cmd, addrs in by_cmd.items():
        got = collections.Counter(E.BANKS[a][0] for a in addrs
                                  if a in E.BANKS and E.BANKS[a][0] is not None)
        if got:
            out[cmd] = got.most_common(1)[0][0]
    return out


def sites_report(rows, names):
    for r in rows:
        print("$%06X %-20s %-7s %-34s %-8s %s" % (
            r["addr"], kind_name(r), shown(r["n"]), sound_text(names, r)[:34],
            r["side"], r["event"][:90]))


# ─────────────────────────────── документ ────────────────────────────────
DOC = "game-sound-events.md"


def write_doc(rows, names):
    import collections
    import soundevents as E
    from paths import docs_dir
    by_kind = collections.Counter(kind_name(r) for r in rows)
    lines = []
    p = lines.append
    p("# Места звука: где ROM заводит звук и зачем\n")
    p("СГЕНЕРИРОВАНО `tools/soundsites.py` (`make soundsites`) из таблиц "
      "`tools/soundevents.py` — правки вносить туда (dyna #231).\n")
    p("Место — слово звукового трапа в коде, `trap #0` или вызов помощника, "
      "который получает номер от вызывающего. Места ищет дизассемблер, а не "
      "поиск байтов: слово `$FF2F` в данных встречается и просто так. Номер "
      "читается из ROM на месте; место без описания, описание без места и "
      "константа, записанная вычисляемой, — ошибка, и выгрузки нет.\n")
    p("## Сколько мест\n")
    p("| место | сколько | что делает |")
    p("|---|---|---|")
    what = {"$FF2F": "команда драйвера как есть в `SoundRequest`, без ожидания; "
                     "в кадре побеждает последняя; бит 4 `GlobalFlags` глушит, "
                     "`$E0`+ отбрасывается",
            "$FF30": "номер `table_music`: банк (`$FF35`, если не `$FF`) и команда "
                     "через `trap #0`, ждёт переноса и свободного драйвера",
            "$FF38": "номер `table_sfx`: банк (`$FF2D`, если не `$FF`) и команда "
                     "через `trap #0`, ждёт переноса",
            "$FF2D": "банк главного цикла: `$A0`, три кадра, банк в `$1C04`, "
                     "ожидание свободного драйвера и кадр",
            "$FF36": "то же с банком 5",
            "$FF35": "банк прерывания (музыка): `$E1`, три кадра, `$1C06`",
            "$FF37": "`$1F` в `$1C14`, команда `$E1`, ожидание нуля в `$1C14`",
            "$FF31": "затухание (`$1F` в `$1C14`, по 2 в `$1C0E`/`$1C0F`, `$28` "
                     "в `$1C0D`) и ожидание конца",
            "$FF33": "то же без ожидания",
            "trap #0": "команда из `d0`: `$FF` пропускается, при затухании "
                       "младше `$E0` отбрасываются, младше `$81` — в `$1C10` "
                       "(пауза), остальные — в `SoundRequest` мимо бита 4",
            "PlaySound": "`$00DFEE`: музыка этапа по номеру `table_music` в `d0`, "
                         "`MusicId` := номер + 1",
            "PlaySfxRemembered": "`$006BDC`: музыка по номеру в `d0`, номер — "
                                 "в `$FF2A78` (имя историческое: это музыка)",
            "PlaySfxWithCallback": "`$00BEC0`: команда `d0` сразу и потом каждые "
                                   "`d1` кадров из VBlank, пока `ClearRasterHookAndSfx`"}
    for k in ("$FF2F", "$FF30", "$FF38", "$FF2D", "$FF36", "$FF35", "$FF37",
              "$FF31", "$FF33", "trap #0", "PlaySound", "PlaySfxRemembered",
              "PlaySfxWithCallback"):
        p("| %s | %d | %s |" % ("`%s`" % k, by_kind.get(k, 0), what[k]))
    p("| всего | %d | |\n" % len(rows))
    p("Сторона: **сим** — в тике симуляции; **меню** — команда игрока в "
      "миссии; **модально** — анимация, на время которой игра стоит; "
      "**экран** — вне миссии; **биос** — внутри обработчика трапа; "
      "**помощник** — внутри помощника, сторона у вызывающего. Банк — "
      "банк главного цикла, который застаёт команда `$FF2F` на этом пути "
      "(для FM-команд без сэмпла он не важен).\n")
    titles = {"музыка": "Музыка", "погода": "Погода", "меню": "Меню и команды",
              "симуляция": "Симуляция", "сценарий": "Сценарии этапов",
              "миссия": "Начало и конец миссии", "анимация": "Повтор звука",
              "экран": "Экраны вне миссии", "биос": "Внутри трапов"}
    for dom in DOMAINS:
        part = [r for r in rows if r["domain"] == dom]
        if not part:
            continue
        p("## %s\n" % titles[dom])
        p("| адрес | место | номер | звук | сторона | банк | событие |")
        p("|---|---|---|---|---|---|---|")
        for r in part:
            bank = E.BANKS.get(r["addr"])
            p("| `$%06X` | %s | %s | %s | %s | %s | %s |" % (
                r["addr"], kind_name(r), shown(r["n"]).replace("вычисл.", "—"),
                sound_text(names, r).replace("|", "/"), r["side"],
                bank[0] if bank and bank[0] is not None else "—",
                r["event"].replace("|", "/")))
        p("")
    p("## Откуда номер\n")
    p("Места, где номер не константа перед трапом.\n")
    p("| адрес | откуда |")
    p("|---|---|")
    for a in sorted(E.DYNAMIC):
        p("| `$%06X` | %s |" % (a, E.DYNAMIC[a][1]))
    p("")
    for extra in getattr(E, "SECTIONS", []):
        p(extra)
    path = os.path.join(docs_dir(), DOC)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    return path


def main():
    if "--raw" in sys.argv:
        raw_report()
        return 0
    listing = load_listing()
    _BY_ADDR.update((i.addr, i) for i in listing)
    r = rom()
    rows = census(listing)
    tree = {"meta": {"game": "Dyna Brothers 2", "generator": "tools/soundsites.py",
                     "doc": "docs/" + DOC, "format": 1},
            "driver": driver(r),
            "owners": owners(),
            "sites": sites_tree(rows) if not ERRORS else [],
            "weather": weather()}
    # Вторая, независимая раскладка — z80dis.load() (make z80dis): образ
    # обязан совпасть с ней байт в байт.
    import z80dis
    if driver_image(r, tree["driver"]["image"]) != bytes(z80dis.load()):
        ERRORS.append("образ драйвера расходится с z80dis.load()")
    if ERRORS:
        for e in ERRORS:
            print("ОШИБКА:", e)
        return 1
    if "--check" in sys.argv:
        print("ошибок нет: мест %d" % len(rows))
        return 0
    names = Names(r)
    if "--sites" in sys.argv:
        sites_report(rows, names)
        return 0
    export(r, tree)
    print("выгружено: %s, мест %d" % (OUT("export", "sounds.json"), len(rows)))
    print("документ: %s" % write_doc(rows, names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
