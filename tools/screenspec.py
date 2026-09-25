#!/usr/bin/env python3
"""Экраны вне уровня и HUD Maui Mallard в JSON для движка ремейка.

    python tools/screenspec.py            записать out/mauimallard/export/
    python tools/screenspec.py --check    только проверить, ничего не писать
    python tools/screenspec.py --text     все тексты экранов на консоль

Пишет `screens.json` и `screens.sources.json` (то же дерево, у каждого
числа — адрес и текст команды). Числа читаются из ROM тем же механизмом,
что в `tools/specjson.py`. Спецификация — docs/mauimallard/screens.md.

Что внутри: порядок экранов (от включения до конца игры), каждый экран —
слои, палитра, музыка, сколько длится и чем пропускается; меню и их пункты;
пароли; сюжетные страницы и надписи крупными буквами; демо; пауза; HUD.
"""
import io
import json
import os
import struct
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import specjson as SJ                                        # noqa: E402
from specjson import D, at, dw, hexa                         # noqa: E402
from paths import OUT                                        # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM = SJ.ROM
U16 = lambda a: struct.unpack_from(">H", ROM, a)[0]          # noqa: E731
S16 = lambda a: struct.unpack_from(">h", ROM, a)[0]          # noqa: E731
U32 = lambda a: struct.unpack_from(">I", ROM, a)[0]          # noqa: E731


# ------------------------------------------------------------ данные

def text_page(a, palette_byte=False):
    """Страница текста: слово строк, строки ASCII с нулём (у второго
    печатника перед строкой байт палитры)."""
    n = U16(a)
    p = a + 2
    lines = []
    for _ in range(n):
        pal = None
        if palette_byte:
            pal = ROM[p]
            p += 1
        e = ROM.index(b"\0", p)
        s = ROM[p:e].decode("latin1")
        lines.append(OrderedDict([("text", s), ("palette", pal)])
                     if palette_byte else s)
        p = e + 1
    return lines


def text_script(a, palette_byte=False):
    """Скрипт сцены: слово страниц, на страницу слово длительности и
    длинное слово-указатель на страницу."""
    n = U16(a)
    out = []
    for i in range(n):
        p = a + 2 + 6 * i
        out.append(OrderedDict([
            ("show_f", dw(p, signed=False)),
            ("lines", text_page(U32(p + 2), palette_byte))]))
    return OrderedDict([("script", hexa(a)), ("pages", out)])


def caption(a):
    """Надпись крупными буквами: записи (буква, x, y) до отрицательного
    слова; буква 0-25 — A-Z, 26 — слово THE."""
    out, p, prev, s = [], a, None, ""
    while S16(p) >= 0:
        i, x, y = U16(p), S16(p + 2), S16(p + 4)
        if prev and (y != prev[1] or x - prev[0] > 18):
            s += " "
        s += "THE" if i == 26 else chr(65 + i)
        prev = (x, y)
        out.append([i, x, y])
        p += 6
    return OrderedDict([("table", hexa(a)), ("text", s),
                        ("letters", out)])


def actors(a):
    n = U16(a)
    return [OrderedDict([("x", S16(a + 2 + 12 * i)),
                         ("y", S16(a + 4 + 12 * i)),
                         ("anim", hexa(U32(a + 6 + 12 * i))),
                         ("update", hexa(U32(a + 10 + 12 * i)))])
            for i in range(n)]


def layer(m, t, what):
    return OrderedDict([("map", hexa(m)), ("tiles", hexa(t)),
                        ("what", what)])


# ------------------------------------------------------------ экраны

WAIT_NOTE = (u"`$2A562A`: ждать n кадров или нажатия Start; `$2A561A`: "
             u"ровно n кадров")


