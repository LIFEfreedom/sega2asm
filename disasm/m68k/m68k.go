// Package m68k implements a Motorola 68000 disassembler.
// Output is compatible with Clownacy/clownassembler (asm68k clone).
// Based on: https://github.com/Clownacy/clown68000
package m68k

import (
	"fmt"
	"strings"

	"sega2asm/disasm"
	"sega2asm/types"
)

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

// FlowKind classifies the control-flow effect of an instruction.
type FlowKind uint8

const (
	FlowNone   FlowKind = iota
	FlowCall            // jsr, bsr — calls a subroutine
	FlowReturn          // rts, rte, rtr — returns from subroutine
	FlowJump            // jmp, bra — unconditional jump (no return)
	FlowBranch          // bcc etc. — conditional branch
	FlowHalt            // illegal, stop — execution stops
)

// Result holds a single disassembled M68K instruction.
type Result struct {
	disasm.BaseResult
	Flow   FlowKind // control-flow classification
	Target uint32   // resolved target address for Call/Jump/Branch (0 = indirect/unknown)
}

// Disassembler holds state needed for a disassembly pass.
type Disassembler struct {
	disasm.Cursor
	lastFlow   FlowKind
	lastTarget uint32
}

// New creates a Disassembler over data starting at baseAddr.
// Genesis hardware register addresses are pre-loaded as symbolic names;
// any entry in labels overrides the built-in defaults.
func New(data []byte, baseAddr uint32, labels types.LabelMap) *Disassembler {
	merged := make(types.LabelMap, len(genesisHWPorts)+len(labels))
	for k, v := range genesisHWPorts {
		merged[k] = v
	}
	for k, v := range labels {
		merged[k] = v
	}
	return &Disassembler{Cursor: disasm.Cursor{Data: data, Base: baseAddr, Labels: merged}}
}

// Next disassembles the instruction at the current position and advances pos.
func (d *Disassembler) Next() Result {
	if d.Pos+2 > len(d.Data) {
		return Result{BaseResult: disasm.BaseResult{Addr: d.PC(), IsValid: false}}
	}
	startPos := d.Pos
	startPC := d.PC()

	d.lastFlow = FlowNone
	d.lastTarget = 0

	text, ok := d.decode()
	text = applyImmStrLiterals(text)

	end := d.Pos
	if !ok {
		// Emit as DC.W
		d.Pos = startPos + 2
		end = d.Pos
		word := types.ReadBEU16(d.Data, startPos)
		text = fmt.Sprintf("\tdc.w\t$%04X", word)
	}

	return Result{
		BaseResult: disasm.BaseResult{
			Addr:    startPC,
			Bytes:   append([]byte(nil), d.Data[startPos:end]...),
			Text:    text,
			IsValid: ok,
		},
		Flow:   d.lastFlow,
		Target: d.lastTarget,
	}
}

// ---------------------------------------------------------------------------
// Internal decode
// ---------------------------------------------------------------------------

func (d *Disassembler) decode() (string, bool) {
	op := types.ReadBEU16(d.Data, d.Pos)
	d.Pos += 2

	switch op >> 12 {
	case 0x0:
		return d.decodeGroup0(op)
	case 0x1, 0x2, 0x3:
		return d.decodeMOVE(op)
	case 0x4:
		return d.decodeGroup4(op)
	case 0x5:
		return d.decodeGroup5(op)
	case 0x6:
		return d.decodeBranch(op)
	case 0x7:
		return d.decodeMOVEQ(op)
	case 0x8:
		return d.decodeGroup8(op)
	case 0x9:
		return d.decodeSUB(op)
	case 0xA:
		return fmt.Sprintf("\tdc.w\t$%04X\t; A-line trap", op), false
	case 0xB:
		return d.decodeCMP(op)
	case 0xC:
		return d.decodeGroupC(op)
	case 0xD:
		return d.decodeADD(op)
	case 0xE:
		return d.decodeShift(op)
	case 0xF:
		return fmt.Sprintf("\tdc.w\t$%04X\t; F-line trap", op), false
	}
	return "", false
}

// ---------------------------------------------------------------------------
// Group 0 – Immediate / bit operations
// ---------------------------------------------------------------------------

