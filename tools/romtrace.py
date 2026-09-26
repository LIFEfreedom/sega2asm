#!/usr/bin/env python3
"""Трасса ROM: сама игра на ядре 68000 без картинки и звука, по кадрам.

    SEGA2ASM_CONFIG=platformer.yaml python tools/romtrace.py           все сценарии
    SEGA2ASM_CONFIG=platformer.yaml python tools/romtrace.py idle      выбранные
    SEGA2ASM_CONFIG=platformer.yaml python tools/romtrace.py --check   дважды, сверить
    SEGA2ASM_CONFIG=platformer.yaml python tools/romtrace.py --list

Нужен `unicorn` 2.1.4 (`pip install unicorn==2.1.4`, ядро QEMU под GPLv2 —
только для этого инструмента). Пишет `out/mauimallard/export/traces/<имя>.json`:
по кадру уровня — запись игрока `$FFFFE1CA` (`$54` байта) и участки ОЗУ из
`LAYOUT` (переменные шага игрока, пульт, камера, счётчик кадров, ГСЧ).
Ремейк проигрывает ту же запись пульта и сверяет каждый кадр.

Машина. Картинки, звука и тактов нет, только то, от чего зависит логика:

* ПЗУ, ОЗУ `$FF0000` с зеркалом `$FFFF0000` (адреса `.w` и `.l $FFFFxxxx`);
* VDP: записи в порты идут в модель памяти `tools/vdp.py` (регистры, VRAM,
  CRAM, VSRAM, DMA); её начальные регистры — таблица `$297A72` (+26): загрузку
  `$297A1C` ROM здесь пропускает, потому что порт `$A10008` читается не нулём,
  как при тёплом перезапуске. Чтения портов от модели не зависят: статус —
  FIFO пуст, DMA не занят, бит 3 (кадровое гашение) внутри прерывания кадра
  поднят (очередь цветов `$2A5726` сбрасывается, только увидев его), а в
  основном потоке меняется на каждом чтении, чтобы ожидание кадра не висело;
  чтение статуса сбрасывает недописанную команду; счётчик HV — ноль;
* Z80: шина выдана сразу, ОЗУ Z80 — просто память; YM — ноль;
* пульт на 3 кнопки в первом порту, по линии TH, как его читает `$290B5E`;
* кадр: основной поток — `BUDGET` команд, потом прерывание уровня 6
  (`$2968FE`), если маска его пускает; обработчик идёт до своего `rte`.
  В нём и выполняется вся логика кадра (списки `$FFFFE166`, `$FFFFE176`),
  так что «лага» нет: следующий кадр — после `rte`. Прерывание, пришедшее
  под маской, теряется (на железе оно бы дождалось снятия маски); на кадры
  уровня это не влияет — там основной поток стоит в пустом цикле. HBlank
  (`$296976`) не вызывается.

Две особенности `unicorn` и что с ними сделано:

* `rte` ядро само не выполняет, а отдаёт в хук прерываний (номер `$100`):
  хук снимает со стека SR и PC (кадр 68000, без слова формата);
* чтение SR через API портит флаги, которые QEMU держит лениво (после него
  `bcs` видит чужой перенос), поэтому SR читает сам процессор: заглушка
  `move.w sr,<ячейка>`. Вход в прерывание тоже через заглушку: PC кладётся
  на стек извне, SR — командой `move.w sr,-(a7)`.

Путь до уровня: с включения каждые 90 кадров 4 кадра держится Start (логотип,
титульный экран, меню, заставка мира). На входе в `LevelSetup` (`$2984C2`)
номер уровня `$FF1B14` подменяется на нужный, и Start больше не жмётся.
Точку возрождения `$FFFFFD86` сценарий может подменить (`at`) перед `$2987B8`,
где она становится позицией игрока. Первый вход в задачу игрока `$298C44` —
вход в уровень: снимок `entry` (до первого шага игрока; сценарий `fly`
включает здесь отладочный полёт `$FFFFFD84`); с этого кадра идёт запись
пульта сценария, и после каждого кадра снимается `frames[k]` — до первого
кадра с сигналом выхода `$FF1A6C` включительно или до `record` кадров.

Сценарии: ходы утки на уровнях 0, 1, 3, 5, 7, 14, 15, 17; клетки урона,
шипы, восходящие потоки, выход и запрет урона на уровнях 2, 3, 10, 12, 16 (гибель
от урона — `hazard_death_16`); присед, лианы уровней 0, 1, 7 и облик «тень»
уровня 0; `set` и `poke` задают слова записи игрока и байты
ОЗУ на входе, до снимка; `sprites_*` (проверка sprites) снимают ещё
таблицу спрайтов `$FF050C`, её счётчик `$FFFFE1BA` и распределитель VRAM
(`SPRITE_LAYOUT`) на уровнях 0, 1 и 10; вход в каждый
уровень 0-18 (`enter_NN`, один кадр); три демо (`demo_N`: запись пульта
взята из потока ROM `$1FD7DC` и развёрнута обратно через раскладку 0, кадры
не снимаются — ремейк проигрывает запись сам); моноцикл бонуса 19 — только
для камеры.

Картинки: сценарий с `pictures` рисует кадры k из памяти VDP так, как их
показывает приставка — то, что очередь DMA кадра k отправила в начале
прерывания кадра k + 1, на входе в задачу игрока `$298C44` (после записанных
кадров игра идёт дальше с отпущенным пультом). В `export/pictures/`:
`<сценарий>_<k>.png` — без спрайтов с тайлами VRAM, занятой при входе после
тайлов уровня (HUD, объекты процедуры уровня — их у ремейка пока нет),
`<сценарий>_<k>_planes.png` — без спрайтов вовсе, и `pictures.json` —
уровень, кадр, камера, счётчик кадров, CRAM. Кадр в режиме тени и подсветки
(уровень 1) не рисуется: в индексе остаётся причина.

Сценарий без объектов (`objects: false`) заменяет на `nop` вызов конструктора
в обоих обходах клеток (`$2914EA` — столбец, `$291800` — строка): объекты из
клеток не заводятся. Заплатки перечислены в выходе.
"""
import argparse
import ctypes
import hashlib
import io
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT, rom_bytes  # noqa: E402
from vdp import Vdp  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    from unicorn import (Uc, UcError, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UC_PROT_ALL,
                         UC_PROT_READ, UC_PROT_EXEC, UC_HOOK_INTR, UC_HOOK_CODE,
                         UC_HOOK_MEM_UNMAPPED, __version__ as UC_VERSION)
    import unicorn.m68k_const as M
