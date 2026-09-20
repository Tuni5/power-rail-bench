"""Load switch: Raspberry Pi Pico running firmware/main.py, line protocol over USB.

Same shape as psu.py. Protocol (see firmware/main.py):
    IDN           -> BENCH,LOAD-SWITCH,GP15,0.1
    LOAD ON/OFF   -> OK
    LOAD?         -> ON / OFF
    STEP <ms>     -> OK, sent after the step has finished
    anything else -> ERR <reason>

Standalone:
    python -m bench.load --idn
    python -m bench.load --on
    python -m bench.load --off
    python -m bench.load --step 200
    python -m bench.load --state

Exit code 0 on success, 1 on any failure.
"""

import argparse
import contextlib
import logging
import sys
import time

import pyvisa

from bench import config
from bench.common import find_port, resource_name, scan_ports, setup_logging, visa

LOG = logging.getLogger("bench.load")


class LoadError(RuntimeError):
    """Anything that stops us from controlling the load. The message says why."""


IDN_PREFIX = "BENCH,LOAD-SWITCH"   # what IDN must start with (firmware/main.py)
TERMINATOR = "\n"

TIMEOUT_MS = 2000               # per query
PROBE_TIMEOUT_MS = 1000         # per port while searching
RETRIES = 1                     # extra attempts per query
OPEN_SETTLE_S = 0.3             # after opening the CDC port; not tested whether needed

CMD_IDN = "IDN"
CMD_ON = "LOAD ON"
CMD_OFF = "LOAD OFF"
CMD_STATE = "LOAD?"
CMD_STEP = "STEP {:d}"


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def open_load(port, timeout_ms=TIMEOUT_MS):
    """Open the Pico, hand out the pyvisa instrument, close it again no matter what.

    Closing does not switch the load. The firmware keeps its state until
    told otherwise, or until the Pico loses power (then the module's
    pull-down keeps the MOSFET off).
    """
    try:
        name = resource_name(port)
    except ValueError as exc:
        raise LoadError(str(exc))

    inst = None
    LOG.info("open %s (timeout=%d ms)", name, timeout_ms)
    try:
        try:
            inst = visa().open_resource(name)
        except pyvisa.VisaIOError as exc:
            raise LoadError(f"cannot open {name}: {exc}")
        inst.write_termination = TERMINATOR
        inst.read_termination = TERMINATOR
        inst.timeout = timeout_ms
        time.sleep(OPEN_SETTLE_S)
        yield inst
    finally:
        if inst is not None:
            try:
                inst.close()
                LOG.info("closed %s", name)
            except Exception:
                pass


def find_load():
    """Which port has the Pico? Ask every port with the Raspberry Pi vendor ID."""
    def ask(port):
        with open_load(port, timeout_ms=PROBE_TIMEOUT_MS) as inst:
            return query(inst, CMD_IDN, retries=0)
    try:
        return find_port(config.LOAD_PROBE_VIDS, ask, IDN_PREFIX, "load switch")
    except LookupError as exc:
        raise LoadError(str(exc))


def resolve_port(port):
    """Command-line port wins, then config.LOAD_PORT, then auto-detect."""
    if port:
        return port
    if config.LOAD_PORT:
        return config.LOAD_PORT
    LOG.info("no port configured, probing for %s", IDN_PREFIX)
    return find_load()


# ---------------------------------------------------------------------------
# Transfer. The firmware answers every command, so one function is enough.
# ---------------------------------------------------------------------------

def query(inst, cmd, retries=RETRIES):
    """Send one line, read one line. ERR from the firmware and timeouts both raise."""
    attempts = retries + 1
    for n in range(1, attempts + 1):
        t0 = time.monotonic()
        try:
            LOG.debug("tx [%d/%d] %r", n, attempts, cmd)
            inst.write(cmd)
            answer = inst.read().strip()
            LOG.debug("rx %r (%.0f ms)", answer, (time.monotonic() - t0) * 1e3)
            if answer.startswith("ERR"):
                raise LoadError(f"firmware rejected {cmd!r}: {answer}")
            if answer:
                return answer
            LOG.warning("empty answer to %r (attempt %d/%d)", cmd, n, attempts)
        except pyvisa.VisaIOError as exc:
            LOG.warning("no answer to %r after %.0f ms (attempt %d/%d): %s",
                        cmd, (time.monotonic() - t0) * 1e3, n, attempts, exc)
        try:
            inst.clear()
        except Exception:
            pass
    raise LoadError(f"no answer to {cmd!r} after {attempts} attempts")


# ---------------------------------------------------------------------------
# Instrument functions
# ---------------------------------------------------------------------------

def idn(inst):
    answer = query(inst, CMD_IDN)
    LOG.info("IDN: %s", answer)
    return answer


def is_on(inst):
    """True if the load is switched on, as reported by the pin state."""
    answer = query(inst, CMD_STATE).upper()
    if answer == "ON":
        return True
    if answer == "OFF":
        return False
    raise LoadError(f"cannot interpret state {answer!r}")


def load(inst, on):
    """Switch the load on or off and confirm by reading the pin back."""
    answer = query(inst, CMD_ON if on else CMD_OFF)
    if answer != "OK":
        raise LoadError(f"unexpected reply {answer!r}")
    if is_on(inst) != on:
        raise LoadError(f"load did not switch {'ON' if on else 'OFF'}")
    LOG.info("load %s", "ON" if on else "OFF")


def step(inst, ms):
    """Load on for ms milliseconds, then off. Returns when the firmware says so.

    The firmware only answers after the step, so the read timeout has to be
    at least as long as the step itself.
    """
    if ms < 1:
        raise LoadError("step length must be at least 1 ms")
    normal_timeout = inst.timeout
    inst.timeout = ms + TIMEOUT_MS
    try:
        answer = query(inst, CMD_STEP.format(ms), retries=0)   # a retry would step twice
    finally:
        inst.timeout = normal_timeout
    if answer != "OK":
        raise LoadError(f"unexpected reply {answer!r} to STEP")
    if is_on(inst):
        raise LoadError(f"load still ON after STEP {ms} ms")
    LOG.info("step %d ms done, load OFF", ms)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(
        prog="python -m bench.load",
        description="Pico load switch control. Actions run in this order: "
                    "--idn --off --on --step --state")
    p.add_argument("--port", help="COM5; default from config, else auto-detect")
    p.add_argument("--scan", action="store_true", help="list serial ports with VID/PID")
    p.add_argument("--idn", action="store_true")
    p.add_argument("--off", action="store_true")
    p.add_argument("--on", action="store_true")
    p.add_argument("--step", type=int, metavar="MS", help="on for MS milliseconds, then off")
    p.add_argument("--state", action="store_true", help="print ON or OFF")
    p.add_argument("-v", "--verbose", action="count", default=0)
    args = p.parse_args(argv)
    setup_logging(args.verbose)

    if args.scan:
        scan_ports()

    needs_instrument = args.idn or args.off or args.on or args.step is not None or args.state
    if not needs_instrument:
        if not args.scan:
            p.print_help()
            return 1
        return 0

    try:
        with open_load(resolve_port(args.port)) as inst:
            if args.idn:
                print(idn(inst))
            if args.off:
                load(inst, False)
            if args.on:
                load(inst, True)
            if args.step is not None:
                step(inst, args.step)
            if args.state:
                print("ON" if is_on(inst) else "OFF")
        return 0
    except LoadError as exc:
        LOG.error("FAIL: %s", exc)
        return 1
    except KeyboardInterrupt:
        LOG.error("FAIL: aborted by user")
        return 1


if __name__ == "__main__":
    sys.exit(main())
