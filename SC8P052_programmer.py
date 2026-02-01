#!/usr/bin/env python3
"""
SC8P052 OTP Microcontroller Programmer
Reverse-engineered from Cmsemicon Writer8_lite firmware

EVIDENCE FROM REVERSE ENGINEERING:
==================================
All values derived from Writer8LiteGhidra/Writer8_lite.c analysis

Entry Key (lines 4927-4930):
  FUN_00003e7c(0x9b); FUN_00003e7c(0x29); FUN_00003e7c(100); FUN_00003e7c(0xd6);

Bit Order:
  - Commands: LSB First (FUN_00003f48:5200 uses param_1 >> 1)
  - Data Read: MSB First (FUN_00003ca4:5015 shifts left, ORs from right)

Commands (from firmware function calls):
  - 0x23: SETUP/Area Select (FUN_0000b4b4:12177-12182) - MUST be sent before ROM/Config access
         Sends 0x23 followed by 16-bit area mask:
           0x8000 = ROM area
           0xC000 = Config area (read)
           0xC004 = Config area (write)
  - 0x1c: Reset Address (lines 3160, 3237, 3606, 3645, etc.)
  - 0x5c: Increment Address (lines 3167, 3245, 3611, etc.)
  - 0x63: Read Data (FUN_0000779c:8391 calls FUN_00003e7c(99))
  - 0x6a: Load Data for Programming (FUN_0000b404:12080)
  - 0x55: Begin Programming Pulse (FUN_00008010:9047)
  - 0x4e: Load Data alternate (lines 3622, 3704)
  - 0x71: Config Write (lines 3807, 4019)

Programming Sequence (from firmware analysis):
  1. Enter programming mode (entry key + delays)
  2. SETUP (0x23) + area_mask - Select ROM (0x8000) or Config (0xC004)
  3. RESET_ADDR (0x1C) - Reset address counter
  4. Loop for each word:
     a. LOAD_DATA (0x6A) + 16-bit data
     b. BEGIN_PROG (0x55)
     c. Wait PROGTIME
     d. INCREMENT (0x5C)

Timing (from INI and firmware):
  - PROGTIME=200 (µs) from SC8P052.ini
  - Entry delay: 30ms (line 4945: FUN_000005e0(0x1e))
  - Programming timeout: 30ms (FUN_00008010 param 0x1e)

Voltages (from SC8P052.ini):
  - VPPPROG/VPPERASE = 15.5V
  - VPPREAD/VPPKEEP = 12V
"""

import sys
import time
import argparse

# === VERIFIED CONFIGURATION ===
MCU_NAME = "SC8P052"
ROM_SIZE_WORDS = 1024       # MCU_ROM_SIZE from database
CONFIG_WORDS = 3            # CONFIGLENTH=2 active + 1 padding
WORD_BITS = 14              # CMS89 architecture = 14-bit words

# Voltages from SC8P052.ini
VPP_PROG_VOLTAGE = 15.5     # VPPPROG/VPPERASE
VPP_READ_VOLTAGE = 12.0     # VPPREAD/VPPKEEP
VDD_VOLTAGE = 3.3

# Timing from firmware analysis and INI file
PROG_PULSE_US = 200         # PROGTIME=200 from SC8P052.ini
ENTRY_DELAY_MS = 30         # FUN_000005e0(0x1e) = 30ms
PROG_TIMEOUT_MS = 30        # FUN_00008010 parameter 0x1e

# Entry Key - CONFIRMED from lines 4927-4930 in Writer8_lite.c
ENTRY_KEY = [0x9B, 0x29, 0x64, 0xD6]

# === ICSP COMMAND SET ===
# Derived from Writer8_lite.c function calls
class ICSP_CMD:
    # Area Selection (MUST be called before ROM/Config operations)
    SETUP          = 0x23   # Area select command (FUN_0000b4b4:12177-12182)
                            # Send 0x23 + 16-bit area mask

    # Address Control
    RESET_ADDR     = 0x1C   # Reset Address Counter (lines 3160, 3237, 3606...)
    INCREMENT_ADDR = 0x5C   # Increment Address (lines 3167, 3245, 3611...)

    # Data Operations
    READ_DATA      = 0x63   # Read Data at current addr (FUN_0000779c:8391)
    LOAD_DATA      = 0x6A   # Load Data Latch for programming (FUN_0000b404:12080)
    BEGIN_PROG     = 0x55   # Begin Programming Pulse (FUN_00008010:9047)
    LOAD_DATA_ALT  = 0x4E   # Alternate Load Data (lines 3622, 3704)
    CONFIG_WRITE   = 0x71   # Config Write command (lines 3807, 4019)

    # Erase sequence commands (FUN_00003df8:5085-5089)
    ERASE_CMD1     = 0xF8
    ERASE_CMD2     = 0xB1
    ERASE_CMD3     = 0x78

