import os
import sys
import struct
import random
import time
import signal

HIDG_DEVICE = "/dev/hidg0"

# --- Constants ---
CMD_READ_VERSION    = 2
CMD_END_WORK        = 80
CMD_SEND_MCUTYPE    = 81
CMD_READ_DATA       = 82
CMD_READ_CONFIG     = 83
CMD_READ_EEDATA     = 84
CMD_READ_MCUINFO    = 85
CMD_READ_BOOTROM    = 86

CMD_DOWNLOAD_VERIFY = 96
CMD_DOWNLOAD_OPT1   = 97
CMD_DOWNLOAD_OPT2   = 98
CMD_DOWNLOAD_DATA   = 99
CMD_DOWNLOAD_CONFIG = 100
CMD_DOWNLOAD_EEDATA = 101
CMD_DOWNLOAD_BOOTROM= 102

# --- Emulated Memory ---
# 64KB Flash Buffer
FLASH_MEMORY = bytearray([0xFF] * 65536)
# Config Buffer (Arbitrary size, usually small)
CONFIG_MEMORY = bytearray([0xFF] * 256)
# EEPROM Buffer
EEPROM_MEMORY = bytearray([0xFF] * 1024)
# BootROM Buffer
BOOT_MEMORY = bytearray([0xFF] * 4096)


def decrypt_packet(data):
    """
    Decrypts a 64-byte packet.
    """
    if len(data) < 64:
        return None, False

    buf = list(data)
    length = buf[0]
    # Sanity check length
    if length > 64 or length < 2:
        return buf, False

    key = buf[63]
    checksum = buf[0]
    
    # Decrypt payload
    for i in range(1, length):
        buf[i] ^= key
        checksum = (checksum + buf[i]) & 0xFF

    valid = (checksum == buf[62])
    return buf, valid

def encrypt_packet(payload):
    """
    Encrypts a payload (list of bytes).
    Constructs a 64-byte packet.
    """
    length = len(payload)
    if length > 62:
        length = 62
    
    buf = [0] * 64
    buf[0] = length
    
    # Copy payload
    for i in range(length):
        # Payload in `buf` starts at index 1? 
        # Wait, protocol says buf[0] is length.
        # buf[1]..buf[N] is data.
        # So we copy payload to buf[1:]
        buf[i+1] = payload[i]
        
    # If payload is smaller than N, N is buf[0].
    # But wait, logic: buf[0] IS N (total bytes used including N itself?).
    # Let's check SendCmd.cs:
    #   data[0] = (byte)(num2 + 5); 
    #   data[1] = cmd;
    # So buf[0] is indeed the total count of meaningful bytes.
    # So if we pass a payload [CMD, arg1, arg2], len is 3.
    # We put them at buf[1], buf[2], buf[3].
    # buf[0] should be 1 + 3 = 4.
    
    # Correction: The `payload` arg to this func should just be the data content.
    # We calculate true N.
    
    N = length + 1
    buf[0] = N

    key = random.randint(0, 255)
    buf[63] = key
    
    checksum = buf[0]
    
    # Encrypt
    for i in range(1, N):
        val = buf[i]
        checksum = (checksum + val) & 0xFF
        buf[i] ^= key
    
    buf[62] = checksum
    return bytes(buf)

