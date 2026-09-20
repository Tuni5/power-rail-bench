"""Bench configuration: everything that depends on this particular setup.

Instrument addresses, USB identities, serial speeds, safety limits, and the
setup version that goes into every measurement record. Nothing in here is
protocol: SCPI command strings and framing live in the instrument modules.

When the bench changes (new cable, new port, different supply of the same
model), edit this file and nothing else.
"""

# Bumped whenever wiring, probes, load or instruments change. Written into
# every JSON record so a result can always be tied to the setup it came from.
SETUP_VERSION = "0.1"

# --- Supply: OWON SPE3102, SCPI over USB-serial -----------------------------
PSU_PORT = None                      # "COM7" to pin it; None = probe by VID
PSU_IDN_PREFIX = "OWON,SPE3102"      # what *IDN? must start with
PSU_PROBE_VIDS = {0x1A86}            # CH340 bridge inside the supply
                                     # verified 2026-09-20: COM7 1A86:7523
PSU_BAUD = 115200                    # verified 2026-09-20, instrument menu
PSU_TIMEOUT_MS = 3000                # per query
PSU_PROBE_TIMEOUT_MS = 1000          # per port while searching
PSU_RETRIES = 2                      # extra attempts per query
PSU_OPEN_SETTLE_S = 0.3              # ASSUMPTION: delay after opening the port
PSU_SET_REPLY_WINDOW_MS = 50         # how long to listen for "ERR" after a set
PSU_OUTPUT_SETTLE_S = 0.2            # pause after OUTPut ON/OFF before the readback;
                                     # 2026-09-20: one OUTPut? lost right after ON
PSU_MAX_VOLT = 30.0                  # instrument rating, refused above
PSU_MAX_CURR = 10.0
PSU_READBACK_TOL_V = 0.002           # setpoint resolution is 1 mV
PSU_READBACK_TOL_A = 0.002
PSU_ON_TIMEOUT_S = 2.0               # output must reach the setpoint within this
PSU_ON_TOL_REL = 0.01                # ... to within 1 % ...
PSU_ON_TOL_ABS_V = 0.05              # ... or 50 mV, whichever is larger
PSU_ON_POLL_S = 0.2                  # MEASure:VOLTage? poll interval
PSU_ON_STABLE_READS = 2              # target must hold for this many polls in a row
PSU_MEAS_SETTLE_S = 2.0              # wait this long after a load change before a
                                     # static reading; current readout is slow

# --- Load resistors, measured with a DMM at the resistor leads ---------------
LOAD_R_5 = 5.14                      # "5 R / 25 W", DMM 2026-09-20; supply sees 5.03-5.22 R
LOAD_R_10 = 10.0                     # "10 R / 25 W", DMM value pending; supply saw 10.3 R

# --- Scope: Rohde & Schwarz RTM2034, SCPI over LAN --------------------------
SCOPE_RESOURCE = "TCPIP0::192.168.178.78::5025::SOCKET"  # raw SCPI socket; verified 2026-09-20
                                        # IP via Fritz!Box DHCP, pinned there; MAC 40-d8-55-0e-98-5a
SCOPE_TIMEOUT_MS = 5000                 # per query
SCOPE_SCREENSHOT_TIMEOUT_MS = 15000     # PNG transfer takes a moment
SCOPE_WAVEFORM_TIMEOUT_MS = 30000       # ASCII waveform of a long record
SCOPE_RETRIES = 1
SCOPE_ARM_MARGIN_S = 0.2                # extra wait after the pre-trigger buffer is full

# --- Load switch: Raspberry Pi Pico, MicroPython, USB-serial ----------------
LOAD_PORT = None                     # "COM5" to pin it; None = probe by VID
LOAD_IDN_PREFIX = "BENCH,LOAD-SWITCH"  # what IDN must start with (firmware/main.py)
LOAD_PROBE_VIDS = {0x2E8A}           # Raspberry Pi
                                     # verified 2026-09-20: COM5 2E8A:0005
LOAD_BAUD = 115200                   # ignored on USB CDC, set for completeness
LOAD_TIMEOUT_MS = 2000
LOAD_PROBE_TIMEOUT_MS = 1000
LOAD_RETRIES = 1
LOAD_OPEN_SETTLE_S = 0.3             # ASSUMPTION: CDC port may need a moment
