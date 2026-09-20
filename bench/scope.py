"""Rohde & Schwarz RTM2034 oscilloscope, SCPI over LAN (VXI-11 through pyvisa-py).

Verified 2026-09-20 on Rohde&Schwarz,RTM2034,5710.0999k34/101580,05.411:
connection over the raw socket, *IDN?, error queue, screenshot to PNG.

Also verified 2026-09-20: channel, timebase, edge trigger with noise
reject, single-shot with pre-trigger wait, built-in measurements, ASCII
waveform readout. command() checks the error queue after every set
command, so a wrong spelling fails at its own line with the instrument's
error text; that is how the spellings above were settled.

Manual: R&S RTM2000 User Manual 1317.4726.02, chapter 16 "Remote Control".

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
CMD_SCREEN_FORMAT = "HCOPy:LANGuage PNG"   # verified; RTB2000 would want HCOPy:FORMat
CMD_SCREEN_DATA = "HCOPy:DATA?"      # screenshot as an IEEE 488.2 definite-length block

# channel <ch> = 1..4
CMD_CH_STATE = "CHANnel{ch}:STATe {on}"
CMD_CH_COUPLING = "CHANnel{ch}:COUPling {coupling}"   # ASSUMPTION: DCLimit = 1 MOhm DC, ACLimit = 1 MOhm AC
CMD_CH_SCALE = "CHANnel{ch}:SCALe {volts_per_div}"
CMD_CH_POSITION = "CHANnel{ch}:POSition {divisions}"  # ASSUMPTION: vertical position in divisions
CMD_CH_BANDWIDTH = "CHANnel{ch}:BANDwidth {bw}"       # FULL | B20

CMD_TB_SCALE = "TIMebase:SCALe {seconds_per_div}"
CMD_TB_POSITION = "TIMebase:POSition {seconds}"

CMD_TRIG_MODE = "TRIGger:A:MODE {mode}"               # AUTO | NORMal
CMD_TRIG_TYPE = "TRIGger:A:TYPE EDGE"
CMD_TRIG_SOURCE = "TRIGger:A:SOURce CH{ch}"
CMD_TRIG_SLOPE = "TRIGger:A:EDGE:SLOPe {slope}"       # POSitive | NEGative
CMD_TRIG_LEVEL = "TRIGger:A:LEVel{ch} {volts}"        # verified: level index = source channel
CMD_TRIG_NREJECT = "TRIGger:A:EDGE:FILTer:NREJect {on}"   # verified; HFReject and FILTer:HF are rejected (-113)

CMD_SINGLE = "SINGle"
CMD_RUN = "RUN"
CMD_STOP = "STOP"

# automatic measurements, slot <m> = 1..6 on the RTM2000
CMD_MEAS_ENABLE = "MEASurement{m}:ENABle {on}"
CMD_MEAS_SOURCE = "MEASurement{m}:SOURce CH{ch}"
CMD_MEAS_TYPE = "MEASurement{m}:MAIN {kind}"         # RTIMe FTIMe PEAK MEAN FREQuency ...
CMD_MEAS_RESULT = "MEASurement{m}:RESult:ACTual?"   # verified 2026-09-20

CMD_DATA_FORMAT = "FORMat:DATA ASCii"
CMD_DATA_HEADER = "CHANnel{ch}:DATA:HEADer?"          # xstart, xstop, record length, values per interval
CMD_DATA = "CHANnel{ch}:DATA?"


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
            shown = answer if len(answer) <= 60 else f"{answer[:60]}... ({len(answer)} chars)"
            LOG.debug("rx %r (%.0f ms)", shown, (time.monotonic() - t0) * 1e3)
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
    try:
        with open(path, "wb") as f:
            f.write(data)
    except OSError as exc:
        # Windows refuses to overwrite a PNG that is open in a viewer. The
        # capture is the valuable part; keep it under a fresh name instead.
        root, ext = os.path.splitext(path)
        path = f"{root}_{time.strftime('%H%M%S')}{ext}"
        LOG.warning("could not write the requested file (%s); saving as %s", exc, path)
        with open(path, "wb") as f:
            f.write(data)
    LOG.info("screenshot %s (%d bytes)", path, len(data))
    return path


def setup_channel(inst, ch, volts_per_div, position_div=0.0,
                  coupling="DCLimit", bandwidth="FULL"):
    """Vertical setup of one channel. position_div moves the ground line:
    -2.5 puts 0 V two and a half divisions below centre."""
    command(inst, CMD_CH_STATE.format(ch=ch, on="ON"))
    command(inst, CMD_CH_COUPLING.format(ch=ch, coupling=coupling))
    command(inst, CMD_CH_BANDWIDTH.format(ch=ch, bw=bandwidth))
    command(inst, CMD_CH_SCALE.format(ch=ch, volts_per_div=volts_per_div))
    command(inst, CMD_CH_POSITION.format(ch=ch, divisions=position_div))
    LOG.info("CH%d: %s V/div, pos %.1f div, %s, bw %s", ch, volts_per_div, position_div,
             coupling, bandwidth)


def setup_timebase(inst, seconds_per_div, position_s=0.0):
    """Horizontal setup. position_s shifts the trigger point on screen."""
    command(inst, CMD_TB_SCALE.format(seconds_per_div=seconds_per_div))
    command(inst, CMD_TB_POSITION.format(seconds=position_s))
    LOG.info("timebase %s s/div, pos %s s", seconds_per_div, position_s)


def setup_trigger(inst, ch, volts, slope="POSitive", mode="NORMal", noise_reject=True):
    """Edge trigger on one channel. NORMal: draw only when the edge occurs.

    noise_reject filters the trigger path. Without it, switching spikes on
    a 5 V rail cross a 2 V level in both directions and the scope fires on
    a spike instead of the edge (2026-09-20, two runs, two different
    trigger points on the same ramp). Combine with a 20 MHz channel limit.
    """
    command(inst, CMD_TRIG_MODE.format(mode=mode))
    command(inst, CMD_TRIG_TYPE)
    command(inst, CMD_TRIG_SOURCE.format(ch=ch))
    command(inst, CMD_TRIG_SLOPE.format(slope=slope))
    command(inst, CMD_TRIG_LEVEL.format(ch=ch, volts=volts))
    command(inst, CMD_TRIG_NREJECT.format(on="ON" if noise_reject else "OFF"))
    LOG.info("trigger CH%d %s at %.2f V, %s, noise reject %s", ch, slope, volts, mode,
             "on" if noise_reject else "off")


def arm_single(inst, seconds_per_div, reference=0.5):
    """Arm one acquisition and wait until the scope is actually ready to trigger.

    After SINGle the scope first fills its pre-trigger memory: with the
    trigger at screen centre that is half the screen width. An edge that
    arrives before the buffer is full is recorded but NOT treated as the
    trigger; the scope then fires on the next crossing, which on a noisy
    rail is a spike (2026-09-20: ramp at the left edge, trigger on a spike).
    So this returns only after 10 * seconds_per_div * reference plus margin.
    """
    command(inst, CMD_SINGLE)
    pretrigger = 10 * seconds_per_div * reference
    time.sleep(pretrigger + config.SCOPE_ARM_MARGIN_S)
    LOG.info("armed, pre-trigger buffer full after %.2f s, waiting for trigger", pretrigger)


def wait_acquired(inst, timeout_s):
    """Block until the armed acquisition has completed, or fail after timeout_s.

    ASSUMPTION: *OPC? does not answer until the single acquisition is done.
    That is the documented R&S pattern (SINGle;*OPC?).
    """
    t0 = time.monotonic()
    wait_done(inst, timeout_ms=int(timeout_s * 1000))
    LOG.info("acquired after %.0f ms", (time.monotonic() - t0) * 1e3)


def measurement(inst, slot, ch, kind):
    """Let the scope compute one of its built-in measurements on the current record.

    kind: RTIMe (10-90 % rise), FTIMe, PEAK (Vpp), MEAN, FREQuency, ...
    Returns the value as float. Used next to the numpy evaluation so the
    two can be compared; a disagreement means one of them is wrong.
    """
    command(inst, CMD_MEAS_ENABLE.format(m=slot, on="ON"))
    command(inst, CMD_MEAS_SOURCE.format(m=slot, ch=ch))
    command(inst, CMD_MEAS_TYPE.format(m=slot, kind=kind))
    wait_done(inst)                                  # let the measurement update
    value = float(query(inst, CMD_MEAS_RESULT.format(m=slot)))
    LOG.info("scope measurement %d: %s on CH%d = %g", slot, kind, ch, value)
    return value


def waveform(inst, ch):
    """Read the displayed record of one channel. Returns (time_s, volts) as numpy arrays.

    ASCII transfer: slow for long records but nothing to get wrong. Switch
    to REAL,32 once the measurements need more than ~100k points.
    """
    import numpy as np
    command(inst, CMD_DATA_FORMAT)
    header = query(inst, CMD_DATA_HEADER.format(ch=ch)).split(",")
    x_start, x_stop, points = float(header[0]), float(header[1]), int(header[2])
    saved = inst.timeout
    inst.timeout = config.SCOPE_WAVEFORM_TIMEOUT_MS
    try:
        raw = query(inst, CMD_DATA.format(ch=ch), retries=0)
    finally:
        inst.timeout = saved
    volts = np.array(raw.split(","), dtype=float)
    if len(volts) != points:
        LOG.warning("header says %d points, got %d", points, len(volts))
    t = np.linspace(x_start, x_stop, len(volts))
    LOG.info("CH%d waveform: %d points, %.3g s to %.3g s", ch, len(volts), x_start, x_stop)
    return t, volts


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