def handle_command(cmd, decrypted_buf):
    print(f"  [Processing] CMD: {cmd} (Decrypted len: {decrypted_buf[0]})")
    
    # --- Handshake / Version ---
    if cmd == CMD_READ_VERSION:
        # Response: [CMD, ID_L, ID, ID, ID_H, ... Ver info ...]
        resp = [0] * 30
        resp[0] = CMD_READ_VERSION

        # Writer ID: 0x04030201
        resp[1] = 0x01
        resp[2] = 0x02
        resp[3] = 0x03
        resp[4] = 0x04

        # Boot Ver (Idx 17-20): V1.01-190101 (example boot version)
        # Encoded date for 2019-01-01: year=19, month=0, day=1
        # num3 = 19*12 + 0 = 228, num = 228*31 + 1 = 7069 = 0x1B9D
        resp[17] = 0x9D; resp[18] = 0x1B  # Date bytes (little-endian)
        resp[19] = 0x01; resp[20] = 0x01  # Version 1.01

        # App Ver (Idx 21-24): V1.10-241227 (matches SCMCU_Writer_V9.01.15 expected version)
        # Encoded date for 2024-12-27: year=24, month=11, day=27
        # num3 = 24*12 + 11 = 299, num = 299*31 + 27 = 9296 = 0x2450
        resp[21] = 0x50; resp[22] = 0x24  # Date bytes (little-endian)
        resp[23] = 0x0A; resp[24] = 0x01  # Version 1.10 (minor=10, major=1)

        # Hardware Ver (Idx 25-28): Set to 0x01 for WRITER8_LITE v1
        resp[25] = 0x01; resp[26] = 0x00; resp[27] = 0x00; resp[28] = 0x00

        # We need a decent length. The app reads up to idx 29.
        # Let's send 40 bytes payload.
        return encrypt_packet(resp[:40])

    # --- Connection ---
    elif cmd == CMD_SEND_MCUTYPE:
        # Request: [CMD, SeriesL, SeriesH, TypeL, TypeH, Power, VCC, GND, DAT, CLK]
        power_sel = decrypted_buf[6]
        pin_vcc = decrypted_buf[7]
        pin_gnd = decrypted_buf[8]
        pin_dat = decrypted_buf[9]
        pin_clk = decrypted_buf[10]
        
        print(f"    -> Set MCU Type. Power: {power_sel}")
        print(f"       Pins (Target): VCC={pin_vcc}, GND={pin_gnd}, DAT={pin_dat}, CLK={pin_clk}")
        
        # App expects [0, 2] status in bytes 1 and 2.
        return encrypt_packet([0, 2])

    # --- Read Operations (Expect RAW DATA response) ---
    elif cmd == CMD_READ_DATA:
        # Request: [CMD, AddrL, AddrM, AddrH, Len, TotalL, TotalM, TotalH]
        # But wait, SendReadDataCmd sends chunks.
        # data[0]=9, data[1]=CMD, data[2..4]=Offset, data[5]=ChunkLen
        
        offset = decrypted_buf[2] + (decrypted_buf[3] << 8) + (decrypted_buf[4] << 16)
        chunk_len = decrypted_buf[5]
        print(f"    -> Read ROM Offset: {offset}, Len: {chunk_len}")
        
        # Return Raw Data
        chunk = FLASH_MEMORY[offset : offset + chunk_len]
        # Pad if necessary (though usually exact)
        if len(chunk) < chunk_len:
            chunk += b'\xFF' * (chunk_len - len(chunk))
        
        return bytes(chunk) # RAW, no encryption

    elif cmd == CMD_READ_CONFIG:
        offset = decrypted_buf[2] + (decrypted_buf[3] << 8)
        chunk_len = decrypted_buf[5]
        print(f"    -> Read Config Offset: {offset}, Len: {chunk_len}")
        chunk = CONFIG_MEMORY[offset : offset + chunk_len]
        if len(chunk) < chunk_len:
            chunk += b'\xFF' * (chunk_len - len(chunk))
        return bytes(chunk) # RAW

    elif cmd == CMD_READ_EEDATA:
        offset = decrypted_buf[2] + (decrypted_buf[3] << 8)
        chunk_len = decrypted_buf[5]
        print(f"    -> Read EEPROM Offset: {offset}, Len: {chunk_len}")
        chunk = EEPROM_MEMORY[offset : offset + chunk_len]
        return bytes(chunk)

    elif cmd == CMD_READ_BOOTROM:
        offset = decrypted_buf[2] + (decrypted_buf[3] << 8)
        chunk_len = decrypted_buf[5]
        print(f"    -> Read BootROM Offset: {offset}, Len: {chunk_len}")
        chunk = BOOT_MEMORY[offset : offset + chunk_len]
        return bytes(chunk)

    elif cmd == CMD_READ_MCUINFO:
        # Returns Info Block.
        # [CMD, INFO_CMD, CRC_L, CRC_H, Ver, Ver, WriterNum_L, WriterNum_H]
        # SendCmd.cs: data2[1] == CMD_READ_MCUINFO (85)
        resp = [0] * 10
        resp[0] = CMD_READ_MCUINFO # 85
        resp[1] = 0xAA # CRC L
        resp[2] = 0xBB # CRC H
        resp[3] = 0x01 # Ver
        resp[4] = 0x02 # Ver
        resp[5] = 0x00 # Num
        resp[6] = 0x01 # Num
        return encrypt_packet(resp)

    # --- Write Operations (Expect Encrypted ACK) ---
    elif cmd == CMD_DOWNLOAD_OPT1 or cmd == CMD_DOWNLOAD_OPT2:
        print("    -> Download Option")
        return encrypt_packet([0, 2])
        
    elif cmd == CMD_DOWNLOAD_DATA:
        # Payload has data.
        # SendDataCmd: data[0]=Len, data[1]=CMD, data[2..4]=Offset, data[5..]=Data
        offset = decrypted_buf[2] + (decrypted_buf[3] << 8) + (decrypted_buf[4] << 16)
        # Data starts at index 5.
        # Length of data?
        # decrypted_buf[0] is Total Len.
        # Header is 5 bytes (Len, Cmd, OffL, OffM, OffH).
        # So data len = decrypted_buf[0] - 5.
        data_len = decrypted_buf[0] - 5
        if data_len > 0:
            print(f"    -> Write ROM Offset: {offset}, Len: {data_len}")
            for i in range(data_len):
                if offset + i < len(FLASH_MEMORY):
                    FLASH_MEMORY[offset + i] = decrypted_buf[5 + i]
        return encrypt_packet([0, 2])

    elif cmd == CMD_DOWNLOAD_CONFIG:
        offset = decrypted_buf[2] + (decrypted_buf[3] << 8)
        data_len = decrypted_buf[0] - 5
        print(f"    -> Write Config Offset: {offset}, Len: {data_len}")
        for i in range(data_len):
             if offset + i < len(CONFIG_MEMORY):
                CONFIG_MEMORY[offset + i] = decrypted_buf[5 + i]
        return encrypt_packet([0, 2])
        
    elif cmd == CMD_DOWNLOAD_VERIFY:
        print("    -> Download Verify")
        return encrypt_packet([0, 2])

    elif cmd == CMD_END_WORK:
        print("    -> End Work")
        # Save Flash Buffer
        try:
            with open("flash_dump.bin", "wb") as f:
                f.write(FLASH_MEMORY)
            print("       [Saved] Flash memory dumped to 'flash_dump.bin'")
        except Exception as e:
            print(f"       [Error] Failed to save flash dump: {e}")
        return encrypt_packet([0, 2])

    # Default fallback
    print(f"    [!] Unknown Command: {cmd}")
    return encrypt_packet([0, 2]) # Try generic ACK


