# SC8P052 ICSP Programming Protocol
## Reverse Engineering Results with Evidence

### Overview

This document details the ICSP (In-Circuit Serial Programming) protocol for the Cmsemicon SC8P052 OTP microcontroller, derived from reverse engineering the Writer8_lite firmware and related software.

---

## 1. VPP Entry Voltage

**Source:** `mcu/ini/SC8P052.ini`

| Parameter | Value | Description |
|-----------|-------|-------------|
| VPPPROG | 15.5V | Programming voltage |
| VPPERASE | 15.5V | Erase voltage |
| VPPREAD | 12V | Read/verify voltage |
| VPPKEEP | 12V | Maintain voltage |
| VPPMODE | 89 | Protocol mode identifier |
| VPPSEL | 100 | Voltage selection |

**Conclusion:** Use **12V** for read operations, **15.5V** for programming.

---

## 2. ICSP Protocol

### 2.1 Entry Sequence

**Evidence:** `Writer8LiteGhidra/Writer8_lite.c` lines 4927-4945

```c
// Lines 4927-4930
FUN_00003e7c(0x9b);
FUN_00003e7c(0x29);
FUN_00003e7c(100);  // 0x64
FUN_00003e7c(0xd6);
// Line 4945
FUN_000005e0(0x1e);  // 30ms delay
```

**Entry Key:** `0x9B, 0x29, 0x64, 0xD6`

**Sequence:**
1. Set DAT and CLK low
2. Apply VDD (3.3V)
3. Apply VPP (12V for read, 15.5V for program)
4. Send entry key bytes (LSB first per byte)
5. Wait 30ms

### 2.2 Command Set

**Evidence:** Function calls throughout `Writer8_lite.c`

| Command | Hex | Function | Evidence Location |
|---------|-----|----------|-------------------|
| **SETUP** | **0x23** | **Area selection (CRITICAL)** | **FUN_0000b4b4:12177-12182** |
| Reset Address | 0x1C | Reset address counter to 0 | Lines 3160, 3237, 3606 |
| Increment | 0x5C | Increment address by 1 | Lines 3167, 3245, 3611 |
| Read Data | 0x63 | Read word at current address | FUN_0000779c:8391 |
| Load Data | 0x6A | Load word to programming latch | FUN_0000b404:12080 |
| Begin Prog | 0x55 | Execute programming pulse | FUN_00008010:9047 |
| Load Alt | 0x4E | Alternate load data | Lines 3622, 3704 |
| Config Write | 0x71 | Write to config area | Lines 3807, 4019 |

### 2.2.1 SETUP Command (0x23) - Area Selection

**CRITICAL DISCOVERY:** The SETUP command must be sent before any ROM or Config operations!

**Evidence:** `FUN_0000b4b4` at lines 12177-12182:
```c
void FUN_0000b4b4(undefined4 param_1) {
  FUN_00003e7c(0x23);           // Send SETUP command (8 bits)
  FUN_00003f48(param_1,0x10);   // Send area mask (16 bits)
}
```

**Area Mask Values:**

| Mask | Hex | Purpose | Evidence |
|------|-----|---------|----------|
| ROM_READ | 0x8000 | Select ROM for reading | Line 8289, 8015 |
| ROM_WRITE | 0x8000 | Select ROM for writing | Line 3794, 3835 |
| CONFIG_READ | 0xC000 | Select Config for reading | Line 9919 |
| CONFIG_WRITE | 0xC004 | Select Config for writing | Lines 5738, 5966, 11909, 12399 |

**Usage Pattern (observed throughout firmware):**
```
1. SETUP (0x23) + area_mask (16 bits LSB first)
2. RESET_ADDR (0x1C)
3. ... perform read/write operations ...
```

**Erase Sequence (FUN_00003df8, lines 5085-5089):**
```
0xF8 → 30ms delay → 0xB1 → 10ms delay → 0x78 → 10ms delay
```

### 2.3 Bit Order

**Command/Data Write = LSB First**

**Evidence:** `FUN_00003f48` at lines 5190-5204
```c
void FUN_00003f48(uint param_1, char param_2)
{
  do {
    _DAT_40010c14 = 0x80;           // CLK low
    _DAT_42218190 = param_1;        // Set data bit (LSB)
    FUN_000005c8(0x21);             // Delay
    _DAT_40010c10 = 0x80;           // CLK high
    FUN_000005c8(0x21);             // Delay
    param_2 = param_2 + -1;
    param_1 = param_1 >> 1;         // *** LSB FIRST: shift RIGHT ***
  } while (param_2 != '\0');
}
```