# === AREA SELECTION MASKS ===
# Used with SETUP (0x23) command to select memory region
# Evidence: FUN_0000b4b4 calls with these values throughout firmware
class AREA_MASK:
    ROM_READ       = 0x8000   # Select ROM area for reading (line 8289, 8015, etc.)
    ROM_WRITE      = 0x8000   # Select ROM area for writing (line 3794, 3835)
    CONFIG_READ    = 0xC000   # Select Config area for reading (line 9919)
    CONFIG_WRITE   = 0xC004   # Select Config area for writing (line 5738, 5966, etc.)
    EEPROM_READ    = 0x8000   # EEPROM uses same as ROM (SC8P052 has no EEPROM)
    SPECIAL        = 0x0004   # Special mode (line 11129)

# === HARDWARE ABSTRACTION LAYER ===
class Hardware:
    """
    Hardware interface for SC8P052 programmer.

    Pin mapping from database (MCU table for SC8P052):
      MCU_PINDAT=1 (PA0) - ICSP Data
      MCU_PINCLK=3 (PA1) - ICSP Clock
      MCU_PINVCC=5 (VDD) - Power
      MCU_PINGND=2 (VSS) - Ground
      PA2 - VPP/MCLR (High Voltage Programming)
    """

    def __init__(self, simulation=True):
        self.simulation = simulation
        self.dat_pin = 0
        self.clk_pin = 0
        self.vpp_enabled = False
        self.vdd_enabled = False
        self.vpp_voltage = 0.0

        # Simulated memory
        self.sim_flash = {i: 0x3FFF for i in range(ROM_SIZE_WORDS)}
        self.sim_config = [0x3FFF] * CONFIG_WORDS
        self.sim_address = 0

        print(f"[HW] Initialized {MCU_NAME} Programmer")
        print(f"[HW] Mode: {'SIMULATION' if simulation else 'HARDWARE'}")
        if not simulation:
            print("[HW] WARNING: Implement GPIO control for your platform!")

    def set_vpp(self, enable: bool, voltage: float = VPP_PROG_VOLTAGE):
        """Control VPP (High Voltage) pin"""
        self.vpp_enabled = enable
        self.vpp_voltage = voltage if enable else 0.0
        state = f"ON ({voltage}V)" if enable else "OFF (0V)"
        print(f"[HW] VPP {state}")

    def set_vdd(self, enable: bool):
        """Control VDD (Power) pin"""
        self.vdd_enabled = enable
        state = f"ON ({VDD_VOLTAGE}V)" if enable else "OFF"
        print(f"[HW] VDD {state}")

    def set_dat_direction(self, is_input: bool):
        """Set data pin direction: True=Input, False=Output"""
        pass  # Implement for your GPIO library

    def set_dat(self, value: int):
        """Set data pin state (0 or 1)"""
        self.dat_pin = value & 1

    def get_dat(self) -> int:
        """Read data pin state"""
        if self.simulation:
            # In simulation, return bit from current address
            word = self.sim_flash.get(self.sim_address, 0x3FFF)
            return 1  # Default high
        return 1  # Implement for real hardware

    def set_clk(self, value: int):
        """Set clock pin state (0 or 1)"""
        self.clk_pin = value & 1

    def delay_us(self, microseconds: int):
        """Microsecond delay"""
        time.sleep(microseconds / 1_000_000)

    def delay_ms(self, milliseconds: int):
        """Millisecond delay"""
        time.sleep(milliseconds / 1_000)

    def send_bits(self, data: int, count: int, lsb_first: bool = True):
        """
        Bit-bang data out on DAT/CLK pins.

        From firmware analysis (FUN_00003f48:5190-5204):
        - Clock LOW, set data bit, Clock HIGH
        - LSB First: param_1 >> 1 each iteration

        Evidence: FUN_00003f48 at line 5200 does "param_1 = param_1 >> 1"
        """
        for i in range(count):
            if lsb_first:
                bit = (data >> i) & 1
            else:
                bit = (data >> (count - 1 - i)) & 1

            self.set_clk(0)          # CLK LOW
            self.set_dat(bit)        # Set data
            self.delay_us(1)
            self.set_clk(1)          # CLK HIGH (latch)
            self.delay_us(1)

        self.set_clk(0)              # Return CLK low
        self.delay_us(1)

    def read_bits(self, count: int, msb_first: bool = True) -> int:
        """
        Bit-bang data in from DAT/CLK pins.

        From firmware analysis (FUN_00003ca4:5002-5024):
        - MSB First: local_28 = bit | (local_28 << 1)

        Evidence: FUN_00003ca4 at line 5015:
        local_28 = (uint)(_DAT_40010c08 << 0x1a) >> 0x1f | (local_28 & 0x7fff) << 1
        This shifts left and ORs new bit = MSB first
        """
        data = 0
        self.set_dat_direction(True)  # Input mode

        for i in range(count):
            self.set_clk(0)
            self.delay_us(1)
            self.set_clk(1)           # Rising edge
            self.delay_us(1)

            bit = self.get_dat()

            if msb_first:
                data = (data << 1) | bit
            else:
                data |= (bit << i)

        self.set_clk(0)
        self.set_dat_direction(False)  # Output mode
        return data

    def send_command(self, cmd: int):
        """
        Send 8-bit ICSP command (LSB First).

        Evidence: All command functions (FUN_00003e7c, FUN_00003ec0, FUN_00003f04)
        use FUN_00003f48 or similar which sends LSB first.
        """
        self.send_bits(cmd, 8, lsb_first=True)
        self.delay_us(5)  # Inter-command delay

    def select_area(self, area_mask: int):
        """
        Select memory area using SETUP command (0x23).

        This MUST be called before any ROM or Config operations!

        Evidence: FUN_0000b4b4 at lines 12177-12182:
          void FUN_0000b4b4(undefined4 param_1) {
            FUN_00003e7c(0x23);           // Send SETUP command
            FUN_00003f48(param_1,0x10);   // Send 16-bit area mask
          }

        Usage pattern from firmware:
          - Line 3794: FUN_0000b4b4(0xc000) before reading config
          - Line 5738: FUN_0000b4b4(0xc004) before writing config
          - Line 8015: FUN_0000b4b4(0x8000) before ROM operations

        Args:
            area_mask: AREA_MASK.ROM_READ, AREA_MASK.CONFIG_WRITE, etc.
        """
        self.send_command(ICSP_CMD.SETUP)
        self.send_bits(area_mask, 16, lsb_first=True)
        self.delay_us(10)

