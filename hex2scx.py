#!/usr/bin/env python3
"""
hex2scx.py - Convert Intel HEX files to SCX format for SCMCU Writer

SCX File Format:
  Bytes 0-31:    MCU name (ASCII, null-terminated)
  Byte 32:       Rolling code enable (0=disabled)
  Bytes 33-159:  Reserved (filled with 0xFF)
  Bytes 160-255: Configuration data
  Bytes 256+:    ROM data (each word is 2 bytes, little-endian)

Usage: python hex2scx.py <input.hex> <output.scx> [--mcu=SC8P052]
"""

import sys
import struct
import argparse

# MCU definitions: name -> (rom_size_words, config_word_address, config_size_words)
MCU_DEFS = {
    'SC8P052': (0x400, 0x2007, 2),      # 1K words ROM, config at 0x2007, 2 config words
    'SC8P052B': (0x400, 0x2007, 2),
    'SC8P052B_A': (0x400, 0x2007, 2),
    'SC8P054': (0x800, 0x2007, 2),      # 2K words ROM
    'SC8P062': (0x400, 0x2007, 2),
}

def parse_hex_file(filename):
    """Parse Intel HEX file and return dict of address -> byte data"""
    data = {}
    extended_addr = 0

    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            if not line.startswith(':'):
                continue

            # Parse record
            byte_count = int(line[1:3], 16)
            address = int(line[3:7], 16)
            record_type = int(line[7:9], 16)

            if record_type == 0x00:  # Data record
                full_addr = extended_addr + address
                for i in range(byte_count):
                    byte_val = int(line[9 + i*2:11 + i*2], 16)
                    data[full_addr + i] = byte_val
            elif record_type == 0x01:  # EOF
                break
            elif record_type == 0x02:  # Extended segment address
                extended_addr = int(line[9:13], 16) << 4
            elif record_type == 0x04:  # Extended linear address
                extended_addr = int(line[9:13], 16) << 16

    return data

def create_scx(hex_data, mcu_name, output_file):
    """Create SCX file from parsed HEX data"""

    if mcu_name not in MCU_DEFS:
        print(f"Warning: Unknown MCU '{mcu_name}', using SC8P052 defaults")
        mcu_name = 'SC8P052'

    rom_size_words, config_addr, config_size = MCU_DEFS[mcu_name]
    rom_size_bytes = rom_size_words * 2
    config_size_bytes = config_size * 2

    # Initialize SCX buffer
    # Header (160 bytes) + Config area (96 bytes) + ROM data
    scx_data = bytearray(256 + rom_size_bytes)

    # Fill with 0xFF (unprogrammed flash value)
    for i in range(len(scx_data)):
        scx_data[i] = 0xFF

    # Write MCU name (bytes 0-31, bang-terminated)
    mcu_name_bytes = mcu_name.encode('ascii')
    for i, b in enumerate(mcu_name_bytes[:31]):  # Max 31 chars
        scx_data[i] = b
    # Add bang terminator (33) after the name
    if len(mcu_name_bytes) < 32:
        scx_data[len(mcu_name_bytes)] = 33

    # Rolling code enable = 0 (byte 32)
    scx_data[32] = 0x00

    # Extract ROM data from HEX (starts at address 0x0000 in HEX)
    # In HEX file, ROM is at byte address 0x0000 (word address 0x0000)
    # Each instruction word is stored as 2 bytes
    rom_start_offset = 256
    for word_addr in range(rom_size_words):
        byte_addr = word_addr * 2  # HEX file byte address

        low_byte = hex_data.get(byte_addr, 0xFF)
        high_byte = hex_data.get(byte_addr + 1, 0xFF)

        scx_offset = rom_start_offset + word_addr * 2
        scx_data[scx_offset] = low_byte
        scx_data[scx_offset + 1] = high_byte

    # Extract config data from HEX (at address 0x2007 word = 0x400E byte)
    # Config words are stored at specific addresses in HEX file
    config_byte_addr = config_addr * 2  # 0x2007 * 2 = 0x400E
    config_start_offset = 160

    for i in range(config_size):
        byte_addr = config_byte_addr + i * 2
        low_byte = hex_data.get(byte_addr, 0xFF)
        high_byte = hex_data.get(byte_addr + 1, 0xFF)

        # Store config as 16-bit words in config area
        scx_offset = config_start_offset + i * 2
        scx_data[scx_offset] = low_byte
        scx_data[scx_offset + 1] = high_byte

    # Write SCX file
    with open(output_file, 'wb') as f:
        f.write(scx_data)

    print(f"Created {output_file}")
    print(f"  MCU: {mcu_name}")
    print(f"  ROM size: {rom_size_words} words ({rom_size_bytes} bytes)")
    print(f"  Config words: {config_size}")

    # Print config values found
    for i in range(config_size):
        byte_addr = config_byte_addr + i * 2
        low = hex_data.get(byte_addr, 0xFF)
        high = hex_data.get(byte_addr + 1, 0xFF)
        word = (high << 8) | low
        print(f"  Config word {i} @ 0x{config_addr + i:04X}: 0x{word:04X}")

def main():
    parser = argparse.ArgumentParser(description='Convert Intel HEX to SCX format')
    parser.add_argument('input', help='Input HEX file')
    parser.add_argument('output', help='Output SCX file')
    parser.add_argument('--mcu', default='SC8P052', help='MCU type (default: SC8P052)')

    args = parser.parse_args()

    print(f"Reading {args.input}...")
    hex_data = parse_hex_file(args.input)
    print(f"  Found {len(hex_data)} bytes of data")

    create_scx(hex_data, args.mcu, args.output)

if __name__ == '__main__':
    main()
