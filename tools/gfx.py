#!/usr/bin/env python3
"""Достаёт графику: распаковывает блоки и рисует их в PNG.

    make gfx                                    сводка по всему
    make gfx GFXARGS=--all                      ВСЁ в цвете в out/<имя>/gfx/
    make gfx GFXARGS="--stages 1 0"             набор тайлов этапа 1 палитрой 0
    make gfx GFXARGS="--sprites 43"             кадры набора 43
    make gfx GFXARGS=062BDA                     блок по адресу
    make gfx GFXARGS=--findpal                  палитры в ROM

Три хранилища и две палитры по умолчанию.

* `table_assets` `$061800` — 30 записей, наборы тайлов местности.
  Идут четвёрками: описание метатайлов, затем наборы по 96, 256 и 128
  тайлов. Описание узнаётся по началу `FF 15 16 17` и тайлами не является.
* `table_gfx_a` `$078818` — 48 записей, каждая ведёт на СВОЮ таблицу
  указателей: три уровня, а не два. На третьем — кадры ровно по 512 байт,
  то есть по 16 тайлов, спрайт 4x4. Всего 5464 кадра.
* `$01318C` — одиннадцать записей по `$1CC` байт: **14 палитр и номера
  трёх наборов тайлов**. Это и есть пара «графика — цвет» для поля боя.

Палитры поля боя раскладываются по слотам CRAM в `$005384`:
слот 0 — `data_99[0]`, слоты 1 и 2 — `data_99` по номерам из байтов
`+$28` и `+$29` описания миссии (на деле всегда 1 и 3), слот 3 — палитра
из записи этапа по байту `+$4C`. Поэтому спрайты по умолчанию рисуются
палитрой `data_99[3]`, а тайлы — палитрой записи.

Тайл: 8x8 точек по 4 бита, 32 байта, строки сверху вниз, в байте сначала
левая точка. **У спрайтов тайлы идут по столбцам**, поэтому кадр 4x4
перед выводом переставляется — иначе картинка рассыпается на полосы.

Палитра — 16 слов CRAM вида `0BGR`, по три значащих бита на составляющую.
Это же правило служит признаком поиска (`--findpal`). В ОЗУ у палитры
другой вид: шесть байт на цвет, «текущий» и «целевой» по три нибблa, —
так устроено затухание (`$00C5B0`), и по этому виду искать бесполезно.
"""
import io
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from unpack import unpack  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT as out_path, rom_bytes

rom = rom_bytes()
ASSETS = 0x061800
SPRITES = 0x078818
PAL_ARRAY = 0x00F784      # data_99: девять палитр по 32 байта подряд
STAGE_GFX = 0x01318C      # одиннадцать записей по $1CC
STAGE_REC = 0x01CC
UNIT_PAL = PAL_ARRAY + 32 * 3   # слот 2 поля боя: им нарисованы юниты
METATILE_MARK = bytes([0xFF, 0x15, 0x16, 0x17])
SPRITE_CUT = frozenset([0])   # у спрайтов нулевой цвет прозрачен
GREY = [(0, 0, 0)] + [(17 * i,) * 3 for i in range(1, 16)]

L = lambda a: struct.unpack(">I", rom[a:a + 4])[0]


def read_palette(a):
    out = []
    for i in range(16):
        v = (rom[a + 2 * i] << 8) | rom[a + 2 * i + 1]
        if v & 0xF111:
            raise ValueError("$%06X не палитра: слово %d = $%04X" % (a, i, v))
        out.append((((v >> 1) & 7) * 36, ((v >> 5) & 7) * 36,
                    ((v >> 9) & 7) * 36))
    return out


def find_palettes(lo=0, hi=None, variety=6):
    """Все 32-байтные участки, проходящие правило `0BGR`."""
    hi = hi if hi is not None else len(rom) - 32
    out, a = [], lo
    while a < hi:
        ws = [(rom[a + 2 * j] << 8) | rom[a + 2 * j + 1] for j in range(16)]
        if not any(v & 0xF111 for v in ws) and len(set(ws)) >= variety:
            out.append(a)
            a += 32
        else:
            a += 2
    return out


def png(path, w, h, rows, alpha=False):
    """Тип 2 (RGB) или 6 (RGBA), если точки заданы четвёрками."""
    nul = bytes([0])
    raw = b"".join(nul + bytes(c for q in r for c in q) for r in rows)

    def chunk(tag, data):
        c = tag + data
        return (struct.pack(">I", len(data)) + c
                + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF))

    sig = bytes([137, 80, 78, 71, 13, 10, 26, 10])
    with open(path, "wb") as f:
        f.write(sig)
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8,
                                           6 if alpha else 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        f.write(chunk(b"IEND", b""))