**Data Read = MSB First**

**Evidence:** `FUN_00003ca4` at lines 5002-5024
```c
uint FUN_00003ca4(void)
{
  local_28 = 0;
  bVar1 = 0;
  do {
    _DAT_40010c14 = 0x80;           // CLK low
    FUN_000005c8(0x21);             // Delay
    // Read bit and shift LEFT (MSB first)
    local_28 = (uint)(_DAT_40010c08 << 0x1a) >> 0x1f | (local_28 & 0x7fff) << 1;
    _DAT_40010c10 = 0x80;           // CLK high
    FUN_000005c8(0x21);             // Delay
    bVar1 = bVar1 + 1;
  } while (bVar1 < 0x10);
  return local_28;
}
```

### 2.4 Timing Parameters

**Source:** `SC8P052.ini` and firmware analysis

| Parameter | Value | Evidence |
|-----------|-------|----------|
| PROGTIME | 200µs | SC8P052.ini line 24 |
| Entry delay | 30ms | Line 4945: FUN_000005e0(0x1e) |
| Prog timeout | 30ms | FUN_00008010 param 0x1e |
| Bit delay | 33 cycles | FUN_000005c8(0x21) |
| Fast delay | 2 cycles | FUN_000005c8(2) |
| ERASECONFIG | 100 | SC8P052.ini |
| ERASEROM | 100 | SC8P052.ini |

---

## 3. Configuration Words

**Source:** `SC8P052.ini` and captured session log

- **CONFIGLENTH=2** (2 active config words)
- **HEXMCU=3FFF** (blank value = 0x3FFF)

**Captured config data:** `0xFEE6, 0xFFFF, 0xFFFF` (6 bytes)

**Config bits from example code:**
```c
#pragma config FOSC = INTRC_NOCLKOUT  // Internal oscillator
#pragma config WDTE = OFF             // Watchdog off
#pragma config PWRTE = ON             // Power-up timer on
#pragma config MCLRE = ON             // MCLR enabled
#pragma config CP = OFF               // Code protect off
#pragma config BOREN = OFF            // Brown-out off
```

Result: `0xFEE6` = 1111 1110 1110 0110 (14-bit)

---

## 4. Memory Map

**Source:** Database and INI file

| Parameter | Value | Source |
|-----------|-------|--------|
| ROM Size | 1024 words | MCU_ROM_SIZE |
| EEPROM Size | 0 | MCU_EEPROM_SIZE |
| Word Width | 14 bits | ARCH=CMS89 |
| CRAFTS | OTP | One-Time Programmable |
| ROM_START_ADDR | 0 | Database |

---

## 5. Pin Configuration

**Source:** Database MCU table

| Pin | Name | ICSP Function | Database Field |
|-----|------|---------------|----------------|
| 1 | PA0 | ICSPDAT (Data) | MCU_PINDAT=1 |
| 2 | VSS | GND | MCU_PINGND=2 |
| 3 | PA1 | ICSPCLK (Clock) | MCU_PINCLK=3 |
| 4 | PA2 | VPP/MCLR | (HV Entry) |
| 5 | VDD | Power (3.3V) | MCU_PINVCC=5 |
| 6 | PA3 | NC | MCU_PINNUM=6 |

---

## 6. Programming Sequence

### Read ROM Operation
```
1. Enter programming mode (VPP=12V)
2. SETUP (0x23) + 0x8000 (16 bits) ← SELECT ROM AREA
3. Send RESET_ADDR (0x1C)
4. For each address:
   a. Send READ_DATA (0x63)
   b. Read 16 bits MSB first
   c. Mask to 14 bits
   d. Send INCREMENT (0x5C)
5. Exit programming mode
```

### Write ROM Operation
```
1. Enter programming mode (VPP=15.5V)
2. SETUP (0x23) + 0x8000 (16 bits) ← SELECT ROM AREA
3. Send RESET_ADDR (0x1C)
4. For each address:
   a. Send LOAD_DATA (0x6A)
   b. Send 16-bit data LSB first
   c. Send BEGIN_PROG (0x55)
   d. Wait for completion (200µs + timeout)
   e. Send INCREMENT (0x5C)
5. Exit programming mode
```

