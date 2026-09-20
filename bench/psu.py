"""OWON SPE3102 bench supply, SCPI over USB-serial.

This module knows how to talk to an SPE3102. Which port, which limits and
which bench it sits on come from bench/config.py.

Command set: from the owon-psu library (github.com/robbederks/owon-psu-control,
MIT), confirmed command by command on this SPE3102 on 2026-09-20.
Two protocol facts everything below relies on:
  - set commands are silent on success and answer "ERR" when refused
  - queries answer with a bare number, e.g. "12.000"

Standalone:
    python -m bench.psu --scan
    python -m bench.psu --idn
    python -m bench.psu --ovp 6 --ocp 1 --volt 5 --curr 0.5 --on
    python -m bench.psu --meas
    python -m bench.psu --off

Exit code 0 on success, 1 on any failure.
"""

import argparse
import contextlib
import logging
import sys
import time

import pyvisa
from pyvisa.constants import ControlFlow, Parity, StopBits

from bench import config
from bench.common import find_port, resource_name, scan_ports, setup_logging, visa

LOG = logging.getLogger("bench.psu")


class PsuError(RuntimeError):
    """Anything that stops us from controlling the supply. The message says why."""


# ---------------------------------------------------------------------------
# Instrument. Verified on OWON,SPE3102,25330431,FV:V5.2.0 (2026-09-20).
# ---------------------------------------------------------------------------

# serial framing; baud rate, model identity and rating come from config,
# because they belong to the unit on this bench, not to the SPE family
DATA_BITS = 8
PARITY = Parity.none
STOP_BITS = StopBits.one
FLOW = ControlFlow.none
TERMINATOR = "\n"

CMD_IDN = "*IDN?"
CMD_SET_VOLT = "VOLTage {:.3f}"
CMD_GET_VOLT = "VOLTage?"
CMD_SET_CURR = "CURRent {:.3f}"
CMD_GET_CURR = "CURRent?"
CMD_SET_OVP = "VOLTage:LIMit {:.3f}"
CMD_GET_OVP = "VOLTage:LIMit?"
CMD_SET_OCP = "CURRent:LIMit {:.3f}"
CMD_GET_OCP = "CURRent:LIMit?"
CMD_OUTPUT_ON = "OUTPut ON"
CMD_OUTPUT_OFF = "OUTPut OFF"
CMD_GET_OUTPUT = "OUTPut?"          # answers ON or OFF
CMD_MEAS_VOLT = "MEASure:VOLTage?"
CMD_MEAS_CURR = "MEASure:CURRent?"

# --- timing and tolerances, all from observing this instrument ---------------
TIMEOUT_MS = 3000               # per query
PROBE_TIMEOUT_MS = 1000         # per port while searching
RETRIES = 2                     # extra attempts per query
OPEN_SETTLE_S = 0.3             # after opening the port; not tested whether needed
SET_REPLY_WINDOW_MS = 50        # how long to listen for "ERR" after a set command
OUTPUT_SETTLE_S = 0.2           # after OUTPut ON/OFF; a query right after was lost once
READBACK_TOL_V = 0.002          # setpoint resolution is 1 mV / 1 mA
READBACK_TOL_A = 0.002
ON_TIMEOUT_S = 2.0              # output must reach the setpoint within this
ON_TOL_REL = 0.01               # ... to within 1 % ...
ON_TOL_ABS_V = 0.05             # ... or 50 mV, whichever is larger
ON_POLL_S = 0.2                 # MEASure:VOLTage? poll interval
ON_STABLE_READS = 2             # target must hold for this many polls in a row
MEAS_SETTLE_S = 2.0             # after a load change; the current readout is slow


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def open_psu(port, timeout_ms=TIMEOUT_MS):
    """Open the supply, hand out the pyvisa instrument, close it again no matter what.

        with open_psu("COM7") as inst:
            idn(inst)

    Closing does NOT touch the output. If a run dies with 12 V on the DUT,
    the 12 V stay on. Switching off is a deliberate call in the sequence,
    never a side effect of a crash.
    """
    try:
        name = resource_name(port)
    except ValueError as exc:
        raise PsuError(str(exc))

    inst = None
    LOG.info("open %s (baud=%d, timeout=%d ms)", name, config.PSU_BAUD, timeout_ms)
    try:
        try:
            inst = visa().open_resource(name)
        except pyvisa.VisaIOError as exc:
            raise PsuError(f"cannot open {name}: {exc}")

        inst.baud_rate = config.PSU_BAUD
        inst.data_bits = DATA_BITS
        inst.parity = PARITY
        inst.stop_bits = STOP_BITS
        inst.flow_control = FLOW
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
                pass                            # already gone; nothing left to do


def find_psu():
    """Which port has the supply? Ask every port with the CH340 vendor ID."""
    def ask(port):
        with open_psu(port, timeout_ms=PROBE_TIMEOUT_MS) as inst:
            return query(inst, CMD_IDN, retries=0)
    try:
        return find_port(config.PSU_PROBE_VIDS, ask, config.PSU_IDN_PREFIX, "supply")
    except LookupError as exc:
        raise PsuError(str(exc))