except ImportError:
    sys.exit("нужен unicorn: pip install unicorn==2.1.4")

VINT_VECTOR = 0x78
VDP_INIT = 0x297A72 + 26       # data_46: d5-d7, a0-a4, затем 24 байта регистров VDP
LEVEL_SETUP = 0x2984C2
PLAYER_POSITION = 0x2987B8     # move.l ($FFFFFD86).w,$12(a0): точка возрождения становится позицией
RESPAWN = 0xFFFFFD86
DEBUG_FLIGHT = 0xFFFFFD84        # не ноль — отладочный полёт $2A5114 и камера $29798E
EXIT = 0xFF1A6C
PLAYER_TASK = 0x298C44
LEVEL_NUMBER = 0xFF1B14
DEMO = 0xFFFFFD90            # не ноль — идёт демо, пульт из записи
PLAYER = 0xFFFFE1CA
PLAYER_LENGTH = 0x54
BUDGET = 12000             # команд основного потока между кадрами (~ такты / 10)
HANDLER_LIMIT = 3_000_000  # команд обработчику кадра, дальше — ошибка
BOOT_LIMIT = 6000          # кадров до входа в уровень

# Кнопки в порядке байта пульта (активная единица): U D L R B C A S.
BUTTONS = "UDLRBCAS"

# Участки ОЗУ, снимаемые после каждого кадра: (адрес, длина, что это).
LAYOUT = [
    (0xFFFFE196, 2, "счётчик кадров"),
    (0xFFFFE14E, 8, "ГСЧ $296B0C"),
    (0xFFFFE1BC, 4, "камера с тряской (показанное окно)"),
    (0xFFFFE120, 8, "карты столкновений: вторая (облик «тень»), текущая"),
    (0xFF1314, 4, "скорость камеры"),
    (0xFF131C, 4, "тряска камеры"),
    (0xFF1322, 6, "сдвиг цели камеры, флаги шага"),
    (0xFF1A5A, 4, "камера без тряски"),
    (0xFF1A8C, 8, "пределы"),
    (0xFF1A6A, 4, "выход открыт, сигнал выхода"),
    (0xFF1A00, 0x20, "пульт: удержание A, держат, нажали, изменилось, кольца"),
    (0xFF1330, 0x10, "таблицы формы, форма, полуширина, топливо"),
    (0xFF1340, 0x18, "с $FF1342 запрет урона, жизни, запас, потолок, начальные, продолжения, серия ниндзя"),
    (0xFF136A, 2, "тарзанка"),
    (0xFF138C, 2, "скорость при посадке"),
    (0xFF1B4E, 2, "потолок скорости падения"),
    (0xFF04DC, 2, "потолок от объектов"),
    (0xFF2130, 0x10, "шаг игрока: код клетки, вода, флаги, запреты"),
    (0xFF2168, 8, "снос"),
    (0xFFFFE1C6, 4, "пульт: сырой байт (активный ноль), держат, нажали"),
    (0xFFFFFD7A, 8, "раскладка пульта, сложность, отладка: уровень старта, столкновения"),
    (0xFFFFFD84, 6, "отладочный полёт, точка возрождения"),
]

# Сценарии с проверкой sprites снимают ещё таблицу спрайтов и распределитель VRAM.
SAT_ENTRIES = 20           # записей $FF050C: утка с объектом сноса и HUD — до 11 на пробах
HEAP_NODES = 16            # узлов распределителя: при выключенных объектах занято не больше пяти
SPRITE_LAYOUT = [
    (0xFFFFE1BA, 2, "сколько записей в таблице спрайтов ($2962EC)"),
    (0xFF050C, 8 * SAT_ENTRIES, "таблица спрайтов $29612E: Y, размер и связь, имя, X"),
    (0xFFFFE0A4, 8, "распределитель VRAM: свободный узел, первый свободный участок, заглушка"),
    (0xFFFFDEC4, 6 * HEAP_NODES, "распределитель VRAM: узлы (следующий, начало, длина)"),
]