def main():
    if not os.path.exists(HIDG_DEVICE):
        print(f"Error: {HIDG_DEVICE} missing. Run setup_cms.sh first.")
        sys.exit(1)

    print(f"Opening {HIDG_DEVICE}...")
    fd = os.open(HIDG_DEVICE, os.O_RDWR)
    print("SCMCU Emulator running...")

    try:
        while True:
            # Read 64 bytes
            data = os.read(fd, 64)
            if not data:
                continue

            # In Gadgetfs/HID, we usually get the Report ID (if nonzero) or just data.
            # My descriptor uses Report IDs? The script didn't set Report IDs explicitly in the descriptor macros 
            # (only Usage Page), but the C# code sends Byte 0 as 'Protocol Length', not Report ID.
            # Wait, C# uses `WriteFile`. If the driver sees Report ID 0, it sends 64 bytes.
            
            # Decrypt
            decrypted, valid = decrypt_packet(data)
            
            if not valid:
                # Sometimes we get garbage or just 0s if idle?
                # print("Invalid Checksum")
                continue
            
            cmd = decrypted[1]
            response = handle_command(cmd, decrypted)
            
            if response:
                # Pad response to 64 bytes if needed?
                # hidg writes typically need to match report size.
                if len(response) < 64:
                    response += b'\xFF' * (64 - len(response))
                elif len(response) > 64:
                    response = response[:64]
                    
                os.write(fd, response)

    except KeyboardInterrupt:
        print("
Stopping...")
    finally:
        os.close(fd)

if __name__ == "__main__":
    main()
