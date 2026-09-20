"""Demo 2: resistor behind the MOSFET module, switched by the Pico, fed by the OWON.

Wiring (all three grounds meet at the module):

    OWON +  -- VIN+ === OUT+ -- resistor
    OWON -  -- VIN-     OUT- -- resistor
                |
               GND  -- Pico pin 18
               TRIG -- Pico pin 20 (GP15)

Always 5 V: that is what the DUT will deliver later, so it is the only level
the load path needs to be checked at. Three repeats show whether the reading
holds; expected current is 5 V / R.

The last step keeps 5 V but sets the current limit BELOW the load current, so
the supply goes into CC and wait_for_voltage must FAIL. That step is there on
purpose to show the failure path; exit code 1 is the correct outcome.

    python demo2_load_switch.py --r 10
    python demo2_load_switch.py --r 5 -v
"""

import argparse
import sys
import time

from bench import config, load, psu
from bench.common import setup_logging

RESISTORS = {"5": config.LOAD_R_5, "10": config.LOAD_R_10}

VOLTS = 5.0
REPEATS = 3         # same step three times: does the reading hold?
LIMIT_MARGIN = 1.5  # working current limit = expected current x this
FAIL_FACTOR = 0.8   # last step: limit = expected current x this -> CC -> FAIL
HOLD_S = config.PSU_MEAS_SETTLE_S   # the supply's current reading needs this long
OVP_V = 6.0
OCP_A = 2.0         # protection only; the working limit is per step


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--r", choices=RESISTORS, default="5", help="which load resistor is wired in")
    ap.add_argument("--psu-port", help="COM7; default from config, else auto")
    ap.add_argument("--load-port", help="COM5; default from config, else auto")
    ap.add_argument("-v", "--verbose", action="count", default=0)
    args = ap.parse_args()
    setup_logging(args.verbose)

    r_load = RESISTORS[args.r]
    expected = VOLTS / r_load
    steps = [(VOLTS, expected * LIMIT_MARGIN)] * REPEATS + [(VOLTS, expected * FAIL_FACTOR)]
    print(f"load resistor {r_load:.2f} R, expect {expected:.2f} A at {VOLTS:.1f} V")
    try:
        with psu.open_psu(psu.resolve_port(args.psu_port)) as supply, \
             load.open_load(load.resolve_port(args.load_port)) as switch:

            load.load(switch, False)
            psu.output(supply, False)
            psu.set_ovp(supply, OVP_V)
            psu.set_ocp(supply, OCP_A)

            try:
                for volts, amps in steps:
                    print(f"step {volts:.1f} V, limit {amps:.2f} A")
                    psu.set_voltage(supply, volts)
                    psu.set_current(supply, amps)
                    psu.output(supply, True)
                    load.load(switch, True)
                    time.sleep(HOLD_S)
                    v, i = psu.measure(supply)
                    print(f"   measured {v:.3f} V  {i:.3f} A   -> {v / i if i else float('nan'):.2f} R as seen by the supply")
                    psu.verify_voltage(supply)      # still at setpoint with the load on? else FAIL
                    load.load(switch, False)
                    psu.output(supply, False)
            finally:
                load.load(switch, False)
                psu.output(supply, False)
        return 0

    except (psu.PsuError, load.LoadError) as exc:
        print("FAIL:", exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("aborted", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
