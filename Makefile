# Makefile for SC8P052 compilation
# Usage: make
#
# Outputs:
#   main.hex - Intel HEX format (intermediate)
#   main.scx - SCX format for SCMCU Writer

CHIP = SC8P052
CC = ../data/bin/picc.exe
INCLUDES = -I"../data/include"
OUTPUT_FORMAT = intel
HEX2SCX = python3 hex2scx.py

CFLAGS = --chip=$(CHIP) $(INCLUDES) --output=$(OUTPUT_FORMAT)

TARGET = main
SRC = main.c

.PHONY: all clean hex scx

all: $(TARGET).scx

hex: $(TARGET).hex

scx: $(TARGET).scx

$(TARGET).hex: $(SRC)
	$(CC) $(CFLAGS) -O$@ $<

$(TARGET).scx: $(TARGET).hex hex2scx.py
	$(HEX2SCX) $(TARGET).hex $(TARGET).scx --mcu=$(CHIP)

clean:
	rm -f $(TARGET).hex $(TARGET).scx $(TARGET).as $(TARGET).cmf $(TARGET).d \
	      $(TARGET).hxl $(TARGET).p1 $(TARGET).pre $(TARGET).sdb $(TARGET).sym \
	      funclist startup.as startup.lst startup.obj startup.rlf
