# DUT: LM2596 buck module

One specimen. Everything below was measured on this bench unless marked
as a claim. Dates are the day of measurement.

## Identity

- Generic LM2596 step-down module, marketplace listing, no manufacturer
  datasheet for the module itself. IC datasheet: TI LM2596.
- Adjustable output via 25-turn trimmer.
- Input limit from the IC datasheet: 40 V absolute, 35 V recommended.
  Bench limit used: 35 V.

## Claims (marketplace listing)

| Parameter       | Claim   | Conditions stated |
|-----------------|---------|-------------------|
| Output ripple   | < 30 mV | none              |
| Max current     | 3 A     | none              |
| Efficiency      | 92 %    | none              |

Treated as claims to be checked, not as specifications.

## Adjustment (2026-09-20)

Input 12.0 V from the supply, output measured with a DMM at the output
capacitor, the same point the scope probe uses.

| Condition        | Output   |
|------------------|----------|
| no load          | 5.007 V  |
| 1 A (5.14 R)     | 4.977 V  |

Trimmer resolution is about 20 mV per fifth of a turn; the output was set
to 5.00 V under load and left there. Load regulation 0 to 1 A: -30 mV
(-0.6 %). Not adjusted further; the +/-20 mV band is the module's, not
the measurement's.

## First figures (2026-09-20, side readings, not a measurement setup)

Input current at 12.0 V with 1 A out: 0.519 A (supply readout).

    P_in  = 11.997 V x 0.519 A = 6.23 W
    P_out = 4.977 V^2 / 5.14 R = 4.82 W
    eta   = 77 %

Uncertainty: supply ammeter about +/-3 %, load resistor warm and a few
percent above its cold value, so 75 to 80 %. The IC datasheet curves put
12 V in / 5 V out / 1 A at around 80 %, which is consistent. The 92 %
in the listing is not met at this operating point. Efficiency is not part
of the measurement plan; this is a note, not a result row.

## Measurements

Not yet run. Filled from the JSON records once the sequence exists.

| # | Measurement            | Result | Screenshot |
|---|------------------------|--------|------------|
| 1 | Ripple at 1 A          | -      | -          |
| 2 | Load step 0 -> 1 A     | -      | -          |
| 2 | Load step 1 A -> 0     | -      | -          |
| 3 | Turn-on                | -      | -          |
| 4 | Line regulation        | -      | -          |
