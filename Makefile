# ─────────────────────────────────────────────────────────────────────────
# Dyna Brothers 2 - Sega Channel Special (Japan) — проект дизассемблирования
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
SHA1        := 8E10298DFFF521397F0E82D1787E701D6928750B
CONFIG      := game.yaml
SYMBOLS     := game_symbols.txt

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
# /m — разрешить мнемоники как метки, /p — строгий разбор, /k — не падать
# на первой ошибке. Взято из smd_alteredbeast.
ASM68K_FLAGS ?= /m /p /k

# Вывод питона в UTF-8, иначе кириллица бьётся о кодовую страницу консоли
export PYTHONIOENCODING := utf-8

.PHONY: all split check build verify rebuild tools clean distclean help

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

# ── Разрезание ROM ───────────────────────────────────────────────────────
split: $(MAIN_ASM)

$(MAIN_ASM): $(SEGA2ASM) $(CONFIG) $(SYMBOLS) $(ROM)
	$(SEGA2ASM) -c $(CONFIG) -v

# ── Проверка сплита (работает без ассемблера) ────────────────────────────
check: $(MAIN_ASM)
	@$(PYTHON) $(TOOLS_DIR)/check_split.py $(CONFIG)

# ── Сборка ───────────────────────────────────────────────────────────────
# asm68k разбирает командную строку как source,object,,listing — запятые
# обязательны, третье поле (файл ошибок) пустое.
# Собирать из корня репозитория: в $(MAIN_ASM) пути include относительные.
build: $(TARGET)

$(TARGET): $(MAIN_ASM) | $(BUILD_DIR)
	$(ASM68K) $(ASM68K_FLAGS) "$(MAIN_ASM)","$(TARGET)",,"$(LISTING)"

# mkdir -p / rm -rf через python: GNU make под Windows зовёт cmd.exe, где их нет
$(BUILD_DIR):
	@$(PYTHON) -c "import os,sys; os.makedirs(sys.argv[1], exist_ok=True)" $(BUILD_DIR)

# ── Сверка ───────────────────────────────────────────────────────────────
verify: $(TARGET)
	@$(PYTHON) $(TOOLS_DIR)/sha1check.py $(TARGET) $(SHA1) $(ROM)

rebuild: split build verify

# ── Уборка ───────────────────────────────────────────────────────────────
RMTREE := $(PYTHON) -c "import shutil,sys; [shutil.rmtree(p, ignore_errors=True) for p in sys.argv[1:]]"

clean:
	$(RMTREE) $(BUILD_DIR)

distclean: clean
	$(RMTREE) $(OUT_DIR)
