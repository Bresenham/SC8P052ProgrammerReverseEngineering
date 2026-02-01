import os
import sys
import struct
import random
import time
import signal
import datetime

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

class Session:
    def __init__(self):
        self.start_time = datetime.datetime.now()
        self.session_id = self.start_time.strftime('%Y%m%d_%H%M%S')
        self.log_filename = f"session_{self.session_id}.log"
        self.flash = {} # offset -> byte
        self.config = {}
        self.eeprom = {}
        self.bootrom = {}
        self.mcu_info = {}
        self.log_file = open(self.log_filename, "w")
        self.log(f"=== Session started at {self.start_time} ===")

    def log(self, message):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        msg = f"[{timestamp}] {message}"
        print(msg)
        self.log_file.write(msg + "\n")
        self.log_file.flush()

    def log_packet(self, direction, raw_data, decrypted_data=None, valid=True):
        prefix = ">>> " if direction == "IN" else "<<< "
        hex_raw = raw_data.hex(' ')
        self.log(f"{prefix}RAW: {hex_raw}")
        if decrypted_data:
            # Only log up to length specified in buf[0]
            length = decrypted_data[0]
            hex_dec = bytes(decrypted_data[:length]).hex(' ')
            valid_str = "" if valid else " [INVALID CHECKSUM]"
            self.log(f"{prefix}DEC: {hex_dec}{valid_str}")

    def save_sparse_data(self, data_dict, name_prefix):
        if not data_dict:
            return
        
        # Sort keys to find ranges
        offsets = sorted(data_dict.keys())
        if not offsets:
            return

        filename = f"{name_prefix}_{self.session_id}.bin"
        max_addr = offsets[-1]
        
        # We save a continuous block from 0 to max_addr, filling holes with 0xFF
        # Alternatively, we could save multiple blocks if there are huge gaps.
        # For MCUs, usually it's one or two blocks.
        output = bytearray([0xFF] * (max_addr + 1))
        for addr, val in data_dict.items():
            output[addr] = val
            
        with open(filename, "wb") as f:
            f.write(output)
        self.log(f"Saved {name_prefix} data to {filename} (Size: {len(output)} bytes, Max Addr: 0x{max_addr:X})")

    def save_all(self):
        self.save_sparse_data(self.flash, "flash")
        self.save_sparse_data(self.config, "config")
        self.save_sparse_data(self.eeprom, "eeprom")
        self.save_sparse_data(self.bootrom, "bootrom")

    def close(self):
        self.log("=== Session closed ===")
        self.log_file.close()

# Global session
session = None

def decrypt_packet(data):
    if len(data) < 64:
        return None, False
    buf = list(data)
    length = buf[0]
    if length > 64 or length < 2:
        return buf, False
    key = buf[63]
    checksum = buf[0]
    for i in range(1, length):
        buf[i] ^= key
        checksum = (checksum + buf[i]) & 0xFF
    valid = (checksum == buf[62])
    return buf, valid

def encrypt_packet(payload):
    length = len(payload)
    if length > 61: # 64 - 1 (len) - 1 (checksum) - 1 (key)
        length = 61
    buf = [0] * 64
    buf[0] = length + 1
    for i in range(length):
        buf[i+1] = payload[i]
    key = random.randint(0, 255)
    buf[63] = key
    checksum = buf[0]
    for i in range(1, buf[0]):
        checksum = (checksum + buf[i]) & 0xFF
        buf[i] ^= key
    buf[62] = checksum
    return bytes(buf)