def ground_colours(data):
    """Цвета фона: набор красок самого простого тайла.

    Земля в этих наборах нарисована прямо в тайле, отдельного слоя нет.
    Но чистые тайлы земли в наборе есть всегда, и красок в них меньше,
    чем в любом тайле с предметом. Берём самый частый из наименьших
    наборов красок — это и есть фон.
    """
    import collections
    per = []
    for i in range(len(data) // 32):
        s = set()
        for b in data[i * 32:(i + 1) * 32]:
            s.add(b >> 4)
            s.add(b & 15)
        per.append(frozenset(s))
    if not per:
        return frozenset()
    least = min(len(s) for s in per)
    cnt = collections.Counter(s for s in per if len(s) == least)
    return cnt.most_common(1)[0][0]


def flood_background(idx, w, h, cut):
    """Точки фона: те, что дотягиваются до края листа заливкой.

    Не «все точки цвета фона»: те же краски идут на затенение внутри
    предметов, и выбивание по всему полю дырявит их насквозь. Заливать
    надо ЛИСТ ЦЕЛИКОМ, а не отдельный тайл: предмет больше восьми точек
    и внутри своего тайла до края достаёт.
    """
    seen = bytearray(w * h)
    stack = []
    for x in range(w):
        stack.append((x, 0))
        stack.append((x, h - 1))
    for y in range(h):
        stack.append((0, y))
        stack.append((w - 1, y))
    while stack:
        x, y = stack.pop()
        if not (0 <= x < w and 0 <= y < h):
            continue
        p = y * w + x
        if seen[p] or idx[y][x] not in cut:
            continue
        seen[p] = 1
        stack.append((x + 1, y))
        stack.append((x - 1, y))
        stack.append((x, y + 1))
        stack.append((x, y - 1))
    return seen


def render(data, path, cols=16, pal=None, scale=2, cut=None):
    """cut — набор индексов фона; они станут прозрачными."""
    pal = pal or GREY
    n = len(data) // 32
    rows = (n + cols - 1) // cols
    w, h = cols * 8, rows * 8
    idx = [[0] * w for _ in range(h)]
    for t in range(n):
        tx, ty = (t % cols) * 8, (t // cols) * 8
        tile = data[t * 32:(t + 1) * 32]
        for y in range(8):
            b = tile[y * 4: y * 4 + 4]
            for x in range(8):
                v = (b[x >> 1] >> 4) if x % 2 == 0 else (b[x >> 1] & 15)
                idx[ty + y][tx + x] = v
    if cut:
        seen = flood_background(idx, w, h, cut)
        blank = (0, 0, 0, 0)
        img = [[blank if seen[y * w + x] else pal[idx[y][x]] + (255,)
                for x in range(w)] for y in range(h)]
    else:
        img = [[pal[idx[y][x]] for x in range(w)] for y in range(h)]
    if scale > 1:
        big = []
        for r in img:
            rr = [q for q in r for _ in range(scale)]
            big.extend([rr] * scale)
        img, w, h = big, w * scale, h * scale
    png(path, w, h, img, alpha=bool(cut))
    return n


def columnwise(frame, side=4):
    """Кадр спрайта: тайлы по столбцам -> построчно."""
    t = [frame[k * 32:(k + 1) * 32] for k in range(side * side)]
    return b"".join(t[x * side + y] for y in range(side) for x in range(side))


def render_frames(frames, path, per_row=8, side=4, pal=None, scale=2,
                  cut=None):
    """Кадры 4x4 сеткой: рядом их видно, а лентой в 4 тайла — нет."""
    blank = bytes(32 * side)
    tiles = []
    rows = (len(frames) + per_row - 1) // per_row
    for r in range(rows):
        band = frames[r * per_row:(r + 1) * per_row]
        for y in range(side):
            for fr in band:
                tiles.append(fr[y * side * 32:(y * side + side) * 32])
            tiles.extend([blank] * (per_row - len(band)))
    return render(b"".join(tiles), path, cols=per_row * side,
                  pal=pal, scale=scale, cut=cut)


def out_dir():
    d = out_path("gfx")
    os.makedirs(d, exist_ok=True)
    return d


def table_len(base):
    n = (L(base) - base) // 4
    return n if 0 < n < 4096 else 0


def do_assets(d, pal):
    n = table_len(ASSETS)
    print("== %d наборов тайлов местности, таблица $%06X ==" % (n, ASSETS))
    for i in range(n):
        p = L(ASSETS + 4 * i)
        m, size, data, _e = unpack(rom, p)
        if bytes(data[:4]) == b"\xFF\x15\x16\x17":
            print("  %2d  $%06X  %6d байт  — описание метатайлов, не тайлы"
                  % (i, p, size))
            continue
        path = os.path.join(d, "asset_%02d.png" % i)
        t = render(data, path, pal=pal)
        print("  %2d  $%06X  %6d байт  %4d тайлов  -> %s"
              % (i, p, size, t, os.path.relpath(path, HERE)))


# Корень $078800 держит два указателя в ОДИН массив: $078810 -> $078818
# (записи 0..47) и $078814 -> $0788D8 (записи 48..115). Первая половина —
# подтаблицы кадров длинными словами, вторая устроена иначе: её читают
# самоотносительными СЛОВАМИ ($0018AA), и сюда она не входит.
SPRITE_SETS = 48


def stage_records():
    """Записи графики этапа: 14 палитр и номера трёх наборов тайлов."""
    _m, size, d, _e = unpack(rom, STAGE_GFX)
    out = []
    for k in range(size // STAGE_REC):
        r = bytes(d[k * STAGE_REC:(k + 1) * STAGE_REC])
        pals = [[(((v >> 1) & 7) * 36, ((v >> 5) & 7) * 36, ((v >> 9) & 7) * 36)
                 for v in [(r[i * 32 + 2 * j] << 8) | r[i * 32 + 2 * j + 1]
                           for j in range(16)]] for i in range(14)]
        assets = [((r[0x1C2 + 2 * i] << 8) | r[0x1C3 + 2 * i]) // 4
                  for i in range(3)]
        out.append((pals, assets))
    return out


def do_stages(d, only=None, pal_no=0):
    recs = stage_records()
    print("== %d записей графики этапа, $%06X ==" % (len(recs), STAGE_GFX))
    for k, (pals, assets) in enumerate(recs):
        if only is not None and k != only:
            continue
        print("  %2d  наборы тайлов %s, палитр 14" % (k, assets))
        if only is None:
            continue
        for a in assets:
            p = L(ASSETS + 4 * a)
            _m, size, data, _e = unpack(rom, p)
            if bytes(data[:4]) == METATILE_MARK:
                print("      набор %2d — описание метатайлов, пропущен" % a)
                continue
            path = os.path.join(d, "stage%02d_pal%d_asset%02d.png"
                                % (k, pal_no, a))
            t = render(data, path, pal=pals[pal_no])
            print("      набор %2d  %4d тайлов -> %s"
                  % (a, t, os.path.relpath(path, HERE)))


def do_sprites(d, pal, only=None):
    pal = pal or read_palette(UNIT_PAL)
    n = SPRITE_SETS
    total = empty = 0
    print("== %d наборов спрайтов, таблица $%06X ==" % (n, SPRITES))
    for i in range(n):
        if only is not None and i != only:
            continue
        sub = L(SPRITES + 4 * i)
        k = table_len(sub)
        if not k:
            print("  %2d  $%06X  подтаблица не разбирается" % (i, sub))
            continue
        frames = []
        for j in range(k):
            p = L(sub + 4 * j)
            if not (0 < p < 0x200000):
                empty += 1
                continue
            _m, _size, data, _e = unpack(rom, p)
            frames.append(columnwise(bytes(data)))
        total += len(frames)
        if only is None:
            print("  %2d  $%06X  записей %4d, кадров %4d" % (i, sub, k, len(frames)))
            continue
        path = os.path.join(d, "sprites_%02d.png" % i)
        render_frames(frames, path, pal=pal, cut=SPRITE_CUT)
        print("  %2d  $%06X  кадров %d -> %s"
              % (i, sub, len(frames), os.path.relpath(path, HERE)))
    if only is None:
        print("  итого кадров %d, пустых записей %d" % (total, empty))


def palette_strip(pals, path, cell=16, scale=1):
    """Полоса палитр: строка на палитру, клетка на цвет."""
    w, h = 16 * cell, len(pals) * cell
    img = [[(0, 0, 0)] * w for _ in range(h)]
    for r, pal in enumerate(pals):
        for c, col in enumerate(pal):
            for y in range(cell):
                for x in range(cell):
                    img[r * cell + y][c * cell + x] = col
    png(path, w, h, img)


def do_all(d):
    """Всё, что является тайлами, в цвете; плюс оглавление."""
    lines = ["# Выгрузка графики", "",
             "СГЕНЕРИРОВАНО `tools/gfx.py --all` (`make gfx GFXARGS=--all`).",
             "", "Тайлы местности покрашены палитрой своей записи этапа,",
             "спрайты — палитрой юнитов `data_99[3]` = `$00F7E4`.", ""]
    recs = stage_records()
    unit = read_palette(UNIT_PAL)
    alt = read_palette(PAL_ARRAY + 32)   # слот 1: вторая палитра юнитов

    lines += ["## Тайлы местности", "",
              "| этап | набор | тайлов | фон | файлы |",
              "|---|---|---|---|---|"]
    used = set()
    seen = {}
    for k, (pals, assets) in enumerate(recs):
        palette_strip(pals, os.path.join(d, "stage%02d_palettes.png" % k))
        for a in assets:
            used.add(a)
            p = L(ASSETS + 4 * a)
            _m, _size, data, _e = unpack(rom, p)
            if bytes(data[:4]) == METATILE_MARK:
                continue
            key = (a, tuple(pals[0]))
            if key in seen:
                lines.append("| %d | %d | — | — | то же, что у этапа %d |"
                             % (k, a, seen[key]))
                continue
            seen[key] = k
            name = "terrain_stage%02d_asset%02d.png" % (k, a)
            t = render(data, os.path.join(d, name), pal=pals[0])
            g = ground_colours(data)
            cutname = name[:-4] + "_cut.png"
            render(data, os.path.join(d, cutname), pal=pals[0], cut=g)
            lines.append("| %d | %d | %d | %s | `%s`, `%s` |"
                         % (k, a, t,
                            ", ".join(str(c) for c in sorted(g)),
                            name, cutname))

    rest = [i for i in range(table_len(ASSETS)) if i not in used]
    if rest:
        lines += ["", "Наборы, которые не берёт ни одна запись этапа "
                  "(рисуются серым): " + ", ".join(str(i) for i in rest), ""]
        for a in rest:
            p = L(ASSETS + 4 * a)
            _m, _size, data, _e = unpack(rom, p)
            if bytes(data[:4]) == METATILE_MARK:
                continue
            render(data, os.path.join(d, "terrain_asset%02d.png" % a))

    lines += ["", "## Спрайты", "",
              "Слоты 1 и 2 CRAM — обе палитры юнитов, и какой набор в каком,",
              "по коду не видно; поэтому оба варианта.", "",
              "| набор | кадров | файлы |", "|---|---|---|"]
    for i in range(SPRITE_SETS):
        sub = L(SPRITES + 4 * i)
        k = table_len(sub)
        if not k:
            lines.append("| %d | — | подтаблица не разбирается |" % i)
            continue
        frames = []
        for j in range(k):
            p = L(sub + 4 * j)
            if not (0 < p < 0x200000):
                continue
            _m, _size, data, _e = unpack(rom, p)
            frames.append(columnwise(bytes(data)))
        for tag, pl in (("pal1", alt), ("pal3", unit)):
            name = "sprites_%02d_%s.png" % (i, tag)
            render_frames(frames, os.path.join(d, name), pal=pl,
                          cut=SPRITE_CUT)
        lines.append("| %d | %d | `sprites_%02d_pal1.png`, `sprites_%02d_pal3.png` |"
                     % (i, len(frames), i, i))

    lines += ["", "## Палитры", "",
              "По записи этапа — полоса из её четырнадцати палитр:", "",
              "| запись | файл |", "|---|---|"]
    for k in range(len(recs)):
        lines.append("| %d | `stage%02d_palettes.png` |" % (k, k))
    lines.append("")
    idx = os.path.join(d, "index.md")
    f = io.open(idx, "w", encoding="utf-8")
    f.write(chr(10).join(lines))
    f.close()
    print("записано: %s" % os.path.relpath(idx, HERE))


def main():
    args = sys.argv[1:]
    d = out_dir()
    pal = None
    if "--pal" in args:
        i = args.index("--pal")
        pal = read_palette(int(args[i + 1], 16))
        del args[i:i + 2]

    if not args:
        do_assets(d, pal)
        print()
        do_sprites(d, pal)
        print()
        do_stages(d)
        return 0

    if args[0] == "--all":
        do_all(d)
        return 0

    if args[0] == "--findpal":
        hits = find_palettes()
        print("палитр в ROM: %d" % len(hits))
        for h in hits:
            print("  $%06X" % h)
        return 0

    if args[0] == "--assets":
        do_assets(d, pal)
        return 0

    if args[0] == "--sprites":
        do_sprites(d, pal, int(args[1]) if len(args) > 1 else None)
        return 0

    if args[0] == "--stages":
        only = int(args[1]) if len(args) > 1 else None
        pal_no = int(args[2]) if len(args) > 2 else 0
        do_stages(d, only, pal_no)
        return 0

    a = int(args[0], 16)
    m, size, data, _e = unpack(rom, a)
    path = os.path.join(d, "block_%06X.png" % a)
    cut = ground_colours(bytes(data)) if "--cut" in args else None
    if cut:
        path = path[:-4] + "_cut.png"
    t = render(data, path, pal=pal, cut=cut)
    print("$%06X: метод %d, %d байт, %d тайлов -> %s"
          % (a, m, size, t, os.path.relpath(path, HERE)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
