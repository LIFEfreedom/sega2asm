package compress

import (
	"fmt"

	"sega2asm/types"
)

func init() {
	types.RegisterAlgorithm(types.Algorithm{
		Name:        "lzcri",
		Family:      types.FamilyLZ,
		Description: "CRI byte-command LZ (Dyna Brothers 2): 4-byte header, control byte selects a literal run or a back-reference with a 1-byte offset",
		Decompress:  DecompressLZCRI,
	})
	types.RegisterSignature(types.CompressSig{
		Name: "lzcri", WordAligned: true,
		Sig: []byte{
			0x48, 0xE7, 0x7F, 0x0C, 0x28, 0x56, 0x2A, 0x6E,
			0x00, 0x04, 0x7E, 0x00, 0x1E, 0x1D, 0xE1, 0x4F,
			0x1E, 0x1D, 0x52, 0x8D, 0x7C, 0x00, 0x70, 0x00,
			0x10, 0x1D, 0x6B, 0x00, 0x00, 0x30, 0x34, 0x00,
		},
	})
}

// DecompressLZCRI decompresses data in CRI's method 1 format, used for the
// graphics of Dyna Brothers 2. It is the dominant asset format in that ROM:
// walking the game's own two-level asset index yields 1629 blocks and every
// one of them is method 1.
//
// Header (4 bytes):
//
//	+0..+1  decompressed size, big-endian
//	+2      method selector (1 here); the game dispatches on it
//
// The stream starts at +3: the routine reads the two size bytes with two
// post-increment moves and then skips exactly one more byte with addq.l #1.
//
// Stream: a control byte followed by its payload, repeated until the
// decompressed size is reached.
//
//	c < $80   literal run of c+1 bytes, copied straight from the source
//	c >= $80  back-reference: count = (c & $7F) + 1, then one offset byte,
//	          copying count bytes from (offset+1) back in the OUTPUT
//
// The original copies byte by byte through a post-increment pointer, so a
// back-reference may overlap the bytes it is still producing — offset 1 with
// a large count is a run fill. The copy below reproduces that byte at a time
// rather than slicing, which would break the overlap.
//
// The routine lives at $000D68 in the ROM and is reachable both through the
// method table at $000D5A and directly as line-F trap $FF11.
func DecompressLZCRI(src []byte) ([]byte, error) {
	if len(src) < 4 {
		return nil, fmt.Errorf("lzcri: header truncated: %d bytes", len(src))
	}
	size := int(src[0])<<8 | int(src[1])
	pos := 3

	out := make([]byte, 0, size)
	for len(out) < size {
		if pos >= len(src) {
			return nil, fmt.Errorf("lzcri: source exhausted at %d/%d bytes decompressed",
				len(out), size)
		}
		c := src[pos]
		pos++

		if c < 0x80 {
			n := int(c) + 1
			if pos+n > len(src) {
				return nil, fmt.Errorf("lzcri: literal run of %d overruns source at %d", n, pos)
			}
			out = append(out, src[pos:pos+n]...)
			pos += n
			continue
		}

		n := int(c&0x7F) + 1
		if pos >= len(src) {
			return nil, fmt.Errorf("lzcri: missing offset byte at %d", pos)
		}
		offset := int(src[pos]) + 1
		pos++
		if offset > len(out) {
			// Оригинал не чистит приёмник: все блоки распаковываются в один
			// и тот же буфер подряд, поэтому ссылка может уйти за начало
			// блока и прочитать хвост предыдущего. Из 1629 блоков индекса
			// ресурсов так делают 5. В одиночку такой блок не распаковать —
			// нужен вывод предшественника, поэтому честно сообщаем.
			return nil, fmt.Errorf("lzcri: back-reference %d reaches past the %d bytes "+
				"decompressed so far; this block continues the previous one in the "+
				"shared buffer and cannot be decompressed on its own",
				offset, len(out))
		}
		from := len(out) - offset
		for i := 0; i < n; i++ {
			out = append(out, out[from+i])
		}
	}

	// Тело оригинала проверяет `cmp.w d7,d6 / bcc`, то есть последняя команда
	// может выйти за объявленный размер. Обрезаем, чтобы длина совпадала с
	// заголовком.
	if len(out) > size {
		out = out[:size]
	}
	return out, nil
}