func (d *Disassembler) decodeGroup0(op uint16) (string, bool) {
	// Dynamic bit ops: bit 8 set, bits 11-9 = data register (e.g. BTST d0,ea)
	if op&0xF100 == 0x0100 {
		return d.decodeBit(op)
	}
	subop := (op >> 8) & 0x0F
	// Static bit ops (subop=0x8): encoding is opword + bit-number-word + EA-words.
	// decodeBit handles all three in order — do NOT pre-consume EA here.
	if subop == 0x8 {
		return d.decodeBit(op)
	}
	// size==3 в этой группе на 68000 не кодирует ORI/ANDI/SUBI/ADDI/EORI/CMPI
	// (такие опкоды появились только в 68020 как CMP2/CHK2). Раньше отсюда
	// выходило несобираемое `ori.? #?,d0`; оставляем данными.
	if (op>>6)&3 == 3 {
		return fmt.Sprintf("	dc.w	$%04X", op), false
	}
	// ORI/ANDI/EORI в CCR или SR: приёмник зашит в опкод, а непосредственный
	// операнд — единственное расширяющее слово. EA пре-вычислять нельзя: при
	// op&0x3F == 0x3C (режим 7/4, immediate) decodeEA съедал это же слово, и
	// следующий readImm брал данные за инструкцией. Из-за этого
	// `ori.w #$0700,sr` выходил как `ori.w #$4EB9,sr`, а два байта пропадали
	// из потока — при пересборке ROM разъезжался начиная с $00030A.
	if op&0xFF == 0x3C || op&0xFF == 0x7C {
		var name string
		switch subop {
		case 0x0:
			name = "ori"
		case 0x2:
			name = "andi"
		case 0xA:
			name = "eori"
		default:
			// SUBI/ADDI/CMPI с непосредственным приёмником на 68000 не бывает.
			return fmt.Sprintf("	dc.w	$%04X", op), false
		}
		if op&0xFF == 0x7C {
			return fmt.Sprintf("	%s.w	#$%04X,sr", name, d.readImm(2)), true
		}
		return fmt.Sprintf("	%s	#$%02X,ccr", name, d.readImm(1)), true
	}
	sz := sizeName((op >> 6) & 3)
	// Порядок чтения критичен: в непосредственной группе за словом опкода
	// идёт СНАЧАЛА непосредственный операнд и только потом расширяющие слова
	// EA. Раньше EA читался первым, и операнды менялись местами:
	// `cmpi.l #$44796E61,($00FF0010).l` выходил как
	// `cmpi.l #$00FF0010,($44796E61).l`.
	imm := d.fmtImm(sz)
	ea := d.decodeEA(op&0x3F, sizeBytes((op>>6)&3))

	switch subop {
	case 0x0: // ORI
		return fmt.Sprintf("	ori.%s	%s,%s", sz, imm, ea), true
	case 0x2: // ANDI
		return fmt.Sprintf("\tandi.%s\t%s,%s", sz, imm, ea), true
	case 0x4: // SUBI
		return fmt.Sprintf("\tsubi.%s\t%s,%s", sz, imm, ea), true
	case 0x6: // ADDI
		return fmt.Sprintf("\taddi.%s\t%s,%s", sz, imm, ea), true
	case 0xA: // EORI
		return fmt.Sprintf("\teori.%s\t%s,%s", sz, imm, ea), true
	case 0xC: // CMPI
		return fmt.Sprintf("\tcmpi.%s\t%s,%s", sz, imm, ea), true
	case 0xE: // MOVES (68010+) – treat as DC
		return fmt.Sprintf("\tdc.w\t$%04X", op), false
	}
	return fmt.Sprintf("\tdc.w\t$%04X", op), false
}

func (d *Disassembler) decodeBit(op uint16) (string, bool) {
	eaReg := op & 0x3F
	bitOp := (op >> 6) & 3
	// Порядок по битам 7-6: 00=btst, 01=bchg, 10=bclr, 11=bset.
	// Раньше три последних были переставлены, и, например, $08C0 (bset)
	// выходил как bchg — при пересборке получался другой опкод.
	names := []string{"btst", "bchg", "bclr", "bset"}
	name := names[bitOp]

	var bit string
	if op&0x0100 != 0 {
		// Dynamic: bit number is in a data register (Dn)
		bit = fmt.Sprintf("d%d", (op>>9)&7)
	} else {
		// Static: bit number is in the low byte of the next extension word.
		// Guard against reading past end of segment.
		if d.Pos+2 > len(d.Data) {
			return fmt.Sprintf("\tdc.w\t$%04X\t; truncated bit-op", op), false
		}
		d.Pos += 2
		bit = fmt.Sprintf("#%d", d.Data[d.Pos-1])
	}
	ea := d.decodeEA(eaReg, 1)
	return fmt.Sprintf("\t%s\t%s,%s", name, bit, ea), true
}

// ---------------------------------------------------------------------------
// MOVE / MOVEA
// ---------------------------------------------------------------------------

func (d *Disassembler) decodeMOVE(op uint16) (string, bool) {
	sizeCode := op >> 12
	var sz string
	var bytes int
	switch sizeCode {
	case 1:
		sz, bytes = "b", 1
	case 3:
		sz, bytes = "w", 2
	case 2:
		sz, bytes = "l", 4
	default:
		return "", false
	}
	src := d.decodeEA(op&0x3F, bytes)
	dstMode := (op >> 6) & 7
	dstReg := (op >> 9) & 7
	dst := d.decodeEAReg(dstMode, dstReg, bytes)

	if dstMode == 1 {
		return fmt.Sprintf("\tmovea.%s\t%s,a%d", sz, src, dstReg), true
	}
	return fmt.Sprintf("\tmove.%s\t%s,%s", sz, src, dst), true
}

// ---------------------------------------------------------------------------
// Group 4 – Misc
// ---------------------------------------------------------------------------