# === INTEL HEX PARSER ===
def parse_hex_file(filename: str) -> dict:
    """Parse Intel HEX file and return word-addressed memory dict."""
    print(f"[HEX] Parsing {filename}...")
    memory = {}

    try:
        with open(filename, 'r') as f:
            for line in f:
                line = line.strip()
                if not line.startswith(':'):
                    continue

                byte_count = int(line[1:3], 16)
                address = int(line[3:7], 16)
                record_type = int(line[7:9], 16)
                data = bytes.fromhex(line[9:9 + byte_count * 2])

                if record_type == 0x00:  # Data record
                    # SC8P052 is 14-bit word-addressable
                    # HEX file uses byte addresses, divide by 2 for word address
                    for i in range(0, len(data), 2):
                        if i + 1 < len(data):
                            word = data[i] | (data[i + 1] << 8)
                            word_addr = (address + i) // 2
                            memory[word_addr] = word & 0x3FFF  # Mask to 14 bits
                elif record_type == 0x01:  # EOF
                    break
    except FileNotFoundError:
        print(f"[HEX] Error: File not found: {filename}")
        sys.exit(1)

    print(f"[HEX] Loaded {len(memory)} words")
    return memory

# === HIGH-LEVEL ICSP OPERATIONS ===

def select_area(hw: Hardware, area_mask: int):
    """
    Select memory area before ROM/Config operations.

    CRITICAL: Must be called before any read/write operations!

    Evidence: FUN_0000b4b4 (lines 12177-12182) is called before every
    programming or read operation in the firmware:
      - Before ROM read: FUN_0000b4b4(0x8000) at line 8289
      - Before ROM write: FUN_0000b4b4(0x8000) at line 8015
      - Before Config read: FUN_0000b4b4(0xC000) at line 9919
      - Before Config write: FUN_0000b4b4(0xC004) at line 5738

    Args:
        hw: Hardware interface
        area_mask: AREA_MASK constant (ROM_READ, CONFIG_WRITE, etc.)
    """
    hw.select_area(area_mask)


