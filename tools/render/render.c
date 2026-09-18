/*
 * Гоняет звуковой драйвер Dyna Brothers 2 на эмуляторе и пишет WAV.
 *
 *   render <rom> <z80.img> <out.wav> <команда> <кадров> <банк-гл> <банк-муз> <стоп>
 *
 * Здесь нет ни одной догадки о том, что играет: код Z80 исполняется как
 * есть, а звук берётся из того, что он сам пишет в YM2612 и PSG. Из
 * готового взяты два ядра (лежат в third_party, в репозиторий не входят):
 *
 *   clownz80     — интерпретатор Z80, из него же сделан дизассемблер
 *                  sega2asm; считает такты каждой команды;
 *   Nuked-OPN2   — потактовая модель YM2612, снятая с кристалла.
 *
 * SN76489 написан здесь: он прост и точен без вариантов.
 *
 * Тактирование сведено к мастер-клоку Mega Drive NTSC 53 693 175 Гц:
 * Z80 = мастер/15, вход YM = мастер/7, шаг Nuked = мастер/42, внутренний
 * тик PSG = мастер/240. Отсчёт на выходе — мастер/1008 = 53 267 Гц, это
 * родная частота микросхемы, и пересэмплирования тут не делается вовсе.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../../third_party/clownz80/source/interpreter.h"
#include "../../third_party/Nuked-OPN2/ym3438.h"

#define MASTER      53693175
#define PER_Z80     15
#define PER_OPN2    42
#define PER_PSG     240
#define PER_SAMPLE  1008
#define Z80_HZ      (MASTER / PER_Z80)
/* Кадр NTSC — не ровно шестидесятая: 3420 мастер-тактов на строку и 262
 * строки дают 59,9227 Гц, то есть 59 736 тактов Z80. Темп музыки привязан
 * к кадровому прерыванию, поэтому округление до 60 Гц уводило бы её на
 * 0,13 процента вперёд. */
#define FRAME_CYC   (3420 * 262 / PER_Z80)

/* ─── SN76489 ──────────────────────────────────────────────────────────
 * Три тональных канала и шум. Счётчик тикает раз в 16 тактов чипа, на
 * нуле перезаряжается и переворачивает выход. Шум — 16-битный регистр
 * сдвига с отводами 0 и 3 (так он устроен в VDP Mega Drive).
 */
typedef struct {
	unsigned reg[8];        /* period/attenuation, 4 канала по два */
	int counter[4];
	int output[4];
	unsigned latch;         /* номер последнего выбранного регистра */
	unsigned lfsr;
} Psg;

/* Шаг аттенюатора 2 дБ, уровень 15 — тишина.
 *
 * Абсолютный уровень взят не с потолка, а из Gens (psg.c и ym2612.cpp):
 * там канал PSG на полной громкости даёт размах MAX_OUTPUT/3 = 6826 при
 * однополярном выходе, то есть амплитуду 3413, а канал FM — 1 <<
 * OUT_BITS = 16384. Отношение 0,208. Полная громкость канала FM здесь
 * равна 768 (в режиме YM2612 значение канала выходит раз за 24 шага и
 * умножается на три, размах ЦАП девять бит), значит канал PSG — 160.
 *
 * Прежде тут стояло 768: я приравнял канал PSG к каналу FM, и PSG был
 * громче FM на 3–7 дБ во всех песнях. */
static const int PSG_VOL[16] = {
	 160,  127,  101,   80,   64,   51,   40,   32,
	  25,   20,   16,   13,   10,    8,    6,    0
};

static void psg_reset(Psg *p)
{
	int i;
	memset(p, 0, sizeof(*p));
	for (i = 0; i < 4; i++) {
		p->reg[i * 2 + 1] = 0x0F;   /* тишина */
		p->output[i] = 1;
	}
	p->lfsr = 0x8000;
}

