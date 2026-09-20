"""Demo 1: step the OWON through a few setpoints, Pico LED in sync, NO LOAD.

Nothing on the supply terminals. The MOSFET module may be wired to the Pico
but must have nothing behind it. For each step:

    supply on -> ramp done -> LED on -> hold 1 s -> read back -> LED off -> supply off

The LED lights exactly while the supply delivers. Measured current stays
at zero; this demo checks sequencing and the two instruments together.

    python demo1_psu_sweep.py
    python demo1_psu_sweep.py -v
"""

import argparse
import sys
import time

from bench import load, psu
from bench.common import setup_logging

STEPS = [           # (volts, current limit)
    (2.0, 0.2),
    (4.0, 0.4),
    (6.0, 0.6),
    (8.0, 0.8),
]
HOLD_S = 1.0
OVP_V = 10.0
OCP_A = 1.5


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--psu-port", help="COM7; default from config, else auto")
    ap.add_argument("--load-port", help="COM5; default from config, else auto")
    ap.add_argument("-v", "--verbose", action="count", default=0)
    args = ap.parse_args()
    setup_logging(args.verbose)

    try:
        with psu.open_psu(psu.resolve_port(args.psu_port)) as supply, \
             load.open_load(load.resolve_port(args.load_port)) as switch:

            load.load(switch, False)                # known starting state
            psu.output(supply, False)
            psu.set_ovp(supply, OVP_V)
            psu.set_ocp(supply, OCP_A)

            try:
                for volts, amps in STEPS:
                    psu.set_voltage(supply, volts)
                    psu.set_current(supply, amps)
                    psu.output(supply, True)        # returns once the ramp is over
                    load.load(switch, True)         # LED on: supply is delivering
                    time.sleep(HOLD_S)
                    v, i = psu.measure(supply)
                    load.load(switch, False)
                    psu.output(supply, False)
                    print(f"set {volts:.1f} V / {amps:.1f} A   measured {v:.3f} V  {i:.3f} A")
            finally:
                load.load(switch, False)            # also on Ctrl-C or any error
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