def handle_command(cmd, decrypted_buf):
    if cmd == CMD_READ_VERSION:
        resp = [0] * 30
        resp[0] = CMD_READ_VERSION
        # Writer SN: 67305985 -> 04 03 02 01
        resp[1:5] = [0x01, 0x02, 0x03, 0x04]
        # Boot Ver: V1.01-190101 -> 9D 1B 01 01
        resp[17:19] = [0x9D, 0x1B]
        resp[19:21] = [0x01, 0x01]
        # App Ver: V1.10-241227 -> 50 24 0A 01
        resp[21:23] = [0x50, 0x24]
        resp[23:25] = [0x0A, 0x01]
        # HW Ver: 1
        resp[25:29] = [0x01, 0x00, 0x00, 0x00]
        return encrypt_packet(resp)

    elif cmd == CMD_SEND_MCUTYPE:
        series = decrypted_buf[2] | (decrypted_buf[3] << 8)
        mcu_type = decrypted_buf[4] | (decrypted_buf[5] << 8)
        power = decrypted_buf[6]
        pins = decrypted_buf[7:11] # VCC, GND, DAT, CLK
        session.log(f"CMD_SEND_MCUTYPE: Series={series}, Type=0x{mcu_type:04X}, Power={power}, Pins={pins}")
        return encrypt_packet([0, 2])

    elif cmd == CMD_DOWNLOAD_DATA:
        offset = decrypted_buf[2] | (decrypted_buf[3] << 8) | (decrypted_buf[4] << 16)
        data_len = decrypted_buf[0] - 5
        session.log(f"CMD_DOWNLOAD_DATA: Offset=0x{offset:06X}, Len={data_len}")
        for i in range(data_len):
            session.flash[offset + i] = decrypted_buf[5 + i]
        return encrypt_packet([0, 2])

    elif cmd == CMD_DOWNLOAD_CONFIG:
        offset = decrypted_buf[2] | (decrypted_buf[3] << 8)
        data_len = decrypted_buf[0] - 5
        session.log(f"CMD_DOWNLOAD_CONFIG: Offset=0x{offset:04X}, Len={data_len}")
        for i in range(data_len):
            session.config[offset + i] = decrypted_buf[5 + i]
        return encrypt_packet([0, 2])

    elif cmd == CMD_DOWNLOAD_EEDATA:
        offset = decrypted_buf[2] | (decrypted_buf[3] << 8)
        data_len = decrypted_buf[0] - 5
        session.log(f"CMD_DOWNLOAD_EEDATA: Offset=0x{offset:04X}, Len={data_len}")
        for i in range(data_len):
            session.eeprom[offset + i] = decrypted_buf[5 + i]
        return encrypt_packet([0, 2])

    elif cmd == CMD_DOWNLOAD_OPT1:
        session.log("CMD_DOWNLOAD_OPT1")
        return encrypt_packet([0, 2])

    elif cmd == CMD_DOWNLOAD_OPT2:
        session.log("CMD_DOWNLOAD_OPT2")
        return encrypt_packet([0, 2])

    elif cmd == CMD_DOWNLOAD_VERIFY:
        session.log("CMD_DOWNLOAD_VERIFY")
        return encrypt_packet([0, 2])

    elif cmd == CMD_END_WORK:
        session.log("CMD_END_WORK - Saving all captured data")
        session.save_all()
        return encrypt_packet([0, 2])

    elif cmd == CMD_READ_MCUINFO:
        session.log("CMD_READ_MCUINFO")
        resp = [CMD_READ_MCUINFO, 0xAA, 0xBB, 0x01, 0x02, 0x00, 0x01]
        return encrypt_packet(resp)

    session.log(f"Unknown CMD: {cmd}")
    return encrypt_packet([0, 2])

def main():
    global session
    if not os.path.exists(HIDG_DEVICE):
        print(f"Error: {HIDG_DEVICE} missing. Run setup_cms.sh first.")
        sys.exit(1)

    print(f"Opening {HIDG_DEVICE}...")
    fd = os.open(HIDG_DEVICE, os.O_RDWR)
    
    session = Session()
    print(f"SCMCU Emulator running. Logging to {session.log_filename}")

    try:
        while True:
            data = os.read(fd, 64)
            if not data:
                continue

            decrypted, valid = decrypt_packet(data)
            session.log_packet("IN", data, decrypted, valid)
            
            if not valid:
                continue
            
            cmd = decrypted[1]
            response = handle_command(cmd, decrypted)
            
            if response:
                if len(response) < 64:
                    response += b'\x00' * (64 - len(response))
                os.write(fd, response)
                session.log_packet("OUT", response)

    except KeyboardInterrupt:
        print("\nStopping...")
        if session:
            session.save_all()
            session.close()
    finally:
        os.close(fd)

if __name__ == "__main__":
    main()