static void psg_write(Psg *p, unsigned v)
{
	if (v & 0x80) {
		p->latch = (v >> 4) & 7;
		p->reg[p->latch] = (p->reg[p->latch] & 0x3F0) | (v & 0x0F);
	} else {
		if (p->latch & 1)               /* громкость — всегда 4 бита */
			p->reg[p->latch] = v & 0x0F;
		else
			p->reg[p->latch] = (p->reg[p->latch] & 0x0F) | ((v & 0x3F) << 4);
	}
	if (p->latch == 6)
		p->lfsr = 0x8000;               /* смена режима перезаряжает регистр */
}

static void psg_tick(Psg *p)
{
	int i;
	for (i = 0; i < 3; i++) {
		if (--p->counter[i] <= 0) {
			p->counter[i] = p->reg[i * 2] ? p->reg[i * 2] : 1;
			p->output[i] = -p->output[i];
		}
	}
	if (--p->counter[3] <= 0) {
		/* Регистр сдвига тикает на clock/512, /1024, /2048 — при тике
		 * счётчика clock/16 это перезарядка на 32, 64, 128. Режим 3
		 * берёт ТОНОВУЮ частоту канала 2, clock/(32*период), то есть
		 * удвоенный период его счётчика. Раньше здесь стояли 16, 32,
		 * 64 и период канала 2 как есть — шум выходил на октаву выше
		 * настоящего. Сверено с psg.c из Gens. */
		static const int rate[4] = { 0x20, 0x40, 0x80, 0 };
		int r = p->reg[6] & 3;
		p->counter[3] = rate[r] ? rate[r]
		                        : (p->reg[4] ? p->reg[4] * 2 : 2);
		{
			unsigned bit = (p->reg[6] & 4)
				? ((p->lfsr ^ (p->lfsr >> 3)) & 1)   /* белый */
				: (p->lfsr & 1);                     /* периодический */
			p->lfsr = (p->lfsr >> 1) | (bit << 15);
			p->output[3] = (p->lfsr & 1) ? 1 : -1;
		}
	}
}

static int psg_out(const Psg *p)
{
	int i, s = 0;
	for (i = 0; i < 4; i++)
		s += p->output[i] * PSG_VOL[p->reg[i * 2 + 1] & 0x0F];
	return s;
}

/* ─── шина Z80 ─────────────────────────────────────────────────────── */
typedef struct {
	unsigned char ram[0x2000];
	const unsigned char *rom;
	long rom_size;
	unsigned bank;          /* сдвиговый регистр $6000, девять бит */
	ym3438_t *ym;
	Psg *psg;
	/* Учёт записей в регистр $2A: это и есть отсчёты DAC. По ним
	 * меряется настоящая частота воспроизведения — расчётная её
	 * завышает, потому что кадровое прерывание ворует такты. */
	unsigned last_addr, last_addr1;   /* у каждого порта YM свой */
	int solo;    /* -1 всё, 0..5 канал FM, 6 только PSG */
	long dac_writes;
	long dac_first, dac_last;
	const long *now;
} Bus;

static cc_u16f bus_read(void *ud, cc_u16f a)
{
	Bus *b = (Bus *)ud;
	a &= 0xFFFF;
	if (a < 0x4000)
		return b->ram[a & 0x1FFF];
	if (a < 0x6000)
		return OPN2_Read(b->ym, a & 3);
	if (a < 0x8000)
		return 0xFF;                    /* $6000 и порты VDP на чтение */
	{
		long o = (long)(b->bank << 15) + (a & 0x7FFF);
		return o < b->rom_size ? b->rom[o] : 0xFF;
	}
}