# Сценарии: уровень, объекты, что по трассе сверять ремейку (camera — шаг камеры
# $297748 по позициям игрока, player — запись игрока, переменные шага и камера,
# entry — вход в уровень, demo — только запись пульта, sprites — ещё таблица
# спрайтов и распределитель VRAM, SPRITE_LAYOUT), точка возрождения at
# (x, y) вместо старта уровня (подменяется $FFFFFD86 перед $2987B8), fly —
# отладочный полёт с камерой $29798E, set — слова записи игрока [(смещение,
# слово)] и poke — байты ОЗУ [(адрес, байты)] на входе, до снимка, запись
# пульта [(кнопки, кадров), ...].
SCENARIOS = {
    "idle": {
        "level": 0, "objects": False, "checks": ["camera", "player"],
        "input": [("", 600)],
        "about": "уровень 0, пульт не трогают: покой и развилки его скрипта по жребию",
    },
    "walk_right": {
        "level": 0, "objects": False, "checks": ["camera", "player"],
        "input": [("R", 90), ("", 60), ("L", 30), ("", 60)],
        "about": "уровень 0: вправо, стоп, разворот влево, стоп",
    },
    "jump_tap": {
        "level": 0, "objects": False, "checks": ["camera", "player"],
        "input": [("", 10), ("C", 1), ("", 70)],
        "about": "уровень 0: прыжок, C держат один кадр — короткий прыжок",
    },
    "jump_full": {
        "level": 0, "objects": False, "checks": ["camera", "player"], "pictures": [50],
        "input": [("", 10), ("C", 45), ("", 40), ("C", 6), ("", 60)],
        "about": "уровень 0: полный прыжок с места, потом C на 6 кадров",
    },
    "run_jump": {
        "level": 0, "objects": False, "checks": ["camera", "player"],
        "input": [("R", 40), ("RC", 30), ("R", 20), ("", 60)],
        "about": "уровень 0: разбег и прыжок с разбега, посадка на ходу, стоп",
    },
    "air_control": {
        "level": 0, "objects": False, "checks": ["camera", "player"],
        "input": [("C", 10), ("CR", 20), ("CL", 25), ("L", 15), ("", 20), ("C", 40), ("CL", 30), ("", 40)],
        "about": "уровень 0: в прыжке вправо, против хода влево (разворот в воздухе), посадка",
    },
    "walk_wall": {
        "level": 0, "objects": False, "checks": ["camera", "player"],
        "input": [("R", 150), ("", 30), ("R", 20), ("L", 20), ("", 30)],
        "about": "уровень 0: ходьба в колонну x=432 (упор, толкание), отход",
    },
    "jump_wall": {
        "level": 0, "objects": False, "checks": ["camera", "player"],
        "input": [("R", 70), ("RC", 45), ("R", 40), ("", 30)],
        "about": "уровень 0: прыжок с разбега в колонну x=432",
    },
    "turns": {
        "level": 0, "objects": False, "checks": ["camera", "player"],
        "input": [("R", 30), ("L", 5), ("R", 5), ("L", 30), ("", 20), ("U", 20), ("UR", 10), ("UL", 10), ("", 30)],
        "about": "уровень 0: развороты на ходу и с места, взгляд вверх",
    },
    "fall_pit_1": {
        "level": 1, "objects": False, "checks": ["camera", "player"],
        "input": [("R", 80)],
        "about": "уровень 1: вправо, с уступа в яму ниже нижнего предела — гибель",
    },
    "ledges_3": {
        "level": 3, "objects": False, "checks": ["camera", "player"], "pictures": [60, 200],
        "input": [("R", 300)],
        "about": "уровень 3: вправо, два срыва с уступов, упор",
    },
    "ledges_5": {
        "level": 5, "objects": False, "checks": ["camera", "player"], "pictures": [60],
        "input": [("R", 20), ("RC", 40), ("R", 30), ("RC", 40), ("R", 30), ("RC", 40), ("R", 60)],
        "about": "уровень 5: вправо с прыжками, срывы с уступов, склоны",
    },
    "ledges_17": {
        "level": 17, "objects": False, "checks": ["camera", "player"], "pictures": [150],
        "input": [("L", 300)],
        "about": "уровень 17: влево, срыв с уступа, упор",
    },
    "viscous_14": {
        "level": 14, "objects": False, "checks": ["camera", "player"], "pictures": [150],
        "input": [("R", 300)],
        "about": "уровень 14, вязкий: вправо, упор, срыв с уступа",
    },
    "viscous_15": {
        "level": 15, "objects": False, "checks": ["camera", "player"], "pictures": [100],
        "input": [("R", 20), ("RC", 40), ("R", 30), ("RC", 20), ("RCL", 20), ("L", 30), ("", 40)],
        "about": "уровень 15, вязкий: прыжки с разбега, разворот в воздухе",
    },
    "ceiling_3": {
        "level": 3, "objects": False, "checks": ["camera", "player"], "at": (664, 370),
        "input": [("", 5), ("C", 40), ("", 30), ("R", 10), ("RC", 40), ("", 40)],
        "about": "уровень 3, утка под потолком в 4 клетках: прыжок в потолок с места и с хода",
    },
    "ceiling_1": {
        "level": 1, "objects": False, "checks": ["camera", "player"], "at": (472, 512),
        "input": [("", 5), ("C", 30), ("", 40), ("L", 8), ("LC", 30), ("", 30)],
        "about": "уровень 1, утка под потолком в 3 клетках: прыжок в потолок",
    },
    "pit_7": {
        "level": 7, "objects": False, "checks": ["camera", "player"], "pictures": [15], "at": (160, 400),
        "input": [("", 40)],
        "about": "уровень 7: падение в яму до гибели; зонд стены у дна читает строки за картой (таблица $FF0020 повторяет последнюю строку)",
    },
    "hazard_10": {
        "level": 10, "objects": False, "checks": ["camera", "player"],
        "input": [("R", 400)],
        "about": "уровень 10: вправо по опасным клеткам (код 7), урон, неуязвимость, выпрыгивание",
    },
    "hazard_death_16": {
        "level": 16, "objects": False, "checks": ["camera", "player"], "pictures": [200],
        "input": [("R", 900)],
        "about": "уровень 16: вправо по опасным клеткам до гибели, запас 100 -> 0",
    },
    "spikes_below_3": {
        "level": 3, "objects": False, "checks": ["camera", "player"], "at": (248, 190),
        "input": [("", 90)],
        "about": "уровень 3: падение на шипы снизу (код 13), подброс, снова на шипы в неуязвимости",
    },
    "spikes_above_12": {
        "level": 12, "objects": False, "checks": ["camera", "player"], "at": (160, 1150),
        "set": [(0x04, 0x0400), (0x18, 0xFA00), (0x22, 0x001D), (0x24, 0x705C)],
        "input": [("", 60)],
        "about": "уровень 12: утка летит вверх (состояние 4, +$18 = $FA00) в шипы сверху (код 32), сброс вниз",
    },
    "updraft_2": {
        "level": 2, "objects": False, "checks": ["camera", "player"], "pictures": [40], "at": (264, 250),
        "input": [("", 60), ("R", 20), ("", 60)],
        "about": "уровень 2: восходящий поток (коды 10-12, состояние 22), выход из шахты",
    },
    "updraft_right_2": {
        "level": 2, "objects": False, "checks": ["camera", "player"], "at": (248, 250),
        "input": [("", 60)],
        "about": "уровень 2: восходящий поток вправо (код 10) в левом столбце шахты",
    },
    "updraft_left_2": {
        "level": 2, "objects": False, "checks": ["camera", "player"], "at": (296, 250),
        "set": [(0x00, 0x2801)],
        "input": [("", 60)],
        "about": "уровень 2: восходящий поток влево (код 12) в правом столбце шахты, утка смотрит влево",
    },
    "no_damage_3": {
        "level": 3, "objects": False, "checks": ["camera", "player"], "at": (248, 190),
        "poke": [(0xFF1342, bytes([1]))],
        "input": [("", 60)],
        "about": "уровень 3: шипы снизу при запрете урона $FF1342 — ни урона, ни подброса",
    },
    "exit_3": {
        "level": 3, "objects": False, "checks": ["camera", "player"], "at": (640, 150),
        "input": [("R", 60)],
        "about": "уровень 3: вправо в клетку выхода (код 5)",
    },
    "crouch_0": {
        "level": 0, "objects": False, "checks": ["camera", "player"],
        "input": [("", 5), ("D", 20), ("", 15), ("DL", 10), ("DR", 10), ("D", 5), ("DC", 1), ("D", 60),
                  ("", 20), ("R", 20), ("DR", 20), ("", 10), ("D", 10), ("DA", 55), ("D", 10), ("", 10)],
        "about": "уровень 0: присед (8) и вставание, «вниз» со стороной — ход, прыжок из приседа, посадка "
                 "с «вниз», A в приседе без топлива",
    },
    "vine_0": {
        "level": 0, "objects": False, "checks": ["camera", "player"], "at": (60, 150),
        "input": [("U", 3), ("", 22), ("U", 80), ("L", 5), ("R", 5), ("D", 80), ("C", 1), ("", 90)],
        "about": "уровень 0: лиана (код 1) — захват в падении, метка, подъём до верхнего края, взгляд, "
                 "спуск до нижнего, прыжок без стороны (назад), падение",
    },
    "vine_side_0": {
        "level": 0, "objects": False, "checks": ["camera", "player"], "at": (60, 150),
        "input": [("U", 3), ("", 22), ("CR", 1), ("R", 40), ("", 30)],
        "about": "уровень 0: прыжок с лианы вправо, управление в воздухе, посадка на уступ",
    },
    "vine_jump_1": {
        "level": 1, "objects": False, "checks": ["camera", "player"], "at": (104, 1050),
        "input": [("", 20), ("CU", 31), ("U", 30), ("", 40), ("DC", 1), ("", 40)],
        "about": "уровень 1: захват лианы в прыжке (+$18 ≥ −$0200), подъём, сброс «вниз» и прыжок",
    },
    "vine_slide_7": {
        "level": 7, "objects": False, "checks": ["camera", "player"], "pictures": [80], "at": (760, 340),
        "input": [("U", 3), ("", 40), ("U", 60), ("", 57)],
        "about": "уровень 7: лиана кода 3 — висит без дела и сползает, подъём до края, снова сползает; "
                 "кончается до пасти внизу",
    },
    "shadow_0": {
        "level": 0, "objects": False, "checks": ["camera", "player"], "at": (1356, 540),
        "poke": [(0xFF1A92, bytes([0x03, 0x80]))],
        "input": [("U", 3), ("", 20), ("D", 80), ("U", 125), ("CR", 1), ("R", 45), ("", 85)],
        "about": "уровень 0: облик «тень» — по лиане вниз через 23 и 24 (тень и обратно), вверх в тень, по "
                 "лиане второй карты, прыжок на её пол, снос, падение назад через 24; нижний предел $FF1A92 "
                 "опущен (его опускают объекты уровня); кончается до того, как низ уровня выйдет на экран "
                 "(там просыпаются объекты процедуры $2A5EC6 и тянут ГСЧ)",
    },
    "sprites_0": {
        "level": 0, "objects": False, "checks": ["camera", "player", "sprites"], "pictures": [5, 40, 75, 130, 200],
        "input": [("", 10), ("R", 60), ("L", 8), ("", 20), ("C", 30), ("", 20), ("RC", 40), ("R", 20),
                  ("", 10), ("D", 30), ("", 10), ("U", 20), ("L", 30), ("", 20)],
        "about": "уровень 0: таблица спрайтов и VRAM — ход, разворот, прыжки, присед, взгляд вверх; "
                 "HUD въезжает в кадре ~5",
    },
    "sprites_shadow_0": {
        "level": 0, "objects": False, "checks": ["camera", "player", "sprites"], "pictures": [30, 90, 200, 300], "at": (1356, 540),
        "poke": [(0xFF1A92, bytes([0x03, 0x80]))],
        "input": [("U", 3), ("", 20), ("D", 80), ("U", 125), ("CR", 1), ("R", 45), ("", 85)],
        "about": "уровень 0: таблица спрайтов в облике «тень» — приоритет снят, объект сноса со скриптом "
                 "утки рисуется и берёт VRAM; ввод как у shadow_0",
    },
    "sprites_vine_1": {
        "level": 1, "objects": False, "checks": ["camera", "player", "sprites"], "at": (104, 1050),
        "input": [("", 20), ("CU", 31), ("U", 30), ("", 40), ("DC", 1), ("", 40)],
        "about": "уровень 1: таблица спрайтов на лиане, два блока VRAM процедуры $2A5EC6; ввод как у vine_jump_1",
    },
    "sprites_10": {
        "level": 10, "objects": False, "checks": ["camera", "player", "sprites"], "pictures": [20, 41, 100], "record": 260,
        "input": [("R", 400)],
        "about": "уровень 10: таблица спрайтов при уроне и мигании, блок $700 процедуры уровня; "
                 "начало hazard_10",
    },
    "fly_0": {
        "level": 0, "objects": False, "checks": ["player"], "fly": True,
        "input": [("R", 40), ("RA", 20), ("U", 30), ("UC", 10), ("L", 60), ("D", 20), ("", 10)],
        "about": "уровень 0, отладочный полёт ($FFFFFD84 на входе): крестовина, A и C удваивают шаг",
    },
    "unicycle_19": {
        "level": 19, "objects": False, "checks": ["camera"],
        "input": [("", 600)],
        "about": "бонус 19: моноцикл едет сам, пульт не трогают",
    },
}

