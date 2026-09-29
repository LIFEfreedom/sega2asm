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
Узел `vdp` (M8c) — сами слои для показа как у VDP: тайлы девяти слоёв после
LZSS `$29766A` листами индексами (`screens/tiles_XXXXXX.png`), карты — имена без
базы тайлов, палитры — 64 слова CRAM; окна ROM как есть — `screens/text.bin`
(ширины шрифта, волна воды, надпись PASSWORD, читы) и `screens/tables.bin`
(потоки демо, пароли, описатели меню, раскладки, демо, сложность).
"""
import io
import json
import os
import struct
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import specjson as SJ                                        # noqa: E402
from specjson import D, at, dl, dw, hexa                     # noqa: E402
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
            ("background", layer(0x1F8A8E, 0x1F927A, u"задник с "
                                                     u"изгородью ($28FE40)")),
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
        ("key", u"Start в уровне переключает паузу ($298C50): $FF132C = 1 "
                u"или 0; при снятии $FF19FE = 0, $FF1A00 = $FFFF, "
                u"$FF21F6 = $FF21F7 = 0 — лицо HUD перерисуется"),
        ("not_during", u"землетрясения уровня 3 ($FF217C)"),
        ("frozen", u"задача объектов $298E06 при $FF132C = 1 только строит "
                   u"список спрайтов ($298E4E): обработчики, скрипты, "
                   u"построитель фона (с ним анимация палитры), уборка и "
                   u"HUD стоят; задача игрока — ветка паузы $298D24 (при "
                   u"$FF1330 — ничего); обработчик кадра уровня $2A52E6 "
                   u"вычитает единицу из счётчика кадров $FFFFE196 (он "
                   u"стоит), не пишет очередь цветов и прокрутку; вспышка "
                   u"уровней 3-5 пропускает шаг ($2A5908); музыка "
                   u"не глушится"),
        ("hud", u"лицо в HUD перебирает три кадра $1EF65E + $240 "
                u"($298BEE): передача прямо из ROM в VRAM записи лица, "
                u"$90 слов"),
        ("hud_every_f", D(12, u"move.b #$0B: перезарядка 11",
                          at(0x298BEE, "move.b #$0B,($FF21F6).l"))),
        ("debug_only", u"при открытом DEBUG ($FF2180): Start + C — запасы "
                       u"1 и 3 по 999 ($298BB0); Start + A — гибель; "
                       u"Start + B — уровень пройден и жетон бонуса"),
        ("dead", u"прокрутка карты и шаг по кадру в паузе ($298D3A-$298D98, "
                 u"$FF132C = 2 и $2A5296) — только при $FF2181, а его "
                 u"никто не ставит"),
    ])


# Окно ROM со шрифтом и глифами HUD, как есть: шрифт $1EC49E ($298932, $2000
# байт), за ним 44 тайла $1EE49E, малые цифры, инь-ян, значки, лица утки и
# ниндзя и три лица паузы; дальше лежат тайлы логотипа ($1EFBFE).
GLYPHS = (0x1EC49E, 0x1EFBFE)
FACE = 0x120                       # кадр лица 24 x 24: девять тайлов
HUD_RAM = (0xFF1496, 0xFF19F0)     # пять кадров HUD в ОЗУ подряд


def hud_table():
    """$298FBA: пять указателей на записи по 18 байт, их разбирает $299030."""
    rows = []
    for k in range(5):
        p = U32(0x298FBA + 4 * k)
        rows.append(OrderedDict([
            ("x", dw(p)), ("y", dw(p + 2)),
            ("vram", dw(p + 4, signed=False)),
            ("frame", dl(p + 6, addr=True)),
            ("palette", dw(p + 10)), ("shape", dw(p + 12)),
            ("slot", dl(p + 14, addr=True))]))
    return rows


def hud():
    return OrderedDict([
        ("how", u"пять спрайтов-объектов с кадром в ОЗУ, созданы $299028 "
                u"по таблице $298FBA; перерисовываются только при "
                u"изменении значения ($299306)"),
        ("table", hud_table()),
        ("table_note", u"x, y — точка объекта на экране; vram — своё место "
                       u"($298EFA); frame — кадр в ОЗУ: запись из шаблона "
                       u"$1E9260 ($298F26), источник тайлов сразу за ней, "
                       u"$298F9A ставит ряд палитры (биты 13-14 имени) и "
                       u"форму куска; slot — где $299028 держит адрес "
                       u"записи объекта"),
        ("frame_template", OrderedDict([
            ("at", "$1E9260"),
            ("words", [dw(0x1E9260 + 2 * i, signed=False)
                       for i in range(9)]),
            ("note", u"один кусок в (-16, -16), общая коробка -16..15 по "
                     u"обеим осям; последнее длинное — адрес тайлов / 2")])),
        ("ram", OrderedDict([("at", "$%06X" % HUD_RAM[0]),
                             ("length", HUD_RAM[1] - HUD_RAM[0])])),
        ("image", OrderedDict([("file", "screens/glyphs.bin"),
                               ("base", "$%06X" % GLYPHS[0]),
                               ("length", GLYPHS[1] - GLYPHS[0])])),
        ("glyphs", OrderedDict([
            ("font", at(0x298932, "lea ($1EC49E).l,a0", addr=True)),
            ("lives", at(0x299306, "lea ($1ECC9E).l,a2", addr=True)),
            ("faces", at(0x299306, "lea ($1EF65E).l,a2", addr=True)),
            ("small_digits", at(0x299306, "lea ($1EE99E).l,a6",
                                addr=True)),
            ("bugs", at(0x299120, "lea ($1EF3DE).l,a5", addr=True)),
            ("yinyang", at(0x299236, "movea.l #$001EEBDE,a2", addr=True)),
            ("pause_faces", D("$%06X" % (0x1EF65E + 2 * FACE),
                              u"лица паузы — за двумя лицами HUD",
                              at(0x298BEE, "addi.l #$001EF65E,d1",
                                 addr=True),
                              at(0x298BEE, "addi.l #$00000240,d1"))),
        ])),
        ("hud_tiles", OrderedDict([
            ("at", at(0x29877C, "lea ($1EE49E).l,a0", addr=True, span=8)),
            ("length", at(0x29877C, "move.w #$0580,d0", signed=False,
                          span=8)),
            ("note", u"уходят в VRAM на входе в уровень ($296B48), место — "
                     u"после тайлов уровня")])),
        ("caches_at_entry", OrderedDict([
            ("fuel", at(0x2985BE, "move.w #$FFFE,($FF1358).l",
                        signed=False)),
            ("lives", at(0x2985BE, "move.w #$FFFF,($FF135A).l",
                         signed=False)),
            ("health", at(0x2985BE, "move.w #$FFFF,($FF135C).l",
                          signed=False)),
            ("set", at(0x299028, "move.w #$FFFE,($FF19FC).l",
                       signed=False)),
            ("face", at(0x299028, "move.w #$FFFF,($FF1A00).l",
                        signed=False)),
            ("note", u"$2985BE — кэши топлива, жизней и здоровья; $299028 — "
                     u"кэш набора, лицо, счётчики $FF19FA = 3, $FF19FB = 0, "
                     u"$FF19FE = 0: первая перерисовка пишет всё")])),
        ("skip_flag", u"$FF135E: писатели столбцов и строк плоскости "
                      u"($2912FA, $291336, $291520, $291560) ставят 1, когда "
                      u"окно сдвинулось; в этом кадре $299306 ничего не "
                      u"перерисовывает и гасит флаг"),
        ("redraw", u"после каждой перезаписи кадра — бит 9 флагов записи; "
                   u"короткая команда 1 скрипта $1D6D78 в следующем кадре "
                   u"гасит его и показывает кадр +$3A заново: передача "
                   u"тайлов из ОЗУ уходит в гашение после этого кадра"),
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
                         ("blink_period_f", D(91, u"перезарядка 90, счёт "
                                                  u"subq.w / bpl: смена, "
                                                  u"когда счётчик ушёл "
                                                  u"ниже нуля",
                                              at(0x299306,
                                                 "move.w #$005A,"
                                                 "($FF19FE).l",
                                                 span=0x100))),
                         ("rule", u"ниндзя — 1; утка без топлива — 0; "
                                  u"утка с топливом — раз в 91 кадр "
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
                                      u"не пишется"),
                         ("ninja", u"у ниндзя кадр пуст, а три цифры "
                                   u"топлива ($299236, шаг 96 байт) "
                                   u"пишутся в нижний ряд кадра значков "
                                   u"(его кадр в ОЗУ + $E0)")]),
        ]),
        ("coords", u"координаты — точки объектов-спрайтов в экранных "
                   u"точках; кадр в (-16, -16) от точки (шаблон $1E9260)"),
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


# ------------------------------------------------------------ слои для ремейка

# Слои экранов (open-questions.md 26: карты и тайлы, упакованные LZSS $29766A; карта — слова w, h и w * h имён).
# Ремейк рисует экраны как VDP: тайлы — лист индексами (как levelNN_tiles.png), карты и палитры — числа.
SCREEN_TILES = [
    (0x1F0692, u"presents ($290084)"),
    (0x1EFBFE, u"логотип MAUI MALLARD ($28FB3A)"),
    (0x1F927A, u"задник с лучами, лианами и изгородью: титульный, меню, заставка мира, титры"),
    (0x1F0FB0, u"пальмы со звёздами, ночное небо с берегом (концовка)"),
    (0x1F6B10, u"силуэты острова (заставка мира, итоги)"),
    (0x1F58B8, u"свиток титров"),
    (0x1FBBDC, u"экран гибели ($2903D4, $2903F2)"),
]
SCREEN_MAPS = [
    (0x1F0D58, u"presents DONALD Starring In ($2900AE, плоскость B)"),
    (0x1F0194, u"логотип MAUI MALLARD ($28FB2E, плоскость A; 56 строк — $28D622 дописывает их по вертикали)"),
    (0x1F8A8E, u"задник с изгородью: титульный ($28FB34) и меню ($28FE40), плоскость B"),
    (0x1F813A, u"задник без изгороди (заставка мира, итоги)"),
    (0x1F2CEC, u"пальмы со звёздами"),
    (0x1F3270, u"ночное небо с берегом"),
    (0x1F6548, u"силуэт острова"),
    (0x1F6850, u"силуэт острова (заставка мира)"),
    (0x1F3B4A, u"свиток титров 40 x 404"),
    (0x1FB1D8, u"экран гибели, обе плоскости ($2903E8, $290406 — $296774: карта в ROM не сжата)"),
]
# Карты, которые ROM пишет без распаковки ($296774 -> $29672C читает w, h и имена прямо из ROM).
RAW_MAPS = {0x1FB1D8}
SCREEN_PALETTES = [
    (0x1F0F30, u"presents ($2900BA PaletteFadeTo)"),
    (0x1F0612, u"титульный ($28FB78 PaletteFadeTo)"),
    (0x1FB0D8, u"меню ($28FE74 PaletteFadeTo)"),
    (0x1F3A4A, u"концовка"),
    (0x1F5BF8, u"титры"),
    (0x1F6ED8, u"заставка мира"),
    (0x1F6FD8, u"сцена после уровня 5 ($28EA38 PaletteFadeTo)"),
    (0x1F6F58, u"LEVEL COMPLETE, продолжение ($2905A8, $290750 PaletteLoad), GAME OVER ($28ED9A PaletteFadeTo)"),
    (0x1FB158, u"экран гибели ($290454 PaletteLoad)"),
]
# Окна ROM как есть: движок описателей меню, пароли, потоки демо, таблицы ширин шрифта и волны воды читают байты.
SCREEN_WINDOWS = [
    ("text", 0x1E967A, 0x1EAA35, u"тексты страниц $1E967A-$1E9E0D (слово — сколько строк, строки с нулём после "
                                 u"каждой), страницы сюжета миров $1EA218-$1EA330 и сцены после уровня 5 $1EA24C (слово — "
                                 u"сколько страниц, на страницу слово кадров и адрес текста), списки актёров сцен "
                                 u"$1EA35C-$1EA5D8 и экранов $1EA992-$1EA9FA (слово — сколько, по 12 байт: x, y, "
                                 u"скрипт, обработчик), кадр буквы шрифта $1EA840, ширины шрифта $1EA5FE и $1EA852, "
                                 u"волна воды титульного $1EA892 (256 байт), PASSWORD: $1EAA14, надпись PASSWORD "
                                 u"$1EAA1E, читы $1EAA27/$1EAA2E (буквы + 1)"),
    ("tables", 0x1FC23E, 0x1FD806, u"названия миров крупными буквами $1FC23E-$1FC5E2 ($28EE28), надписи LEVEL "
                                   u"COMPLETE $1FC5E2, CONTINUE $1FC694, COWABUNGA $1FC6C6, NO BONUS $1FC6FE, GAME "
                                   u"OVER $1FC72A (по 6 байт: буква, x, y, конец — "
                                   u"$FFFF), потоки демо $1FC75C/$1FC84C/$1FC9C0, слова паролей $1FCAEE, таблица паролей "
                                   u"$1FCB26, указатели уровней $1FCB50, названия $1FCBAC, процедуры миров $1FCC08, "
                                   u"описатели меню $1FD440/$1FD46E/$1FD4AA/$1FD5BC, раскладки $1FD7AC, демо $1FD7DC, "
                                   u"сложность $1FD7EE"),
]


def tiles_sheet(data, path):
    """Тайлы 8x8 по 32 в ряд, серая шкала 17 * индекс, индекс 0 прозрачен (как levelNN_tiles.png)."""
    import sprites as S
    cnt = len(data) // 32
    cols = 32
    w, h = cols * 8, (cnt + cols - 1) // cols * 8
    buf = [(0, 0, 0, 0)] * (w * h)
    for i in range(cnt):
        ox, oy = (i % cols) * 8, (i // cols) * 8
        for y in range(8):
            for xb in range(4):
                b = data[i * 32 + y * 4 + xb]
                for half, c in ((0, b >> 4), (1, b & 15)):
                    buf[(oy + y) * w + ox + xb * 2 + half] = (17 * c, 17 * c, 17 * c, 255 if c else 0)
    S.png(path, w, h, buf)


def vdp_layers(outdir):
    """-> узел vdp для screens.json; тайлы пишет в outdir (screens/tiles_XXXXXX.png), окна — screens/<имя>.bin."""
    import lzss
    tiles = OrderedDict()
    for a, what in SCREEN_TILES:
        data, _ = lzss.unpack(a, ROM)
        if len(data) % 32:
            raise ValueError("тайлы $%06X: %d байт — не целое число тайлов" % (a, len(data)))
        name = "tiles_%06X.png" % a
        if outdir:
            tiles_sheet(data, os.path.join(outdir, name))
        tiles[hexa(a)] = OrderedDict([("what", what), ("count", len(data) // 32), ("png", "screens/" + name)])
    maps = OrderedDict()
    for a, what in SCREEN_MAPS:
        if a in RAW_MAPS:
            w, h = struct.unpack_from(">HH", ROM, a)
            data = ROM[a:a + 4 + 2 * w * h]
        else:
            data, _ = lzss.unpack(a, ROM)
        w, h = struct.unpack_from(">HH", data, 0)
        if len(data) != 4 + 2 * w * h:
            raise ValueError("карта $%06X: %d байт при %d x %d" % (a, len(data), w, h))
        maps[hexa(a)] = OrderedDict([("what", what), ("width", w), ("height", h),
                                     ("names", list(struct.unpack_from(">%dH" % (w * h), data, 4)))])
    palettes = OrderedDict()
    for a, what in SCREEN_PALETTES:
        palettes[hexa(a)] = OrderedDict([("what", what), ("cram", list(struct.unpack_from(">64H", ROM, a)))])
    windows = OrderedDict()
    for name, a, end, what in SCREEN_WINDOWS:
        if outdir:
            with open(os.path.join(outdir, name + ".bin"), "wb") as f:
                f.write(ROM[a:end])
        windows[name] = OrderedDict([("what", what), ("from", hexa(a)), ("to", hexa(end)),
                                     ("file", "screens/%s.bin" % name)])
    return OrderedDict([
        ("about", u"слои экранов вне уровня для показа как у VDP: тайлы после LZSS $29766A — лист индексами, "
                  u"карты — имена VDP без базы тайлов (её прибавляет $29672C), палитры — 64 слова CRAM"),
        ("tiles", tiles), ("maps", maps), ("palettes", palettes), ("windows", windows)])


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
    glyphs = os.path.join(out, "screens")
    if not os.path.isdir(glyphs):
        os.makedirs(glyphs)
    doc["vdp"] = vdp_layers(glyphs)
    for name, data in (("screens.json", doc),
                       ("screens.sources.json", srcs)):
        p = os.path.join(out, name)
        with io.open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=1))
            f.write(u"\n")
        print(p)
    p = os.path.join(glyphs, "glyphs.bin")
    with open(p, "wb") as f:
        f.write(ROM[GLYPHS[0]:GLYPHS[1]])
    print(p)
    print(u"чисел: %d" % SJ.count(tree))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