def boot():
    return OrderedDict([
        ("sega", OrderedDict([
            ("layers", [layer(0x1F7058, 0x1F70BC, u"логотип SEGA, "
                                                  u"карта без сжатия")]),
            ("palette", "$1F74BE"),
            ("hold_f", at(0x28FF5E, "move.w #$003C,d0")),
            ("shine_f", at(0x28FF5E, "move.w #$00B4,d0")),
            ("shine", u"каждые 2 кадра 22 цвета с индекса 2 из $1F7480, "
                      u"сдвиг таблицы от 40 к 0 по 2 ($28FF12)"),
            ("skip", u"нельзя")])),
        ("disney", OrderedDict([
            ("layers", [layer(0x1F753E, 0x1F7772,
                              u"логотип Disney Interactive")]),
            ("palette", "$1F80BA"),
            ("hold_f", at(0x28FFF2, "move.w #$00B4,d0")),
            ("skip", u"Start")])),
        ("presents", OrderedDict([
            ("layers", [layer(0x1F0D58, 0x1F0692,
                              u"presents DONALD Starring In")]),
            ("palette", "$1F0F30"),
            ("plane_b_vscroll", at(0x290056, "move.w #$FFEC,(a5)")),
            ("hold_f", at(0x290056, "move.w #$00B4,d0")),
            ("skip", u"Start")])),
        ("title", OrderedDict([
            ("music", D(0, u"SoundStart(0) перед экраном",
                        at(0x2988CC, "pea (header).w", span=0x40,
                           value=0))),
            ("layers", [layer(0x1F0194, 0x1EFBFE, u"логотип MAUI MALLARD, "
                                                  u"плоскость A"),
                        layer(0x1F8A8E, 0x1F927A, u"задник: лучи, лозы, "
                                                  u"изгородь, плоскость B")]),
            ("palette", "$1F0612"),
            ("logo_vscroll_from", at(0x28FB02, "move.w #$0020,"
                                               "($FFFFE1BE).l")),
            ("logo_vscroll_to", at(0x28FC80, "cmpi.w #$00E0,d0")),
            ("logo_step_px_f", D(1, u"addq.w #1", at(0x28FC80,
                                                     "addq.w #1,d0"))),
            ("then_sprite", OrderedDict([
                ("x", at(0x28FC54, "move.w #$0090,d1")),
                ("y", at(0x28FC54, "move.w #$00C4,d2")),
                ("anim", "$1D6E92")])),
            ("water", u"нижние 48 строк: волна по таблице $1EA892, шаг "
                      u"раз в 3 кадра ($28FD6A); с 190-й строки — "
                      u"построчная вертикаль по прерыванию строки "
                      u"($28FD04): отражение"),
            ("hold_f", at(0x28FB02, "move.w #$0258,d0")),
            ("hold_f_pal", at(0x28FB02, "move.w #$01F4,d0")),
            ("skip", u"Start")])),
    ])


def menus():
    return OrderedDict([
        ("main", OrderedDict([
            ("descriptor", "$1FD440"),
            ("items", [u"START", u"OPTIONS", u"PASSWORD"]),
            ("with_debug", u"$1FD46E: START, OPTIONS, DEBUG, PASSWORD — "
                           u"после паролей IMCARY и MAUIMM"),
            ("timeout_f", at(0x2908FA, "move.w #$0258,d0")),
            ("timeout_f_pal", at(0x2908FA, "move.w #$01F4,d0")),
            ("timeout_rule", u"счёт идёт с входа в меню и нажатиями не "
                             u"сбрасывается; вышел — демо"),
            ("background", layer(0x1F813A, 0x1F927A, u"задник без "
                                                     u"изгороди")),
        ])),
        ("options", OrderedDict([
            ("descriptor", "$1FD4AA"),
            ("items", [
                OrderedDict([("name", "DIFFICULTY"),
                             ("values", ["NORMAL", "HARD", "PRACTICE"]),
                             ("stored", "$FFFD7C")]),
                OrderedDict([("name", "SOUND TEST"), ("stored", "$FFFD85"),
                             ("play", u"C играет номер ($298462)")]),
                OrderedDict([("name", "CONTROLS"), ("stored", "$FFFD7B"),
                             ("values", [
                                 "A-POWERUP / B-SHOOT / C-JUMP",
                                 "A-JUMP / B-SHOOT / C-POWERUP",
                                 "A-SHOOT / B-POWERUP / C-JUMP",
                                 "A-SHOOT / B-JUMP / C-POWERUP",
                                 "A-JUMP / B-POWERUP / C-SHOOT",
                                 "A-POWERUP / B-JUMP / C-SHOOT"])]),
                OrderedDict([("name", "EXIT")])]),
            ("timeout", None),
        ])),
        ("input", OrderedDict([
            ("move", u"вверх-вниз по кругу ($297466)"),
            ("run", u"пункт-процедура — только Start ($2974A4)"),
            ("choose", u"выбор из списка: влево или A — назад, вправо или "
                       u"B — вперёд, по кругу; Start выходит из меню "
                       u"($2974DA)"),
            ("sound_test", u"C — сыграть ($2974B6)"),
            ("layout", u"пункт по центру — столбец $80: (40 - ширина) / 2 "
                       u"клеток"),
        ])),
        ("debug", OrderedDict([
            ("descriptor", "$1FD5BC"),
            ("items", ["ENEMY COLL", "GAME FLOW", "MAP MODE", "LEVEL",
                       "EXIT"])])),
    ])