for _level in range(19):          # 19-22 — бонус, утка с входа на моноцикле
    SCENARIOS["enter_%02d" % _level] = {
        "level": _level, "objects": False, "checks": ["entry"], "pictures": [20],
        "input": [("", 1)],
        "about": "вход в уровень %d: запись игрока и переменные, которые ставит вход" % _level,
    }

# Демо: уровень и поток пульта ($1FD7DC, screens.md 4). Поток — пары (кнопки в
# активном нуле уже после раскладки, кадров); первая пара звучит один кадр, ноль в
# кнопках — конец ($2A56BA). Раскладка 0 меняет B и C местами, она же и обратна себе.
DEMOS = ((0, 0x1FC75C), (3, 0x1FC84C), (7, 0x1FC9C0))


def demo_input(rom, at):
    def buttons(stored):
        held = ~stored & 0xFF
        held = (held & ~0x30) | ((held & 0x10) << 1) | ((held & 0x20) >> 1)
        return "".join(ch for i, ch in enumerate(BUTTONS) if held >> i & 1)

    out = [(buttons(rom[at]), 1)]
    at += 2
    while rom[at]:
        out.append((buttons(rom[at]), rom[at + 1] or 256))
        at += 2
    return out


for _n, (_level, _at) in enumerate(DEMOS):
    SCENARIOS["demo_%d" % _level] = {
        "level": _level, "objects": False, "checks": ["demo"], "demo": _at, "record": 1,
        "about": "демо %d: запись пульта из ROM ($%06X), кадры не снимаются — ремейк проигрывает её целиком" % (_n, _at),
    }