### Read Config Operation
```
1. Enter programming mode (VPP=12V)
2. SETUP (0x23) + 0xC000 (16 bits) ← SELECT CONFIG AREA
3. Send RESET_ADDR (0x1C)
4. For each config word:
   a. Send READ_DATA (0x63)
   b. Read 16 bits MSB first
   c. Mask to 14 bits
   d. Send INCREMENT (0x5C)
5. Exit programming mode
```

### Write Config Operation
```
1. Enter programming mode (VPP=15.5V)
2. SETUP (0x23) + 0xC004 (16 bits) ← SELECT CONFIG AREA FOR WRITE
3. Send RESET_ADDR (0x1C)
4. For each config word:
   a. Send LOAD_DATA (0x6A)
   b. Send 16-bit data LSB first
   c. Send BEGIN_PROG (0x55)
   d. Wait for completion (200µs + timeout)
   e. Send INCREMENT (0x5C)
5. Exit programming mode
```

### Verify Operation
```
1. Enter programming mode (VPP=12V)
2. SETUP (0x23) + 0x8000 ← SELECT ROM AREA
3. Read all programmed locations
4. Compare with expected data
5. Exit programming mode
```

---

## 7. USB Protocol (PC ↔ Writer Hardware)

**Source:** `Global.cs` and `AgentKnowledge.txt`

| Code | Name | Function |
|------|------|----------|
| 0x02 | CMD_READ_VERSION | Read writer version |
| 0x50 | CMD_END_WORK | End session |
| 0x51 | CMD_SEND_MCUTYPE | Set MCU type |
| 0x60 | CMD_DOWNLOAD_VERIFY | Verify with CRC |
| 0x61 | CMD_DOWNLOAD_OPTION1 | Send MCU info |
| 0x63 | CMD_DOWNLOAD_DATA | Send ROM data |
| 0x64 | CMD_DOWNLOAD_CONFIG | Send config |
| 0x65 | CMD_DOWNLOAD_EEDATA | Send EEPROM |

**Packet Format (64 bytes):**
- Byte 0: Length
- Bytes 1-61: Command + Data (XOR encrypted)
- Byte 62: Checksum
- Byte 63: XOR key

---

## 8. Files Created

| File | Purpose |
|------|---------|
| `sc8p052_programmer.py` | Full-featured programmer with evidence documentation |
| `sc8p052_verify_connection.py` | Minimal verification script for testing |
| `SC8P052_ICSP_Protocol.md` | This documentation |

---

## 9. Minimal Verification Test

To verify your hardware is working:

1. Connect SC8P052 to your programmer
2. Run `sc8p052_verify_connection.py`
3. Expected results:
   - Blank chip: All reads return 0x3FFF
   - Programmed chip: Address 0 contains reset vector (GOTO instruction)
   - Error: Reads return 0x0000 or 0xFFFF

**Complete Test Sequence:**
```
1. Power sequence: VDD ON → VPP ON (12V)
2. Send entry key: 0x9B, 0x29, 0x64, 0xD6 (LSB first)
3. Wait 30ms
4. SETUP (0x23) + 0x8000 (select ROM)
5. RESET_ADDR (0x1C)
6. READ_DATA (0x63) → read 16 bits MSB first
7. If result = 0x3FFF → blank chip (SUCCESS)
8. If result = 0x0000 or 0xFFFF → connection error
9. If result = 0x2xxx → programmed chip with GOTO instruction
```

**Reset Vector Decoding:**
- If bits 13-11 = 0b101 (5), it's a GOTO instruction
- Bits 10-0 = target address

Example: `0x2BFE` = `10 101 11111110` = GOTO 0x3FE (jump to main code)

**Troubleshooting:**
- 0x0000: Data line stuck low or no power
- 0xFFFF/0x3FFF constantly: Check if VPP is reaching 12V
- Random garbage: Check clock timing, try slower bit delays
- Timeout: Entry sequence failed, verify entry key bytes

---

## 10. References