def passwords():
    out = []
    for i in range(7):
        a = 0x1FCB26 + 6 * i
        lv = U16(a)
        s = ROM[U32(a + 2):U32(a + 2) + 6].decode("latin1")
        out.append(OrderedDict([("password", s),
                                ("start_level", D(lv + 1, u"слово + 1",
                                                  dw(a)))]))
    return OrderedDict([
        ("screen", OrderedDict([
            ("title", u"PASSWORD в (12, 10) клеток ($1EAA1E)"),
            ("letters", D(6, u"moveq #5 / курсор 0..5",
                          at(0x29098C, "cmpi.b #$06,d7"))),
            ("start_value", u"AAAAAA — при включении ($290B4C), дальше "
                            u"остаётся последнее введённое"),
            ("keys", u"влево-вправо — курсор по кругу; вверх или A — "
                     u"буква назад, вниз или B — вперёд, Z <-> A по "
                     u"кругу; Start — проверить"),
            ("ok", u"звук $31, 60 кадров и старт с уровня пароля"),
            ("bad", u"назад в главное меню")])),
        ("levels", out),
        ("debug_unlock", [u"IMCARY", u"MAUIMM"]),
    ])


def story():
    world_procs = OrderedDict()
    tab = 0x1FCC08
    for n in range(23):
        world_procs[str(n)] = hexa(U32(tab + 4 * n))
    scripts = [
        (u"мир 0-2, MOJO MANSION", 0x1EA218, 0x1EA35C),
        (u"мир 3-6, NINJA TRAINING GROUNDS", 0x1EA232, 0x1EA376),
        (u"мир 7-9, MUDDRAKE MAYHEM", 0x1EA272, 0x1EA390),
        (u"мир 10-11, THE SACRIFICE OF MAUI", 0x1EA292, 0x1EA3E6),
        (u"мир 12-13, THE TEST OF DUCKHOOD", 0x1EA2B2, 0x1EA4AC),
        (u"мир 14-15, THE FLYING DUCKMAN", 0x1EA2D8, 0x1EA448),
        (u"мир 16-17, THE REALM OF THE DEAD", 0x1EA30A, 0x1EA46E),
        (u"мир 18, MOJO STRONGHOLD", 0x1EA330, 0x1EA4EA),
    ]
    worlds = []
    for what, s, a in scripts:
        d = OrderedDict([("world", what)])
        d.update(text_script(s))
        d["actors"] = actors(a)
        worlds.append(d)
    worlds.append(OrderedDict([
        ("world", u"бонус 19-22, BABALUAU BABY"),
        ("script", None), ("pages", []),
        ("actors", actors(0x1EA5CA))]))
    titles = OrderedDict()
    for n in range(23):
        titles[str(n)] = caption(U32(0x1FCBAC + 4 * n))["text"]
    level5 = OrderedDict([("after_level", 5), ("hook", "$28E9C6"),
                          ("set_by", u"процедура уровня 5 $2A5F5E -> "
                                     u"$FF1360")])
    level5.update(text_script(0x1EA24C))
    level5["actors"] = actors(0x1EA57C)
    level5["palette"] = "$1F6FD8"
    return OrderedDict([
        ("page_gap_f", at(0x28E698, "moveq #10,d0")),
        ("page_gap_f_second_printer", at(0x28E6CE, "moveq #8,d0")),
        ("font", u"$1EC49E: 64 глифа 16x16, ширины $1EA5FE (12, пробел "
                 u"8); строки по центру X = 160, шаг 16 точек, блок по "
                 u"центру своей точки"),
        ("world_proc_by_level", world_procs),
        ("worlds", worlds),
        ("level_titles", titles),
        ("after_level5", level5),
        ("stronghold_extra", OrderedDict([
            ("after", u"заставки мира 18, слот $FF1364 = $28EABE"),
            ("layers", [layer(0x284BD6, 0x280BA4, u"плоскость A"),
                        layer(0x283D14, 0x280BA4, u"плоскость B")]),
            ("palette", "$2843EA"),
            ("background", u"построчно, как фон уровня 18 ($2A636E)"),
            ("actors", actors(0x1EA5A2)),
            ("ends", u"когда кончатся актёры или по Start")])),
    ])


