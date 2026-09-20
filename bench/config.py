"""Bench configuration: what is true about THIS table.

Ports and addresses, which instruments these are and what they are rated
for, the load resistors as measured, and the setup version written into
every record. How an instrument behaves (timing, tolerances, protocol) is in
the instrument's module; the devices under test are in bench/duts.toml.

Config is read, never written. Measured results go into the JSON records and
into docs/, not into this file.
"""

# Bumped whenever wiring, probes, load or instruments change. Written into
# every JSON record so a result can always be tied to the setup it came from.
SETUP_VERSION = "0.1"

# --- Supply: OWON SPE3102, USB-serial ----------------------------------------
# psu.py speaks the OWON SPE family; which member sits here, and its rating,
# is a property of this bench.
PSU_IDN_PREFIX = "OWON,SPE3102" # what *IDN? must start with
PSU_MAX_VOLT = 30.0             # rating; setpoints above are refused
PSU_MAX_CURR = 10.0
PSU_PORT = None                 # "COM7" to pin it; None = find by USB vendor ID
PSU_PROBE_VIDS = {0x1A86}       # CH340 bridge inside the supply (COM7 on this PC)
PSU_BAUD = 115200               # instrument menu setting

# --- Scope: Rohde & Schwarz RTM2034, raw SCPI socket over LAN ----------------
SCOPE_RESOURCE = "TCPIP0::192.168.178.78::5025::SOCKET"   # IP pinned in the router

# --- Load switch: Raspberry Pi Pico running firmware/main.py, USB-serial ----
LOAD_PORT = None                # "COM5" to pin it; None = find by USB vendor ID
LOAD_PROBE_VIDS = {0x2E8A}      # Raspberry Pi (COM5 on this PC)

# --- Load resistors, DMM at the resistor leads, cold ------------------------
LOAD_R_5 = 5.14                 # "5 R / 25 W", 2026-09-20
LOAD_R_10 = 10.0                # "10 R / 25 W", DMM value pending

# --- Bench-level safety ------------------------------------------------------
# Never set the supply above this, whatever the DUT: the MP1584 dies at 28 V.
BENCH_MAX_VIN_V = 28.0