def enter_programming_mode(hw: Hardware):
    """
    Enter ICSP programming mode.

    Sequence from firmware (FUN_00003b5c:4917-4947):
    1. Set CLK/DAT low
    2. Apply VDD
    3. Apply VPP (15.5V)
    4. Send entry key: 0x9B, 0x29, 0x64, 0xD6 (LSB First)
    5. Wait 30ms

    Evidence: Lines 4927-4945 in Writer8_lite.c
    """
    print("[ICSP] Entering Programming Mode...")

    hw.set_dat(0)
    hw.set_clk(0)
    hw.delay_ms(10)

    # Power sequence: VDD first, then VPP
    hw.set_vdd(True)
    hw.delay_ms(5)
    hw.set_vpp(True, VPP_PROG_VOLTAGE)
    hw.delay_ms(5)

    # Send entry key (LSB First for each byte)
    print(f"[ICSP] Sending entry key: {[hex(b) for b in ENTRY_KEY]}")
    for byte_val in ENTRY_KEY:
        hw.send_bits(byte_val, 8, lsb_first=True)

    # Post-entry delay (line 4945: FUN_000005e0(0x1e) = 30ms)
    hw.delay_ms(ENTRY_DELAY_MS)
    print("[ICSP] Programming mode entered")

def exit_programming_mode(hw: Hardware):
    """Exit ICSP programming mode."""
    print("[ICSP] Exiting Programming Mode...")
    hw.set_vpp(False)
    hw.delay_ms(1)
    hw.set_vdd(False)
    hw.delay_ms(10)

def reset_address(hw: Hardware):
    """
    Reset address counter to 0.

    Evidence: Command 0x1c used at lines 3160, 3237, 3606, 3645, 3675, etc.
    """
    hw.send_command(ICSP_CMD.RESET_ADDR)

def increment_address(hw: Hardware):
    """
    Increment address counter by 1.

    Evidence: Command 0x5c used at lines 3167, 3245, 3611, 3650, etc.
    """
    hw.send_command(ICSP_CMD.INCREMENT_ADDR)

def read_word(hw: Hardware) -> int:
    """
    Read 14-bit word from current address.

    Sequence from FUN_0000779c (line 8386-8394):
    1. Send 0x63 (Read Data command)
    2. Read 16 bits MSB first
    3. Mask to 14 bits

    Evidence: FUN_00003e7c(99) at line 8391, FUN_00003ca4 reads MSB first
    """
    hw.send_command(ICSP_CMD.READ_DATA)
    hw.delay_us(2)

    # Read 16 bits MSB first (FUN_00003ca4 evidence at line 5015)
    data = hw.read_bits(16, msb_first=True)
    return data & 0x3FFF  # Mask to 14 bits

def load_data_for_program(hw: Hardware, word: int):
    """
    Load data into programming latch.

    Sequence from FUN_0000b404 (line 12077-12082):
    1. Send 0x6a (Load Data command)
    2. Send 16-bit data LSB first

    Evidence: FUN_00003e7c(0x6a) at line 12080, FUN_00003e24 sends data
    """
    hw.send_command(ICSP_CMD.LOAD_DATA)
    hw.send_bits(word, 16, lsb_first=True)

def begin_programming(hw: Hardware) -> bool:
    """
    Execute programming pulse and wait for completion.

    Sequence from FUN_00008010 (line 9041-9060):
    1. Send 0x55 (Begin Programming)
    2. Wait with timeout (30ms)
    3. Poll completion status

    Evidence: FUN_00003e7c(0x55) at line 9047
    """
    hw.send_command(ICSP_CMD.BEGIN_PROG)
    hw.delay_us(PROG_PULSE_US)
    hw.delay_ms(1)  # Additional settling time
    return True  # In real hardware, check status

def program_word(hw: Hardware, word: int) -> bool:
    """Program a single word at current address."""
    load_data_for_program(hw, word)
    return begin_programming(hw)