def card():
    return OrderedDict([
        ("when", u"начало мира: новая игра ($298050), после мира "
                 u"($298178), вход в бонус ($2982AE); ещё демо"),
        ("layers", [layer(0x1F6850, 0x1F6B10, u"силуэт острова, "
                                              u"плоскость A"),
                    layer(0x1F813A, 0x1F927A, u"задник, плоскость B")]),
        ("palette", "$1F6ED8"),
        ("music", u"уже играет музыка уровня: её включают до заставки"),
        ("order", u"страницы сюжета мира (story.worlds) у точки (128, "
                  u"192) -> $FF000C -> буквы названия падают -> "
                  u"выдержка -> конец"),
        ("letter_fall_px_f", at(0x28EE94, "addq.w #8,d0")),
        ("letter_start_above_px", at(0x28EE3C, "subi.w #$0100,d0")),
        ("letters_hold_f", at(0x28EE94, "move.w #$00B4,$6(a0)")),
        ("skip", u"Start в любой момент ($28E704 -> $FF21EC)"),
    ])


def results():
    return OrderedDict([
        ("level_complete", OrderedDict([
            ("when", u"пройден последний уровень мира (+$40 записи)"),
            ("music", at(0x290494, "pea ($000053).w")),
            ("layers", [layer(0x1F6548, 0x1F6B10, u"силуэт острова"),
                        layer(0x1F813A, 0x1F927A, u"задник")]),
            ("palette", "$1F6F58"),
            ("actors", actors(0x1EA9C6)),
            ("caption", caption(0x1FC5E2)),
            ("caption_delay_f", at(0x290494, "move.w #$00A0,d7",
                                   span=0x100)),
            ("caption_fall", u"буквы с y = -32, по 6 точек за кадр, "
                             u"каждая следующая на кадр позже, до y = 72 "
                             u"($2900DE)"),
            ("password_if_treasures_ge",
             at(0x2905EE, "cmpi.w #$000C,($FF1352).l")),
            ("password_layout", u"PASSWORD: с (88, 184) и шесть букв с "
                                u"(112, 200), шаг 16 ($29061E)"),
            ("hold_f", at(0x290494, "move.w #$0226,d0", span=0x140)),
            ("skip", u"Start")])),
        ("bonus_result", OrderedDict([
            ("when", u"после бонусной игры ($28EBFA)"),
            ("base", u"как заставка мира: силуэт и задник, палитра $1F6ED8"),
            ("no_bonus", OrderedDict([
                ("if", u"бонус кончился проигрышем ($FF1A6C < 0) или "
                       u"стопка пуста"),
                ("caption", caption(0x1FC6FE)),
                ("hold_f", at(0x28ED44, "move.w #$00D2,$6(a0)"))])),
            ("prizes", OrderedDict([
                ("apply", u"все предметы стопки $FF21FA применяются сразу "
                          u"($29FEC2): 0 жизнь (до 9), 1 продолжение, 2 "
                          u"потолок +50 и запас +50, 3 серия ниндзя +1"),
                ("show", u"предметы выстраиваются в ряд по центру, Мауи "
                         u"вбегает слева и лопает каждый (звук 1)"),
                ("caption", caption(0x1FC6C6))])),
            ("skip", u"Start")])),
        ("death", OrderedDict([
            ("when", u"игрок погиб ($298136)"),
            ("background", u"чёрный: карта $1FB1D8 в обе плоскости"),
            ("palette", "$1FB158"),
            ("actors", actors(0x1EA992)),
            ("hold_f", at(0x2903A8, "move.w #$006E,d0", span=0xD0)),
            ("skip", u"Start"),
            ("then", u"жизни -1; остались — тот же уровень с точки "
                     u"возврата; нет — экран продолжения или конец "
                     u"игры")])),
        ("continue", OrderedDict([
            ("when", u"жизней не осталось, продолжений больше нуля"),
            ("music", at(0x29066A, "pea ($000056).w")),
            ("layers", [layer(0x1F6548, 0x1F6B10, u"силуэт острова"),
                        layer(0x1F813A, 0x1F927A, u"задник")]),
            ("palette", "$1F6F58"),
            ("actors_first", actors(0x1EA9E0)),
            ("wait_f", at(0x29066A, "move.w #$00A0,d0", span=0x110)),
            ("actors_then", actors(0x1EA9FA)),
            ("actors_then_note", u"стрелки «no» (глиф 27) и «yes» (28) "
                                 u"падают до y = 112 ($290270); после "
                                 u"выбора разъезжаются по 8 точек за кадр"),
            ("caption", caption(0x1FC694)),
            ("caption_delay_f", at(0x29066A, "move.w #$000A,d7",
                                   span=0x130)),
            ("choice", u"ждёт без срока: вправо — да ($FF2150 = 1), "
                       u"влево — нет (-1)"),
            ("after_choice_f", at(0x29066A, "move.w #$003C,d0",
                                  span=0x170, nth=1)),
            ("yes", u"продолжения -1, жизни и здоровье — как на старте, "
                    u"точка возврата стёрта: уровень с начала"),
            ("no", u"конец игры")])),
        ("game_over", OrderedDict([
            ("music", at(0x28ED64, "pea ($000097).w")),
            ("base", u"силуэт острова и задник, палитра $1F6F58"),
            ("actors", actors(0x1EA5D8)),
            ("caption", caption(0x1FC72A)),
            ("hold_after_caption_f", at(0x28EDE2, "move.w #$00F0,"
                                                  "$6(a0)")),
            ("skip", u"Start"),
            ("then", u"снова заставки с логотипа SEGA")])),
        ("ending", OrderedDict([
            ("when", u"пройден уровень 18"),
            ("music", at(0x28DCEC, "pea ($000099).w")),
            ("layers", [layer(0x1F2CEC, 0x1F0FB0, u"пальмы"),
                        layer(0x1F3270, 0x1F0FB0, u"ночное небо, берег "
                                                  u"и вода")]),
            ("palette", "$1F3A4A"),
            ("tiles_anim", "$1E9672"),
            ("actors", actors(0x1E9272)),
            ("monologue", text_script(0x1E92F0)),
            ("credits_in_scene", text_script(0x1E9352, True)),
            ("then_scroll", OrderedDict([
                ("layers", [layer(0x1F3B4A, 0x1F58B8, u"свиток титров "
                                                      u"40 x 404"),
                            layer(0x1F8A8E, 0x1F927A, u"задник "
                                                      u"титульного")]),
                ("palette", "$1F5BF8"),
                ("scroll", u"плоскость A вверх на 1 точку раз в 2 кадра "
                           u"до конца свитка ($28DF4A)"),
                ("hold_f", at(0x28DE36, "move.w #$1824,d0", span=0xC0)),
                ("skip", u"Start")])),
            ("scroll_only_if", u"речь дошла до конца ($FF000E); Start на "
                               u"концовке пропускает и свиток"),
            ("unused_caption", caption(0x1FC632)),
            ("then", u"снова заставки с логотипа SEGA")])),
    ])