static void bus_write(void *ud, cc_u16f a, cc_u16f v)
{
	Bus *b = (Bus *)ud;
	a &= 0xFFFF;
	v &= 0xFF;
	if (a < 0x4000) {
		b->ram[a & 0x1FFF] = (unsigned char)v;
	} else if (a < 0x6000) {
		if ((a & 3) == 2)
			b->last_addr1 = v;
		if (b->solo >= 0 && (a & 3) & 1) {
			/* Регистры $30–$B6 принадлежат каналу (reg & 3) своего
			 * порта; $28 называет канал в данных; всё ниже $30 —
			 * общее и пропускается всегда. */
			unsigned r = (a & 2) ? b->last_addr1 : b->last_addr;
			int port = (a & 2) ? 1 : 0;
			if (r == 0x28) {
				int c = v & 7;
				if ((c & 4 ? 3 + (c & 3) : (c & 3)) != b->solo)
					return;
			} else if (r >= 0x30 && r <= 0xB6) {
				if ((int)(r & 3) + 3 * port != b->solo)
					return;
			}
		}
		if ((a & 3) == 0) {
			b->last_addr = v;
		} else if ((a & 3) == 1 && b->last_addr == 0x2A) {
			if (!b->dac_writes)
				b->dac_first = *b->now;
			b->dac_last = *b->now;
			b->dac_writes++;
		}
		OPN2_Write(b->ym, a & 3, (Bit8u)v);
	} else if (a < 0x6100) {
		b->bank = ((b->bank >> 1) | ((v & 1) << 8)) & 0x1FF;
	} else if (a >= 0x7F00 && a < 0x8000) {
		if ((a & 0xFF) == 0x11 && (b->solo < 0 || b->solo == 6))
			psg_write(b->psg, v);
	}
}

static void bus_log(void *ud, const char *fmt, ...)
{
	(void)ud; (void)fmt;
}

/* ─── WAV ──────────────────────────────────────────────────────────── */
static void put32(FILE *f, unsigned v)
{
	fputc(v & 0xFF, f); fputc((v >> 8) & 0xFF, f);
	fputc((v >> 16) & 0xFF, f); fputc((v >> 24) & 0xFF, f);
}

static void put16(FILE *f, unsigned v)
{
	fputc(v & 0xFF, f); fputc((v >> 8) & 0xFF, f);
}

static void wav_header(FILE *f, unsigned rate, unsigned frames)
{
	unsigned data = frames * 4;
	fwrite("RIFF", 1, 4, f); put32(f, 36 + data);
	fwrite("WAVEfmt ", 1, 8, f); put32(f, 16);
	put16(f, 1); put16(f, 2); put32(f, rate);
	put32(f, rate * 4); put16(f, 4); put16(f, 16);
	fwrite("data", 1, 4, f); put32(f, data);
}

/* ─── почтовый ящик ────────────────────────────────────────────────── */
/* Трапы $FF2D и $FF35 кладут в ящик пару (x >> 4, x << 4), где
 * x = номер банка * 8 + $1C0; адрес окна получается x << 12. */
static void set_bank(unsigned char *ram, int at, int n)
{
	unsigned x = (unsigned)n * 8 + 0x1C0;
	ram[at] = (unsigned char)(x >> 4);
	ram[at + 1] = (unsigned char)((x << 4) & 0xFF);
}

/* Эффект кончился, когда ни один из семи эффектных слотов не занят
 * (бит 7 поля +0) и главный цикл не крутит сэмпл ($1C3C). */
static int sfx_done(const unsigned char *ram)
{
	int i;
	if (ram[0x1C3C])
		return 0;
	for (i = 0; i < 7; i++)
		if (ram[0x1E20 + i * 0x30] & 0x80)
			return 0;
	return 1;
}

static unsigned char *slurp(const char *path, long *len)
{
	FILE *f = fopen(path, "rb");
	unsigned char *buf;
	if (!f) { fprintf(stderr, "не открыть %s\n", path); exit(1); }
	fseek(f, 0, SEEK_END); *len = ftell(f); fseek(f, 0, SEEK_SET);
	buf = (unsigned char *)malloc((size_t)*len);
	if (fread(buf, 1, (size_t)*len, f) != (size_t)*len) { exit(1); }
	fclose(f);
	return buf;
}

