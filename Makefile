# ─────────────────────────────────────────────────────────────────────────
# Dyna Brothers 2 (Japan) — проект дизассемблирования
#
# ROM: 2 МБ, SHA-1 0D6C3D9EB0CB9A56AB91B7507B09473B078E773C,
# заголовок ﾀﾞｲﾅ ﾌﾞﾗｻﾞｰｽﾞ2, серийный GM T-68063-00.
# Это НЕ Sega Channel Special: та версия на полмегабайта больше
# (2,5 МБ, заголовок с ｾｶﾞﾁｬﾝﾈﾙｽﾍﾟｼｬﾙ) и здесь не разбирается.
# Общего у них 0,92 МБ подряд, $07820C-$164406 — графика и ассеты;
# код и звук расходятся почти полностью.
#
# Нужен GNU make. ВНИМАНИЕ: на этой машине в PATH лежит Borland make из
# Embarcadero — он этот файл не разберёт. Поставить GNU make:
#     winget install GnuWin32.Make
# и звать его полным путём либо поправив PATH.
#
# Структура повторяет hansbonini/smd_alteredbeast: split -> правки -> build
# -> сверка SHA-1 с оригиналом. Цель — побайтовая пересборка.
# ─────────────────────────────────────────────────────────────────────────

# Разбираемый ROM. Второй задаётся из командной строки целиком:
#     make rebuild NAME=mauimallard ROM=platformer.gen CONFIG=platformer.yaml
NAME        := dynabrothers2
ROM         := game.gen
CONFIG      := game.yaml

# Питоновские инструменты берут отсюда, какой проект разбирается: пути и
# имена файлов у них считаются в tools/paths.py, а не зашиты.
export SEGA2ASM_CONFIG := $(CONFIG)
export SEGA2ASM_ROM    := $(ROM)

# Символы разведены: свои имена переживают смену ROM и пересборку.
#   .user.txt — ваш, под git
#   .gen.txt  — генерируется анализатором, перезаписывается
#   .txt      — склейка для сборки (артефакт, в .gitignore)
# Имена идут от YAML, а не от NAME: символы привязаны к ROM, а не к проекту
# вывода. game.yaml -> game_symbols.*, platformer.yaml -> platformer_symbols.*
SYM_BASE     := $(basename $(CONFIG))_symbols
USER_SYMBOLS := $(SYM_BASE).user.txt
GEN_SYMBOLS  := $(SYM_BASE).gen.txt
SYMBOLS      := $(SYM_BASE).txt

# Каталоги (должны совпадать с options.* в $(CONFIG))
# Вывод разведён по проектам: out/<NAME>/. Второй ROM в том же дереве
# не затирает первый, и `make clean` сносит только свой.
OUT_DIR     := out/$(NAME)
ASM_DIR     := $(OUT_DIR)/asm
ASSET_DIR   := $(OUT_DIR)/assets
# Собранное тоже разведено по проектам. Исключение — скомпилированные
# помощники: render.exe от ROM не зависит, собирать его на каждый проект
# незачем.
BUILD_DIR   := build/$(NAME)
TOOLBIN_DIR := build/tools
TOOLS_DIR   := tools

MAIN_ASM    := $(ASM_DIR)/$(NAME).asm
TARGET      := $(BUILD_DIR)/$(NAME).bin
LISTING     := $(BUILD_DIR)/$(NAME).txt

# Инструменты
GO          ?= go
PYTHON      ?= python
SEGA2ASM    := ./sega2asm.exe

# Ассемблер. Оригинальный asm68k (SN 68k) — проприетарный Windows-бинарник;
# clownassembler даёт совместимый по командной строке clownassembler_asm68k
# (портируемый ANSI C). Переопределить:  make build ASM68K=/path/to/asm68k
ASM68K      ?= asm68k
# /m — разворачивать все макросы, /p — выводить плоский бинарник (без него
# ассемблер ругается Executable output format is not supported).
# /k из smd_alteredbeast убран: clownassembler его не реализует и warning'ит.
ASM68K_FLAGS ?= /m /p

# Вывод питона в UTF-8, иначе кириллица бьётся о кодовую страницу консоли
export PYTHONIOENCODING := utf-8

# Обязательно для Git Bash: MSYS конвертирует аргументы вида /p и /m в
# Windows-пути, ассемблер перестаёт видеть в них ключи и принимает за имена
# файлов. Без этого сборка падает на «Source file could not be opened».
export MSYS_NO_PATHCONV := 1