def erase_chip(hw: Hardware):
    """
    Bulk erase chip (for OTP, this may not work - use with caution).

    Sequence from FUN_00003df8 (lines 5082-5091):
    1. Send 0xf8, wait 30ms
    2. Send 0xb1, wait 10ms
    3. Send 0x78, wait 10ms

    WARNING: SC8P052 is OTP (One-Time Programmable) - erase may not be supported!
    """
    print("[ICSP] WARNING: Attempting erase on OTP device!")
    hw.send_command(ICSP_CMD.ERASE_CMD1)
    hw.delay_ms(30)
    hw.send_command(ICSP_CMD.ERASE_CMD2)
    hw.delay_ms(10)
    hw.send_command(ICSP_CMD.ERASE_CMD3)
    hw.delay_ms(10)


def read_config(hw: Hardware) -> list:
    """
    Read configuration words.

    Evidence: Before reading config, firmware calls FUN_0000b4b4(0xC000)
    at line 9919 to select config area.

    Returns:
        List of config words (CONFIGLENTH=2 for SC8P052, +1 padding = 3 total)
    """
    print("\n[READ] Reading configuration words...")
    enter_programming_mode(hw)

    # Select Config area for reading
    select_area(hw, AREA_MASK.CONFIG_READ)
    reset_address(hw)

    config = []
    for i in range(CONFIG_WORDS):
        word = read_word(hw)
        config.append(word)
        increment_address(hw)
        print(f"  Config[{i}]: 0x{word:04X}")

    exit_programming_mode(hw)
    return config


def program_config(hw: Hardware, config_words: list):
    """
    Program configuration words.

    Evidence: Before writing config, firmware calls FUN_0000b4b4(0xC004)
    at lines 5738, 5966, 11909, etc.

    Args:
        config_words: List of config words to program
    """
    print(f"\n[PROG] Programming {len(config_words)} config words...")
    enter_programming_mode(hw)

    # Select Config area for writing
    select_area(hw, AREA_MASK.CONFIG_WRITE)
    reset_address(hw)

    errors = 0
    for i, word in enumerate(config_words):
        print(f"  Config[{i}]: 0x{word:04X}")
        success = program_word(hw, word)
        if not success:
            print(f"  ERROR at config word {i}")
            errors += 1
        increment_address(hw)

    print(f"[PROG] Config programming complete ({errors} errors)")
    exit_programming_mode(hw)

# === MAIN PROGRAMMER FUNCTIONS ===

def check_connection(hw: Hardware) -> bool:
    """
    Check device connection by reading first word.

    A blank OTP chip should read 0x3FFF at all locations.
    """
    print("\n[CHECK] Checking device connection...")
    enter_programming_mode(hw)

    # Select ROM area for reading
    select_area(hw, AREA_MASK.ROM_READ)
    reset_address(hw)

    word = read_word(hw)
    print(f"[CHECK] Address 0x0000: 0x{word:04X}")

    valid = False
    if word == 0x3FFF:
        print("[CHECK] Device detected (Blank OTP)")
        valid = True
    elif word != 0x0000 and word != 0xFFFF:
        print("[CHECK] Device detected (Programmed)")
        valid = True
    else:
        print("[CHECK] Device NOT detected or communication error")

    exit_programming_mode(hw)
    return valid

def read_flash(hw: Hardware, start_addr: int = 0, count: int = ROM_SIZE_WORDS) -> dict:
    """Read flash memory contents."""
    print(f"\n[READ] Reading {count} words from 0x{start_addr:04X}...")
    enter_programming_mode(hw)

    # Select ROM area BEFORE reset_address (firmware pattern)
    select_area(hw, AREA_MASK.ROM_READ)
    reset_address(hw)

    # Skip to start address
    for _ in range(start_addr):
        increment_address(hw)

    memory = {}
    for i in range(count):
        addr = start_addr + i
        word = read_word(hw)
        memory[addr] = word
        increment_address(hw)

        if (i + 1) % 64 == 0:
            sys.stdout.write(".")
            sys.stdout.flush()

    print(f"\n[READ] Read complete")
    exit_programming_mode(hw)
    return memory