func (d *Disassembler) decodeGroup4(op uint16) (string, bool) {
	// Specific patterns first
	switch op {
	case 0x4AFC:
		d.lastFlow = FlowHalt
		return "\tillegal", true
	case 0x4E70:
		return "\treset", true
	case 0x4E71:
		return "\tnop", true
	case 0x4E72:
		d.lastFlow = FlowHalt
		ext := d.readImmU16()
		return fmt.Sprintf("\tstop\t#$%04X", ext), true
	case 0x4E73:
		d.lastFlow = FlowReturn
		return "\trte", true
	case 0x4E75:
		d.lastFlow = FlowReturn
		return "\trts", true
	case 0x4E76:
		return "\ttrapv", true
	case 0x4E77:
		d.lastFlow = FlowReturn
		return "\trtr", true
	}

	if op&0xFFF0 == 0x4E40 {
		return fmt.Sprintf("\ttrap\t#%d", op&0xF), true
	}
	if op&0xFFF8 == 0x4E50 {
		d16 := int16(d.readImmU16())
		return fmt.Sprintf("\tlink\ta%d,#%d", op&7, d16), true
	}
	if op&0xFFF8 == 0x4E58 {
		return fmt.Sprintf("\tunlk\ta%d", op&7), true
	}
	if op&0xFFF8 == 0x4E60 {
		return fmt.Sprintf("\tmove.l\ta%d,usp", op&7), true
	}
	if op&0xFFF8 == 0x4E68 {
		return fmt.Sprintf("\tmove.l\tusp,a%d", op&7), true
	}
	if op&0xFFC0 == 0x4E80 {
		d.lastFlow = FlowCall
		posBeforeEA := d.Pos
		ea := d.decodeEA(op&0x3F, 4)
		d.lastTarget = eaAbsTarget(op&0x3F, d.Data, posBeforeEA, d.Base)
		return fmt.Sprintf("\tjsr\t%s", ea), true
	}
	if op&0xFFC0 == 0x4EC0 {
		d.lastFlow = FlowJump
		posBeforeEA := d.Pos
		ea := d.decodeEA(op&0x3F, 4)
		d.lastTarget = eaAbsTarget(op&0x3F, d.Data, posBeforeEA, d.Base)
		return fmt.Sprintf("\tjmp\t%s", ea), true
	}
	// MOVEM работает только с памятью. Режим 0 (Dn) под той же маской — это
	// EXT; без этой проверки decodeMOVEM съедает лишнее слово под маску
	// регистров и сбивает весь дальнейший разбор.
	if op&0xFB80 == 0x4880 && (op&0x38) != 0x00 {
		// MOVEM
		return d.decodeMOVEM(op)
	}
	if op&0xFF00 == 0x4A00 && (op>>6)&3 != 3 {
		sz := sizeName((op >> 6) & 3)
		ea := d.decodeEA(op&0x3F, sizeBytes((op>>6)&3))
		return fmt.Sprintf("\ttst.%s\t%s", sz, ea), true
	}
	if op&0xFFC0 == 0x4800 {
		ea := d.decodeEA(op&0x3F, 1)
		return fmt.Sprintf("\tnbcd\t%s", ea), true
	}
	// size==3 в группе 4 кодирует MOVE в/из SR и CCR. Без этих веток
	// `move #$2700,sr` и `move sr,-(a7)` выходили как not.?/negx.? —
	// несобираемый мусор. $42C0 (MOVE CCR,<ea>) есть только с 68010,
	// на 68000 это данные, поэтому намеренно не декодируем.
	if op&0xFFC0 == 0x40C0 {
		ea := d.decodeEA(op&0x3F, 2)
		return fmt.Sprintf("	move	sr,%s", ea), true
	}
	if op&0xFFC0 == 0x44C0 {
		ea := d.decodeEA(op&0x3F, 2)
		return fmt.Sprintf("	move	%s,ccr", ea), true
	}
	if op&0xFFC0 == 0x46C0 {
		ea := d.decodeEA(op&0x3F, 2)
		return fmt.Sprintf("	move	%s,sr", ea), true
	}
	if op&0xFF00 == 0x4200 && (op>>6)&3 != 3 {
		sz := sizeName((op >> 6) & 3)
		ea := d.decodeEA(op&0x3F, sizeBytes((op>>6)&3))
		return fmt.Sprintf("\tclr.%s\t%s", sz, ea), true
	}
	if op&0xFF00 == 0x4400 && (op>>6)&3 != 3 {
		sz := sizeName((op >> 6) & 3)
		ea := d.decodeEA(op&0x3F, sizeBytes((op>>6)&3))
		return fmt.Sprintf("\tneg.%s\t%s", sz, ea), true
	}
	if op&0xFF00 == 0x4000 && (op>>6)&3 != 3 {
		sz := sizeName((op >> 6) & 3)
		ea := d.decodeEA(op&0x3F, sizeBytes((op>>6)&3))
		return fmt.Sprintf("\tnegx.%s\t%s", sz, ea), true
	}
	if op&0xFF00 == 0x4600 && (op>>6)&3 != 3 {
		sz := sizeName((op >> 6) & 3)
		ea := d.decodeEA(op&0x3F, sizeBytes((op>>6)&3))
		return fmt.Sprintf("\tnot.%s\t%s", sz, ea), true
	}
	// SWAP ($4840-$4847) целиком внутри маски PEA, поэтому проверяется первым.
	if op&0xFFF8 == 0x4840 {
		return fmt.Sprintf("\tswap\td%d", op&7), true
	}
	if op&0xFFC0 == 0x4840 {
		ea := d.decodeEA(op&0x3F, 4)
		return fmt.Sprintf("\tpea\t%s", ea), true
	}
	if op&0xFFC0 == 0x4AC0 {
		ea := d.decodeEA(op&0x3F, 1)
		return fmt.Sprintf("\ttas\t%s", ea), true
	}
	if op&0xF1C0 == 0x41C0 {
		ea := d.decodeEA(op&0x3F, 4)
		return fmt.Sprintf("\tlea\t%s,a%d", ea, (op>>9)&7), true
	}
	if op&0xF1C0 == 0x4180 {
		ea := d.decodeEA(op&0x3F, 2)
		return fmt.Sprintf("\tchk.w\t%s,d%d", ea, (op>>9)&7), true
	}
	if op&0xFFF8 == 0x4880 {
		return fmt.Sprintf("\text.w\td%d", op&7), true
	}
	if op&0xFFF8 == 0x48C0 {
		return fmt.Sprintf("\text.l\td%d", op&7), true
	}
	return fmt.Sprintf("\tdc.w\t$%04X", op), false
}

func (d *Disassembler) decodeMOVEM(op uint16) (string, bool) {
	toMem := op&0x0400 == 0
	sz := "w"
	bytes := 2
	if op&0x0040 != 0 {
		sz = "l"
		bytes = 4
	}
	mask := d.readImmU16()
	ea := d.decodeEA(op&0x3F, bytes)
	regList := regListStr(mask, toMem && (op&0x38) == 0x20)
	if toMem {
		return fmt.Sprintf("\tmovem.%s\t%s,%s", sz, regList, ea), true
	}
	return fmt.Sprintf("\tmovem.%s\t%s,%s", sz, ea, regList), true
}

// ---------------------------------------------------------------------------
// Group 5 – ADDQ / SUBQ / Scc / DBcc
// ---------------------------------------------------------------------------