.PHONY: all analyze codegaps symbols split check codemap findcode aiscripts packmap terrain maps maptex cutscene menus worldmap nameprocs dumptext findtext packedtext unpack missions stages gfx unitgfx unitanim exportanim pcm music sfx render deps vectors xcheck chains whocalls z80dis z80seq z80render z80voice frames sprites levels anim unlz coverage tileprobe build verify rebuild tools clean cleantools distclean help

# По умолчанию — то, что работает без ассемблера
all: split check

# Текст лежит в UTF-8 файле и печатается через python: `echo` под Windows
# уходит в cmd.exe мимо кодировки и выдаёт кракозябры на кириллице.
help:
	@$(PYTHON) -c "import sys; sys.stdout.reconfigure(encoding='utf-8'); print(open(sys.argv[1], encoding='utf-8').read())" $(TOOLS_DIR)/help.txt

# ── Инструменты ──────────────────────────────────────────────────────────
tools: $(SEGA2ASM)

$(SEGA2ASM): main.go go.mod $(wildcard */*.go) $(wildcard */*/*.go)
	$(GO) build -o $(SEGA2ASM) .

# ── Анализ ROM ───────────────────────────────────────────────────────────
# Пересобирает game_symbols.gen.txt из самой ROM. Запускать при смене
# game.gen. game.yaml НЕ трогается: он производный только на первом прогоне,
# дальше в нём руками режут сегменты и переводят их в m68k. Полная
# перегенерация — `make analyze ANALYZEARGS=--write`, и она стирает эту работу.
analyze:
	$(PYTHON) $(TOOLS_DIR)/analyze.py --name $(NAME) $(ANALYZEARGS)

# Что из bin-сегментов game.yaml обход считает кодом. Переводить по одному,
# арбитр — `make rebuild`.
codegaps:
	@$(PYTHON) $(TOOLS_DIR)/analyze.py --report

# game_symbols.gen.txt в .gitignore, поэтому в свежем клоне его нет —
# восстанавливаем анализатором, иначе сборка не стартует.
$(GEN_SYMBOLS): $(ROM) $(TOOLS_DIR)/analyze.py
	$(PYTHON) $(TOOLS_DIR)/analyze.py --name $(NAME)

# ── Символы ──────────────────────────────────────────────────────────────
symbols: $(SYMBOLS)

$(SYMBOLS): $(USER_SYMBOLS) $(GEN_SYMBOLS)
	@$(PYTHON) $(TOOLS_DIR)/symbols.py --merge

# ── Разрезание ROM ───────────────────────────────────────────────────────
split: $(MAIN_ASM)

# После split дописываем equ для имён, которым sega2asm не печатает метку
# (ОЗУ, данные, регистры) — иначе ссылка на них не соберётся.
$(MAIN_ASM): $(SEGA2ASM) $(CONFIG) $(SYMBOLS) $(ROM)
	$(SEGA2ASM) -c $(CONFIG) -v
	@$(PYTHON) $(TOOLS_DIR)/symbols.py --equates

# ── Проверка сплита (работает без ассемблера) ────────────────────────────
check: $(MAIN_ASM)
	@$(PYTHON) $(TOOLS_DIR)/check_split.py $(CONFIG)

# ── Карта кода ───────────────────────────────────────────────────────────
# Пересчитывает, что в каком банке лежит, по механическим признакам.
# Удобно прогонять после добавления имён: видно, где разбор продвинулся.
codemap: $(MAIN_ASM)
	@$(PYTHON) $(TOOLS_DIR)/codemap.py

# Ищет bin-сегменты, которые на самом деле код: анализатор не находит то,
# до чего добираются только через указатель на функцию. Находки правятся
# в game.yaml вручную и обязательно сверяются побайтовой пересборкой.
findcode:
	@$(PYTHON) $(TOOLS_DIR)/findcode.py

# Показать кусок ROM как тайлы 4bpp серой шкалой: лежит там графика или нет.
#   make tileprobe ADDR=020000 TILES=256
TILES ?= 256
tileprobe:
	@$(PYTHON) $(TOOLS_DIR)/tileprobe.py $(ADDR) $(TILES)

# Предлагает имена безымянным процедурам по механическим признакам тела.
# Диапазон задаётся аргументами:  make nameprocs FROM=050000 TO=060000
FROM ?= 000000
TO   ?= 200000
nameprocs:
	@$(PYTHON) $(TOOLS_DIR)/nameprocs.py $(FROM) $(TO)

# ── Текст ────────────────────────────────────────────────────────────────
# Выгружает текст ПО ТАБЛИЦАМ: напутствия к миссиям, названия, списки
# музыки и звуков, надписи интерфейса. В отличие от findtext.py, который
# сканирует ROM подряд и ловит графику, здесь каждая строка привязана
# к месту в игре.
dumptext:
	@$(PYTHON) $(TOOLS_DIR)/dumptext.py

# Сырое сканирование: все прогоны допустимых байт, с шумом.
findtext:
	@$(PYTHON) $(TOOLS_DIR)/findtext.py

# Текст ВНУТРИ сжатых блоков: findtext.py сканирует сырое ПЗУ и его не видит
packedtext:
	@$(PYTHON) $(TOOLS_DIR)/packedtext.py

# Описания миссий: 92 байта на миссию, семь глав, всё сжатое
missions:
	@$(PYTHON) $(TOOLS_DIR)/missions.py

# Распаковщик трапа $FF10, все пять методов:  make unpack ADDR=060424
ADDR ?= 060424
unpack:
	@$(PYTHON) $(TOOLS_DIR)/unpack.py $(ADDR)

# ── Графика ──────────────────────────────────────────────────────────────
# Распаковывает блоки и рисует их в out/<имя>/gfx/*.png. Без палитры — серым,
# с палитрой:  make gfx GFXARGS="--sprites 43 --pal 031D3C"
GFXARGS ?=
gfx:
	@$(PYTHON) $(TOOLS_DIR)/gfx.py $(GFXARGS)

# Как выглядит каждый тип юнита: от номера типа до PNG.
#   make unitgfx            сводка по всем типам, кто с кем совпадает
#   make unitgfx UARGS=32   кадры типа 32
UARGS ?=
unitgfx:
	@$(PYTHON) $(TOOLS_DIR)/unitgfx.py $(UARGS)

# Сценарии событий этапов: что делает покадровый обработчик каждой карты.
# Читает листинги, поэтому зависит от split.
stages: $(MAIN_ASM)
	@$(PYTHON) $(TOOLS_DIR)/stagescript.py

# Таблица исключений 68000: точки входа, до которых по ссылкам не добраться
vectors:
	@$(PYTHON) $(TOOLS_DIR)/vectors.py

# Сверка нашего дизассемблера с чужим (smd_recomp из MegaDriveRecomp).
# Нужен их вывод в build/recomp/out — как получить, сказано в шапке tools/xcheck.py
xcheck:
	@$(PYTHON) $(TOOLS_DIR)/xcheck.py

# Списки правил по приоритету: скрипты видов и цепочка ИИ противника
chains: $(MAIN_ASM)
	@$(PYTHON) $(TOOLS_DIR)/chains.py

# Скрипты ИИ миссий: что противник делает на каждом этапе и в какой фазе
aiscripts: $(MAIN_ASM)
	@$(PYTHON) $(TOOLS_DIR)/aiscript.py

# Карта сжатых блоков внутри bin-сегментов банков кода
packmap: $(MAIN_ASM)
	@$(PYTHON) $(TOOLS_DIR)/packmap.py

# Скорость и урон от местности по видам: три таблицы блока параметров
terrain:
	@$(PYTHON) $(TOOLS_DIR)/terrain.py

# Карты этапов: местность 40x40 в PNG и сводка по расстановке
maps:
	@$(PYTHON) $(TOOLS_DIR)/maps.py

# Анимации шести видов в раскладке ремейка Dyna: листы top/bottom/right,
# layouts.cs и покадровые длительности.  make exportanim EAARGS=--all
EAARGS ?=
exportanim:
	@$(PYTHON) $(TOOLS_DIR)/exportanim.py $(EAARGS)

# Анимации юнитов поодиночке: своя полоса кадров на анимацию, длительности
# и точка возврата, плюс units.json для переноса.
#     make unitanim UAARGS="5 --split"
UAARGS ?=
unitanim:
	@$(PYTHON) $(TOOLS_DIR)/unitanim.py $(UAARGS)

# Карты миссий настоящими тайлами игры: 123 PNG 1280x1280 со спрайтами
# юнитов, плюс лист образцов местности. Аргументы — глава и миссия:
#     make maptex MTARGS="1 5"
#     make maptex MTARGS=--types
#     make maptex MTARGS="--anim 1 1"           GIF: живые вода и огонь
#     make maptex MTARGS="--anim 1 1 14 7 8 8"  он же, окно задано руками
MTARGS ?=
maptex:
	@$(PYTHON) $(TOOLS_DIR)/maptex.py $(MTARGS)

# Меню команд: восемь картинок, пункты, переходы, доступность по миссиям.
MNARGS ?=
menus:
	@$(PYTHON) $(TOOLS_DIR)/menus.py $(MNARGS)

# Сценки между миссиями: заголовок блока, скрипты актёров и реплики.
#     make cutscene CSARGS=3       только одна сценка
#     make cutscene CSARGS=--back  четыре фона в PNG
#     make cutscene CSARGS="--play 0"  проиграть сценку в GIF
CSARGS ?=
cutscene:
	@$(PYTHON) $(TOOLS_DIR)/cutscene.py $(CSARGS)

# Карта мира целиком: таблица имён из блоков и метатайлов. Аргумент —
# адрес набора тайлов, по умолчанию $183CB6.
worldmap:
	@$(PYTHON) $(TOOLS_DIR)/worldmap.py $(TILESET)

# Кто ведёт на адрес: скан сырых байт по всем формам перехода. Нужен там,
# где анализатор не считает окрестность кодом:  make whocalls WHO=008392
WHO ?= 008392
whocalls:
	@$(PYTHON) $(TOOLS_DIR)/whocalls.py $(WHO)

# ── Звук ─────────────────────────────────────────────────────────────────
# Дизассемблер Z80: сам достаёт звуковой драйвер из z80_driver, распаковывает
# и раскладывает по адресам ОЗУ Z80. Диапазон:  make z80dis Z80FROM=0BB Z80LEN=200
# У второго ROM драйвер несжатый, поэтому образ берётся прямо из картриджа:
#   make z80dis Z80ROM=2ABADA:1862 Z80LEN=1862 NAME=mauimallard ...
Z80FROM ?= 0
Z80LEN  ?= 1AC0
Z80ROM  ?=
z80dis:
	@$(PYTHON) $(TOOLS_DIR)/z80dis.py $(if $(Z80ROM),--rom $(Z80ROM),) $(Z80FROM) $(Z80LEN)

# Скрипты дорожек звукового драйвера Maui Mallard: без аргументов — сводка,
# иначе разбор звука.   make z80seq SOUND=0 [TRACK=2]
SOUND ?=
TRACK ?=
z80seq:
	@$(PYTHON) $(TOOLS_DIR)/z80seq.py $(SOUND) $(TRACK)

# Мелодии Maui Mallard в WAV: драйвер Z80 исполняется на эмуляторе.
# Нужен компилятор C (gcc, clang или MSVC — ищет tools/ccbuild.py) и `make deps`.
#   make z80render                        все многодорожечные звуки
#   make z80render RENDERARGS=--all       все 169
#   make z80render RENDERARGS="--seconds 90 36"
z80render:
	@$(PYTHON) $(TOOLS_DIR)/z80render.py $(RENDERARGS)

# Записи тембров Maui Mallard: без аргумента — сводка по всем 156.
#   make z80voice VOICE=0
VOICE ?=
z80voice:
	@$(PYTHON) $(TOOLS_DIR)/z80voice.py $(VOICE)

# Таблица кадров спрайтов в начале картриджа (Maui Mallard).
#   make frames                 сводка
#   make frames FRAME=0         разбор одного кадра
#   make frames FRAME=--parts   вторая половина: сборные объекты
#   make frames FRAME=--sets    шесть наборов графики
#   make frames FRAME=--descs   таблица описателей спрайта
FRAME ?=
frames:
	@$(PYTHON) $(TOOLS_DIR)/frames.py $(FRAME)

# Что в картридже разобрано, а что нет:  make coverage
#   COVARGS=--raw      сырые тайлы вне системы кадров
#   COVARGS="--raw 1"  и нарисовать их в PNG
coverage:
	@$(PYTHON) $(TOOLS_DIR)/coverage.py $(COVARGS)

# Скрипт анимации объекта Maui Mallard:  make anim ANIM=1D8980
#   ANIM=--forms — три формы игрока (утка, ниндзя, уменьшенный)
ANIM ?=
anim:
	@$(PYTHON) $(TOOLS_DIR)/anim.py $(ANIM)

# Уровни Maui Mallard: таблица, карты, фон, метатайлы. Нужен только питон.
#   make levels                    сводка по 23 уровням
#   make levels LEVEL="--map 0"    карта уровня целиком в PNG
#   make levels LEVEL="--bg 6"     фоновый слой
#   make levels LEVEL="--solid 0"  карта с профилем земли и преградами
#   make levels LEVEL=--names      названия всех уровней
#   make levels LEVEL="--title 0"  заставка уровня в PNG
#   make levels LEVEL="--objects 0" карта со спрайтами объектов
#   make levels LEVEL=--passwords пароли уровней и чит на DEBUG
#   make levels LEVEL="--scene 7" заставка вместе с актёрами
#   make levels LEVEL=--hud        глифы счётчиков HUD
#   make levels LEVEL=--screen     титульный экран и титры
#   make levels LEVEL=--actors     актёры сценок
#   make levels LEVEL="--meta 0"   лист метатайлов
#   make levels LEVEL="--tiles 0"  лист тайлов
LEVEL ?=
levels:
	@$(PYTHON) $(TOOLS_DIR)/levels.py $(LEVEL)

# Распаковщик LZSS: любой блок по адресу.  make unlz UNLZ=221904
UNLZ ?=
unlz:
	@$(PYTHON) $(TOOLS_DIR)/lzss.py $(UNLZ)

# Кадры спрайтов Maui Mallard в PNG. Нужен только питон.
#   make sprites SPRITE="0 1 2"
#   make sprites SPRITE="--sheet 900 64 --pal 1F6F58"
#   make sprites SPRITE="--parts 150"
#   make sprites SPRITE=--pals          палитры, найденные в ROM
SPRITE ?=
sprites:
	@$(PYTHON) $(TOOLS_DIR)/sprites.py $(SPRITE)

# Сэмплы DAC в WAV: четырёхбитная дельта, декодер повторяет главный цикл Z80
pcm:
	@$(PYTHON) $(TOOLS_DIR)/pcm.py

# Партитуры всех песен в читаемый вид
music:
	@$(PYTHON) $(TOOLS_DIR)/music.py

# Звуковые эффекты: 50 записей драйвера, из них 33 без единого сэмпла
sfx:
	@$(PYTHON) $(TOOLS_DIR)/sfx.py

# Чужие ядра для render: clownz80 и Nuked-OPN2, в репозиторий не входят
deps:
	@$(PYTHON) $(TOOLS_DIR)/deps.py

# Звук с эмулятора: драйвер исполняется, а не пересказывается.
# Нужен компилятор C (CC) и `make deps`.  make render RENDERARGS=--music
CC        ?= gcc
RENDER    := $(TOOLBIN_DIR)/render.exe
RENDERARGS ?=

$(RENDER): $(TOOLS_DIR)/render/render.c third_party/clownz80/unity.c third_party/Nuked-OPN2/ym3438.c
	@$(PYTHON) -c "import os,sys; os.makedirs(sys.argv[1], exist_ok=True)" $(TOOLBIN_DIR)
	$(CC) -O2 -o $@ $^ -lm

render: $(RENDER)
	@$(PYTHON) $(TOOLS_DIR)/render.py $(RENDERARGS)

# ── Сборка ───────────────────────────────────────────────────────────────
# asm68k разбирает командную строку как source,object,,listing — запятые
# обязательны, третье поле (файл ошибок) пустое.
# Собирать из корня репозитория: в $(MAIN_ASM) пути include относительные.
build: $(TARGET)

# Каталог создаётся прямо в рецепте: отдельная цель $(BUILD_DIR) конфликтовала
# бы с phony-целью `build` — это одно и то же имя.
# mkdir -p через python: GNU make под Windows зовёт cmd.exe, где его нет.
$(TARGET): $(MAIN_ASM)
	@$(PYTHON) -c "import os,sys; os.makedirs(sys.argv[1], exist_ok=True)" $(BUILD_DIR)
	$(ASM68K) $(ASM68K_FLAGS) "$(MAIN_ASM)","$(TARGET)",,"$(LISTING)"

# ── Сверка ───────────────────────────────────────────────────────────────
verify: $(TARGET)
	@$(PYTHON) $(TOOLS_DIR)/sha1check.py $(TARGET) $(CONFIG) $(ROM)

rebuild: split build verify

# ── Уборка ───────────────────────────────────────────────────────────────
RMTREE := $(PYTHON) -c "import shutil,sys; [shutil.rmtree(p, ignore_errors=True) for p in sys.argv[1:]]"

# clean сносит собранное ЭТОГО проекта. build/tools остаётся: render.exe
# компилируется из C и к ROM отношения не имеет — пересобирать его на
# каждую уборку незачем. Снести и его: make cleantools
clean:
	$(RMTREE) $(BUILD_DIR)

cleantools:
	$(RMTREE) $(TOOLBIN_DIR)

distclean: clean
	$(RMTREE) $(OUT_DIR)