def demo():
    out = []
    for i in range(3):
        a = 0x1FD7DC + 6 * i
        p = U32(a + 2)
        # первая пара звучит один кадр ($2A5684 ставит счётчик $FFFFFD91 = 1),
        # каждая следующая — свой счётчик; subq.b/bne ($2A56CE): 0 — 256 кадров
        q, frames = p + 2, 1
        while ROM[q] != 0:
            frames += ROM[q + 1] or 256
            q += 2
        out.append(OrderedDict([("level", dw(a)), ("stream", hexa(p)),
                                ("frames", D(frames, u"первая пара — один кадр, "
                                                     u"дальше сумма счётчиков до "
                                                     u"нуля в кнопках; счётчик 0 — "
                                                     u"256 кадров")),
                                ("end", hexa(q))]))
    return OrderedDict([
        ("when", u"главное меню простояло свой срок"),
        ("count", at(0x2981B8, "cmpi.w #$0003,d1")),
        ("order", u"по кругу 0, 1, 2 ($FF21F4)"),
        ("stream", u"пары байт (кнопки, кадров); кнопки в «активном "
                   u"нуле», ноль — конец ($2A5694)"),
        ("ends", u"поток кончился — снова заставки с SEGA; Start — "
                 u"сразу титульный экран и меню"),
        ("shows_card", True),
        ("demos", out)])


