"""Rohde & Schwarz RTM2034 oscilloscope, SCPI over LAN (VXI-11 through pyvisa-py).

This step: connection, *IDN?, instrument error queue, screenshot to PNG.
Channel setup, trigger, single-shot and measurements follow once the manual
measurement has been done by hand and the commands checked against the
RTM2000 manual. Anything marked ASSUMPTION below has two known spellings in
the R&S families and needs to be confirmed on this instrument.

Standalone:
    python -m bench.scope --idn
    python -m bench.scope --errors
    python -m bench.scope --screenshot reports/screenshots/test.png

Exit code 0 on success, 1 on any failure.
"""

import argparse
import contextlib
import logging
import os
import sys
import time

import pyvisa

from bench import config
from bench.common import setup_logging, visa

LOG = logging.getLogger("bench.scope")


class ScopeError(RuntimeError):
    """Anything that stops us from controlling the scope. The message says why."""


TERMINATOR = "\n"

CMD_IDN = "*IDN?"
CMD_OPC = "*OPC?"                    # answers "1" when all previous commands are done
CMD_ERROR = "SYSTem:ERRor?"          # pops one entry from the error queue, '0,"No error"' when empty
CMD_SCREEN_FORMAT = "HCOPy:LANGuage PNG"   # ASSUMPTION: RTM2000 spelling; RTB2000 uses HCOPy:FORMat PNG
CMD_SCREEN_DATA = "HCOPy:DATA?"      # screenshot as an IEEE 488.2 definite-length block


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def open_scope(resource=config.SCOPE_RESOURCE, timeout_ms=config.SCOPE_TIMEOUT_MS):
    """Open the scope, hand out the pyvisa instrument, close it again no matter what.

    Nothing about the scope's state is changed on open or close. Whatever
    setup is on the screen stays there; the sequence configures explicitly.
    """
    inst = None
    LOG.info("open %s (timeout=%d ms)", resource, timeout_ms)
    try:
        try:
            inst = visa().open_resource(resource)
        except pyvisa.VisaIOError as exc:
            raise ScopeError(f"cannot open {resource}: {exc}")
        inst.write_termination = TERMINATOR
        inst.read_termination = TERMINATOR
        inst.timeout = timeout_ms
        yield inst
    finally:
        if inst is not None:
            try:
                inst.close()
                LOG.info("closed %s", resource)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Transfers
# ---------------------------------------------------------------------------

def query(inst, cmd, retries=config.SCOPE_RETRIES):
    """Send a command that expects a text answer, return it as a string."""
    attempts = retries + 1
    for n in range(1, attempts + 1):
        t0 = time.monotonic()
        try:
            LOG.debug("tx [%d/%d] %r", n, attempts, cmd)
            inst.write(cmd)
            answer = inst.read().strip()
            LOG.debug("rx %r (%.0f ms)", answer, (time.monotonic() - t0) * 1e3)
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
    raise ScopeError(f"no answer to {cmd!r} after {attempts} attempts")


def command(inst, cmd):
    """Send a command that expects no answer, then check the error queue.

    R&S instruments do not acknowledge set commands. The only way to know a
    command was accepted is to ask the error queue afterwards, so every
    command() does that. Slower than fire-and-forget, but a typo in a SCPI
    string fails at the line that caused it instead of three lines later.
    """
    LOG.debug("tx %r", cmd)
    try:
        inst.write(cmd)
    except pyvisa.VisaIOError as exc:
        raise ScopeError(f"write {cmd!r} failed: {exc}")
    err = query(inst, CMD_ERROR)
    if not err.startswith("0,"):
        raise ScopeError(f"scope rejected {cmd!r}: {err}")


def wait_done(inst, timeout_ms=None):
    """Block until the scope has finished everything sent so far (*OPC?)."""
    saved = inst.timeout
    if timeout_ms is not None:
        inst.timeout = timeout_ms
    try:
        answer = query(inst, CMD_OPC, retries=0)
    finally:
        inst.timeout = saved
    if answer != "1":
        raise ScopeError(f"unexpected *OPC? answer {answer!r}")


# ---------------------------------------------------------------------------
# Instrument functions
# ---------------------------------------------------------------------------

def idn(inst):
    answer = query(inst, CMD_IDN)
    LOG.info("IDN: %s", answer)
    return answer


def errors(inst, limit=20):
    """Drain the error queue. Returns the list of entries, empty when clean."""
    found = []
    for _ in range(limit):
        err = query(inst, CMD_ERROR)
        if err.startswith("0,"):
            break
        LOG.warning("scope error: %s", err)
        found.append(err)
    return found


def screenshot(inst, path):
    """Save what is on the screen as PNG. Returns the number of bytes written.

    The screenshot is the evidence for every measurement in the report, so
    this is the first thing to verify on the scope after *IDN?.
    """
    command(inst, CMD_SCREEN_FORMAT)
    LOG.debug("tx %r", CMD_SCREEN_DATA)
    saved = inst.timeout
    inst.timeout = config.SCOPE_SCREENSHOT_TIMEOUT_MS
    try:
        data = inst.query_binary_values(CMD_SCREEN_DATA, datatype="B", container=bytes)
    except pyvisa.VisaIOError as exc:
        raise ScopeError(f"screenshot transfer failed: {exc}")
    finally:
        inst.timeout = saved
    if not data.startswith(b"\x89PNG"):
        raise ScopeError(f"screenshot is not a PNG ({len(data)} bytes, starts {data[:8]!r})")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    LOG.info("screenshot %s (%d bytes)", path, len(data))
    return len(data)



# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(
        prog="python -m bench.scope",
        description="R&S RTM2034 connection check. Actions run in this order: "
                    "--idn --errors --screenshot")
    p.add_argument("--resource", default=config.SCOPE_RESOURCE,
                   help="VISA resource string; default from config")
    p.add_argument("--idn", action="store_true")
    p.add_argument("--errors", action="store_true", help="drain and print the error queue")
    p.add_argument("--screenshot", metavar="PNG", help="save the screen to this file")
    p.add_argument("-v", "--verbose", action="count", default=0)
    args = p.parse_args(argv)
    setup_logging(args.verbose)

    if not (args.idn or args.errors or args.screenshot):
        p.print_help()
        return 1

    try:
        with open_scope(args.resource) as inst:
            if args.idn:
                print(idn(inst))
            if args.errors:
                found = errors(inst)
                print("\n".join(found) if found else "error queue empty")
            if args.screenshot:
                screenshot(inst, args.screenshot)
        return 0
    except ScopeError as exc:
        LOG.error("FAIL: %s", exc)
        return 1
    except KeyboardInterrupt:
        LOG.error("FAIL: aborted by user")
        return 1


if __name__ == "__main__":
    sys.exit(main())
