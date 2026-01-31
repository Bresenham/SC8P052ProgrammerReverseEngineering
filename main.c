#define _XTAL_FREQ 8000000
#include <sc.h>

// Use the default value from the .ini file (0x3FFF)
// This usually means all features off/default
#pragma config FOSC = INTRC_NOCLKOUT
#pragma config WDTE = OFF
#pragma config PWRTE = ON
#pragma config MCLRE = ON
#pragma config CP = OFF
#pragma config BOREN = OFF

void main(void)
{
    TRISB = 0x00; // Set all PORTB as output
    
    while(1)
    {
        PORTB = 0x01; // RB0 High
        _delay(100000); // Simple delay
        PORTB = 0x00; // RB0 Low
        _delay(100000);
    }
}