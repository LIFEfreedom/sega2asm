#!/usr/bin/env python3
"""Уровни Maui Mallard: таблица, графика, карты.

    python tools/levels.py             сводка по 23 уровням
    python tools/levels.py --tiles 0   лист тайлов уровня
    python tools/levels.py --meta 0    лист метатайлов 16x16
    python tools/levels.py --map 0     карта уровня целиком
    python tools/levels.py --bg 0      фоновый слой (64x32)
    python tools/levels.py --solid 0   карта с профилем земли и преградами
    python tools/levels.py --objects 0 карта со спрайтами объектов
    python tools/levels.py --names     названия всех уровней
    python tools/levels.py --passwords пароли уровней и чит на DEBUG
    python tools/levels.py --title 0   заставка уровня в PNG
    python tools/levels.py --scene 0   заставка вместе с её актёрами
    python tools/levels.py --hud       глифы счётчиков HUD
    python tools/levels.py --hud 1ECC9E 10   произвольная таблица глифов
    python tools/levels.py --screen    титульный экран и титры
    python tools/levels.py --screen 1F0194 1EFBFE 1F0612   своя тройка
    python tools/levels.py --actors    актёры сценок, все 11 списков
    python tools/levels.py --actors 1E9272   один список
    make levels LEVEL="--map 0"

Три таблицы по 23 записи идут подряд и держат всё об уровне:

| адрес | что |
|---|---|
| `$1FCB50` | запись уровня, `$42` байта |
| `$1FCBAC` | буквы названия уровня для заставки |
| `$1FCC08` | процедура уровня (все 23 ведут в код) |

Читает их `$2984BC` по номеру из `$FF1B14`. Из записи нам нужны два поля:
`+$00` — палитра (128 байт, все четыре ряда CRAM) и `+$08` — запись
графики, которую разбирает загрузчик `$291012`:

```
+$00 слово  флаг: карта (+$04) упакована
+$02 слово  флаг: таблица метатайлов (+$08) упакована
+$04 long   карта: слово ширины, слово высоты, дальше по слову на клетку —
            СМЕЩЕНИЕ в таблице метатайлов (всегда кратно восьми)
+$08 long   таблица метатайлов -> $FFFFE11C: по 8 байт, четыре имени VDP
            в порядке «слева сверху, справа сверху, слева снизу, справа снизу»
+$0C long   тайлы уровня, упакованы всегда -> VRAM
+$10 long   свойства клеток -> $FFFFE140: по четыре байта на метатайл,
            слово-профиль земли, код местности, номер порождаемого объекта
+$14 long   карта имён фона: ширина, высота, дальше имена -> VRAM $E000
+$18 слово  флаг: блок (+$1A) упакован
+$1A long   -> $FFFFE120
```

Почти всё это **сжато** — см. [tools/lzss.py](lzss.py).

Что метатайлы лежат именно в `+$08`, видно в отрисовщике столбца
`$29135E`: он берёт слово карты в `d2` и пишет в VDP `($0,a2,d2.l)` и
`($4,a2,d2.l)`, где `a2` — `$FFFFE11C`. Автоинкремент VDP там `$8F80`,
то есть 64 слова, ровно ряд плоскости: запись идёт СТОЛБЦОМ, и пара
`+0`/`+4` — левая половина метатайла, `+2`/`+6` — правая.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT as out_path
from paths import rom_bytes

import anim as A
import frames as F
import lzss
import sprites as S

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROM = rom_bytes()
TABLE, COUNT, REC = 0x1FCB50, 23, 0x42
OBJLISTS, PROCS = 0x1FCBAC, 0x1FCC08
U16 = lambda o: struct.unpack_from(">H", ROM, o)[0]
U32 = lambda o: struct.unpack_from(">I", ROM, o)[0]


def record(n):
    return U32(TABLE + n * 4)


def gfx(n):
    """Запись графики уровня -> словарь распакованных кусков."""
    g = U32(record(n) + 8)
    out = {"at": g, "map": U32(g + 4), "meta": U32(g + 8),
           "tiles": U32(g + 0xC), "blk10": U32(g + 0x10), "bg": U32(g + 0x14)}
    out["tiles_data"] = lzss.unpack(out["tiles"])[0]
    out["bg_data"] = lzss.unpack(out["bg"])[0]
    out["blk10_data"] = lzss.unpack(out["blk10"])[0]
    # Два флага в +$0: старшее слово — сжата ли карта, младшее — сжата ли
    # таблица метатайлов. Несжатое лежит в ROM как есть.
    if U16(g):
        out["map_data"] = lzss.unpack(out["map"])[0]
    else:
        w, h = struct.unpack_from(">HH", ROM, out["map"])
        out["map_data"] = ROM[out["map"]:out["map"] + 4 + w * h * 2]
    # Несжатую таблицу метатайлов обрезаем по самому дальнему смещению,
    # которое встретилось в карте: длины она нигде не хранит.
    if U16(g + 2):
        out["meta_data"] = lzss.unpack(out["meta"])[0]
    else:
        d = out["map_data"]
        far = max(struct.unpack_from(">H", d, 4 + i * 2)[0]
                  for i in range((len(d) - 4) // 2))
        out["meta_data"] = ROM[out["meta"]:out["meta"] + far + 8]
    return out


def pal(n):
    return S.cram(U32(record(n)))


def blit(dst, w, h, tiles, name, ox, oy, pals):
    """Одно имя VDP: тайл 8x8 с отражениями и рядом палитры."""
    t = name & 0x7FF
    if (t + 1) * 32 > len(tiles):
        return
    row = pals[(name >> 13) & 3]
    hf, vf = name & 0x800, name & 0x1000
    for y in range(8):
        py = oy + (7 - y if vf else y)
        if not (0 <= py < h):
            continue
        for xb in range(4):
            b = tiles[t * 32 + y * 4 + xb]
            for half, c in ((0, b >> 4), (1, b & 15)):
                x = xb * 2 + half
                px = ox + (7 - x if hf else x)
                if 0 <= px < w:
                    dst[py * w + px] = row[c] + (255,)


def out_dir():
    d = out_path("gfx")
    os.makedirs(d, exist_ok=True)
    return d


def save(name, w, h, buf, scale=1):
    p = os.path.join(out_dir(), name)
    S.png(p, w, h, buf, scale)
    print("  %dx%d -> %s" % (w * scale, h * scale, p))


def do_tiles(n, cols=32):
    g, p = gfx(n), pal(n)
    t = g["tiles_data"]
    cnt = len(t) // 32
    rows = (cnt + cols - 1) // cols
    w, h = cols * 8, rows * 8
    buf = [None] * (w * h)
    for i in range(cnt):
        blit(buf, w, h, t, i, (i % cols) * 8, (i // cols) * 8, p)
    print("уровень %d: тайлов %d" % (n, cnt))
    save("level%02d_tiles.png" % n, w, h, buf)


def metatiles(g):
    """-> список из четырёх имён на метатайл 2x2."""
    m = g["meta_data"]
    return [struct.unpack_from(">4H", m, i * 8) for i in range(len(m) // 8)]


def do_meta(n, cols=24):
    g, p = gfx(n), pal(n)
    mt, t = metatiles(g), g["tiles_data"]
    rows = (len(mt) + cols - 1) // cols
    w, h = cols * 16, rows * 16
    buf = [None] * (w * h)
    for i, q in enumerate(mt):
        ox, oy = (i % cols) * 16, (i // cols) * 16
        for k, name in enumerate(q):
            blit(buf, w, h, t, name, ox + (k % 2) * 8, oy + (k // 2) * 8, p)
    print("уровень %d: метатайлов %d" % (n, len(mt)))
    save("level%02d_meta.png" % n, w, h, buf)


def do_map(n, scale=1):
    g, p = gfx(n), pal(n)
    d = g["map_data"]
    mw, mh = struct.unpack_from(">HH", d, 0)
    mt, t = metatiles(g), g["tiles_data"]
    w, h = mw * 16, mh * 16
    buf = [None] * (w * h)
    bad = 0
    for cy in range(mh):
        for cx in range(mw):
            off = struct.unpack_from(">H", d, 4 + (cy * mw + cx) * 2)[0]
            if off % 8 or off // 8 >= len(mt):
                bad += 1
                continue
            for k, name in enumerate(mt[off // 8]):
                blit(buf, w, h, t, name, cx * 16 + (k % 2) * 8,
                     cy * 16 + (k // 2) * 8, p)
    print("уровень %d: карта %dx%d клеток (%dx%d точек), негодных клеток %d"
          % (n, mw, mh, w, h, bad))
    save("level%02d_map.png" % n, w, h, buf, scale)


TERRAIN = 0x1FCF14   # свойства кода местности: бит 0 — не пройти
GLYPHS = 0x1D6D80    # скрипты анимации букв: индекс буквы * 2
S16 = lambda o: struct.unpack_from(">h", ROM, o)[0]


def title(n):
    """Заставка уровня: по шесть байт на букву, конец — отрицательное слово.

    Разбор из `$28EE02`: он зовёт процедуру уровня из `$1FCC08`, потом идёт
    по списку из `$1FCBAC` и на каждую запись заводит объект — скрипт
    анимации берётся как `$1D6D80 + индекс * 2`, положение кладётся в
    `$12`, а исходное — в `$4C`, причём по вертикали объект стартует на
    `$100` выше, то есть буквы слетают сверху.
    """
    a = U32(OBJLISTS + n * 4)
    out = []
    while S16(a) >= 0:
        out.append((S16(a), S16(a + 2), S16(a + 4)))
        a += 6
    return out


def title_text(n):
    """Буквы -> строка. Индексы 0-25 это A-Z, 26 — слово THE."""
    out, prev = "", None
    for i, x, y in title(n):
        if prev and (y != prev[1] or x - prev[0] > 18):
            out += " "
        out += ("THE" if i == 26 else
                chr(65 + i) if 0 <= i < 26 else "?%d" % i)
        prev = (x, y)
    return out


PASSWORDS = 0x1FCB26   # семь записей: слово уровня и указатель на строку
CHEAT = (0x1EAA27, 0x1EAA2E)   # два пароля-шифра, хранятся со сдвигом +1


def do_passwords():
    """Пароли уровней и двухступенчатый чит, открывающий меню DEBUG.

    Разбор из `$290A3E` и `$290AAE`. Пароль всегда шесть букв A-Z, буфер
    ввода — `$FF0016`. Для паролей уровней сравнение прямое, для чита
    строки лежат **со сдвигом на единицу**: код сравнивает введённое плюс
    один. Совпавший пароль уровня кладёт `слово + 1` в `$FF1B14` и играет
    звук `$31`; чит ставит `$FF2180`, а `$2908FA` по этому байту берёт не
    обычный описатель меню `$1FD440`, а `$1FD46E` — тот, где есть DEBUG.
    """
    print("пароли уровней, таблица $%06X (семь записей по шесть байт):" % PASSWORDS)
    print()
    print("  пароль   уровень  название")
    for i in range(7):
        a = PASSWORDS + i * 6
        lv = U16(a) + 1
        txt = ROM[U32(a + 2):U32(a + 2) + 6].decode("ascii", "replace")
        print("  %-8s %2d       %s" % (txt, lv, title_text(lv)))
    print()
    print("чит: ввести по очереди два пароля, каждый шесть букв.")
    for a in CHEAT:
        print("  $%06X: хранится %s, вводить %s"
              % (a, ROM[a:a + 6].decode("ascii", "replace"),
                 "".join(chr(b - 1) for b in ROM[a:a + 6])))
    print("после второго ставится $FF2180, и в главном меню появляется DEBUG")


def do_names():
    print("названия уровней: список букв в `$1FCBAC`, глиф — кадр спрайта,")
    print("скрипт анимации — `$1D6D80 + индекс * 2` (буквы шевелятся)")
    print()
    for n in range(COUNT):
        print(" %2d  $%06X  %2d букв  %s"
              % (n, U32(OBJLISTS + n * 4), len(title(n)), title_text(n)))


def scene(n):
    """Актёры заставки уровня: список из процедуры `$1FCC08`.

    Процедура каждого мира одинакова: `lea <скрипт>,a1; bsr $28E654` и
    `lea <актёры>,a2; bsr $28E73A`. Второй список и есть расстановка:
    слово-счётчик, дальше по двенадцать байт — x, y, скрипт анимации,
    обработчик. Координаты экранные, и почти все актёры начинают за краем
    (x = -16 или 336), то есть входят в кадр.
    """
    at = U32(PROCS + n * 4)
    leas = []
    for a in range(at, at + 0x40, 2):
        if U16(a) in (0x43F9, 0x45F9):      # lea xxx.l,a1 / lea xxx.l,a2
            leas.append((U16(a), U32(a + 2)))
        if U16(a) == 0x4E75:
            break
    lst = [v for w, v in leas if w == 0x45F9]
    if not lst:
        return []
    a = lst[0]
    cnt = U16(a)
    return [(S16(a + 2 + k * 12), S16(a + 4 + k * 12),
             U32(a + 6 + k * 12), U32(a + 10 + k * 12)) for k in range(cnt)]


def do_scene(n, scale=2):
    """Заставка целиком: буквы названия и актёры на своих местах."""
    import sprites as SP
    SP.PALS = pal(n)
    placed = []
    for i, x, y in title(n):
        for q in F.parse(F.U32(F.BASE + i * 4)):
            placed.append((q[0], q[1], q[2] + x, q[3] + y, q[4]))
    act = scene(n)
    for x, y, sc, _h in act:
        fr = A.first_frame(sc)
        if fr is None:
            continue
        for q in F.parse(F.U32(F.BASE + fr * 4)) or []:
            placed.append((q[0], q[1], q[2] + x, q[3] + y, q[4]))
    if not placed:
        print("уровень %d: рисовать нечего" % n)
        return
    x0, y0, x1, y1 = SP.bounds(placed)
    w, h = x1 - x0, y1 - y0
    buf = [None] * (w * h)
    for q in placed:
        SP.draw(buf, w, h, -x0, -y0, q)
    print("уровень %d: «%s», актёров %d" % (n, title_text(n), len(act)))
    save("level%02d_scene.png" % n, w, h, buf, scale)


# Списки актёров СЦЕНОК, которые не привязаны к заставке уровня. Формат тот
# же, что у `scene()`: слово-счётчик, дальше по 12 байт — x, y, скрипт
# анимации, обработчик. Найдены перебором неразобранных адресов: у всех
# одиннадцати скрипт попадает в область скриптов, обработчик — в банк кода,
# а координаты держатся в пределах экрана. Скрипты сценок лежат ВЫШЕ
# скриптов порождения объектов: `$1DCE74`-`$1DD7C2` против `$1D6E38`-`$1DB670`.
SCENES = (0x1E9272, 0x1E9298, 0x1EA57C, 0x1EA5A2, 0x1EA5BC, 0x1EA5D8,
          0x1EA992, 0x1EA9AC, 0x1EA9C6, 0x1EA9E0, 0x1EA9FA)


def actors_at(a):
    """Список актёров по адресу: счётчик и записи по 12 байт."""
    n = U16(a)
    return [(S16(a + 2 + k * 12), S16(a + 4 + k * 12),
             U32(a + 6 + k * 12), U32(a + 10 + k * 12)) for k in range(n)]


def do_actors(at=None, scale=2):
    """Актёры сценки в PNG. Без аргумента — все одиннадцать списков."""
    import sprites as SP
    SP.PALS = pal(0)
    for a in ([at] if at else SCENES):
        placed = []
        act = actors_at(a)
        for x, y, sc, _h in act:
            fr = A.first_frame(sc)
            if fr is None:
                continue
            for q in F.parse(F.U32(F.BASE + fr * 4)) or []:
                placed.append((q[0], q[1], q[2] + x, q[3] + y, q[4]))
        if not placed:
            print("$%06X: %d актёров, рисовать нечего" % (a, len(act)))
            continue
        x0, y0, x1, y1 = SP.bounds(placed)
        w, h = x1 - x0, y1 - y0
        buf = [None] * (w * h)
        for q in placed:
            SP.draw(buf, w, h, -x0, -y0, q)
        print("$%06X: актёров %d, нарисовано %d"
              % (a, len(act), sum(1 for x, y, sc, _h in act
                                  if A.first_frame(sc) is not None)))
        save("actors_%06X.png" % a, w, h, buf, scale)


def do_title(n, scale=2):
    """Заставка как она есть: буквы кадрами спрайтов на своих местах."""
    import sprites as SP
    SP.PALS = pal(n)
    letters = title(n)
    placed = []
    for i, x, y in letters:
        for d, name, px, py, src in F.parse(F.U32(F.BASE + i * 4)):
            placed.append((d, name, px + x, py + y, src))
    x0, y0, x1, y1 = SP.bounds(placed)
    w, h = x1 - x0, y1 - y0
    buf = [None] * (w * h)
    for q in placed:
        SP.draw(buf, w, h, -x0, -y0, q)
    print("уровень %d: «%s», %d букв" % (n, title_text(n), len(letters)))
    save("level%02d_title.png" % n, w, h, buf, scale)


def props(g):
    """Блок +$10: по четыре байта на метатайл.

    Разбор вычитан из трёх читателей:

    * `$291A7C` — слово `+0` плюс `x & 15` даёт байт в таблице профилей
      (поле `+$4` записи уровня, `$FF1B1E`), по 16 байт на профиль: это
      высота земли в каждом из шестнадцати столбцов клетки, считая от её
      верха. Ноль — земли в этом столбце нет;
    * `$2A5180` — байт `+2` это код местности, а `$1FCF14` по нему даёт
      свойства, бит 0 — «не пройти» (`$2A51BC`);
    * `$2914D0` — байт `+3` это номер объекта, который надо породить, когда
      клетка въезжает на экран; номер ищется в таблице `$FF1B32` (поле
      `+$20` записи уровня). Объект помнит клетку в `$2A` и при гибели
      возвращает номер на место (`$2918BA`).
    """
    b = g["blk10_data"]
    return [(struct.unpack_from(">H", b, i * 4)[0], b[i * 4 + 2], b[i * 4 + 3])
            for i in range(len(b) // 4)]


def do_solid(n, scale=1):
    """Карта, поверх неё профиль земли и клетки, через которые не пройти."""
    g, p = gfx(n), pal(n)
    d, pr = g["map_data"], props(g)
    prof = U32(record(n) + 4)
    mw, mh = struct.unpack_from(">HH", d, 0)
    mt, t = metatiles(g), g["tiles_data"]
    w, h = mw * 16, mh * 16
    buf = [None] * (w * h)
    solid = ground = 0
    for cy in range(mh):
        for cx in range(mw):
            off = struct.unpack_from(">H", d, 4 + (cy * mw + cx) * 2)[0]
            for k, name in enumerate(mt[off // 8]):
                blit(buf, w, h, t, name, cx * 16 + (k % 2) * 8,
                     cy * 16 + (k // 2) * 8, p)
            # В коде индекс — `off >> 1` БАЙТОВОГО смещения, а записи по
            # четыре байта: метатайлу k (off = k*8) отвечает pr[k].
            slope, code, _spawn = pr[off // 8]
            block = ROM[TERRAIN + code] & 1
            solid += bool(block)
            for i in range(16):
                px, py = cx * 16 + i, cy * 16
                if block:
                    for y in range(16):
                        q = buf[(py + y) * w + px] or (0, 0, 0, 255)
                        buf[(py + y) * w + px] = (q[0] // 2, q[1] // 2,
                                                  min(255, q[2] // 2 + 90), 255)
                if not slope:
                    continue
                v = ROM[prof + slope + i]
                if not v:
                    continue
                ground += 1
                yy = py + min(v, 15)
                for k in range(2):     # линия в две точки, иначе не видно
                    if yy + k < h:
                        buf[(yy + k) * w + px] = (255, 40, 40, 255)
    print("уровень %d: клеток «не пройти» %d, точек профиля %d, профиль $%06X"
          % (n, solid, ground, prof))
    save("level%02d_solid.png" % n, w, h, buf, scale)


def do_objects(n, scale=1):
    """Карта, а поверх — спрайты объектов, которые порождают клетки."""
    import sprites as SP
    SP.PALS = pal(n)
    g, p = gfx(n), pal(n)
    d, pr = g["map_data"], props(g)
    jump = U32(record(n) + 0x20)
    mw, mh = struct.unpack_from(">HH", d, 0)
    mt, t = metatiles(g), g["tiles_data"]
    w, h = mw * 16, mh * 16
    buf = [None] * (w * h)
    for cy in range(mh):
        for cx in range(mw):
            off = struct.unpack_from(">H", d, 4 + (cy * mw + cx) * 2)[0]
            for k, name in enumerate(mt[off // 8]):
                blit(buf, w, h, t, name, cx * 16 + (k % 2) * 8,
                     cy * 16 + (k // 2) * 8, p)
    # приглушаем фон, чтобы объекты читались
    for i, q in enumerate(buf):
        if q:
            buf[i] = (q[0] // 3, q[1] // 3, q[2] // 3, 255)
    cache, drawn, blank = {}, 0, 0
    for cy in range(mh):
        for cx in range(mw):
            off = struct.unpack_from(">H", d, 4 + (cy * mw + cx) * 2)[0]
            code = pr[off // 8][2]
            if not code:
                continue
            if code not in cache:
                sc = A.script_of_any(U32(jump + code * 4))
                cache[code] = A.first_frame(sc) if sc else None
            fr = cache[code]
            if fr is None:
                blank += 1
                continue
            drawn += 1
            for q in F.parse(F.U32(F.BASE + fr * 4)) or []:
                SP.draw(buf, w, h, cx * 16 + 8, cy * 16 + 8, q)
    print("уровень %d: объектов %d, из них нарисовано %d, без кадра %d"
          % (n, drawn + blank, drawn, blank))
    save("level%02d_objects.png" % n, w, h, buf, scale)


# Глифы счётчиков HUD: запись $80 байт — четыре тайла 2x2, и ВНУТРИ ЗАПИСИ
# ТАЙЛЫ ИДУТ ПО СТОЛБЦАМ. Размер доказан `$298E6A`: `moveq #31,d7` и
# `move.l (a2)+,(a3)+` — ровно 128 байт в буфер ОЗУ. Индекс — `$29933A`:
# значение зажимается в 0..9 и умножается на 128 (`lsl.w #7,d0`).
# Палитра не установлена, поэтому рисуем серым, как `tileprobe`.
HUD_STEP = 0x80
HUD = (
    (0x1ECC9E, 10, "цифры счётчика, берёт $299344"),
    (0x1EE99E, 12, "второй набор: цифры парами и значки, берёт $299312"),
)
HUD_GREY = [[(v, v, v) for v in (0, 17, 34, 51, 68, 85, 102, 119,
                                 136, 153, 170, 187, 204, 221, 238, 255)]] * 4


def do_hud(base=None, count=None, scale=4):
    """Таблица глифов HUD в PNG: запись — четыре тайла 2x2 по столбцам.

    Без аргументов проходит по обеим известным таблицам. Число записей у
    `$1EE99E` взято по виду, а не из кода: сколько их на самом деле, не
    установлено — потому и вынесено в аргумент.
    """
    todo = ([(base, count or 10, "по аргументу")] if base is not None
            else list(HUD))
    for at, n, what in todo:
        blob = ROM[at:at + n * HUD_STEP]
        if len(blob) < n * HUD_STEP:
            print("$%06X: за концом ROM" % at)
            continue
        w, h = n * 16, 16
        buf = [None] * (w * h)
        for i in range(n):
            for t in range(4):
                tx, ty = t // 2, t % 2        # по столбцам, не построчно
                blit(buf, w, h, blob, i * 4 + t,
                     i * 16 + tx * 8, ty * 8, HUD_GREY)
        print("$%06X: записей %d по $%02X байт — %s" % (at, n, HUD_STEP, what))
        save("hud_%06X.png" % at, w, h, buf, scale)


# Статические экраны: титульный и титры. Грузит их `loc_28D74A` четвёркой
# ресурсов, все LZSS-сжатые. У распакованной КАРТЫ заголовок — два слова,
# ширина и высота в клетках, дальше `w*h` слов имени VDP; у ТАЙЛОВ
# заголовка нет. Размер сходится точно: 64x32 -> 4096, 64x56 -> 7168,
# 40x404 -> 32320 байт, а `lsr.w #5,d4` в коде даёт те же 518 тайлов.
# Задник общий у обоих экранов: `a1` и `a3` в двух вызовах совпадают.
#
# Палитры взяты из кода: после загрузки экрана идёт `PaletteFadeTo` с
# `$1F0612` (титульный) и `$1F5BF8` (титры). Для задника это проверяется —
# ряд 0 там синяя лесенка индексов 7…14, и тайлы используют ровно её.
# ЧЕГО НЕ УСТАНОВЛЕНО: как слои складываются на экране. Рисуем каждый
# отдельно и на непрозрачном фоне, а в игре логотип ложится поверх задника
# с прозрачным цветом 0 и, судя по низкому контрасту, не рядом 0 палитры.
# Пары «карта — набор» подобраны по вместимости: у семи из девяти размер
# набора РОВНО равен наибольшему номеру тайла в карте плюс один, у титров
# запас в один тайл. Палитры взяты из ближайшего `PaletteFadeTo` после
# площадки карты.
SCREENS = (
    (0x1F0D58, 0x1F0692, 0x1F0F30, "заставка «presents DONALD Starring In»"),
    (0x1F8A8E, 0x1F927A, 0x1F0612, "задник титульного: лучи, лозы, изгородь"),
    (0x1F0194, 0x1EFBFE, 0x1F0612, "логотип MAUI MALLARD"),
    (0x1F813A, 0x1F927A, 0x1F6ED8, "тот же задник для меню, без изгороди"),
    (0x1F2CEC, 0x1F0FB0, 0x1F3A4A, "пальмы и звёздное небо"),
    (0x1F3270, 0x1F0FB0, 0x1F3A4A, "ночное небо со звёздами, берег и вода"),
    (0x1F6548, 0x1F6B10, None, "силуэт острова: пальмы и хижины"),
    (0x1F6850, 0x1F6B10, None, "силуэт острова, второй вариант"),
    (0x1F3B4A, 0x1F58B8, 0x1F5BF8, "свиток титров"),
)


def do_screen(map_at=None, tiles_at=None, pal_at=None, scale=1):
    """Статический экран: карта имён поверх своего набора тайлов.

    Без аргументов проходит по всем девяти известным слоям. У карт шириной
    64 клетки видно на экране 40 — правый край в данных пустой. Слои с
    палитрой `None` рисуются серым: это силуэты, нарисованные одним цветом,
    и с настоящей палитрой они выходят почти чёрными.
    """
    todo = ([(map_at, tiles_at, pal_at, "по аргументу")] if map_at is not None
            else list(SCREENS))
    for m_at, t_at, p_at, what in todo:
        m = lzss.unpack(m_at)[0]
        t = lzss.unpack(t_at)[0]
        pals = S.cram(p_at) if p_at else [[(v, v, v) for v in range(0, 256, 17)]] * 4
        w, h = struct.unpack_from(">HH", m, 0)
        buf = [None] * (w * 8 * h * 8)
        used = set()
        for ty in range(h):
            for tx in range(w):
                o = 4 + (ty * w + tx) * 2
                if o + 2 > len(m):
                    continue
                nm = struct.unpack_from(">H", m, o)[0]
                used.add(nm & 0x7FF)
                blit(buf, w * 8, h * 8, t, nm, tx * 8, ty * 8, pals)
        print("$%06X %dx%d клеток + тайлы $%06X (%d), в ходу номеров %d — %s"
              % (m_at, w, h, t_at, len(t) // 32, len(used), what))
        save("screen_%06X.png" % m_at, w * 8, h * 8, buf, scale)


def do_bg(n, scale=1):
    g, p = gfx(n), pal(n)
    d = g["bg_data"]
    bw, bh = struct.unpack_from(">HH", d, 0)
    t = g["tiles_data"]
    w, h = bw * 8, bh * 8
    buf = [None] * (w * h)
    for y in range(bh):
        for x in range(bw):
            name = struct.unpack_from(">H", d, 4 + (y * bw + x) * 2)[0]
            blit(buf, w, h, t, name, x * 8, y * 8, p)
    print("уровень %d: фон %dx%d имён" % (n, bw, bh))
    save("level%02d_bg.png" % n, w, h, buf, scale)


def summary():
    print("уровней %d, запись $%02X байт, таблицы $%06X / $%06X / $%06X\n"
          % (COUNT, REC, TABLE, OBJLISTS, PROCS))
    print(" №  запись   палитра  карта клеток   тайлов  метатайлов  фон"
          "    сжато -> распаковано")
    tot_in = tot_out = 0
    for n in range(COUNT):
        try:
            g = gfx(n)
        except Exception as e:
            print(" %2d  $%06X  не разбирается: %s" % (n, record(n), e))
            continue
        mw, mh = struct.unpack_from(">HH", g["map_data"], 0)
        bw, bh = struct.unpack_from(">HH", g["bg_data"], 0)
        raw = sum(lzss.unpack(g[k])[1] for k in ("tiles", "blk10", "bg"))
        big = sum(len(g[k + "_data"]) for k in ("tiles", "blk10", "bg"))
        tot_in += raw
        tot_out += big
        print(" %2d  $%06X  $%06X  %4dx%-4d    %5d   %9d  %2dx%-2d  "
              "%7d -> %7d" % (n, record(n), U32(record(n)), mw, mh,
                              len(g["tiles_data"]) // 32,
                              len(g["meta_data"]) // 8, bw, bh, raw, big))
    print("\nвсего %d байт сжатого дают %d (x%.2f)"
          % (tot_in, tot_out, float(tot_out) / tot_in))


def main():
    argv = sys.argv[1:]
    mode, scale, args = None, 1, []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--scale":
            i += 1
            scale = int(argv[i])
        elif a.startswith("--"):
            mode = a
        else:
            try:
                args.append(int(a, 0))
            except ValueError:
                args.append(int(a, 16))   # голый шестнадцатеричный: 1ECC9E
        i += 1
    if mode is None:
        summary()
        return 0
    fn = {"--tiles": do_tiles, "--meta": do_meta}.get(mode)
    if fn:
        for n in args or [0]:
            fn(n)
        return 0
    if mode == "--map":
        for n in args or [0]:
            do_map(n, scale)
        return 0
    if mode == "--bg":
        for n in args or [0]:
            do_bg(n, scale)
        return 0
    if mode == "--solid":
        for n in args or [0]:
            do_solid(n, scale)
        return 0
    if mode == "--objects":
        for n in args or [0]:
            do_objects(n, scale)
        return 0
    if mode == "--passwords":
        do_passwords()
        return 0
    if mode == "--scene":
        for n in args or [0]:
            do_scene(n, scale)
        return 0
    if mode == "--actors":
        do_actors(args[0] if args else None, scale)
        return 0
    if mode == "--screen":
        do_screen(args[0] if args else None,
                  args[1] if len(args) > 1 else None,
                  args[2] if len(args) > 2 else None, scale)
        return 0
    if mode == "--hud":
        # глифы 16x16, поэтому без явного --scale рисуем крупнее
        do_hud(args[0] if args else None,
               args[1] if len(args) > 1 else None,
               scale if scale != 1 else 4)
        return 0
    if mode == "--names":
        do_names()
        return 0
    if mode == "--title":
        for n in args or [0]:
            do_title(n, scale)
        return 0
    print("неизвестный ключ %s" % mode)
    return 2


if __name__ == "__main__":
    sys.exit(main())
