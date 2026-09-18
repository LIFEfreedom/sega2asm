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

NAME        := dynabrothers2
ROM         := game.gen
CONFIG      := game.yaml

# Символы разведены: свои имена переживают смену ROM и пересборку.
#   .user.txt — ваш, под git
#   .gen.txt  — генерируется анализатором, перезаписывается
#   .txt      — склейка для сборки (артефакт, в .gitignore)
USER_SYMBOLS := game_symbols.user.txt
GEN_SYMBOLS  := game_symbols.gen.txt
SYMBOLS      := game_symbols.txt

# Каталоги (должны совпадать с options.* в $(CONFIG))
OUT_DIR     := out
ASM_DIR     := $(OUT_DIR)/asm
ASSET_DIR   := $(OUT_DIR)/assets
BUILD_DIR   := build
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

.PHONY: all analyze symbols split check codemap findcode nameprocs dumptext findtext packedtext unpack missions stages gfx pcm music sfx render deps vectors xcheck chains whocalls z80dis build verify rebuild tools clean distclean help

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
# Пересобирает game.yaml и game_symbols.gen.txt из самой ROM. Запускать при
# смене game.gen; оба файла — производные, в них не правят.
analyze:
	$(PYTHON) $(TOOLS_DIR)/analyze.py

# game_symbols.gen.txt в .gitignore, поэтому в свежем клоне его нет —
# восстанавливаем анализатором, иначе сборка не стартует.
$(GEN_SYMBOLS): $(ROM) $(TOOLS_DIR)/analyze.py
	$(PYTHON) $(TOOLS_DIR)/analyze.py

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
# Распаковывает блоки и рисует их в out/gfx/*.png. Без палитры — серым,
# с палитрой:  make gfx GFXARGS="--sprites 43 --pal 031D3C"
GFXARGS ?=
gfx:
	@$(PYTHON) $(TOOLS_DIR)/gfx.py $(GFXARGS)

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

# Кто ведёт на адрес: скан сырых байт по всем формам перехода. Нужен там,
# где анализатор не считает окрестность кодом:  make whocalls WHO=008392
WHO ?= 008392
whocalls:
	@$(PYTHON) $(TOOLS_DIR)/whocalls.py $(WHO)

# ── Звук ─────────────────────────────────────────────────────────────────
# Дизассемблер Z80: сам достаёт звуковой драйвер из z80_driver, распаковывает
# и раскладывает по адресам ОЗУ Z80. Диапазон:  make z80dis Z80FROM=0BB Z80LEN=200
Z80FROM ?= 0
Z80LEN  ?= 1AC0
z80dis:
	@$(PYTHON) $(TOOLS_DIR)/z80dis.py $(Z80FROM) $(Z80LEN)

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
RENDER    := $(BUILD_DIR)/render.exe
RENDERARGS ?=

$(RENDER): $(TOOLS_DIR)/render/render.c third_party/clownz80/unity.c third_party/Nuked-OPN2/ym3438.c
	@$(PYTHON) -c "import os,sys; os.makedirs(sys.argv[1], exist_ok=True)" $(BUILD_DIR)
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

clean:
	$(RMTREE) $(BUILD_DIR)

distclean: clean
	$(RMTREE) $(OUT_DIR)
