"""Shared helpers: logging setup, serial port scan, port auto-detect.

No instrument knowledge here. Everything that talks SCPI or the Pico
protocol lives in the module for that instrument.
"""

import logging
import re
import tomllib
from pathlib import Path

import pyvisa
from serial.tools import list_ports

DUTS_FILE = Path(__file__).resolve().parent / "duts.toml"   # next to config.py

LOG = logging.getLogger("bench")

_rm = None


def visa():
    """The one ResourceManager for this process.

    pyvisa hands every caller the same manager object per backend, so closing
    it anywhere closes every open instrument. Nobody closes this one; pyvisa
    releases it when the interpreter exits.
    """
    global _rm
    if _rm is None:
        _rm = pyvisa.ResourceManager("@py")
    return _rm


def setup_logging(verbose=0):
    """One log format for every module.

    -v  shows our own transfers (tx/rx lines)
    -vv shows pyvisa internals as well
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    if verbose < 2:
        logging.getLogger("pyvisa").setLevel(logging.WARNING)


def resource_name(port):
    """Turn 'COM7' or '/dev/ttyUSB0' into the VISA form pyvisa expects.

    A string that already looks like a VISA resource is passed through.
    """
    port = port.strip()
    if re.match(r"^(ASRL|TCPIP|USB|GPIB)", port, re.IGNORECASE):
        return port
    if re.match(r"^COM\d+$", port, re.IGNORECASE):
        return f"ASRL{port[3:]}::INSTR"            # COM7 -> ASRL7::INSTR
    if port.startswith("/dev/"):
        return f"ASRL{port}::INSTR"                # /dev/ttyUSB0 -> ASRL/dev/ttyUSB0::INSTR
    raise ValueError(f"cannot interpret port {port!r} as a VISA resource")


def scan_ports():
    """List serial ports with their USB vendor/product IDs. Returns the list."""
    ports = sorted(list_ports.comports(), key=lambda p: p.device)
    for p in ports:
        vid = f"{p.vid:04X}" if p.vid is not None else "----"
        pid = f"{p.pid:04X}" if p.pid is not None else "----"
        LOG.info("port %-12s vid=%s pid=%s  %s", p.device, vid, pid, p.description)
    if not ports:
        LOG.warning("no serial ports found")
    return ports


def find_port(probe_vids, ask_identity, expected_prefix, what):
    """Find the serial port of one instrument by asking each candidate who it is.

    probe_vids       USB vendor IDs worth asking; every other port is left alone,
                     so a debugger or programmer on the same PC never sees our traffic
    ask_identity     function(port) -> identity string, raises on failure
    expected_prefix  what the identity string must start with
    what             name for the log, e.g. "supply"

    Returns the port name. Raises LookupError if nothing matched.
    """
    for p in scan_ports():
        if p.vid not in probe_vids:
            LOG.info("skip %s (vid not in probe list)", p.device)
            continue
        try:
            identity = ask_identity(p.device)
        except Exception as exc:
            LOG.info("%s: no usable answer (%s)", p.device, exc)
            continue
        if identity.startswith(expected_prefix):
            LOG.info("%s found on %s: %s", what, p.device, identity)
            return p.device
        LOG.info("%s answered %r, not the %s", p.device, identity, what)
    raise LookupError(f"no {expected_prefix} found on any serial port")


def dut(dut_id):
    """One device-under-test block from duts.toml, by its table name.

    Raises KeyError with the available ids if the name is unknown, so a typo
    on the command line fails before any instrument is touched.
    """
    with open(DUTS_FILE, "rb") as f:
        table = tomllib.load(f)
    if dut_id not in table:
        raise KeyError(f"unknown DUT {dut_id!r}; duts.toml has: {', '.join(table)}")
    entry = dict(table[dut_id])
    entry["id"] = dut_id
    return entry
