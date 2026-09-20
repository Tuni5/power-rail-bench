"""Demo 3: the supply's turn-on ramp, captured by script.

Same measurement as the manual one (psu_ramp_manual.png): probe on the OWON
terminals, no load. The script sets what was set by hand, arms a single
shot, switches the output on, saves the screenshot and reads the waveform
back to compute the 10-90 % rise time and the time to settle within 1 %.

Compare the two screenshots and the rise time with the cursor reading.
If they agree, step 3 of the plan is done.

    python demo3_psu_ramp.py
"""

import argparse
import sys

import numpy as np

from bench import psu, scope
from bench.common import setup_logging

VOLTS = 5.0
CURR_LIMIT = 0.5
CH = 1
TB = 0.02           # s/div: 200 ms on screen, ramp is ~100 ms
SCREENSHOT = "reports/screenshots/psu_ramp_script.png"


def median5(v):
    """Median of five neighbours: removes single-sample spikes, keeps edges."""
    pad = np.pad(v, 2, mode="edge")
    return np.median(np.stack([pad[i:i + len(v)] for i in range(5)]), axis=0)


def rise_and_settle(t, v):
    """10-90 % rise time and time from 10 % to the last excursion outside the band.

    Levels are base-to-top like the scope's own RTIMe: base = median of the
    first 10 % of the record, top = median of the last 10 %. Measuring from
    0 V instead of the base gave 8 ms too much on a run where the supply's
    output capacitors still held 0.3 V (2026-09-20).

    The settle band is 1 % of the plateau, but never less than two ADC steps:
    an 8-bit scope at 1 V/div has 40 mV steps, and a band narrower than that
    would report noise as settling time. Returns the band so it gets printed.
    """
    v = median5(v)
    lsb = np.min(np.diff(np.unique(v)))         # smallest step in the data = ADC resolution
    n = len(v) // 10
    v_base = np.median(v[:n])
    v_final = np.median(v[-n:])
    swing = v_final - v_base
    if swing < 0.5 * v_final:
        raise ValueError(f"record starts at {v_base:.2f} V with the plateau at {v_final:.2f} V: "
                         "the ramp foot is not in the capture, the trigger fired late")
    i10 = np.argmax(v > v_base + 0.1 * swing)
    i90 = np.argmax(v > v_base + 0.9 * swing)
    band = max(0.01 * v_final, 2 * lsb)
    outside = np.where(np.abs(v - v_final) > band)[0]
    i_settle = outside[-1] + 1 if len(outside) else i10
    return v_final, t[i90] - t[i10], t[i_settle] - t[i10], band, lsb


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-v", "--verbose", action="count", default=0)
    args = ap.parse_args()
    setup_logging(args.verbose)

    try:
        with psu.open_psu(psu.resolve_port(None)) as supply, scope.open_scope() as rtm:
            psu.output(supply, False)
            psu.set_voltage(supply, VOLTS)
            psu.set_current(supply, CURR_LIMIT)

            scope.setup_channel(rtm, CH, volts_per_div=1.0, position_div=-2.5, bandwidth="B20")
            scope.setup_timebase(rtm, seconds_per_div=TB)
            scope.setup_trigger(rtm, CH, volts=2.0)
            scope.arm_single(rtm, TB)           # returns once the scope can trigger

            try:
                psu.output(supply, True)
                scope.wait_acquired(rtm, timeout_s=10)
                scope_rise = scope.measurement(rtm, 1, CH, "RTIMe")   # the scope's own 10-90 %
                scope.screenshot(rtm, SCREENSHOT)                    # with the readout on screen
                t, v = scope.waveform(rtm, CH)
            finally:
                psu.output(supply, False)

        v_final, t_rise, t_settle, band, lsb = rise_and_settle(t, v)
        print(f"plateau     {v_final:.3f} V   (scope, 8 bit at 1 V/div: +/-1.5 % DC accuracy)")
        print(f"base        {v[:len(v) // 10].mean():.3f} V   (residual charge before turn-on)")
        print(f"rise 10-90  {t_rise * 1e3:.1f} ms  (numpy)   {scope_rise * 1e3:.1f} ms  (scope MEAS)")
        print(f"settle      {t_settle * 1e3:.1f} ms  to +/-{band * 1e3:.0f} mV "
              f"(ADC step {lsb * 1e3:.0f} mV; use a finer V/div with offset for a real 1 % band)")
        return 0

    except (psu.PsuError, scope.ScopeError, ValueError) as exc:
        print("FAIL:", exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("aborted", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
