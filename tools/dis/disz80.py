#!/usr/bin/env python3
"""disz80.py — disassembler Z80 pro Cheeky Mouse (Universal 1980).

Použití:
    ./disz80.py [--hints ../../sources/asm/hints.txt] [--out ../../sources/asm/cheekyms.asm]
                [--cov coverage.txt]

Vzor: ~/sw/stinger/tools/dis/disz80.py (rekurzivní sledování toku od vstupních bodů,
oddělení kódu od dat, hinty, návěští L_/S_, symboly HW a RAM, křížové odkazy, DB bloky).

Odlišnosti proti Stingeru:
  - **jediný, nešifrovaný obraz** — program je cm03…cm06 slepené na 0000h–1FFFh,
  - **vstupy a výstupy jsou porty**, ne paměť; symboly portů jsou v PORTS,
  - vektory: 0000h reset, 0038h přerušení VBLANK (IM 1), 0066h NMI (vhozená mince).

`--cov` přečte pokrytí z trasovacího emulátoru (`tools/dis/trace-cheekyms.py --cov`)
a přidá každou skutečně vykonanou adresu jako vstupní bod kódu. Statická analýza tak
nemusí uhodnout cíle nepřímých skoků — hra je prostě odehraje.

Soubor hints — řádky (jako u Stingeru):
    code 0x1234              ; další vstupní bod kódu (cíl JP (HL) / tabulky)
    data 0x1f00 0x1fff       ; rozsah je určitě data
    label 0x0552 name
    comment 0x0552 text
    ram 0x3045 name          ; symbol pro RAM/HW adresu
    ptrs lohi 0x1f00 0x1fff  ; tabulka 16bit ukazatelů na kód (Z80 = lohi)
    ptrs lohi 0x1f00 0x1fff step 3
"""
import argparse
import re
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))

PROGRAM_FILES = [("cm03.c5", 0x0000), ("cm04.c6", 0x0800),
                 ("cm05.c7", 0x1000), ("cm06.c8", 0x1800)]
SIZE = 0x2000
ROM_DIR = os.path.join(ROOT, "sources/rom/cheekyms")

TITLE = "Cheeky Mouse (Universal 1980) — Z80, programová ROM 0000h-1FFFh (cm03.c5, cm04.c6, cm05.c7, cm06.c8)"
VECTORS = [0x0000, 0x0038, 0x0066]   # reset, IM 1 VBLANK, NMI (mince)

# paměťová mapa podle sources/mame/cheekyms.cpp
HW = [
    (0x3000, 0x33FF, "RAM",   "pracovní RAM 1 KiB"),
    (0x3800, 0x3BFF, "VRAM",  "videopaměť 32x32 kódů dlaždic"),
]

