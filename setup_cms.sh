#!/bin/bash
set -e

# Config
GADGET_NAME="cms_writer"
GADGET_PATH="/sys/kernel/config/usb_gadget/${GADGET_NAME}"
VID="0x1209"
# PID Selection:
# PID="0x003A" # WRITER8 (Standard) - Decimal 58
# PID="0x0032" # WRITER8 (Alt)      - Decimal 50
# PID="0x0023" # WRITER8 PRO        - Decimal 35
# PID="0x0201" # WRITER8 LITE       - Decimal 513 (Normal Mode)
# PID="0x0101" # WRITER8 LITE       - Decimal 257 (Bootloader Mode)

PID="0x0201" # Selected: WRITER8 LITE

MANUFACTURER="CMS"
PRODUCT="CMS-WRITER8"
SERIAL="0001"

# Standard HID Report Descriptor (64 bytes in/out)
# Usage Page 0xFF00, Usage 0x01
HID_REPORT_DESC=( 
    0x06 0x00 0xFF
    0x09 0x01
    0xA1 0x01
    0x15 0x00
    0x26 0xFF 0x00
    0x75 0x08
    0x95 0x40
    0x09 0x01
    0x81 0x02
    0x95 0x40
    0x09 0x01
    0x91 0x02
    0xC0
)

cleanup() {
    echo "Cleaning up..."
    if [ -d "${GADGET_PATH}" ]; then
        echo "" > "${GADGET_PATH}/UDC" 2>/dev/null || true
        rm -f "${GADGET_PATH}/configs/c.1/hid.usb0" 2>/dev/null || true
        rmdir "${GADGET_PATH}/configs/c.1/strings/0x409" 2>/dev/null || true
        rmdir "${GADGET_PATH}/configs/c.1" 2>/dev/null || true
        rmdir "${GADGET_PATH}/functions/hid.usb0" 2>/dev/null || true
        rmdir "${GADGET_PATH}/strings/0x409" 2>/dev/null || true
        rmdir "${GADGET_PATH}" 2>/dev/null || true
    fi
}

setup_gadget() {
    echo "Loading modules..."
    modprobe libcomposite || true
    modprobe usb_f_hid || true

    if ! mountpoint -q /sys/kernel/config; then
        mount -t configfs none /sys/kernel/config
    fi

    mkdir -p "${GADGET_PATH}"
    cd "${GADGET_PATH}"

    echo "${VID}" > idVendor
    echo "${PID}" > idProduct
    echo 0x0100 > bcdDevice
    echo 0x0200 > bcdUSB
    echo 0x00 > bDeviceClass
    echo 0x00 > bDeviceSubClass
    echo 0x00 > bDeviceProtocol

    mkdir -p strings/0x409
    echo "${MANUFACTURER}" > strings/0x409/manufacturer
    echo "${PRODUCT}" > strings/0x409/product
    echo "${SERIAL}" > strings/0x409/serialnumber

    mkdir -p configs/c.1/strings/0x409
    echo "CMS Config" > configs/c.1/strings/0x409/configuration
    echo 250 > configs/c.1/MaxPower

    mkdir -p functions/hid.usb0
    echo 0 > functions/hid.usb0/protocol
    echo 0 > functions/hid.usb0/subclass
    echo 64 > functions/hid.usb0/report_length
    
    # Write report descriptor using Python for safety
    # We pass the hex strings as arguments
    python3 -c "import sys; sys.stdout.buffer.write(bytes([int(x, 16) for x in sys.argv[1:]]))" "${HID_REPORT_DESC[@]}" > functions/hid.usb0/report_desc

    ln -sf functions/hid.usb0 configs/c.1/

    # Enable gadget
    UDC=$(ls /sys/class/udc | head -n 1)
    if [ -z "$UDC" ]; then
        echo "Error: No UDC found in /sys/class/udc"
        exit 1
    fi
    echo "${UDC}" > UDC

    echo "Gadget Active: VID:${VID} PID:${PID} Device:/dev/hidg0"
}

case "${1:-setup}" in
    setup)
        cleanup
        setup_gadget
        ;;
    stop)
        cleanup
        ;;
    *)
        echo "Usage: $0 {setup|stop}"
        exit 1
        ;;
esac