def pause():
    return OrderedDict([
        ("key", u"Start в уровне переключает паузу ($298C50)"),
        ("not_during", u"землетрясения уровня 3 ($FF217C)"),
        ("frozen", u"объекты и анимация стоят, спрайты рисуются; музыка "
                   u"не глушится"),
        ("hud", u"лицо в HUD перебирает три кадра $1EF65E + $240"),
        ("hud_every_f", D(12, u"move.b #$0B: перезарядка 11",
                          at(0x298BEE, "move.b #$0B,($FF21F6).l"))),
        ("debug_only", u"при открытом DEBUG: Start + C — запасы 1 и 3 по "
                       u"999; Start + A — гибель; Start + B — уровень "
                       u"пройден и жетон бонуса"),
    ])


def hud():
    return OrderedDict([
        ("how", u"пять спрайтов-объектов с кадром в ОЗУ, созданы $299028 "
                u"по таблице $298FBA; перерисовываются только при "
                u"изменении значения ($299306)"),
        ("elements", [
            OrderedDict([("what", u"жизни: одна большая цифра"),
                         ("x", 28), ("y", 30), ("w", 16), ("h", 16),
                         ("glyphs", "$1ECC9E"),
                         ("max", at(0x299306, "cmpi.w #$0009,d0"))]),
            OrderedDict([("what", u"лицо: утка (0) или ниндзя (1)"),
                         ("x", 41), ("y", 22), ("w", 24), ("h", 24),
                         ("glyphs", "$1EF65E"),
                         ("blink_f", at(0x299306, "move.w #$005A,"
                                                  "($FF19FE).l",
                                        span=0x100)),
                         ("rule", u"ниндзя — 1; утка без топлива — 0; "
                                  u"утка с топливом — раз в 90 кадров "
                                  u"меняет 0 и 1: можно превратиться")]),
            OrderedDict([("what", u"здоровье: три малые цифры, ведущие "
                                  u"нули пустые"),
                         ("x", 39), ("y", 48), ("w", 24), ("h", 8),
                         ("glyphs", "$1EE99E"),
                         ("max", at(0x299306, "cmpi.w #$0999,d0"))]),
            OrderedDict([("what", u"утка и уменьшенный: значки жуков "
                                  u"выбранного набора (до трёх); ниндзя: "
                                  u"вращающийся инь-ян"),
                         ("x", 284), ("y", 24), ("w", 32), ("h", 32),
                         ("glyphs", u"$1EF3DE (жуки, по 4 тайла), "
                                    u"$1EEBDE (инь-ян, 16 кадров)"),
                         ("yinyang_every_f", D(4, u"перезарядка 3",
                                               at(0x299236,
                                                  "move.b #$03,"
                                                  "($FF19FA).l"))),
                         ("sets", [list(ROM[0x2990FC + 4 * s:
                                            0x2990FC + 4 * s + 4])
                                   for s in range(9)]),
                         ("sets_note", u"на набор: сколько значков, потом "
                                       u"их номера; набор 8 — «нет "
                                       u"оружия»")]),
            OrderedDict([("what", u"утка: запасы по значкам, по две "
                                  u"цифры; ниндзя: топливо тремя цифрами"),
                         ("x", 284), ("y", 56), ("w", 32), ("h", 16),
                         ("ammo_max", at(0x2990F0, "cmpi.w #$0099,d0")),
                         ("fuel_max", at(0x299236, "cmpi.w #$0999,d0",
                                         span=0xD0)),
                         ("free_set", u"у набора 0 и «нет оружия» число "
                                      u"не пишется")]),
        ]),
        ("coords", u"координаты — точки объектов-спрайтов в экранных "
                   u"точках; где у кадра начало, в выгрузке не сведено"),
        ("unused", u"шкала топлива из $1EACF0 (восемь тайлов, $296A20) "
                   u"в игре не вызывается"),
    ])