NO_OBJECTS = [
    (0x2914EA, "4E96", "4E71", "обход столбца клеток: jsr (a6) — конструктор объекта клетки"),
    (0x291800, "4E96", "4E71", "обход строки клеток: jsr (a6) — конструктор объекта клетки"),
]


def pad_byte(buttons):
    v = 0
    for ch in buttons:
        v |= 1 << BUTTONS.index(ch)
    return v


class MegaDrive:
    """Mega Drive без картинки и звука на ядре unicorn."""

    SCRATCH = 0x00900000

    def __init__(self, rom, patches=()):
        rom = bytearray(rom)
        for at, old, new, _ in patches:
            old_b, new_b = bytes.fromhex(old), bytes.fromhex(new)
            if rom[at:at + len(old_b)] != old_b:
                raise ValueError("заплатка $%06X: в ROM не %s" % (at, old))
            rom[at:at + len(new_b)] = new_b
        self.rom = bytes(rom)
        uc = self.uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
        uc.ctl_set_cpu_model(M.UC_CPU_M68K_M68000)
        uc.mem_map(0, 0x400000, UC_PROT_READ | UC_PROT_EXEC)
        uc.mem_write(0, self.rom)
        self.ram = ctypes.create_string_buffer(0x10000)
        uc.mem_map_ptr(0x00FF0000, 0x10000, UC_PROT_ALL, self.ram)
        uc.mem_map_ptr(0xFFFF0000, 0x10000, UC_PROT_ALL, self.ram)
        self.z80 = bytearray(0x2000)
        self.th = 1
        self.pad = 0
        self.status = 0
        self.odd_io = {}
        uc.mmio_map(0xA00000, 0x20000, self._io_read, None, self._io_write, None)
        uc.mmio_map(0xC00000, 0x1000, self._vdp_read, None, self._vdp_write, None)
        # Регистры VDP с включения: загрузку `$297A1C` из таблицы `$297A72` (+26, 24 байта) ROM
        # пропускает — порт `$A10008` здесь читается не нулём, как при тёплом перезапуске, — а часть
        # регистров (2, 3 — адреса плоскости A и окна) игра потом не пишет.
        self.vdp = Vdp(self._bus_word, list(self.rom[VDP_INIT:VDP_INIT + 24]))
        uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._unmapped)
        uc.hook_add(UC_HOOK_INTR, self._intr)

        # Заглушки: прочитать SR процессором; войти в прерывание кадра.
        vint = struct.unpack_from(">I", self.rom, VINT_VECTOR)[0]
        uc.mem_map(self.SCRATCH, 0x1000, UC_PROT_ALL)
        self.stub_sr = self.SCRATCH
        self.stub_irq = self.SCRATCH + 0x20
        self.sr_cell = self.SCRATCH + 0x100
        uc.mem_write(self.stub_sr, bytes.fromhex("40F9") + struct.pack(">I", self.sr_cell) + bytes.fromhex("4E71"))
        uc.mem_write(self.stub_irq, bytes.fromhex("40E7" "46FC2600" "4EF9") + struct.pack(">I", vint))
        self.frame_sp = None

        ssp, pc = struct.unpack_from(">II", self.rom, 0)
        uc.reg_write(M.UC_M68K_REG_SR, 0x2700)
        uc.reg_write(M.UC_M68K_REG_A7, ssp)
        self.pc = pc
        self.fault = None

    # --- память ---

    def read(self, address, length):
        a = address & 0xFFFF
        return bytes(self.ram.raw[a:a + length])

    def word(self, address):
        return struct.unpack(">H", self.read(address, 2))[0]

    def write(self, address, data):
        a = address & 0xFFFF
        ctypes.memmove(ctypes.addressof(self.ram) + a, data, len(data))

    def _io_read(self, uc, offset, size, user):
        a = 0xA00000 + offset
        if a < 0xA04000:
            v = self.z80[offset & 0x1FFF]
            return (v << 8 | v) if size == 2 else v
        if a < 0xA04004:
            return 0
        if a in (0xA10000, 0xA10001):
            return 0xA0          # заграничная NTSC, без дисковода
        if a in (0xA10002, 0xA10003):
            p = self.pad
            if self.th:
                return 0x40 | (~p & 0x3F)
            # TH = 0: A и Start на битах 4 и 5, биты 2 и 3 — ноль (пульт на 3 кнопки)
            return ~((p & 3) | ((p >> 6) & 1) << 4 | ((p >> 7) & 1) << 5) & 0x33
        if a < 0xA10020:
            return 0x7F
        if a in (0xA11100, 0xA11101):
            return 0             # шина Z80 выдана
        self.odd_io[a] = self.odd_io.get(a, 0) + 1
        return 0

    def _io_write(self, uc, offset, size, value, user):
        a = 0xA00000 + offset
        if a < 0xA04000:
            if size == 2:
                self.z80[offset & 0x1FFF] = (value >> 8) & 0xFF
                self.z80[(offset + 1) & 0x1FFF] = value & 0xFF
            else:
                self.z80[offset & 0x1FFF] = value & 0xFF
        elif a in (0xA10002, 0xA10003):
            self.th = (value >> 6) & 1

    def _vdp_read(self, uc, offset, size, user):
        if 4 <= offset < 8:
            # Чтение статуса сбрасывает у VDP недописанную команду (первое слово без второго).
            self.vdp.pending = False
            # Бит 3 — кадровое гашение. Внутри прерывания кадра оно идёт (очередь цветов `$2A5726`
            # сбрасывается, только увидев его); в основном потоке бит меняется на каждом чтении,
            # чтобы циклы ожидания кадра не висели.
            if self.frame_sp is not None:
                return 0x3608 if size == 2 else 0x36
            self.status ^= 8
            return 0x3600 | self.status if size == 2 else 0x36
        return 0

    def _vdp_write(self, uc, offset, size, value, user):
        self.vdp.write(offset, size, value)

    def _bus_word(self, address):
        """Слово шины 68000 для DMA: ROM или ОЗУ."""
        a = address & 0xFFFFFE
        if a < len(self.rom):
            return struct.unpack_from(">H", self.rom, a)[0]
        if a >= 0xFF0000:
            return struct.unpack_from(">H", self.ram.raw, a & 0xFFFF)[0]
        return 0

    def _unmapped(self, uc, access, address, size, value, user):
        self.fault = "обращение к $%08X (вид %d) из $%08X" % (address, access, uc.reg_read(M.UC_M68K_REG_PC))
        return False

    def _intr(self, uc, intno, user):
        if intno != 0x100:
            self.fault = "исключение %d в $%08X" % (intno, uc.reg_read(M.UC_M68K_REG_PC))
            uc.emu_stop()
            return
        # rte на 68000: слово SR, длинное PC, слова формата нет
        sp = uc.reg_read(M.UC_M68K_REG_A7)
        sr, pc = struct.unpack(">HI", bytes(uc.mem_read(sp, 6)))
        uc.reg_write(M.UC_M68K_REG_A7, (sp + 6) & 0xFFFFFFFF)
        uc.reg_write(M.UC_M68K_REG_SR, sr)
        uc.reg_write(M.UC_M68K_REG_PC, pc)
        if sp == self.frame_sp:
            self.frame_sp = None
            uc.emu_stop()

    # --- исполнение ---

    def _run(self, begin, until, count):
        try:
            self.uc.emu_start(begin, until, 0, count)
        except UcError as e:
            raise RuntimeError(self.fault or "%s в $%08X" % (e, self.uc.reg_read(M.UC_M68K_REG_PC)))
        if self.fault:
            raise RuntimeError(self.fault)

    def _sr(self):
        self._run(self.stub_sr, self.stub_sr + 6, 0)
        return struct.unpack(">H", bytes(self.uc.mem_read(self.sr_cell, 2)))[0]

    def frame(self):
        """Кусок основного потока и прерывание кадра, если маска его пускает."""
        self._run(self.pc, 0xFFFFFFFF, BUDGET)
        self.pc = self.uc.reg_read(M.UC_M68K_REG_PC)
        if (self._sr() >> 8) & 7 >= 6:
            return False
        sp = (self.uc.reg_read(M.UC_M68K_REG_A7) - 4) & 0xFFFFFFFF
        self.uc.mem_write(sp, struct.pack(">I", self.pc))
        self.uc.reg_write(M.UC_M68K_REG_A7, sp)
        self.frame_sp = (sp - 2) & 0xFFFFFFFF
        self._run(self.stub_irq, 0xFFFFFFFF, HANDLER_LIMIT)
        if self.frame_sp is not None or self.uc.reg_read(M.UC_M68K_REG_PC) != self.pc:
            raise RuntimeError("обработчик кадра не вернулся за %d команд" % HANDLER_LIMIT)
        return True