# porty (IN/OUT) podle sources/mame/cheekyms.cpp
PORTS_IN = {
    0x00: ("DSW",    "DIP přepínače"),
    0x01: ("INPUTS", "vstupy: mince, start 1P/2P, vlevo, vpravo, kladivo (aktivní v nule)"),
}
PORTS_OUT = {
    0x40: ("SOUND",  "zvukové spouštěče d7-d1"),
    0x80: ("VIDEO",  "d0 mute, d1 zvuk, d2 povolení IRQ, d3-d5 posun pruhu muže, d6 paleta, d7 flip"),
}
for _p in range(0x20, 0x40):
    PORTS_OUT[_p] = ("SPR%d_%d" % ((_p - 0x20) // 4, (_p - 0x20) % 4),
                     "sprite %d, bajt %d" % ((_p - 0x20) // 4, (_p - 0x20) % 4))


# ---- dekodér Z80 --------------------------------------------------------------------------------
R8 = ["B", "C", "D", "E", "H", "L", "(HL)", "A"]
RP = ["BC", "DE", "HL", "SP"]
RP2 = ["BC", "DE", "HL", "AF"]
CC = ["NZ", "Z", "NC", "C", "PO", "PE", "P", "M"]
ALU = ["ADD A,", "ADC A,", "SUB ", "SBC A,", "AND ", "XOR ", "OR ", "CP "]
ROT = ["RLC", "RRC", "RL", "RR", "SLA", "SRA", "SLL", "SRL"]
BLI = {0xA0: "LDI", 0xA1: "CPI", 0xA2: "INI", 0xA3: "OUTI", 0xA8: "LDD", 0xA9: "CPD", 0xAA: "IND", 0xAB: "OUTD",
       0xB0: "LDIR", 0xB1: "CPIR", 0xB2: "INIR", 0xB3: "OTIR", 0xB8: "LDDR", 0xB9: "CPDR", 0xBA: "INDR", 0xBB: "OTDR"}


class Insn:
    __slots__ = ("addr", "length", "text", "flow", "target", "raw")

    def __init__(self, addr, length, text, flow="", target=None, raw=b""):
        self.addr, self.length, self.text, self.flow, self.target, self.raw = addr, length, text, flow, target, raw


def decode(opc, dat, pc, size):
    """Dekóduje instrukci na pc. Opkód (a prefixy) z `opc`, operandy z `dat`.
    flow: '' | 'jmp' | 'jcc' | 'call' | 'ccc' | 'ret' | 'rcc' | 'rst' | 'stop' (JP (HL), HALT)."""
    def op(i):
        return opc[(pc + i) % size]

    def arg(i):
        return dat[(pc + i) % size]

    def imm16(i):
        return arg(i) | (arg(i + 1) << 8)

    def rel(i):
        d = arg(i)
        return (pc + i + 1 + (d - 256 if d > 127 else d)) & 0xFFFF

    b = op(0)
    if b in (0xDD, 0xFD):
        ix = "IX" if b == 0xDD else "IY"
        b2 = op(1)
        if b2 == 0xCB:
            d = arg(2)
            o = arg(3)   # u DDCB je finální opkód načten jako operand (bez M1) -> z datového obrazu
            disp = f"{ix}{d - 256 if d > 127 else d:+d}"
            x, y, z = o >> 6, (o >> 3) & 7, o & 7
            if x == 0:
                t = f"{ROT[y]} ({disp})" + (f",{R8[z]}" if z != 6 else "")
            elif x == 1:
                t = f"BIT {y},({disp})"
            elif x == 2:
                t = f"RES {y},({disp})" + (f",{R8[z]}" if z != 6 else "")
            else:
                t = f"SET {y},({disp})" + (f",{R8[z]}" if z != 6 else "")
            return Insn(pc, 4, t)
        # prefix DD/FD: dekódovat jako základní instrukci s HL->IX, (HL)->(IX+d)
        inner = decode_base(op, arg, imm16, rel, pc, 1, ix)
        if inner is None:
            return Insn(pc, 1, f"DB {b:02X}h ; prefix {ix} bez efektu")
        return inner
    if b == 0xCB:
        o = op(1)
        x, y, z = o >> 6, (o >> 3) & 7, o & 7
        t = [f"{ROT[y]} {R8[z]}", f"BIT {y},{R8[z]}", f"RES {y},{R8[z]}", f"SET {y},{R8[z]}"][x]
        return Insn(pc, 2, t)
    if b == 0xED:
        o = op(1)
        x, y, z, p, q = o >> 6, (o >> 3) & 7, o & 7, (o >> 4) & 3, (o >> 3) & 1
        if x == 1:
            if z == 0:
                return Insn(pc, 2, f"IN {R8[y] if y != 6 else 'F'},(C)")
            if z == 1:
                return Insn(pc, 2, f"OUT (C),{R8[y] if y != 6 else '0'}")
            if z == 2:
                return Insn(pc, 2, f"{'ADC' if q else 'SBC'} HL,{RP[p]}")
            if z == 3:
                a = imm16(2)
                return Insn(pc, 4, f"LD ({{a16}}),{RP[p]}" if not q else f"LD {RP[p]},({{a16}})", target=a) if False else \
                    Insn(pc, 4, (f"LD (%s),{RP[p]}" if not q else f"LD {RP[p]},(%s)"), "", a)
            if z == 4:
                return Insn(pc, 2, "NEG")
            if z == 5:
                return Insn(pc, 2, "RETI" if y == 1 else "RETN", "ret")
            if z == 6:
                return Insn(pc, 2, f"IM {[0, 0, 1, 2, 0, 0, 1, 2][y]}")
            if z == 7:
                return Insn(pc, 2, ["LD I,A", "LD R,A", "LD A,I", "LD A,R", "RRD", "RLD", "NOP", "NOP"][y])
        if x == 2 and o in BLI:
            return Insn(pc, 2, BLI[o])
        return Insn(pc, 2, f"DB EDh,{o:02X}h ; NONI")
    r = decode_base(op, arg, imm16, rel, pc, 0, "HL")
    return r


def decode_base(op, arg, imm16, rel, pc, i, hl):
    """Základní tabulka (bez prefixu CB/ED). i = 1 pro DD/FD prefix (hl = 'IX'/'IY'); pak (HL) -> (IX+d).
    Vrací Insn; text s '%s' + target pro a16."""
    b = op(i)
    x, y, z, p, q = b >> 6, (b >> 3) & 7, b & 7, (b >> 4) & 3, (b >> 3) & 1
    pre = i  # délka prefixu
    ixd = (hl != "HL")

    def r8(n, k):
        """registr n; k = offset dalšího operandu (pro (IX+d))"""
        if n == 6 and ixd:
            d = arg(k)
            return f"({hl}{d - 256 if d > 127 else d:+d})", 1
        if n in (4, 5) and ixd:
            return hl[0] + ("H" if n == 4 else "L"), 0   # IXH/IXL (nedokumentované)
        return R8[n], 0

    def rp(n):
        return hl if n == 2 else RP[n]

    L = pre + 1
    if x == 0:
        if z == 0:
            if y == 0: return Insn(pc, L, "NOP")
            if y == 1: return Insn(pc, L, "EX AF,AF'")
            if y == 2: return Insn(pc, L + 1, "DJNZ %s", "jcc", rel(pre + 1))
            if y == 3: return Insn(pc, L + 1, "JR %s", "jmp", rel(pre + 1))
            return Insn(pc, L + 1, f"JR {CC[y - 4]},%s", "jcc", rel(pre + 1))
        if z == 1:
            if q == 0: return Insn(pc, L + 2, f"LD {rp(p)},%s", "", imm16(pre + 1))
            return Insn(pc, L, f"ADD {hl},{rp(p)}")
        if z == 2:
            if q == 0:
                if p == 0: return Insn(pc, L, "LD (BC),A")
                if p == 1: return Insn(pc, L, "LD (DE),A")
                if p == 2: return Insn(pc, L + 2, f"LD (%s),{hl}", "", imm16(pre + 1))
                return Insn(pc, L + 2, "LD (%s),A", "", imm16(pre + 1))
            if p == 0: return Insn(pc, L, "LD A,(BC)")
            if p == 1: return Insn(pc, L, "LD A,(DE)")
            if p == 2: return Insn(pc, L + 2, f"LD {hl},(%s)", "", imm16(pre + 1))
            return Insn(pc, L + 2, "LD A,(%s)", "", imm16(pre + 1))
        if z == 3:
            return Insn(pc, L, f"{'DEC' if q else 'INC'} {rp(p)}")
        if z in (4, 5):
            t, e = r8(y, pre + 1)
            return Insn(pc, L + e, f"{'INC' if z == 4 else 'DEC'} {t}")
        if z == 6:
            t, e = r8(y, pre + 1)
            return Insn(pc, L + e + 1, f"LD {t},{arg(pre + 1 + e):02X}h")
        return Insn(pc, L, ["RLCA", "RRCA", "RLA", "RRA", "DAA", "CPL", "SCF", "CCF"][y])
    if x == 1:
        if b == 0x76: return Insn(pc, L, "HALT", "stop")
        if y == 6 or z == 6:
            t1, e1 = r8(y, pre + 1)
            t2, e2 = r8(z, pre + 1)
            if y == 6 and ixd: t2 = R8[z]
            if z == 6 and ixd: t1 = R8[y]
            return Insn(pc, L + max(e1, e2), f"LD {t1},{t2}")   # oprava: posun d i u LD r,(IX+d)
        return Insn(pc, L, f"LD {r8(y, 0)[0]},{r8(z, 0)[0]}")
    if x == 2:
        t, e = r8(z, pre + 1)
        return Insn(pc, L + e, f"{ALU[y]}{t}")
    # x == 3
    if z == 0: return Insn(pc, L, f"RET {CC[y]}", "rcc")
    if z == 1:
        if q == 0: return Insn(pc, L, f"POP {hl if p == 2 else RP2[p]}")
        if p == 0: return Insn(pc, L, "RET", "ret")
        if p == 1: return Insn(pc, L, "EXX")
        if p == 2: return Insn(pc, L, f"JP ({hl})", "stop")
        return Insn(pc, L, f"LD SP,{hl}")
    if z == 2: return Insn(pc, L + 2, f"JP {CC[y]},%s", "jcc", imm16(pre + 1))
    if z == 3:
        if y == 0: return Insn(pc, L + 2, "JP %s", "jmp", imm16(pre + 1))
        if y == 1: return None  # CB prefix — řeší decode()
        if y == 2: return Insn(pc, L + 1, f"OUT ({arg(pre + 1):02X}h),A")
        if y == 3: return Insn(pc, L + 1, f"IN A,({arg(pre + 1):02X}h)")
        if y == 4: return Insn(pc, L, f"EX (SP),{hl}")
        if y == 5: return Insn(pc, L, "EX DE,HL")
        if y == 6: return Insn(pc, L, "DI")
        return Insn(pc, L, "EI")
    if z == 4: return Insn(pc, L + 2, f"CALL {CC[y]},%s", "ccc", imm16(pre + 1))
    if z == 5:
        if q == 0: return Insn(pc, L, f"PUSH {hl if p == 2 else RP2[p]}")
        if p == 0: return Insn(pc, L + 2, "CALL %s", "call", imm16(pre + 1))
        return None  # DD/ED/FD prefixy — řeší decode()
    if z == 6: return Insn(pc, L + 1, f"{ALU[y]}{arg(pre + 1):02X}h")
    return Insn(pc, L, f"RST {y * 8:02X}h", "rst", y * 8)


# ---- načtení ------------------------------------------------------------------------------------
def load_image():
    """Slepí program z ROM sad do jednoho obrazu 0000h-1FFFh."""
    buf = bytearray(SIZE)
    for name, off in PROGRAM_FILES:
        path = os.path.join(ROM_DIR, name)
        if not os.path.exists(path):
            sys.exit("Chybí %s — ROM set viz sources/rom/README.md" % path)
        data = open(path, "rb").read()
        buf[off:off + len(data)] = data
    return bytes(buf)


def load_coverage(path):
    """Adresy, které se v trasovacím emulátoru opravdu vykonaly."""
    hit = set()
    if not path:
        return hit
    if not os.path.exists(path):
        sys.exit("Chybí %s — spusť tools/dis/trace-cheekyms.py --cov" % path)
    for ln in open(path, encoding="utf-8"):
        ln = ln.split(";", 1)[0].strip()
        if not ln:
            continue
        tok = ln.split()[0].rstrip(":")
        try:
            a = int(tok, 16)
        except ValueError:
            continue
        if 0 <= a < SIZE:
            hit.add(a)
    return hit


def load_hints(path):
    h = {"code": set(), "data": [], "label": {}, "comment": {}, "ram": {}, "ptrs": []}
    if not path or not os.path.exists(path):
        return h
    for ln in open(path, encoding="utf-8"):
        ln = ln.split(";", 1)[0].strip()
        if not ln:
            continue
        parts = ln.split(None, 2)
        kind = parts[0]
        if kind == "code":
            h["code"].add(int(parts[1], 0))
        elif kind == "data":
            rest = (parts[1] + " " + (parts[2] if len(parts) > 2 else "")).split()
            h["data"].append((int(rest[0], 0), int(rest[1], 0)))
        elif kind in ("label", "ram"):
            h[kind][int(parts[1], 0)] = parts[2].strip()
        elif kind == "comment":
            h["comment"][int(parts[1], 0)] = parts[2]
        elif kind == "ptrs":
            rest = parts[2].split()
            a, b = int(rest[0], 0), int(rest[1], 0)
            step = int(rest[3], 0) if len(rest) >= 4 and rest[2] == "step" else 2
            h["ptrs"].append((parts[1], a, b, step))
    return h


# ---- analýza toku -------------------------------------------------------------------------------
def analyze(opc, dat, size, hints, vectors):
    is_code = bytearray(size)      # 1 = začátek instrukce, 2 = pokračování
    forced = bytearray(size)
    for a, b in hints["data"]:
        for x in range(a, min(b, size - 1) + 1):
            forced[x] = 1
    targets = defaultdict(set)
    subs = set()
    insns = {}
    work = list(vectors) + sorted(hints["code"])
    for order, a, b, step in hints["ptrs"]:
        for x in range(a, b + 1 - 1, step):
            forced[x] = forced[x + 1] = 1
            t = (dat[x] | dat[x + 1] << 8) if order == "lohi" else (dat[x] << 8 | dat[x + 1])
            if 0 < t < size:
                targets[t].add((x, "ptr"))
                work.append(t)
    while work:
        pc = work.pop()
        while 0 <= pc < size and not is_code[pc] and not forced[pc]:
            if pc >= 0x80 and opc[pc] in (0x00, 0xFF) and opc[pc:pc + 32] == bytes([opc[pc]]) * 32:
                break   # výplň (>= 32 shodných bajtů; kratší NOP sledy jsou průchozí kód)
            ins = decode(opc, dat, pc, size)
            if pc + ins.length > size:
                break
            insns[pc] = ins
            is_code[pc] = 1
            for k in range(1, ins.length):
                is_code[pc + k] = 2
            if ins.flow in ("jmp", "jcc", "call", "ccc", "rst") and ins.target is not None:
                t = ins.target
                targets[t].add((pc, ins.flow))
                if ins.flow in ("call", "ccc", "rst"):
                    subs.add(t)
                if t < size:
                    work.append(t)
            pc += ins.length
            if ins.flow in ("jmp", "ret", "stop"):
                break
    return is_code, targets, subs, insns


# ---- výstup -------------------------------------------------------------------------------------
def hw_symbol(addr):
    for lo, hi, sym, _ in HW:
        if lo <= addr <= hi:
            return sym if addr == lo else "%s+%X" % (sym, addr - lo)
    return None


def port_names(text):
    """Nahradí čísla portů symboly: OUT (40h),A -> OUT (SOUND),A."""
    def out(m):
        p = int(m.group(1), 16)
        return "OUT (%s)," % (PORTS_OUT[p][0] if p in PORTS_OUT else m.group(1) + "h")
    def inp(m):
        p = int(m.group(2), 16)
        return "IN %s,(%s)" % (m.group(1), PORTS_IN[p][0] if p in PORTS_IN else m.group(2) + "h")
    text = re.sub(r"OUT \(([0-9A-F]{2})h\),", out, text)
    text = re.sub(r"IN (\w+),\(([0-9A-F]{2})h\)", inp, text)
    return text


def emit(rom, is_code, targets, subs, insns, hints, covered, out):
    labels = {}
    for t in targets:
        if t >= SIZE:
            continue
        labels[t] = hints["label"].get(t, "S_%04X" % t if t in subs else "L_%04X" % t)
    for a, n in hints["label"].items():
        labels.setdefault(a, n)

    def sym(v, is_addr):
        if v in labels:
            return labels[v]
        if v in hints["ram"]:
            return hints["ram"][v]
        s = hw_symbol(v)
        if s and (is_addr or v >= 0x3000):
            return s
        return "%04Xh" % v

    ncode = sum(1 for x in is_code if x)
    w = out.write
    w("; %s\n" % TITLE)
    w("; Vygenerováno tools/dis/disz80.py; pokrytí kódem %d/%d B (%.1f %%)\n" % (ncode, SIZE, 100.0 * ncode / SIZE))
    if covered:
        w("; Vstupní body doplněné z běhu originálu (--cov): %d adres\n" % len(covered))
    w(";\n; Mapa paměti (sources/mame/cheekyms.cpp):\n")
    for lo, hi, s, desc in HW:
        w(";   %04X-%04X  %-8s %s\n" % (lo, hi, s, desc))
    w(";\n; Porty:\n")
    for p, (s, desc) in sorted(PORTS_IN.items()):
        w(";   IN  %02X  %-8s %s\n" % (p, s, desc))
    for p, (s, desc) in sorted(PORTS_OUT.items()):
        w(";   OUT %02X  %-8s %s\n" % (p, s, desc))
    w("\n")
    for a, n in sorted(hints["ram"].items()):
        w("%-24s EQU %04Xh\n" % (n, a))
    for lo, hi, s, _ in HW:
        w("%-24s EQU %04Xh\n" % (s, lo))
    w("\n\tORG 0000h\n\n")
    pc = 0
    while pc < SIZE:
        if pc in labels:
            refs = sorted(a for a, _ in targets.get(pc, ()))
            kinds = {k for _, k in targets.get(pc, ())}
            w("\n")
            head = []
            if "ptr" in kinds:
                head.append("z tabulky ukazatelů")
            if "cov" in kinds:
                head.append("vykonáno v běhu")
            if refs:
                head.append("xref: " + ", ".join("%04X" % a for a in refs))
            if head:
                w("; " + " ".join(head) + "\n")
            w("%s:\n" % labels[pc])
        if pc in hints["comment"]:
            w("; %s\n" % hints["comment"][pc])
        if is_code[pc] == 1:
            ins = insns[pc]
            raw = " ".join("%02X" % rom[pc + k] for k in range(ins.length))
            text = ins.text
            if "%s" in text:
                text = text % sym(ins.target, ins.flow != "" or text.startswith("LD (") or "),(" in text or text.endswith("(%s)"))
            w("%04X  %-12s \t%s\n" % (pc, raw, port_names(text)))
            pc += ins.length
            if ins.flow in ("jmp", "ret", "stop"):
                w("\n")
        else:
            start = pc
            pc += 1
            while pc < SIZE and is_code[pc] == 0 and pc not in labels and pc not in hints["comment"] and pc - start < 16:
                pc += 1
            chunk = rom[start:pc]
            hexs = ",".join("%02Xh" % b for b in chunk)
            asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            w("%04X  \tDB %-80s ; %s\n" % (start, hexs, asc))
    w("\n\tEND\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hints", default=os.path.join(ROOT, "sources/asm/hints.txt"))
    ap.add_argument("--out", default=os.path.join(ROOT, "sources/asm/cheekyms.asm"))
    ap.add_argument("--cov", help="pokrytí z tools/dis/trace-cheekyms.py --cov")
    a = ap.parse_args()
    rom = load_image()
    hints = load_hints(a.hints)
    covered = load_coverage(a.cov)
    is_code, targets, subs, insns = analyze(rom, rom, SIZE, hints, VECTORS + sorted(covered))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        emit(rom, is_code, targets, subs, insns, hints, covered, f)
    ncode = sum(1 for x in is_code if x)
    print("%s: kód %d B (%.1f %%), návěští %d, podprogramů %d, instrukcí %d"
          % (a.out, ncode, 100.0 * ncode / SIZE, len(targets), len(subs), len(insns)))


if __name__ == "__main__":
    main()