def resolve_port(port):
    """Command-line port wins, then config.PSU_PORT, then auto-detect."""
    if port:
        return port
    if config.PSU_PORT:
        return config.PSU_PORT
    LOG.info("no port configured, probing for %s", config.PSU_IDN_PREFIX)
    return find_psu()


# ---------------------------------------------------------------------------
# Transfers. Everything goes through these two.
# ---------------------------------------------------------------------------

def query(inst, cmd, retries=RETRIES):
    """Send a command that expects an answer, return the answer as a string.

    Retries on timeout. Never hangs, never invents a value: after the last
    attempt it raises PsuError and the caller turns that into a FAIL.
    """
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
            inst.clear()                        # drop half-received bytes before retrying
        except Exception:
            pass
    raise PsuError(f"no answer to {cmd!r} after {attempts} attempts")


def command(inst, cmd):
    """Send a command that expects NO answer.

    The supply stays silent when it accepts a set command and sends "ERR"
    when it does not. So we listen briefly: silence is success.
    """
    LOG.debug("tx %r", cmd)
    try:
        inst.write(cmd)
    except pyvisa.VisaIOError as exc:
        raise PsuError(f"write {cmd!r} failed: {exc}")

    normal_timeout = inst.timeout
    inst.timeout = SET_REPLY_WINDOW_MS
    try:
        reply = inst.read().strip()
    except pyvisa.VisaIOError:
        reply = ""                              # timeout here is the good case
    finally:
        inst.timeout = normal_timeout

    if reply == "ERR":
        raise PsuError(f"supply rejected {cmd!r}")
    if reply:
        # Not seen so far. Logged and dropped so it cannot be mistaken for
        # the answer to the next query.
        LOG.warning("unexpected reply %r to %r (dropped)", reply, cmd)


# ---------------------------------------------------------------------------
# Instrument functions. Each setter reads its value back: what the supply
# confirms is what we log, not what we asked for.
# ---------------------------------------------------------------------------

def idn(inst):
    answer = query(inst, CMD_IDN)
    LOG.info("IDN: %s", answer)
    return answer


def set_voltage(inst, volts):
    """Voltage setpoint. Returns the value the supply confirms."""
    if not 0 <= volts <= config.PSU_MAX_VOLT:
        raise PsuError(f"voltage {volts} V outside 0..{config.PSU_MAX_VOLT} V")
    command(inst, CMD_SET_VOLT.format(volts))
    back = float(query(inst, CMD_GET_VOLT))
    if abs(back - volts) > READBACK_TOL_V:
        raise PsuError(f"voltage readback {back} V, asked for {volts} V")
    LOG.info("voltage setpoint %.3f V", back)
    return back


def set_current(inst, amps):
    """Current limit (CC threshold). Returns the value the supply confirms."""
    if not 0 <= amps <= config.PSU_MAX_CURR:
        raise PsuError(f"current {amps} A outside 0..{config.PSU_MAX_CURR} A")
    command(inst, CMD_SET_CURR.format(amps))
    back = float(query(inst, CMD_GET_CURR))
    if abs(back - amps) > READBACK_TOL_A:
        raise PsuError(f"current readback {back} A, asked for {amps} A")
    LOG.info("current limit %.3f A", back)
    return back


def set_ovp(inst, volts):
    """Over-voltage protection. Trips the output off above this."""
    if not 0 <= volts <= config.PSU_MAX_VOLT:
        raise PsuError(f"OVP {volts} V outside 0..{config.PSU_MAX_VOLT} V")
    command(inst, CMD_SET_OVP.format(volts))
    back = float(query(inst, CMD_GET_OVP))
    if abs(back - volts) > READBACK_TOL_V:
        raise PsuError(f"OVP readback {back} V, asked for {volts} V")
    LOG.info("OVP %.3f V", back)
    return back


def set_ocp(inst, amps):
    """Over-current protection. Trips the output off above this."""
    if not 0 <= amps <= config.PSU_MAX_CURR:
        raise PsuError(f"OCP {amps} A outside 0..{config.PSU_MAX_CURR} A")
    command(inst, CMD_SET_OCP.format(amps))
    back = float(query(inst, CMD_GET_OCP))
    if abs(back - amps) > READBACK_TOL_A:
        raise PsuError(f"OCP readback {back} A, asked for {amps} A")
    LOG.info("OCP %.3f A", back)
    return back


def output_is_on(inst):
    """True if the output is enabled."""
    answer = query(inst, CMD_GET_OUTPUT).upper()
    if answer == "ON":
        return True
    if answer == "OFF":
        return False
    raise PsuError(f"cannot interpret output state {answer!r}")


