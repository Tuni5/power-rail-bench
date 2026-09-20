# Load switch firmware for the power-rail-bench, Raspberry Pi Pico, MicroPython.
#
# Drives the TRIG input of the MOSFET load module from one GPIO and answers
# line commands on the USB serial port. Runs at boot as main.py; Ctrl-C from
# a terminal drops back to the REPL.
#
# Commands (case-insensitive, one per line, newline-terminated):
#     IDN          -> BENCH,LOAD-SWITCH,GP15,0.1
#     LOAD ON      -> OK          load on, pin high
#     LOAD OFF     -> OK          load off, pin low
#     LOAD?        -> ON / OFF    current pin state
#     STEP <ms>    -> OK          load on for <ms> milliseconds, then off;
#                                 reply comes after the step has finished
# Anything else  -> ERR <reason>
#
# The pin is low at boot and after every error path: the load is never on
# unless a command switched it on, and the module's own pull-down keeps it
# off while the Pico is unpowered.

import sys
from machine import Pin

VERSION = "0.1"
TRIG_GPIO = 15                 # Pico pin 20; GND on pin 18 next to it
STEP_MAX_MS = 60000            # refuse longer steps; 5 W in a 25 W resistor
                               # is fine forever, this is about typos

trig = Pin(TRIG_GPIO, Pin.OUT, value=0)
led = Pin("LED", Pin.OUT, value=0)


def set_load(on):
    trig.value(1 if on else 0)
    led.value(1 if on else 0)


def handle(line):
    parts = line.strip().upper().split()
    if not parts:
        return None
    cmd = parts[0]

    if cmd == "IDN" and len(parts) == 1:
        return "BENCH,LOAD-SWITCH,GP{},{}".format(TRIG_GPIO, VERSION)

    if cmd == "LOAD" and len(parts) == 2:
        if parts[1] == "ON":
            set_load(True)
            return "OK"
        if parts[1] == "OFF":
            set_load(False)
            return "OK"
        return "ERR LOAD takes ON or OFF"

    if cmd == "LOAD?" and len(parts) == 1:
        return "ON" if trig.value() else "OFF"

    if cmd == "STEP" and len(parts) == 2:
        try:
            ms = int(parts[1])
        except ValueError:
            return "ERR STEP needs an integer millisecond count"
        if not 1 <= ms <= STEP_MAX_MS:
            return "ERR STEP range is 1..{} ms".format(STEP_MAX_MS)
        import time
        set_load(True)
        time.sleep_ms(ms)
        set_load(False)
        return "OK"

    return "ERR unknown command: " + line.strip()


def main():
    set_load(False)
    while True:
        line = sys.stdin.readline()
        if not line:
            continue
        reply = handle(line)
        if reply is not None:
            sys.stdout.write(reply + "\n")


try:
    main()
finally:
    set_load(False)
