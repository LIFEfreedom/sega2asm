#!/usr/bin/env python3
"""Найти и выгрузить весь текст ROM.

    python tools/findtext.py [--out docs/text.md]

Кодировка опознана по сообщениям обработчиков исключений ($000228 и далее):
байты BC BD C3 D1 B4 D7 B0 читаются как システムエラー — это стандартная
JIS X 0201, один байт на символ, строка кончается $00.

Строкой считается прогон допустимых байт, завершённый $00. Чтобы не ловить
шум, требуем минимум катаканы: в настоящем тексте она преобладает, в
случайных данных подряд почти не встречается.

Раскладка ниже $41 своя, не ASCII: код символа служит индексом тайла, потому
что строки уходят в BiosDrawTilemap, пишущий их прямо в таблицу имён.
$40 — переключатель размера шрифта, а не пробел (см. decode).
$20 — пробел, $5F — заполнитель в надписях интерфейса.
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

KANA = "｡｢｣､･ｦｧｨｩｪｫｬｭｮｯｰｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝﾞﾟ"
KAT = {0xA1 + i: ch for i, ch in enumerate(KANA)}
OK = set(KAT) | set(range(0x20, 0x7F))

MIN_LEN = 6      # короче — почти всегда совпадение по случайности
MIN_KANA = 4     # столько катаканы обязано быть в прогоне


def decode(b):
    """Развернуть строку в читаемый вид.

    $40 — НЕ пробел, а переключатель шрифта. Разбор строк в BIOS игры
    ($00172A) перехватывает этот байт, делает `eori.b #$01,d7` и переходит
    к следующему символу, ничего не выводя. В поднятом состоянии коды
    $A6..$DD уменьшаются на $40 и попадают в другой диапазон таблицы
    символ->тайл ($FF0070): вместо мелких тайлов $21+ берутся крупные
    $780+. То есть переключается РАЗМЕР шрифта, а не смысл символов,
    поэтому текст читается одинаково в обоих состояниях.

    Пробел — это $20: в таблице символ->тайл он даёт тайл 0, пустой.
    """
    out = []
    big = False
    for x in b:
        if x == 0x40:
            big = not big
            out.append("⟨крупный⟩" if big else "⟨мелкий⟩")
        elif x in KAT:
            out.append(KAT[x])
        elif 0x20 <= x < 0x7F:
            out.append(chr(x))
        else:
            out.append("?")
    return "".join(out)


def main():
    rom_path = os.path.join(HERE, "game.gen")
    if not os.path.exists(rom_path):
        print("[--] нет game.gen")
        return 1
    rom = open(rom_path, "rb").read()
    n = len(rom)

    found = []
    i = 0
    while i < n:
        if rom[i] not in OK:
            i += 1
            continue
        j = i
        while j < n and rom[j] in OK:
            j += 1
        if j < n and rom[j] == 0 and j - i >= MIN_LEN:
            run = rom[i:j]
            if sum(1 for x in run if x in KAT) >= MIN_KANA:
                found.append((i, run))
        i = j + 1

    out_path = os.path.join(HERE, "docs", "text.md")
    if "--out" in sys.argv:
        out_path = os.path.join(HERE, sys.argv[sys.argv.index("--out") + 1])
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    banks = {}
    for off, run in found:
        banks.setdefault(off >> 16, []).append((off, run))

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Текст ROM\n\n")
        f.write("Извлечено `tools/findtext.py`. Кодировка — JIS X 0201, ")
        f.write("полуширинная катакана, один байт на символ, терминатор `$00`.\n\n")
        f.write("Опознана по сообщениям обработчиков исключений: байты ")
        f.write("`BC BD C3 D1 B4 D7 B0` на `$000228` читаются как ")
        f.write("システムエラー. `$40` — пробел, `$5F` — заполнитель.\n\n")
        f.write("Строк: **%d**, байт текста: **%d**.\n\n" % (
            len(found), sum(len(r) for _, r in found)))
        for b in sorted(banks):
            rows = banks[b]
            f.write("## Банк `$%02X0000` — %d строк\n\n" % (b, len(rows)))
            f.write("| адрес | текст |\n|---|---|\n")
            for off, run in rows:
                txt = decode(run).replace("|", "\\|")
                f.write("| `$%06X` | %s |\n" % (off, txt))
            f.write("\n")

    print("строк: %d, байт текста: %d" % (len(found), sum(len(r) for _, r in found)))
    print("записано: %s" % os.path.relpath(out_path, HERE))
    print("\nкрупнейшие скопления:")
    for b in sorted(banks, key=lambda k: -len(banks[k]))[:5]:
        print("  $%02X0000: %4d строк" % (b, len(banks[b])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