func (d *Disassembler) decodeGroup5(op uint16) (string, bool) {
	cond := (op >> 8) & 0xF
	if (op>>6)&3 == 3 {
		// Scc or DBcc
		if (op>>3)&7 == 1 {
			// DBcc
			disp := int16(d.readImmU16())
			target := d.PC() + uint32(disp) - 2
			d.lastFlow = FlowBranch
			d.lastTarget = target
			return fmt.Sprintf("\tdb%s\td%d,%s", condName(cond), op&7, d.labelOrHex(target)), true
		}
		ea := d.decodeEA(op&0x3F, 1)
		return fmt.Sprintf("\ts%s\t%s", condName(cond), ea), true
	}
	sz := sizeName((op >> 6) & 3)
	imm := (op >> 9) & 7
	if imm == 0 {
		imm = 8
	}
	ea := d.decodeEA(op&0x3F, sizeBytes((op>>6)&3))
	if op&0x0100 != 0 {
		return fmt.Sprintf("\tsubq.%s\t#%d,%s", sz, imm, ea), true
	}
	return fmt.Sprintf("\taddq.%s\t#%d,%s", sz, imm, ea), true
}

// ---------------------------------------------------------------------------
// Branch instructions
// ---------------------------------------------------------------------------

func (d *Disassembler) decodeBranch(op uint16) (string, bool) {
	cond := (op >> 8) & 0xF
	disp8 := int8(op & 0xFF)
	var target uint32
	var size string

	if disp8 == 0 {
		disp16 := int16(d.readImmU16())
		target = d.PC() + uint32(disp16) - 2
		size = ".w"
	} else if disp8 == -1 { // 0xFF = long branch (68020)
		disp32 := int32(d.readImmU32())
		target = d.PC() + uint32(disp32) - 4
		size = ".l"
	} else {
		target = d.PC() + uint32(disp8)
		size = ".s"
	}

	d.lastTarget = target
	label := d.labelOrHex(target)
	if cond == 0 {
		d.lastFlow = FlowJump
		return fmt.Sprintf("\tbra%s\t%s", size, label), true
	}
	if cond == 1 {
		d.lastFlow = FlowCall
		return fmt.Sprintf("\tbsr%s\t%s", size, label), true
	}
	d.lastFlow = FlowBranch
	return fmt.Sprintf("\tb%s%s\t%s", condName(cond), size, label), true
}

// ---------------------------------------------------------------------------
// MOVEQ
// ---------------------------------------------------------------------------

func (d *Disassembler) decodeMOVEQ(op uint16) (string, bool) {
	if op&0x0100 != 0 {
		return fmt.Sprintf("\tdc.w\t$%04X", op), false
	}
	imm := int8(op & 0xFF)
	dn := (op >> 9) & 7
	return fmt.Sprintf("\tmoveq\t#%d,d%d", imm, dn), true
}

// ---------------------------------------------------------------------------
// Group 8 – OR / DIVU / DIVS / SBCD
// ---------------------------------------------------------------------------

func (d *Disassembler) decodeGroup8(op uint16) (string, bool) {
	dn := (op >> 9) & 7
	opmode := (op >> 6) & 7

	if opmode == 3 {
		ea := d.decodeEA(op&0x3F, 2)
		return fmt.Sprintf("\tdivu.w\t%s,d%d", ea, dn), true
	}
	if opmode == 7 {
		ea := d.decodeEA(op&0x3F, 2)
		return fmt.Sprintf("\tdivs.w\t%s,d%d", ea, dn), true
	}
	if opmode == 4 && (op>>3)&7 == 0 {
		return fmt.Sprintf("\tsbcd\td%d,d%d", op&7, dn), true
	}
	if opmode == 4 && (op>>3)&7 == 1 {
		return fmt.Sprintf("\tsbcd\t-(a%d),-(a%d)", op&7, dn), true
	}
	sz := sizeName(opmode & 3)
	ea := d.decodeEA(op&0x3F, sizeBytes(uint16(opmode&3)))
	if opmode&4 != 0 {
		return fmt.Sprintf("\tor.%s\td%d,%s", sz, dn, ea), true
	}
	return fmt.Sprintf("\tor.%s\t%s,d%d", sz, ea, dn), true
}

// ---------------------------------------------------------------------------
// SUB
// ---------------------------------------------------------------------------

func (d *Disassembler) decodeSUB(op uint16) (string, bool) {
	dn := (op >> 9) & 7
	opmode := (op >> 6) & 7
	if opmode == 3 {
		ea := d.decodeEA(op&0x3F, 2)
		return fmt.Sprintf("\tsuba.w\t%s,a%d", ea, dn), true
	}
	if opmode == 7 {
		ea := d.decodeEA(op&0x3F, 4)
		return fmt.Sprintf("\tsuba.l\t%s,a%d", ea, dn), true
	}
	sz := sizeName(uint16(opmode & 3))
	ea := d.decodeEA(op&0x3F, sizeBytes(uint16(opmode&3)))
	// SUBX занимает режимы 0 и 1 при bit8=1; прочие режимы там — обычный
	// `sub.<sz> Dn,<ea>`. Без этого $D300 (`addx.b d0,d1`) выходил как
	// `add.b d1,d0`, и пересборка давала другой опкод.
	if opmode&4 != 0 {
		switch (op >> 3) & 7 {
		case 0:
			return fmt.Sprintf("	subx.%s	d%d,d%d", sz, op&7, dn), true
		case 1:
			return fmt.Sprintf("	subx.%s	-(a%d),-(a%d)", sz, op&7, dn), true
		}
	}
	if opmode&4 != 0 {
		return fmt.Sprintf("\tsub.%s\td%d,%s", sz, dn, ea), true
	}
	return fmt.Sprintf("\tsub.%s\t%s,d%d", sz, ea, dn), true
}

// ---------------------------------------------------------------------------
// CMP / EOR
// ---------------------------------------------------------------------------

