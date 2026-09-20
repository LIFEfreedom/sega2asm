#!/usr/bin/env python3
"""Куда писать и откуда читать сгенерированное.

Всё, что делают инструменты, лежит под `out/<имя проекта>/`, а не прямо в
`out/`. Имя берётся из `name:` разбираемого YAML, так что второй ROM в том
же дереве не затирает первый.

Пользоваться так:

    from paths import OUT, asm_dir
    d = OUT("gfx")            # out/dynabrothers2/gfx
    a = asm_dir()             # out/dynabrothers2/asm/m68k

Переопределить проект можно переменной окружения `SEGA2ASM_CONFIG`
(путь к YAML) или `SEGA2ASM_OUT` (готовый каталог вывода целиком).
"""
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_CONFIG = os.path.join(HERE, "game.yaml")


def project_name(config=None):
    """Значение `name:` из YAML. Без файла — имя самого YAML без расширения."""
    path = config or os.environ.get("SEGA2ASM_CONFIG") or DEFAULT_CONFIG
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^name:\s*(\S+)", line)
                if m:
                    return m.group(1).strip("\"'")
    except OSError:
        pass
    return os.path.splitext(os.path.basename(path))[0]


def out_root(config=None):
    """Корень вывода: out/<имя>. Целиком переопределяется SEGA2ASM_OUT."""
    forced = os.environ.get("SEGA2ASM_OUT")
    if forced:
        return forced if os.path.isabs(forced) else os.path.join(HERE, forced)
    return os.path.join(HERE, "out", project_name(config))


def OUT(*parts):
    """Путь внутри корня вывода. Каталоги не создаёт — это дело вызывающего."""
    return os.path.join(out_root(), *parts)


def asm_dir():
    """Каталог с дизассемблированным кодом — самый ходовой вход."""
    return OUT("asm", "m68k")


def build_dir():
    """Собранное этого проекта: build/<имя>. render.exe туда НЕ кладут."""
    return os.path.join(HERE, "build", project_name())


def toolbin(*parts):
    """Скомпилированные помощники, общие на все проекты: build/tools."""
    return os.path.join(HERE, "build", "tools", *parts)


def rom_path(config=None):
    """Разбираемая ROM: `target_path:` из YAML. Переопределяется SEGA2ASM_ROM."""
    forced = os.environ.get("SEGA2ASM_ROM")
    if forced:
        return forced if os.path.isabs(forced) else os.path.normpath(os.path.join(HERE, forced))
    path = config or os.environ.get("SEGA2ASM_CONFIG") or DEFAULT_CONFIG
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^\s+target_path:\s*(\S+)", line)
                if m:
                    v = m.group(1).strip("\"'")
                    return v if os.path.isabs(v) else os.path.normpath(os.path.join(HERE, v))
    except OSError:
        pass
    return os.path.join(HERE, "game.gen")


def rom_bytes(config=None):
    """Содержимое ROM целиком — самый ходовой вход в инструментах."""
    with open(rom_path(config), "rb") as f:
        return f.read()


def config_path(config=None):
    """Разбираемый YAML: аргумент, SEGA2ASM_CONFIG или game.yaml."""
    return config or os.environ.get("SEGA2ASM_CONFIG") or DEFAULT_CONFIG


def sym_base(config=None):
    """Префикс файлов символов: `game.yaml` -> `game_symbols`.

    Имена символов привязаны к ROM, а не к проекту вывода, поэтому берутся
    от имени YAML, а не от `name:` внутри него.
    """
    stem = os.path.splitext(os.path.basename(config_path(config)))[0]
    return os.path.join(HERE, stem + "_symbols")


def user_symbols(config=None):
    """Ваши имена, под git. Переживают смену ROM и пересборку."""
    return sym_base(config) + ".user.txt"


def gen_symbols(config=None):
    """Имена от анализатора. Перезаписываются каждым прогоном."""
    return sym_base(config) + ".gen.txt"


def merged_symbols(config=None):
    """Склейка для сборки — артефакт, в .gitignore."""
    return sym_base(config) + ".txt"


def coverage_path(config=None):
    """Карта покрытия анализатора. Своя на каждый ROM, иначе второй затрёт."""
    stem = os.path.splitext(os.path.basename(config_path(config)))[0]
    return os.path.join(HERE, "tools", ".coverage-%s.pkl" % stem)


def docs_dir(config=None):
    """Каталог документов проекта.

    У первого разбора (Dyna Brothers 2) документы лежат плоско в `docs/` с
    префиксом `game-`; заводить ему подкаталог задним числом значило бы
    переписать полсотни ссылок. Все остальные проекты пишут в `docs/<имя>/`,
    иначе второй ROM затирает документы первого — так уже случалось.
    """
    name = project_name(config)
    if name == "dynabrothers2":
        return os.path.join(HERE, "docs")
    return os.path.join(HERE, "docs", name)