int main(int argc, char **argv)
{
	Bus bus;
	ym3438_t ym;
	Psg psg;
	ClownZ80_State cpu;
	ClownZ80_ReadAndWriteCallbacks cb;
	FILE *out;
	long img_len, rom_len;
	unsigned char *img;
	int cmd, max_frames, main_bank, music_bank, stop_when_done;
	int gain = 256;
	double hp_xl = 0.0, hp_yl = 0.0, hp_xr = 0.0, hp_yr = 0.0;
	int frame, quiet = 0, after_done = 0;
	long frame_peak = 0, run_peak = 1, floor_peak = 0;
	int recording = 0;
	long long acc_opn2 = 0, acc_psg = 0;
	long samples = 0, peak = 0;
	int opn2_cycle = 0;
	long fm_l = 0, fm_r = 0, psg_sum = 0, psg_n = 0;

	if (argc < 9) {
		fprintf(stderr, "render <rom> <z80.img> <out.wav> <cmd> <frames> "
		                "<main> <music> <stop> [усиление/256] [соло]\n");
		fprintf(stderr, "  соло: 0..5 — один канал FM, 6 — только PSG\n");
		return 2;
	}
	if (argc > 9)
		gain = atoi(argv[9]);
	bus.rom = slurp(argv[1], &rom_len);
	bus.rom_size = rom_len;
	img = slurp(argv[2], &img_len);
	cmd = (int)strtol(argv[4], NULL, 16);
	max_frames = atoi(argv[5]);
	main_bank = atoi(argv[6]);
	music_bank = atoi(argv[7]);
	stop_when_done = atoi(argv[8]);

	memset(bus.ram, 0, sizeof(bus.ram));
	memcpy(bus.ram, img, img_len < 0x2000 ? (size_t)img_len : 0x2000);
	bus.bank = 0;
	bus.ym = &ym;
	bus.psg = &psg;
	bus.last_addr = 0;
	bus.dac_writes = 0;
	bus.dac_first = bus.dac_last = 0;
	bus.now = &samples;
	bus.last_addr1 = 0;
	bus.solo = argc > 10 ? atoi(argv[10]) : -1;

	OPN2_SetChipType(ym3438_mode_ym2612);
	OPN2_Reset(&ym);
	psg_reset(&psg);

	cb.read = bus_read;
	cb.write = bus_write;
	cb.log = bus_log;
	cb.user_data = &bus;

	ClownZ80_Constant_Initialise();
	ClownZ80_State_Initialise(&cpu);
	ClownZ80_Reset(&cpu);

	out = fopen(argv[3], "wb");
	if (!out) { fprintf(stderr, "не создать %s\n", argv[3]); return 1; }
	wav_header(out, MASTER / PER_SAMPLE, 0);

	for (frame = 0; frame < max_frames; frame++) {
		long long budget = 0;

		/* Кадр первый — драйвер только проснулся; на третьем 68000
		 * выставляет банки и кладёт команду, как это делает VBlank. */
		if (frame == 2) {
			if (main_bank >= 0) set_bank(bus.ram, 0x1C04, main_bank);
			if (music_bank >= 0) set_bank(bus.ram, 0x1C06, music_bank);
		}
		if (frame == 3)
			bus.ram[0x1C0A] = (unsigned char)cmd;
		if (frame >= 3)
			recording = 1;

		ClownZ80_Interrupt(&cpu, cc_true);

		while (budget < (long long)FRAME_CYC * PER_Z80) {
			unsigned cycles = ClownZ80_DoInstruction(&cpu, &cb);
			long long step = (long long)cycles * PER_Z80;
			budget += step;

			acc_psg += step;
			while (acc_psg >= PER_PSG) {
				acc_psg -= PER_PSG;
				psg_tick(&psg);
				psg_sum += psg_out(&psg);
				psg_n++;
			}
			acc_opn2 += step;
			while (acc_opn2 >= PER_OPN2) {
				Bit16s s[2];
				acc_opn2 -= PER_OPN2;
				OPN2_Clock(&ym, s);
				fm_l += s[0];
				fm_r += s[1];
				/* Полный отсчёт чипа — ровно 24 шага: за них он по
				 * очереди выдаёт все шесть каналов. Считать их
				 * отдельным накопителем времени нельзя: получалось то
				 * 23, то 25, и сумма дрожала на несколько процентов. */
				if (++opn2_cycle < 24)
					continue;
				opn2_cycle = 0;
				{
					long p, l, r;
					/* PSG усреднён по своим тикам, чтобы не ловить
					 * наложение частот; FM уже полный отсчёт. */
					p = psg_n ? psg_sum / psg_n : 0;
					l = fm_l + p;
					r = fm_r + p;
					/* У YM2612 на выходе есть постоянная составляющая;
					 * на плате её снимает разделительный конденсатор,
					 * здесь — однополюсный фильтр на 10 Гц, свой на
					 * каждый канал, иначе файл начинается щелчком. */
					hp_yl = (double)l - hp_xl + 0.99882 * hp_yl;
					hp_xl = (double)l;
					hp_yr = (double)r - hp_xr + 0.99882 * hp_yr;
					hp_xr = (double)r;
					l = (long)(hp_yl * gain / 256.0);
					r = (long)(hp_yr * gain / 256.0);
					if (l > 32767) l = 32767;
					if (l < -32768) l = -32768;
					if (r > 32767) r = 32767;
					if (r < -32768) r = -32768;
					if (l > frame_peak) frame_peak = l;
					if (-l > frame_peak) frame_peak = -l;
					if (recording) {
						put16(out, (unsigned)(l & 0xFFFF));
						put16(out, (unsigned)(r & 0xFFFF));
						if (l > peak) peak = l;
						if (-l > peak) peak = -l;
						samples++;
					}
					fm_l = fm_r = 0;
					psg_sum = 0;
					psg_n = 0;
				}
			}
		}

		if (frame_peak > run_peak)
			run_peak = frame_peak;
		/* Первые кадры идут до команды: там слышен только собственный
		 * шум покоя YM2612 («лесенка»). Его уровень и берётся за порог
		 * тишины — сравнивать с долей от пика нельзя, этот шум никуда
		 * не девается и порог никогда бы не сработал. */
		if (frame < 3 && frame_peak > floor_peak)
			floor_peak = frame_peak;
		if (stop_when_done && frame > 8 && sfx_done(bus.ram)) {
			/* Драйвер отчитался, но FM ещё может затухать. Ждём, пока
			 * сигнал не сравняется с шумом покоя — и не дольше
			 * секунды, чтобы не зависнуть на гудящем канале. */
			if (frame_peak <= floor_peak + floor_peak / 2 + 8)
				quiet++;
			else
				quiet = 0;
			if (quiet >= 3 || ++after_done > 60)
				break;
		} else {
			quiet = 0;
			after_done = 0;
		}
		frame_peak = 0;
	}

	fseek(out, 0, SEEK_SET);
	wav_header(out, MASTER / PER_SAMPLE, (unsigned)samples);
	fclose(out);
	printf("%s: кадров %d, отсчётов %ld, пик %ld\n",
	       argv[3], frame, samples, peak);
	if (bus.dac_writes > 1 && bus.dac_last > bus.dac_first)
		fprintf(stderr, "DAC: %ld отсчётов, %.0f Гц, начало %ld\n",
		        bus.dac_writes,
		        (bus.dac_writes - 1) * (double)(MASTER / PER_SAMPLE)
		            / (double)(bus.dac_last - bus.dac_first),
		        bus.dac_first);
	return 0;
}