def output(inst, on):
    """Switch the output on or off and confirm it happened.

    Switching on also waits until the measured voltage has reached the
    setpoint. The output itself is up within ~100 ms (scope, 2026-09-20);
    what takes about a second is the supply's own readout catching up.
    Waiting for the readout is still right: it is the same value the
    sequence records afterwards.
    """
    command(inst, CMD_OUTPUT_ON if on else CMD_OUTPUT_OFF)
    # The relay takes a moment. A query sent right away was lost once
    # (2026-09-20); the pause avoids relying on the retry for that.
    time.sleep(OUTPUT_SETTLE_S)
    if output_is_on(inst) != on:
        raise PsuError(f"output did not switch {'ON' if on else 'OFF'}")
    LOG.info("output %s", "ON" if on else "OFF")
    if on:
        wait_for_voltage(inst, float(query(inst, CMD_GET_VOLT)))


def wait_for_voltage(inst, target, timeout_s=ON_TIMEOUT_S):
    """Poll the measured voltage until it sits at target. Returns seconds taken.

    "Sits at" means: within tolerance on PSU_ON_STABLE_READS consecutive polls.
    The first reading inside the band still belongs to the ramp's tail; the
    second one says the ramp is over.

    Fails if target is not held in time. On this bench that means one of
    two things, both worth a FAIL: the ramp is unusually slow, or the supply
    is in current limit because the DUT draws more than allowed.
    """
    tol = max(ON_TOL_ABS_V, ON_TOL_REL * target)
    t0 = time.monotonic()
    good_reads = 0
    while True:
        measured = float(query(inst, CMD_MEAS_VOLT))
        elapsed = time.monotonic() - t0
        good_reads = good_reads + 1 if abs(measured - target) <= tol else 0
        if good_reads >= ON_STABLE_READS:
            LOG.info("output at %.3f V after %.0f ms", measured, elapsed * 1e3)
            return elapsed
        if elapsed >= timeout_s:
            raise PsuError(f"output at {measured} V after {elapsed*1e3:.0f} ms, "
                           f"target {target} V (still ramping or in current limit)")
        time.sleep(ON_POLL_S)


def verify_voltage(inst):
    """Check that the output still sits at its setpoint. Returns the measured volts.

    Call this after the load has changed. wait_for_voltage only covers the
    ramp; a supply that drops into current limit once the load is switched on
    is only caught here. Raises PsuError if the voltage is off the setpoint.
    """
    target = float(query(inst, CMD_GET_VOLT))
    measured = float(query(inst, CMD_MEAS_VOLT))
    tol = max(ON_TOL_ABS_V, ON_TOL_REL * target)
    if abs(measured - target) > tol:
        raise PsuError(f"output at {measured:.3f} V, setpoint {target:.3f} V "
                       f"(supply in current limit or load fault)")
    LOG.info("output holds %.3f V under load", measured)
    return measured


def measure(inst):
    """Measured terminal voltage and output current, as (volts, amps).

    These are the supply's display values, updated about 3 times per second,
    and the current reading needs more than a second to settle after a load
    change (2026-09-20: still rising after 1 s). Good for static readings
    taken after PSU_MEAS_SETTLE_S; useless for anything dynamic, use the scope.
    """
    volts = float(query(inst, CMD_MEAS_VOLT))
    amps = float(query(inst, CMD_MEAS_CURR))
    LOG.info("measured %.3f V  %.3f A", volts, amps)
    return volts, amps


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(
        prog="python -m bench.psu",
        description="OWON SPE3102 control. Actions run in this order: "
                    "--idn --off --ovp --ocp --volt --curr --on --meas")
    p.add_argument("--port", help="COM7; default from config, else auto-detect")
    p.add_argument("--scan", action="store_true", help="list serial ports with VID/PID")
    p.add_argument("--idn", action="store_true")
    p.add_argument("--off", action="store_true")
    p.add_argument("--ovp", type=float, metavar="V")
    p.add_argument("--ocp", type=float, metavar="A")
    p.add_argument("--volt", type=float, metavar="V")
    p.add_argument("--curr", type=float, metavar="A")
    p.add_argument("--on", action="store_true")
    p.add_argument("--meas", action="store_true", help="print measured V and A")
    p.add_argument("-v", "--verbose", action="count", default=0)
    args = p.parse_args(argv)
    setup_logging(args.verbose)

    if args.scan:
        scan_ports()

    needs_instrument = (args.idn or args.off or args.on or args.meas
                        or args.ovp is not None or args.ocp is not None
                        or args.volt is not None or args.curr is not None)
    if not needs_instrument:
        if not args.scan:
            p.print_help()
            return 1
        return 0

    try:
        with open_psu(resolve_port(args.port)) as inst:
            if args.idn:
                print(idn(inst))
            if args.off:
                output(inst, False)
            if args.ovp is not None:
                set_ovp(inst, args.ovp)
            if args.ocp is not None:
                set_ocp(inst, args.ocp)
            if args.volt is not None:
                set_voltage(inst, args.volt)
            if args.curr is not None:
                set_current(inst, args.curr)
            if args.on:
                output(inst, True)
            if args.meas:
                volts, amps = measure(inst)
                print(f"{volts:.3f} V  {amps:.3f} A")
        return 0
    except PsuError as exc:
        LOG.error("FAIL: %s", exc)
        return 1
    except KeyboardInterrupt:
        LOG.error("FAIL: aborted by user")
        return 1


if __name__ == "__main__":
    sys.exit(main())
