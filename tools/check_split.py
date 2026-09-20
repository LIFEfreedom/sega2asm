#!/usr/bin/env python3
"""Проверка, что сплит по YAML покрывает ROM без дыр и пересечений,
а извлечённые .bin совпадают с исходными байтами.

Это проверяет конфиг и вывод sega2asm независимо от ассемблера: если здесь
ошибка, побайтовая пересборка не сойдётся в любом случае.

    python tools/check_split.py [config.yaml]
"""
import hashlib
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import config_path

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def fail(msg):
    print("  [FAIL] " + msg)
    return 1


def main():
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else config_path()
    cfg = yaml.safe_load(open(cfg_path, encoding="utf-8"))
    opts = cfg["options"]

    rom_path = os.path.join(os.path.dirname(os.path.abspath(cfg_path)),
                            opts["target_path"])
    rom = open(rom_path, "rb").read()
    base = os.path.join(os.path.dirname(os.path.abspath(cfg_path)),
                        opts["base_path"])
    asset_dir = os.path.join(base, opts.get("asset_path", "assets"))

    print("ROM    : %s (%d bytes)" % (os.path.basename(rom_path), len(rom)))
    want = cfg.get("sha1", "")
    got = hashlib.sha1(rom).hexdigest().upper()
    if want and got != want.upper():
        return fail("SHA-1 ROM: %s, в конфиге %s" % (got, want.upper()))
    print("SHA-1  : %s%s" % (got, "  (совпадает с конфигом)" if want else ""))

    segs = sorted(cfg["segments"], key=lambda s: s["start"])
    errs = 0

    # --- 1. покрытие без дыр и пересечений ------------------------------
    print("\n1. Покрытие ROM %d сегментами" % len(segs))
    cur = 0
    for s in segs:
        st, en = s["start"], s["end"]
        if st > cur:
            errs += fail("дыра $%06X-$%06X (%d байт) перед %s"
                         % (cur, st, st - cur, s["name"]))
        elif st < cur:
            errs += fail("пересечение на $%06X в %s" % (st, s["name"]))
        if en <= st:
            errs += fail("%s: end <= start" % s["name"])
        cur = max(cur, en)
    if cur != len(rom):
        errs += fail("сегменты кончаются на $%06X, ROM — на $%06X"
                     % (cur, len(rom)))
    if not errs:
        print("  [OK] $000000-$%06X покрыт сплошняком, пересечений нет" % cur)

    # --- 2. извлечённые .bin совпадают с ROM ----------------------------
    bins = [s for s in segs if s["type"] == "bin"]
    print("\n2. Сверка %d извлечённых .bin с исходными байтами" % len(bins))
    checked = missing = 0
    for s in bins:
        sub = s.get("subdir", "bin")
        path = os.path.join(asset_dir, sub, s["name"] + ".bin")
        if not os.path.exists(path):
            missing += 1
            continue
        blob = open(path, "rb").read()
        orig = rom[s["start"]:s["end"]]
        if blob != orig:
            errs += fail("%s: %d байт на диске против %d в ROM%s"
                         % (s["name"], len(blob), len(orig),
                            "" if len(blob) != len(orig) else ", содержимое отличается"))
        else:
            checked += 1
    print("  [OK] совпало: %d" % checked)
    if missing:
        print("  [--] не найдено на диске: %d (запусти сплит: make split)" % missing)

    # --- 3. сводка по типам ---------------------------------------------
    print("\n3. Сводка")
    by_type = {}
    for s in segs:
        t = s["type"]
        by_type.setdefault(t, [0, 0])
        by_type[t][0] += 1
        by_type[t][1] += s["end"] - s["start"]
    for t in sorted(by_type):
        n, b = by_type[t]
        print("  %-8s %2d сегм.  %9d байт  %5.1f%%"
              % (t, n, b, b / len(rom) * 100))

    print("\n%s" % ("ОШИБОК НЕТ" if not errs else "ОШИБОК: %d" % errs))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