def layout_of(sc):
    return LAYOUT + (SPRITE_LAYOUT if "sprites" in sc["checks"] else [])


def snapshot(md, layout=LAYOUT):
    return {
        "player": md.read(PLAYER, PLAYER_LENGTH).hex().upper(),
        "ram": "".join(md.read(at, n).hex().upper() for at, n, _ in layout),
    }


def run(name, sc, rom):
    patches = [] if sc["objects"] else NO_OBJECTS
    md = MegaDrive(rom, patches)
    if "demo" in sc:
        sc = dict(sc, input=demo_input(rom, sc["demo"]))
    pads = []
    for buttons, n in sc["input"]:
        pads += [pad_byte(buttons)] * n
    state = {"setup": False, "entry": None, "frame": 0, "done": 0}
    layout = layout_of(sc)
    frames = []
    pictures = {}
    wanted = set(sc.get("pictures", ()))

    def on_setup(uc, address, size, user):
        if not state["setup"]:
            state["setup"] = True
            state["setup_frame"] = boot_frame[0]
            md.write(LEVEL_NUMBER, struct.pack(">H", sc["level"]))

    def on_position(uc, address, size, user):
        if "at" in sc:
            md.write(RESPAWN, struct.pack(">hh", *sc["at"]))

    def on_player(uc, address, size, user):
        if state["entry"] is None:
            for offset, value in sc.get("set", ()):
                md.write(PLAYER + offset, struct.pack(">H", value & 0xFFFF))
            for address, data in sc.get("poke", ()):
                md.write(address, data)
            if sc.get("fly"):
                md.write(DEBUG_FLIGHT, b"\x01")
            state["entry"] = snapshot(md, layout)
            md.pad = pads[0]
            state["skip"] = hidden_tiles(md)
        elif state["done"] - 1 in wanted and state["done"] - 1 not in pictures:
            # Кадр k показывает то, что очередь DMA кадра k отправила в начале прерывания кадра
            # k + 1: к задаче игрока кадра k + 1 оно уже в VRAM.
            k = state["done"] - 1
            pictures[k] = {
                "camera": list(struct.unpack(">hh", md.read(0xFFFFE1BC, 4))),
                "t": md.word(0xFFFFE196) - 1,
                "cram": "".join("%04X" % c for c in md.vdp.cram),
                "vsram": "".join("%04X" % c for c in md.vdp.vsram[:2]),
            }
            why = md.vdp.check()
            if why:
                pictures[k]["skipped"] = why
            else:
                pictures[k]["full"] = md.vdp.picture(skip_tiles=state["skip"])
                pictures[k]["planes"] = md.vdp.picture(sprites=False)

    md.uc.hook_add(UC_HOOK_CODE, on_setup, None, LEVEL_SETUP, LEVEL_SETUP)
    md.uc.hook_add(UC_HOOK_CODE, on_player, None, PLAYER_TASK, PLAYER_TASK)
    md.uc.hook_add(UC_HOOK_CODE, on_position, None, PLAYER_POSITION, PLAYER_POSITION)

    boot = 0
    boot_frame = [0]
    while state["entry"] is None:
        boot_frame[0] = boot
        if boot >= BOOT_LIMIT:
            raise RuntimeError("%s: за %d кадров до уровня не дошли" % (name, BOOT_LIMIT))
        md.pad = 0 if state["setup"] else (pad_byte("S") if boot % 90 < 4 else 0)
        md.frame()
        boot += 1
    if md.word(LEVEL_NUMBER) != sc["level"]:
        raise RuntimeError("%s: вошли в уровень %d" % (name, md.word(LEVEL_NUMBER)))
    if md.read(DEMO, 1) != b"\0":
        raise RuntimeError("%s: вошли в демо, а не в игру" % name)

    # Кадр входа уже прошёл: пульт на нём — pads[0] (задача игрока читает его после снимка).
    # Уровень кончается первым кадром с сигналом выхода (гибель, выход).
    frames.append(dict(pad=pads[0], **snapshot(md, layout)))
    state["done"] = 1
    for k in range(1, min(len(pads), sc.get("record", len(pads)))):
        if md.word(EXIT) != 0:
            break
        md.pad = pads[k]
        while not md.frame():
            pass
        state["done"] += 1
        frames.append(dict(pad=pads[k], **snapshot(md, layout)))
    # Картинки после записанных кадров: игра идёт дальше с отпущенным пультом (картинке кадра k
    # нужен кадр k + 1).
    md.pad = 0
    while wanted and state["done"] <= max(wanted) + 1 and md.word(EXIT) == 0:
        while not md.frame():
            pass
        state["done"] += 1
    missing = wanted - set(pictures)
    if missing:
        raise RuntimeError("%s: нет картинок кадров %s" % (name, sorted(missing)))

    return {
        "meta": {
            "generator": "tools/romtrace.py",
            "rom_sha1": hashlib.sha1(rom).hexdigest().upper(),
            "core": "unicorn %s, M68000" % UC_VERSION,
            "boot_frames": boot,
            "setup_frame": state["setup_frame"],
            "odd_io": {"$%06X" % a: n for a, n in sorted(md.odd_io.items())},
            "pad_bits": BUTTONS,
            "frame": "frames[k] — ОЗУ после k-го кадра уровня (после rte обработчика $2968FE); "
                     "pad — пульт, который прочитала задача игрока в этом кадре; entry — "
                     "ОЗУ на первом входе в задачу игрока $298C44, до шага игрока кадра 0",
        },
        "scenario": {
            "name": name,
            "about": sc["about"],
            "level": sc["level"],
            "objects": sc["objects"],
            "checks": sc["checks"],
            "at": list(sc["at"]) if "at" in sc else None,
            "fly": bool(sc.get("fly")),
            "set": ["+$%02X = $%04X" % (o, v & 0xFFFF) for o, v in sc.get("set", ())],
            "poke": ["$%06X = %s" % (a & 0xFFFFFF, d.hex().upper()) for a, d in sc.get("poke", ())],
            "input": [[b, n] for b, n in sc["input"]],
            "patches": [{"at": "$%06X" % at, "was": old, "now": new, "why": why}
                        for at, old, new, why in patches],
        },
        "layout": {
            "player": {"at": "$%08X" % PLAYER, "length": PLAYER_LENGTH},
            "ram": [{"at": "$%08X" % at, "length": n, "what": what} for at, n, what in layout],
        },
        "entry": state["entry"],
        "frames": frames,
        "_pictures": pictures,
    }