func (d *Disassembler) decodeCMP(op uint16) (string, bool) {
	dn := (op >> 9) & 7
	opmode := (op >> 6) & 7
	if opmode == 3 {
		ea := d.decodeEA(op&0x3F, 2)
		return fmt.Sprintf("\tcmpa.w\t%s,a%d", ea, dn), true
	}
	if opmode == 7 {
		ea := d.decodeEA(op&0x3F, 4)
		return fmt.Sprintf("\tcmpa.l\t%s,a%d", ea, dn), true
	}
	sz := sizeName(uint16(opmode & 3))
	ea := d.decodeEA(op&0x3F, sizeBytes(uint16(opmode&3)))
	if opmode&4 != 0 {
		// CMPM — это режим 1 при bit8=1; любой другой режим там означает EOR.
		// Раньше CMPM проверялся как `opmode < 3`, то есть ровно наоборот, и
		// $B089 (`cmp.l a1,d0`) выходил как `cmpm.l (a1)+,(a0)+`.
		if (op>>3)&7 == 1 {
			return fmt.Sprintf("	cmpm.%s	(a%d)+,(a%d)+", sz, op&7, dn), true
		}
		return fmt.Sprintf("	eor.%s	d%d,%s", sz, dn, ea), true
	}
	return fmt.Sprintf("\tcmp.%s\t%s,d%d", sz, ea, dn), true
}

// ---------------------------------------------------------------------------
// Group C – AND / MUL / ABCD / EXG
// ---------------------------------------------------------------------------

func (d *Disassembler) decodeGroupC(op uint16) (string, bool) {
	dn := (op >> 9) & 7
	opmode := (op >> 6) & 7

	if opmode == 3 {
		ea := d.decodeEA(op&0x3F, 2)
		return fmt.Sprintf("\tmulu.w\t%s,d%d", ea, dn), true
	}
	if opmode == 7 {
		ea := d.decodeEA(op&0x3F, 2)
		return fmt.Sprintf("\tmuls.w\t%s,d%d", ea, dn), true
	}
	// ABCD и EXG занимают только режимы 0 и 1; при любом другом режиме те же
	// opmode означают обычный `and.<sz> Dn,<ea>`. Раньше opmode 5 и 6 всегда
	// давали exg, и, например, $C390 (`and.l d1,(a0)`) выходил как
	// `exg d1,a0` — при пересборке получался опкод $C388.
	mode := (op >> 3) & 7
	if opmode == 4 && mode == 0 {
		return fmt.Sprintf("	abcd	d%d,d%d", op&7, dn), true
	}
	if opmode == 4 && mode == 1 {
		return fmt.Sprintf("	abcd	-(a%d),-(a%d)", op&7, dn), true
	}
	if opmode == 5 && mode == 0 {
		return fmt.Sprintf("	exg	d%d,d%d", dn, op&7), true
	}
	if opmode == 5 && mode == 1 {
		return fmt.Sprintf("	exg	a%d,a%d", dn, op&7), true
	}
	if opmode == 6 && mode == 1 {
		return fmt.Sprintf("	exg	d%d,a%d", dn, op&7), true
	}
	sz := sizeName(uint16(opmode & 3))
	ea := d.decodeEA(op&0x3F, sizeBytes(uint16(opmode&3)))
	if opmode&4 != 0 {
		return fmt.Sprintf("\tand.%s\td%d,%s", sz, dn, ea), true
	}
	return fmt.Sprintf("\tand.%s\t%s,d%d", sz, ea, dn), true
}

// ---------------------------------------------------------------------------
// ADD
// ---------------------------------------------------------------------------

func (d *Disassembler) decodeADD(op uint16) (string, bool) {
	dn := (op >> 9) & 7
	opmode := (op >> 6) & 7
	if opmode == 3 {
		ea := d.decodeEA(op&0x3F, 2)
		return fmt.Sprintf("\tadda.w\t%s,a%d", ea, dn), true
	}
	if opmode == 7 {
		ea := d.decodeEA(op&0x3F, 4)
		return fmt.Sprintf("\tadda.l\t%s,a%d", ea, dn), true
	}
	sz := sizeName(uint16(opmode & 3))
	ea := d.decodeEA(op&0x3F, sizeBytes(uint16(opmode&3)))
	// ADDX занимает режимы 0 и 1 при bit8=1; прочие режимы там — обычный
	// `add.<sz> Dn,<ea>`. Без этого $D300 (`addx.b d0,d1`) выходил как
	// `add.b d1,d0`, и пересборка давала другой опкод.
	if opmode&4 != 0 {
		switch (op >> 3) & 7 {
		case 0:
			return fmt.Sprintf("	addx.%s	d%d,d%d", sz, op&7, dn), true
		case 1:
			return fmt.Sprintf("	addx.%s	-(a%d),-(a%d)", sz, op&7, dn), true
		}
	}
	if opmode&4 != 0 {
		return fmt.Sprintf("\tadd.%s\td%d,%s", sz, dn, ea), true
	}
	return fmt.Sprintf("\tadd.%s\t%s,d%d", sz, ea, dn), true
}

// ---------------------------------------------------------------------------
// Shifts / Rotates
// ---------------------------------------------------------------------------

func (d *Disassembler) decodeShift(op uint16) (string, bool) {
	dir := (op >> 8) & 1 // 0=right, 1=left
	mode := (op >> 3) & 7
	// Тип сдвига у регистровой формы лежит в битах 4-3: биты 11-9 там заняты
	// счётчиком или номером регистра. Только у формы «сдвиг памяти»
	// (size == 3) тип в битах 10-9. Раньше он всегда брался из 11-9, и,
	// например, $E998 (`rol.l #4,d0`) выходил как `asl.l #4,d0`.
	var kind uint16
	if (op>>6)&3 == 3 {
		kind = (op >> 9) & 3
	} else {
		kind = (op >> 3) & 3
	}
	names := [4]string{"as", "ls", "rox", "ro"}
	name := names[kind]
	dirStr := "r"
	if dir != 0 {
		dirStr = "l"
	}

	if (op>>6)&3 == 3 {
		// Memory shift
		ea := d.decodeEA(op&0x3F, 2)
		return fmt.Sprintf("\t%s%s.w\t%s", name, dirStr, ea), true
	}

	sz := sizeName((op >> 6) & 3)
	dr := op & 7
	var count string
	if mode&4 != 0 {
		count = fmt.Sprintf("d%d", (op>>9)&7)
	} else {
		c := (op >> 9) & 7
		if c == 0 {
			c = 8
		}
		count = fmt.Sprintf("#%d", c)
	}
	return fmt.Sprintf("\t%s%s.%s\t%s,d%d", name, dirStr, sz, count, dr), true
}