def flow():
    return OrderedDict([
        ("boot", [u"sega", u"disney", u"presents", u"title", u"menu"]),
        ("power_on_only", u"пароль = AAAAAA ($290B4C)"),
        ("menu_start", u"новая игра: раскладка, сложность (запас, жизни, "
                       u"продолжения $1FD7EE), сброс $2983E2, уровень 0 "
                       u"(или из пароля), заставка мира, уровень"),
        ("menu_timeout", u"демо"),
        ("level_won", u"+$40 у уровня — LEVEL COMPLETE (и пароль), бонус, "
                      u"если есть жетон, заставка следующего мира; иначе "
                      u"сразу следующий уровень; после уровня 5 — сцена "
                      u"$28E9C6"),
        ("level18_won", u"концовка и титры, потом снова с SEGA"),
        ("died", u"экран гибели -> жизни -> продолжение -> GAME OVER"),
        ("music_restarts", u"при входе в игру, после гибели, после мира; "
                           u"между уровнями одного мира музыка не "
                           u"перезапускается"),
        ("fade_f", D(16, u"PaletteFadeTo: $10 шагов",
                     at(0x290C70, "move.w #$0010,($FFFFDEC2).w",
                        span=8))),
    ])


def build():
    return OrderedDict([
        ("flow", flow()),
        ("boot", boot()),
        ("menus", menus()),
        ("password", passwords()),
        ("card", card()),
        ("story", story()),
        ("results", results()),
        ("demo", demo()),
        ("pause", pause()),
        ("hud", hud()),
    ])


def main():
    tree = build()
    if SJ.ERRORS:
        for e in SJ.ERRORS:
            print(u"ошибка: %s" % e)
        return 1
    vals, srcs = SJ.split(tree)
    if "--text" in sys.argv:
        st = vals["story"]
        for w in st["worlds"] + [st["after_level5"]]:
            print(u"== %s" % w.get("world", u"после уровня 5"))
            for p in w["pages"]:
                print(u"  %4d  %s" % (p["show_f"], u" / ".join(p["lines"])))
        return 0
    if "--check" in sys.argv:
        print(u"проверено чисел: %d" % SJ.count(tree))
        return 0
    out = OUT("export")
    if not os.path.isdir(out):
        os.makedirs(out)
    meta = OrderedDict([
        ("game", "Maui Mallard in Cold Shadow (Mega Drive)"),
        ("generator", "tools/screenspec.py"),
        ("spec", "docs/mauimallard/screens.md"),
        ("units", u"_f — кадры при 60 Гц; координаты — экранные точки "
                  u"320 x 224; адреса — строки «$xxxxxx»"),
        ("waits", WAIT_NOTE)])
    doc = OrderedDict([("meta", meta)])
    doc.update(vals)
    for name, data in (("screens.json", doc),
                       ("screens.sources.json", srcs)):
        p = os.path.join(out, name)
        with io.open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=1))
            f.write(u"\n")
        print(p)
    print(u"чисел: %d" % SJ.count(tree))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