def hidden_tiles(md):
    """Тайлы VRAM, которые на входе в уровень заняли после тайлов уровня (HUD, объекты процедуры
    уровня; graphics.md): ремейк их объектов пока не заводит, их спрайты картинка пропускает."""
    size, address = struct.unpack(">HH", md.read(0xFFFFE138, 4))
    node = md.word(0xFFFFE0A6)
    first_free = md.word(0xFFFF0000 | (node + 2)) if node else 0x10000
    return range((address + size) >> 5, first_free >> 5)


def write_pictures(name, level, pictures):
    import sprites as S
    out = OUT("export", "pictures")
    os.makedirs(out, exist_ok=True)
    index_path = os.path.join(out, "pictures.json")
    index = {}
    if os.path.exists(index_path):
        with io.open(index_path, encoding="utf-8") as f:
            index = json.load(f)
    index = {k: v for k, v in index.items() if v["scenario"] != name}
    for k, pic in sorted(pictures.items()):
        entry = {"scenario": name, "level": level, "frame": k, "camera": pic["camera"], "t": pic["t"],
                 "cram": pic["cram"], "vsram": pic["vsram"]}
        if "skipped" in pic:
            entry["skipped"] = pic["skipped"]
        else:
            for kind in ("full", "planes"):
                stem = "%s_%d%s" % (name, k, "" if kind == "full" else "_planes")
                S.png(os.path.join(out, stem + ".png"), 320, 224, [c + (255,) for c in pic[kind]])
        index["%s_%d" % (name, k)] = entry
    with io.open(index_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(dict(sorted(index.items())), ensure_ascii=False, indent=1))
        f.write("\n")