- `Writer8LiteGhidra/Writer8_lite.c` - Decompiled firmware
- `mcu/ini/SC8P052.ini` - MCU configuration
- `SCMCU_Writer_V9.01.15/library/WriterCoreDLLCode/` - DLL source
- `query_database_output.txt` - Database dump
- `AgentKnowledge.txt` - Captured session logs


  PCB Design - Component List & Connections

  Core Components
  ┌──────────────────┬───────────────────────────┬─────────────────────┐
  │    Component     │           Part            │       Purpose       │
  ├──────────────────┼───────────────────────────┼─────────────────────┤
  │ MCU              │ ATmega328P (or STM32F103) │ Protocol controller │
  ├──────────────────┼───────────────────────────┼─────────────────────┤
  │ USB-UART         │ CH340G or CP2102          │ PC communication    │
  ├──────────────────┼───────────────────────────┼─────────────────────┤
  │ 6-pin ZIF Socket │ 6-pin DIP ZIF             │ SC8P052 holder      │
  ├──────────────────┼───────────────────────────┼─────────────────────┤
  │ Crystal          │ 16MHz + 2x 22pF caps      │ MCU clock           │
  └──────────────────┴───────────────────────────┴─────────────────────┘
  Power Supply
  ┌────────────────┬────────────────┬────────────────────┐
  │   Component    │      Part      │      Purpose       │
  ├────────────────┼────────────────┼────────────────────┤
  │ USB Connector  │ USB-B or USB-C │ Power + data input │
  ├────────────────┼────────────────┼────────────────────┤
  │ 3.3V Regulator │ AMS1117-3.3    │ VDD for SC8P052    │
  ├────────────────┼────────────────┼────────────────────┤
  │ 5V from USB    │ -              │ MCU power          │
  ├────────────────┼────────────────┼────────────────────┤
  │ Filter caps    │ 100nF + 10µF   │ Decoupling         │
  └────────────────┴────────────────┴────────────────────┘
  High Voltage Generation (VPP = 15.5V)
  ┌─────────────────┬─────────────────────────────────┬────────────────────────┐
  │    Component    │              Part               │        Purpose         │
  ├─────────────────┼─────────────────────────────────┼────────────────────────┤
  │ Boost Converter │ MT3608 module or MC34063        │ 5V → 18V boost         │
  ├─────────────────┼─────────────────────────────────┼────────────────────────┤
  │ Voltage Divider │ Resistors to set 15.5V          │ Feedback for regulator │
  ├─────────────────┼─────────────────────────────────┼────────────────────────┤
  │ HV Switch       │ BSS138 + 2N7002 or Si2301 P-FET │ Control VPP on/off     │
  ├─────────────────┼─────────────────────────────────┼────────────────────────┤
  │ Zener Diode     │ 16V zener                       │ Overvoltage protection │
  ├─────────────────┼─────────────────────────────────┼────────────────────────┤
  │ Filter caps     │ 10µF + 100nF                    │ Smooth VPP             │
  └─────────────────┴─────────────────────────────────┴────────────────────────┘
  Signal Level Shifting (5V MCU ↔ 3.3V SC8P052)
  ┌───────────────┬──────────────────────┬─────────────────────┐
  │   Component   │         Part         │       Purpose       │
  ├───────────────┼──────────────────────┼─────────────────────┤
  │ Level Shifter │ TXS0102 or 2x BSS138 │ DAT/CLK 5V↔3.3V     │
  ├───────────────┼──────────────────────┼─────────────────────┤
  │ Pull-ups      │ 10kΩ                 │ For BSS138 shifters │
  └───────────────┴──────────────────────┴─────────────────────┘
  Control & Protection
  ┌────────────────┬────────────────┬───────────────────┐
  │   Component    │      Part      │      Purpose      │
  ├────────────────┼────────────────┼───────────────────┤
  │ VDD Switch     │ Si2301 P-FET   │ MCU controls VDD  │
  ├────────────────┼────────────────┼───────────────────┤
  │ Status LEDs    │ 2x LED + 330Ω  │ Power/Activity    │
  ├────────────────┼────────────────┼───────────────────┤
  │ Reset Button   │ Tactile switch │ MCU reset         │
  ├────────────────┼────────────────┼───────────────────┤
  │ ESD Protection │ TVS diodes     │ Socket protection │
  └────────────────┴────────────────┴───────────────────┘
  ---
  Block Diagram

                      +5V USB
                         │
           ┌─────────────┼─────────────┐
           │             │             │
           ▼             ▼             ▼
      ┌─────────┐   ┌─────────┐   ┌─────────┐
      │ CH340G  │   │AMS1117  │   │ MT3608  │
      │USB-UART │   │  3.3V   │   │ Boost   │
      └────┬────┘   └────┬────┘   └────┬────┘
           │             │             │
        TX/RX          3.3V          15.5V
           │             │             │
           ▼             │             │
      ┌─────────┐        │             │
      │ATmega328│        │             │
      │         │        │             │
      │  PD0◄───┼── RX   │             │
      │  PD1────┼── TX   │             │
      │         │        │             │
      │  PB0────┼────────┼──►VDD_EN (P-FET gate)
      │  PB1────┼────────┼─────────────┼──►VPP_EN (P-FET gate)
      │         │        │             │
      │  PD2────┼──►Level├──►ICSPDAT───┼──►Pin 1
      │  PD3────┼──►Shift├──►ICSPCLK───┼──►Pin 3
      └─────────┘        │             │
                         │             │
                         ▼             ▼
                   ┌─────────────────────────┐
                   │    6-Pin ZIF Socket     │
                   │                         │
                   │  Pin 1: DAT ◄──Level    │
                   │  Pin 2: GND             │
                   │  Pin 3: CLK ◄──Level    │
                   │  Pin 4: VPP ◄──15.5V SW │
                   │  Pin 5: VDD ◄──3.3V SW  │
                   │  Pin 6: NC              │
                   └─────────────────────────┘

  ---
  Key Connections Summary

  1. USB → CH340G → ATmega328P (UART at 115200 baud)
  2. ATmega GPIO:
    - PD2 → Level Shifter → ICSPDAT (Pin 1)
    - PD3 → Level Shifter → ICSPCLK (Pin 3)
    - PB0 → P-FET Gate → Controls 3.3V to VDD (Pin 5)
    - PB1 → P-FET Gate → Controls 15.5V to VPP (Pin 4)
  3. Power Path:
    - USB 5V → AMS1117 → 3.3V → P-FET → SC8P052 VDD
    - USB 5V → MT3608 → 15.5V → P-FET → SC8P052 VPP
  4. Protection:
    - TVS diodes on socket pins
    - Zener on VPP line
    - Reverse polarity protection on USB

  ---
  Bill of Materials (Approximate)
  ┌─────┬──────────────────────┬─────────────────────────┐
  │ Qty │      Component       │          Notes          │
  ├─────┼──────────────────────┼─────────────────────────┤
  │ 1   │ ATmega328P-PU (DIP)  │ Or SMD version          │
  ├─────┼──────────────────────┼─────────────────────────┤
  │ 1   │ CH340G               │ USB-UART                │
  ├─────┼──────────────────────┼─────────────────────────┤
  │ 1   │ 16MHz Crystal        │ + 2x 22pF               │
  ├─────┼──────────────────────┼─────────────────────────┤
  │ 1   │ AMS1117-3.3          │ 3.3V LDO                │
  ├─────┼──────────────────────┼─────────────────────────┤
  │ 1   │ MT3608 module        │ Or build discrete boost │
  ├─────┼──────────────────────┼─────────────────────────┤
  │ 2   │ Si2301 P-FET         │ VDD/VPP switches        │
  ├─────┼──────────────────────┼─────────────────────────┤
  │ 2   │ BSS138 N-FET         │ Level shifter           │
  ├─────┼──────────────────────┼─────────────────────────┤
  │ 4   │ 10kΩ resistors       │ Pull-ups                │
  ├─────┼──────────────────────┼─────────────────────────┤
  │ 1   │ 6-pin DIP ZIF socket │ For SC8P052             │
  ├─────┼──────────────────────┼─────────────────────────┤
  │ 1   │ USB-B connector      │ Power + data            │
  ├─────┼──────────────────────┼─────────────────────────┤
  │ -   │ Caps (100nF, 10µF)   │ Decoupling              │
  ├─────┼──────────────────────┼─────────────────────────┤
  │ 2   │ LEDs + 330Ω          │ Status                  │
  ├─────┼──────────────────────┼─────────────────────────┤
  │ 1   │ 16V Zener            │ VPP protection          │
  └─────┴──────────────────────┴─────────────────────────┘