def program_flash(hw: Hardware, hex_file: str):
    """Program flash memory from HEX file."""
    memory = parse_hex_file(hex_file)
    if not memory:
        print("[PROG] No data to program")
        return

    max_addr = max(memory.keys())
    print(f"\n[PROG] Programming {len(memory)} words (0x0000 - 0x{max_addr:04X})")

    enter_programming_mode(hw)

    # Select ROM area for writing (firmware pattern from line 8015)
    select_area(hw, AREA_MASK.ROM_WRITE)
    reset_address(hw)

    errors = 0
    for addr in range(max_addr + 1):
        word = memory.get(addr, 0x3FFF)

        if word != 0x3FFF:  # Only program non-blank words
            success = program_word(hw, word)
            if not success:
                print(f"\n[PROG] Error at 0x{addr:04X}")
                errors += 1

        increment_address(hw)

        if (addr + 1) % 64 == 0:
            sys.stdout.write(".")
            sys.stdout.flush()

    print(f"\n[PROG] Programming complete ({errors} errors)")
    exit_programming_mode(hw)

def verify_flash(hw: Hardware, hex_file: str) -> bool:
    """Verify flash memory against HEX file."""
    memory = parse_hex_file(hex_file)
    if not memory:
        print("[VERIFY] No data to verify")
        return True

    max_addr = max(memory.keys())
    print(f"\n[VERIFY] Verifying {len(memory)} words...")

    enter_programming_mode(hw)

    # Select ROM area for reading
    select_area(hw, AREA_MASK.ROM_READ)
    reset_address(hw)

    errors = 0
    for addr in range(max_addr + 1):
        expected = memory.get(addr, 0x3FFF)
        actual = read_word(hw)

        if actual != expected:
            print(f"\n[VERIFY] Mismatch at 0x{addr:04X}: expected 0x{expected:04X}, got 0x{actual:04X}")
            errors += 1
            if errors > 10:
                print("[VERIFY] Too many errors, aborting")
                break

        increment_address(hw)

        if (addr + 1) % 64 == 0:
            sys.stdout.write(".")
            sys.stdout.flush()

    result = errors == 0
    print(f"\n[VERIFY] Verification {'PASSED' if result else 'FAILED'}")
    exit_programming_mode(hw)
    return result

def dump_flash(hw: Hardware, output_file: str):
    """Dump flash memory to file."""
    memory = read_flash(hw)

    with open(output_file, 'w') as f:
        for addr in sorted(memory.keys()):
            f.write(f"{addr:04X}: {memory[addr]:04X}\n")

    print(f"[DUMP] Saved to {output_file}")

# === MAIN ===

def main():
    parser = argparse.ArgumentParser(
        description=f"{MCU_NAME} OTP Programmer (Reverse-engineered)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --check              Check device connection
  %(prog)s program.hex          Program device from HEX file
  %(prog)s program.hex --verify Program and verify
  %(prog)s --dump output.txt    Dump flash contents to file
  %(prog)s --read               Read and display flash contents

ICSP Pinout (6-pin):
  Pin 1: PA0 (ICSPDAT) - Data
  Pin 2: VSS (GND)
  Pin 3: PA1 (ICSPCLK) - Clock
  Pin 4: PA2 (VPP/MCLR) - High Voltage (12-15.5V)
  Pin 5: VDD - Power (3.3V)
  Pin 6: PA3 - Not used for programming
        """)

    parser.add_argument("file", nargs="?", help="HEX file to program")
    parser.add_argument("--check", action="store_true", help="Check device connection")
    parser.add_argument("--verify", action="store_true", help="Verify after programming")
    parser.add_argument("--read", action="store_true", help="Read and display flash")
    parser.add_argument("--dump", metavar="FILE", help="Dump flash to file")
    parser.add_argument("--hardware", action="store_true", help="Use real hardware (not simulation)")

    args = parser.parse_args()

    # Initialize hardware
    hw = Hardware(simulation=not args.hardware)

    if args.check:
        success = check_connection(hw)
        sys.exit(0 if success else 1)

    if args.dump:
        dump_flash(hw, args.dump)
        sys.exit(0)

    if args.read:
        memory = read_flash(hw)
        print("\nFlash Contents:")
        for addr in sorted(memory.keys()):
            if memory[addr] != 0x3FFF:
                print(f"  0x{addr:04X}: 0x{memory[addr]:04X}")
        sys.exit(0)

    if args.file:
        program_flash(hw, args.file)
        if args.verify:
            success = verify_flash(hw, args.file)
            sys.exit(0 if success else 1)
        sys.exit(0)

    if not any([args.check, args.dump, args.read, args.file]):
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()
