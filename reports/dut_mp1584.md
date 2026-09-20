# DUT: MP1584EN buck module

One specimen. Everything below was measured on this bench unless marked
as a claim. Dates are the day of measurement.

## Identity

- Generic MP1584EN step-down module, marketplace listing, no manufacturer
  datasheet for the module itself. IC datasheet: MPS MP1584.
- Adjustable output via single-turn trimmer.
- Input limit from the IC datasheet: 28 V maximum. Bench limit used: 28 V.
  Line regulation (measurement 4) goes to 24 V, not higher.

## Claims (marketplace listing)

| Parameter           | Claim   | Conditions stated |
|---------------------|---------|-------------------|
| Output ripple       | 30 mV   | none              |
| Max current         | 3 A     | none              |
| Switching frequency | 1.5 MHz | none              |

Treated as claims to be checked, not as specifications.

## Adjustment (2026-09-20)

Input 12.0 V from the supply, output measured with a DMM at the output
capacitor, the same point the scope probe uses. Trimmer set with no load
and left there.

| Condition        | Output   |
|------------------|----------|
| no load          | 4.990 V  |
| 1 A (5.14 R)     | 4.880 V  |

Load regulation 0 to 1 A: -110 mV (-2.2 %). That is large for a
synchronous buck with the feedback divider on the module; it points to
resistance in the output path after the sense point (trace, trimmer
wiring) rather than to the control loop. To be looked at with the load
step in measurement 2.

## First figures (2026-09-20, side readings, not a measurement setup)

Input current at 12.0 V with 1 A out: 0.475 A (supply readout).

    P_in  = 11.997 V x 0.475 A = 5.70 W
    P_out = 4.880 V^2 / 5.14 R = 4.63 W
    eta   = 81 %

Uncertainty as for the LM2596: about 79 to 84 %. Better than the LM2596
module (77 %) but below what the IC datasheet suggests for this operating
point (mid 80s); consistent with the load-regulation observation above.
The listing makes no efficiency claim. Note, not a result row.

## Measurements

Not yet run. Filled from the JSON records once the sequence exists.

| # | Measurement            | Result | Screenshot |
|---|------------------------|--------|------------|
| 1 | Ripple at 1 A          | -      | -          |
| 1 | Switching frequency    | -      | -          |
| 2 | Load step 0 -> 1 A     | -      | -          |
| 2 | Load step 1 A -> 0     | -      | -          |
| 3 | Turn-on                | -      | -          |
| 4 | Line regulation        | -      | -          |