def dump(trace):
    s = io.StringIO()
    s.write("{\n")
    keys = list(trace)
    for i, key in enumerate(keys):
        s.write("  %s: " % json.dumps(key))
        if key == "frames":
            s.write("[\n")
            rows = trace[key]
            for j, row in enumerate(rows):
                s.write("    " + json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                s.write(",\n" if j + 1 < len(rows) else "\n")
            s.write("  ]")
        else:
            s.write(json.dumps(trace[key], ensure_ascii=False, indent=2).replace("\n", "\n  "))
        s.write(",\n" if i + 1 < len(keys) else "\n")
    s.write("}\n")
    return s.getvalue()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("names", nargs="*", help="сценарии (по умолчанию все)")
    ap.add_argument("--check", action="store_true", help="каждый прогнать дважды и сверить, не писать")
    ap.add_argument("--list", action="store_true", help="перечислить сценарии")
    args = ap.parse_args()
    if args.list:
        for name, sc in SCENARIOS.items():
            print("%-14s уровень %2d  %s" % (name, sc["level"], sc["about"]))
        return
    names = args.names or list(SCENARIOS)
    for name in names:
        if name not in SCENARIOS:
            sys.exit("нет сценария %s (--list)" % name)
    rom = rom_bytes()
    out = OUT("export", "traces")
    if not args.check:
        os.makedirs(out, exist_ok=True)
    for name in names:
        trace = run(name, SCENARIOS[name], rom)
        pictures = trace.pop("_pictures")
        text = dump(trace)
        if args.check:
            again = run(name, SCENARIOS[name], rom)
            again.pop("_pictures")
            again = dump(again)
            print("%s: %s" % (name, "повтор совпал" if text == again else "ПОВТОР РАЗОШЁЛСЯ"))
            if text != again:
                sys.exit(1)
            continue
        path = os.path.join(out, name + ".json")
        with io.open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        if pictures:
            write_pictures(name, SCENARIOS[name]["level"], pictures)
        print("%s: %s" % (name, path))


if __name__ == "__main__":
    main()
