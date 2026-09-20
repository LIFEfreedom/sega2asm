#!/usr/bin/env python3
"""Собрать C-помощника тем компилятором, который есть на машине.

    from ccbuild import build
    build(toolbin("render.exe"), [src1, src2, ...])

Зачем. Makefile зовёт `$(CC) -O2 -o ... -lm`, то есть подразумевает gcc.
На этой машине gcc нет вовсе, зато есть MSVC от Visual Studio, и ключи у
него другие. Поиск идёт по порядку: gcc, clang, cc — и только потом MSVC,
которому нужен ещё и `vcvars64.bat`, иначе он не найдёт собственные
заголовки.

Пересборка пропускается, если готовый файл новее всех исходников.
"""
import os
import shutil
import subprocess
import sys

VS_ROOTS = [
    r"C:\Program Files\Microsoft Visual Studio",
    r"C:\Program Files (x86)\Microsoft Visual Studio",
]


def _find_vcvars():
    """Путь к vcvars64.bat самой свежей установки Visual Studio."""
    found = []
    for root in VS_ROOTS:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, files in os.walk(root):
            if "vcvars64.bat" in files:
                found.append(os.path.join(dirpath, "vcvars64.bat"))
            # глубже Auxiliary\Build лезть незачем
            if os.path.basename(dirpath) == "Build":
                dirnames[:] = []
    return sorted(found)[-1] if found else None


def _fresh(exe, sources):
    if not os.path.exists(exe):
        return False
    t = os.path.getmtime(exe)
    return all(os.path.getmtime(s) <= t for s in sources)


def build(exe, sources, quiet=False):
    """-> путь к собранному файлу. Бросает SystemExit, если собрать нечем."""
    sources = [os.path.abspath(s) for s in sources]
    exe = os.path.abspath(exe)
    if _fresh(exe, sources):
        return exe
    os.makedirs(os.path.dirname(exe), exist_ok=True)

    cc = None
    for name in (os.environ.get("CC"), "gcc", "clang", "cc"):
        if name and shutil.which(name):
            cc = shutil.which(name)
            break
    if cc:
        cmd = [cc, "-O2", "-o", exe] + sources + ["-lm"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            raise SystemExit("%s: %s" % (os.path.basename(cc),
                                         (r.stderr or r.stdout).strip()))
        if not quiet:
            print("собрано %s (%s)" % (os.path.basename(exe),
                                       os.path.basename(cc)))
        return exe

    vcvars = _find_vcvars()
    if not vcvars:
        raise SystemExit(
            "нет ни gcc/clang, ни Visual Studio — поставьте компилятор C\n"
            "  winget install -e --id BrechtSanders.WinLibs.POSIX.UCRT")
    obj = os.path.join(os.path.dirname(exe), "obj")
    os.makedirs(obj, exist_ok=True)
    # cl не понимает POSIX-путей MSYS, поэтому всё через cmd и os.path.
    line = ('call "%s" >nul && cl /nologo /O2 /TC /wd4996 %s /Fe:"%s" /Fo:"%s\\\\"'
            % (vcvars, " ".join('"%s"' % s for s in sources), exe, obj))
    r = subprocess.run(["cmd", "/c", line], capture_output=True, text=True)
    if r.returncode or not os.path.exists(exe):
        raise SystemExit("cl: %s" % (r.stdout or r.stderr).strip())
    if not quiet:
        print("собрано %s (MSVC)" % os.path.basename(exe))
    return exe


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    build(sys.argv[1], sys.argv[2:])
