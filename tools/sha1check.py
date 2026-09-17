#!/usr/bin/env python3
"""Сверка собранного ROM с оригиналом.

    python tools/sha1check.py <built.bin> <expected-sha1|config.yaml> [original.gen]

При расхождении показывает первое различие и то, в каком сегменте game.yaml
оно лежит — это сразу указывает, какой сегмент собрался не так.
"""
import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def seg_at(offset):
    """Имя сегмента game.yaml, покрывающего offset."""
    try:
        import yaml
        cfg = yaml.safe_load(open(os.path.join(HERE, "game.yaml"), encoding="utf-8"))
    except Exception:
        return None
    for s in cfg.get("segments", []):
        if s["start"] <= offset < s["end"]:
            return "%s (%s, $%06X-$%06X)" % (s["name"], s["type"], s["start"], s["end"])
    return None


def dump(data, off, n=16):
    lo = max(0, off - (off % n))
    chunk = data[lo:lo + n]
    return "$%06X  %s" % (lo, " ".join("%02X" % b for b in chunk))


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    built_path, want = sys.argv[1], sys.argv[2]
    # Ожидаемый хеш берём из конфига, а не из копии в Makefile: две копии
    # разъезжаются, стоит подменить ROM.
    if not re.fullmatch(r"[0-9A-Fa-f]{40}", want):
        import yaml
        want = yaml.safe_load(open(want, encoding="utf-8")).get("sha1", "")
    want = want.upper()
    orig_path = sys.argv[3] if len(sys.argv) > 3 else None

    if not os.path.exists(built_path):
        print("[FAIL] нет файла %s" % built_path)
        return 1

    built = open(built_path, "rb").read()
    got = hashlib.sha1(built).hexdigest().upper()

    print("собрано : %s (%d байт)" % (built_path, len(built)))
    print("SHA-1   : %s" % got)
    print("ожидание: %s" % want)

    if got == want:
        print("\n[OK] Побайтово совпадает с оригиналом.")
        return 0

    print("\n[FAIL] SHA-1 не совпал.")

    if not orig_path or not os.path.exists(orig_path):
        print("Оригинал не передан — где расхождение, сказать нельзя.")
        return 1

    orig = open(orig_path, "rb").read()
    if len(built) != len(orig):
        print("Размер: собрано %d, оригинал %d (разница %+d)"
              % (len(built), len(orig), len(built) - len(orig)))

    n = min(len(built), len(orig))
    first = next((i for i in range(n) if built[i] != orig[i]), None)
    if first is None:
        if len(built) == len(orig):
            print("Байты совпадают с %s — расходится только ОЖИДАЕМЫЙ хеш."
                  % os.path.basename(orig_path))
            print("Похоже, sha1 в конфиге устарел относительно самой ROM.")
        else:
            print("Общая часть совпадает; отличается только длина.")
        return 1

    diff = sum(1 for i in range(n) if built[i] != orig[i])
    print("\nПервое расхождение на $%06X (всего различий в общей части: %d)"
          % (first, diff))
    s = seg_at(first)
    if s:
        print("Сегмент : %s" % s)
    print("оригинал %s" % dump(orig, first))
    print("собрано  %s" % dump(built, first))
    return 1


if __name__ == "__main__":
    sys.exit(main())