// ---------------------------------------------------------------------------
// Effective Address decoder
// ---------------------------------------------------------------------------

func (d *Disassembler) decodeEA(ea uint16, bytes int) string {
	mode := (ea >> 3) & 7
	reg := ea & 7
	return d.decodeEAReg(mode, reg, bytes)
}

func (d *Disassembler) decodeEAReg(mode, reg uint16, bytes int) string {
	switch mode {
	case 0:
		return fmt.Sprintf("d%d", reg)
	case 1:
		return fmt.Sprintf("a%d", reg)
	case 2:
		return fmt.Sprintf("(a%d)", reg)
	case 3:
		return fmt.Sprintf("(a%d)+", reg)
	case 4:
		return fmt.Sprintf("-(a%d)", reg)
	case 5:
		disp := int16(d.readImmU16())
		if disp < 0 {
			return fmt.Sprintf("-$%X(a%d)", -disp, reg)
		}
		return fmt.Sprintf("$%X(a%d)", disp, reg)
	case 6:
		ext := d.readImmU16()
		disp := int8(ext & 0xFF)
		idxReg := (ext >> 12) & 7
		idxKind := "d"
		if ext&0x8000 != 0 {
			idxKind = "a"
		}
		idxSz := "w"
		if ext&0x0800 != 0 {
			idxSz = "l"
		}
		if disp < 0 {
			return fmt.Sprintf("(-$%X,a%d,%s%d.%s)", -disp, reg, idxKind, idxReg, idxSz)
		}
		return fmt.Sprintf("($%X,a%d,%s%d.%s)", disp, reg, idxKind, idxReg, idxSz)
	case 7:
		switch reg {
		case 0:
			// Absolute short: sign-extend 16→32.
			addr := uint32(int32(int16(d.readImmU16())))
			return d.labelOrHex16(addr)
		case 1:
			addr := d.readImmU32()
			return d.labelOrHex32(addr)
		case 2:
			disp := int16(d.readImmU16())
			target := d.PC() + uint32(disp) - 2
			return fmt.Sprintf("%s(pc)", d.labelOrHex(target))
		case 3:
			ext := d.readImmU16()
			disp := int8(ext & 0xFF)
			idxReg := (ext >> 12) & 7
			idxKind := "d"
			if ext&0x8000 != 0 {
				idxKind = "a"
			}
			idxSz := "w"
			if ext&0x0800 != 0 {
				idxSz = "l"
			}
			// Первым операндом asm68k ждёт АДРЕС и сам считает смещение от PC
			// (как в режиме (d16,pc) выше). Сырое смещение он принимал за
			// абсолютный адрес и ругался Displacement values cannot be larger
			// than $7F. База — адрес самого расширяющего слова, т.е. PC()-2.
			target := d.PC() + uint32(int32(disp)) - 2
			return fmt.Sprintf("(%s,pc,%s%d.%s)", d.labelOrHex(target), idxKind, idxReg, idxSz)
		case 4:
			switch bytes {
			case 1:
				v := d.readImmU16()
				return fmt.Sprintf("#$%02X", v&0xFF)
			case 2:
				v := d.readImmU16()
				return fmt.Sprintf("#$%04X", v)
			case 4:
				v := d.readImmU32()
				return fmt.Sprintf("#$%08X", v)
			}
		}
	}
	return fmt.Sprintf("?ea(%d,%d)", mode, reg)
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func (d *Disassembler) readImmU16() uint16 {
	if d.Pos+2 > len(d.Data) {
		return 0
	}
	v := types.ReadBEU16(d.Data, d.Pos)
	d.Pos += 2
	return v
}

func (d *Disassembler) readImmU32() uint32 {
	if d.Pos+4 > len(d.Data) {
		return 0
	}
	v := types.ReadBEU32(d.Data, d.Pos)
	d.Pos += 4
	return v
}

func (d *Disassembler) readImm(n int) uint32 {
	switch n {
	case 1:
		if d.Pos+2 > len(d.Data) {
			return 0
		}
		v := types.ReadBEU16(d.Data, d.Pos)
		d.Pos += 2
		return uint32(v & 0xFF)
	case 2:
		if d.Pos+2 > len(d.Data) {
			return 0
		}
		v := types.ReadBEU16(d.Data, d.Pos)
		d.Pos += 2
		return uint32(v)
	case 4:
		if d.Pos+4 > len(d.Data) {
			return 0
		}
		v := types.ReadBEU32(d.Data, d.Pos)
		d.Pos += 4
		return v
	}
	return 0
}

func (d *Disassembler) fmtImm(sz string) string {
	switch sz {
	case "b":
		return fmt.Sprintf("#$%02X", d.readImm(1))
	case "w":
		return fmt.Sprintf("#$%04X", d.readImm(2))
	case "l":
		return fmt.Sprintf("#$%08X", d.readImm(4))
	}
	return "#?"
}

// applyImmStrLiterals rewrites known immediate values to string literal form
// for specific destination registers where the value is a 4-byte ASCII tag.
func applyImmStrLiterals(text string) string {
	// TMSS unlock: move.l #'SEGA',TMSS_REG
	return strings.ReplaceAll(text, "#$53454741,TMSS_REG", "#'SEGA',TMSS_REG")
}

func (d *Disassembler) labelOrHex(addr uint32) string {
	return types.LookupOrHex(d.Labels, addr)
}

func (d *Disassembler) labelOrHex16(addr uint32) string {
	if name, ok := d.Labels[addr]; ok {
		return fmt.Sprintf("(%s).w", name)
	}
	return fmt.Sprintf("($%06X).w", addr)
}

func (d *Disassembler) labelOrHex32(addr uint32) string {
	if name, ok := d.Labels[addr]; ok {
		return fmt.Sprintf("(%s).l", name)
	}
	return fmt.Sprintf("($%06X).l", addr)
}

// eaAbsTarget extracts the resolved absolute address from a JSR/JMP EA field
// when the EA encodes a static address (absolute long/short or PC-relative).
// posAfterOpword is the index in data right after the instruction opword.
// Returns 0 for indirect/register-based EA modes.
func eaAbsTarget(ea uint16, data []byte, posAfterOpword int, base uint32) uint32 {
	if (ea>>3)&7 != 7 {
		return 0 // not an extended EA mode
	}
	switch ea & 7 {
	case 0: // absolute short (.w)
		if posAfterOpword+2 <= len(data) {
			return uint32(types.ReadBEU16(data, posAfterOpword))
		}
	case 1: // absolute long (.l)
		if posAfterOpword+4 <= len(data) {
			return types.ReadBEU32(data, posAfterOpword)
		}
	case 2: // PC-relative (d16,PC) — PC points past the displacement word
		if posAfterOpword+2 <= len(data) {
			disp := int16(types.ReadBEU16(data, posAfterOpword))
			pc := base + uint32(posAfterOpword+2)
			return uint32(int32(pc) + int32(disp))
		}
	}
	return 0
}

func sizeName(sz uint16) string {
	switch sz & 3 {
	case 0:
		return "b"
	case 1:
		return "w"
	case 2:
		return "l"
	}
	return "?"
}

func sizeBytes(sz uint16) int {
	switch sz & 3 {
	case 0:
		return 1
	case 1:
		return 2
	case 2:
		return 4
	}
	return 2
}

func condName(cond uint16) string {
	names := []string{"t", "f", "hi", "ls", "cc", "cs", "ne", "eq", "vc", "vs", "pl", "mi", "ge", "lt", "gt", "le"}
	if int(cond) < len(names) {
		return names[cond]
	}
	return fmt.Sprintf("?%d", cond)
}

func regListStr(mask uint16, predecrement bool) string {
	var parts []string
	regs := [16]string{"d0", "d1", "d2", "d3", "d4", "d5", "d6", "d7", "a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7"}
	if predecrement {
		// Reversed for predecrement addressing
		var rev [16]string
		for i := 0; i < 8; i++ {
			rev[i] = regs[15-i]
			rev[8+i] = regs[7-i]
		}
		regs = rev
	}
	// Бит i соответствует regs[i], а НЕ regs[15-i]: в маске MOVEM бит 0 — это
	// d0 (для -(An) — a7, что уже учтено переворотом regs выше). Из-за
	// инвертированного индекса неверно читались все movem: классический
	// `movem.w (a5)+,d5-d7` из boot-кода Sega выходил как `a0/a1/a2`, а
	// `movem.l d0-d7/a0,-(a7)` — как `a7-a0/d7`.
	for i, r := range regs {
		if mask&(1<<uint(i)) != 0 {
			parts = append(parts, r)
		}
	}
	return strings.Join(parts, "/")
}

// DisassembleBlock disassembles data[start:end] treating it as M68K code.
// Returns all Result entries with labels resolved, including automatic
// jump-table detection (dc.l entries replacing garbled post-terminator bytes).
func DisassembleBlock(data []byte, baseAddr, start, end uint32, labels types.LabelMap) []Result {
	segData := data[start:end]
	segBase := baseAddr + start
	d := New(segData, segBase, labels)
	var results []Result
	for d.Remaining() >= 2 {
		results = append(results, d.Next())
	}
	results = detectJumpTables(results, segData, segBase, d.Labels)
	results = convertDeadDataToDCW(results, segData, segBase)
	return results
}

// ---------------------------------------------------------------------------
// Jump table detection
// ---------------------------------------------------------------------------

// detectJumpTables performs a post-disassembly pass and replaces bytes that
// immediately follow a flow terminator with dc.l entries when those bytes look
// like a table of valid Genesis/Mega Drive code pointers.
//
// Trigger: any result with FlowJump or FlowHalt.
// Entry test: 32-bit value where the high byte is 0x00 (ROM range), the
// address is word-aligned, and >= 0x000200 (past the vector table).
// Minimum 2 consecutive valid entries required to trigger.
//
// After a detected table, disassembly continues as normal code.
func detectJumpTables(results []Result, data []byte, segBase uint32, labels types.LabelMap) []Result {
	if len(results) == 0 {
		return results
	}

	type insertion struct {
		afterIdx int
		entries  []Result
	}

	skip := make([]bool, len(results))
	var inserts []insertion

	for i, res := range results {
		if res.Flow != FlowJump && res.Flow != FlowHalt {
			continue
		}

		// Table candidate starts at the first byte after this instruction.
		tableBase := res.Addr + uint32(len(res.Bytes))
		off := int(tableBase - segBase)

		// Read consecutive valid jump table entries (4-byte long addresses).
		var addrs []uint32
		for off+4 <= len(data) {
			v := uint32(data[off])<<24 | uint32(data[off+1])<<16 |
				uint32(data[off+2])<<8 | uint32(data[off+3])
			if !isJumpTableEntry(v) {
				break
			}
			addrs = append(addrs, v)
			off += 4
		}
		if len(addrs) < 2 {
			continue
		}

		tableEnd := tableBase + uint32(len(addrs)*4)

		// Build dc.l Result entries for the table.
		var dcls []Result
		for k, addr := range addrs {
			entryAddr := tableBase + uint32(k*4)
			rawOff := int(entryAddr - segBase)
			var rawBytes []byte
			if rawOff+4 <= len(data) {
				rawBytes = data[rawOff : rawOff+4]
			}
			name := resolveLabel(addr, labels)
			dcls = append(dcls, Result{
				BaseResult: disasm.BaseResult{
					Addr:    entryAddr,
					Bytes:   rawBytes,
					Text:    fmt.Sprintf("\tdc.l\t%s", name),
					IsValid: true,
				},
				Flow: FlowNone,
			})
		}

		// Mark results that fall inside the table region for removal.
		for j := i + 1; j < len(results); j++ {
			if results[j].Addr >= tableEnd {
				break
			}
			skip[j] = true
		}

		inserts = append(inserts, insertion{afterIdx: i, entries: dcls})
	}

	if len(inserts) == 0 {
		return results
	}

	// Build a map: resultIndex → dc.l entries to insert after it.
	insertAfter := make(map[int][]Result, len(inserts))
	for _, ins := range inserts {
		insertAfter[ins.afterIdx] = ins.entries
	}

	out := make([]Result, 0, len(results))
	for i, res := range results {
		if skip[i] {
			continue
		}
		out = append(out, res)
		if extra, ok := insertAfter[i]; ok {
			out = append(out, extra...)
		}
	}
	return out
}

// convertDeadDataToDCW converts unreachable instruction sequences whose opcode
// word is in the $0000–$000F range (ori.b/ori.w to any Dn) into dc.w entries.
// These opcodes virtually never appear in real M68K code and are almost always
// embedded data that follows a flow terminator.
//
// Dead mode starts after FlowReturn/FlowJump/FlowHalt and ends when either:
//   - A known intra-segment branch target is reached, or
//   - An opcode outside $0000–$000F is encountered (new function entry).
//
// Already-formatted dc.* entries from detectJumpTables are kept as-is.
func convertDeadDataToDCW(results []Result, data []byte, segBase uint32) []Result {
	if len(results) == 0 {
		return results
	}

	// Collect all intra-segment branch/call targets.
	branchTargets := make(map[uint32]bool)
	branchTargets[results[0].Addr] = true
	for _, res := range results {
		if res.Target != 0 {
			branchTargets[res.Target] = true
		}
	}

	out := make([]Result, 0, len(results))
	inDead := false

	for _, res := range results {
		addr := res.Addr

		// Known branch target always resumes code mode.
		if branchTargets[addr] {
			inDead = false
		}

		if inDead {
			// Keep entries already formatted by detectJumpTables.
			if strings.HasPrefix(res.Text, "\tdc.") {
				out = append(out, res)
				continue
			}

			rawOff := int(addr - segBase)
			if rawOff+2 > len(data) {
				out = append(out, res)
				continue
			}
			opcode := uint16(data[rawOff])<<8 | uint16(data[rawOff+1])
			if opcode <= 0x000F {
				// Convert each word of this instruction to dc.w.
				for j := 0; j+1 < len(res.Bytes); j += 2 {
					off := rawOff + j
					if off+2 > len(data) {
						break
					}
					w := uint16(data[off])<<8 | uint16(data[off+1])
					out = append(out, Result{
						BaseResult: disasm.BaseResult{
							Addr:    addr + uint32(j),
							Bytes:   data[off : off+2],
							Text:    fmt.Sprintf("\tdc.w\t$%04X", w),
							IsValid: true,
						},
					})
				}
				continue
			}
			// Non-trivial opcode: exit dead mode and emit as code.
			inDead = false
		}

		out = append(out, res)

		if res.Flow == FlowReturn || res.Flow == FlowJump || res.Flow == FlowHalt {
			inDead = true
		}
	}
	return out
}

// isJumpTableEntry returns true for 32-bit values that look like valid Genesis
// code pointers: high byte must be 0x00 (ROM 0–4 MB range), address must be
// word-aligned and above the vector table ($000200).
func isJumpTableEntry(addr uint32) bool {
	if addr>>24 != 0x00 {
		return false
	}
	lo := addr & 0x00FFFFFF
	return lo >= 0x000200 && lo <= 0x3FFFFF && lo&1 == 0
}

// resolveLabel returns the symbolic name for addr from the labels map, or a
// hex literal if addr is not a known label.
func resolveLabel(addr uint32, labels types.LabelMap) string {
	if name, ok := labels[addr]; ok {
		return name
	}
	return fmt.Sprintf("$%06X", addr&0x00FFFFFF)
}

// ---------------------------------------------------------------------------
// Genesis hardware ports
// ---------------------------------------------------------------------------

// HWPortName returns the built-in symbolic name for a Genesis hardware
// register address, or "" if the address is not a known hardware port.
func HWPortName(addr uint32) string {
	return genesisHWPorts[addr]
}

// genesisHWPorts maps Sega Genesis / Mega Drive hardware register addresses
// to their canonical symbolic names. They are pre-loaded into the disassembler
// label table so that absolute-long memory references print as symbolic names
// instead of raw hex addresses. User-provided symbols override these defaults.
var genesisHWPorts = map[uint32]string{
	// VDP
	0x00C00000: "VDP_DATA",
	0x00C00002: "VDP_DATA_W",
	0x00C00004: "VDP_CTRL",
	0x00C00006: "VDP_CTRL_W",
	0x00C00008: "VDP_HVCOUNTER",
	0x00C0001C: "VDP_DEBUG",
	// PSG
	0x00C00011: "PSG_DATA",
	// Z80
	0x00A00000: "Z80_RAM",
	0x00A11100: "Z80_BUSREQ",
	0x00A11200: "Z80_RESET",
	// I/O
	0x00A10001: "IO_PCBVER",
	0x00A10003: "IO_DATA_1",
	0x00A10005: "IO_DATA_2",
	0x00A10007: "IO_DATA_EXP",
	0x00A10009: "IO_CTRL_1",
	0x00A1000B: "IO_CTRL_2",
	0x00A1000D: "IO_CTRL_EXP",
	0x00A1000F: "IO_TXDATA_1",
	0x00A10011: "IO_RXDATA_1",
	0x00A10013: "IO_SCTRL_1",
	0x00A10015: "IO_TXDATA_2",
	0x00A10017: "IO_RXDATA_2",
	0x00A10019: "IO_SCTRL_2",
	0x00A1001B: "IO_TXDATA_EXP",
	0x00A1001D: "IO_RXDATA_EXP",
	0x00A1001F: "IO_SCTRL_EXP",
	// Memory control
	0x00A11000: "MEM_MODE",
	0x00A13000: "TIME_REG",
	0x00A14000: "TMSS_REG",
	0x00A14100: "TMSS_VDP",
}
