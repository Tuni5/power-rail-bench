# power-rail-bench

Automated characterisation of two buck converter modules on a 12 V rail.
The bench drives an OWON SPE3102 supply, a Rohde & Schwarz RTM2034
oscilloscope and a MOSFET load switch over SCPI and serial, and produces a
pass/fail verdict against the values the module vendors claim. Every number
in the report comes from an instrument, not from a datasheet.

---

## Setup

> TODO: photo of the bench at `docs/setup.jpg`

```
  OWON SPE3102                DUT                       load bank
  30 V / 10 A            LM2596 module              5R / 25 W  ||  10R / 25 W
  SCPI over USB-serial   MP1584EN module            (~1 A)         (~0.5 A)
                                                    parallel ~1.5 A
       +12 V  o---------->  VIN     VOUT  +5 V  o------+-----------+
                                                       |
       GND    o---------->  GND     GND    o--+        |
                                              |    CH1 probe
                                              |  (spring ground,
                                              |   at output cap)
                                              |        |
                                              |        v
                                              |   low-side switch
                                              |   2x D4184, module
                                              |     GND      TRIG
                                              |      |         |
       GND ---------------------------------- + ----+          +---> Pico GPIO
                                              |                 \
                                    single ground point          `-> CH2 probe
                                (DUT GND, Pico GND, scope GND)
```

- Measurement point: probe with spring ground directly at the module output
  capacitor. CH1 = output, CH2 = TRIG (trigger source for the load step).
- Load switching: Raspberry Pi Pico, MicroPython, serial commands
  `LOAD ON`, `LOAD OFF`, `STEP <ms>`, `IDN`.

## What it measures

| # | Measurement | Result |
|---|-------------|--------|
| 0 | Source noise floor: ripple of the OWON output with no DUT connected | mV pp |
| 1 | Output ripple at 1 A (AC coupling, 20 MHz BW limit) | mV pp, switching frequency |
| 2 | Load step 0 -> 1 A and 1 A -> 0, single shot on TRIG | droop/overshoot in mV, recovery time in us to the +/-1 % band |
| 3 | Turn-on behaviour, supply enabled over SCPI | overshoot in %, rise time in ms |
| 4 | Line regulation at 9 / 12 / 24 V input | output voltage per step |

Measurement 0 runs before every session. It is the baseline the other
numbers are read against.

## Pass criteria with source

| Parameter | LM2596 module | MP1584EN module | Source |
|-----------|---------------|-----------------|--------|
| Output ripple | < 30 mV | 30 mV | vendor listing |
| Max output current | 3 A | 3 A | vendor listing |
| Switching frequency | no spec - characterized | 1.5 MHz | vendor listing |
| Efficiency | 92 % | no spec - characterized | vendor listing |
| Load step droop | no spec - characterized | no spec - characterized | - |
| Recovery time | no spec - characterized | no spec - characterized | - |
| Turn-on overshoot | no spec - characterized | no spec - characterized | - |
| Line regulation | no spec - characterized | no spec - characterized | - |

The source is a marketplace listing, not a manufacturer datasheet, and the
listing does not state the conditions the numbers apply to. Treated as a
claim to be checked, not as a specification. Input voltage limits are taken
from the converter IC datasheets: MP1584EN up to 28 V, LM2596 up to 35 V.

## Results (claimed vs measured)

Sequence not run yet. Per-DUT notes with adjustment data and first
side readings: `docs/dut_lm2596.md`, `docs/dut_mp1584.md`.

| Parameter | Claimed | Measured (LM2596) | Measured (MP1584EN) | Verdict |
|-----------|---------|-------------------|---------------------|---------|
| Efficiency 12 V -> 5 V, 1 A | 92 % (LM2596), none (MP1584) | ~77 % (75-80 %), side reading | ~81 % (79-84 %), side reading | LM2596: not met |
| Load regulation 0 -> 1 A | no spec - characterized | -30 mV | -110 mV | characterized |

## Method notes

Things learned while bringing the bench up that shape how the measurements
are taken. Each one cost a wrong number first.

- Vertical scale is chosen per question, not per signal. The RTM2034 has an
  8-bit ADC: at 1 V/div one step is 40 mV, so a +/-1 % band around 5 V is
  one step wide and a recovery time read at that scale is noise. Ramps and
  overshoot are read at a coarse scale; recovery into a +/-1 % band is read
  at 100 mV/div or finer with the DC offset feature.
- Absolute DC values do not come from the scope at coarse scales (+/-1.5 %
  DC accuracy); they come from the supply readout or a DMM.
- Single-shot on a slow timebase: after SINGle the scope first fills its
  pre-trigger memory and ignores edges until then. The script waits for that
  before it causes the event.
- Edge triggers on a switching rail get the channel's 20 MHz limit and the
  trigger noise-reject filter; without them the scope fired on spikes.
- Every number computed from a waveform is cross-checked once against the
  scope's own measurement on the same record. Levels for rise time are
  base-to-top as the scope defines them; measuring from 0 V instead gave
  8 ms too much when the supply's output capacitors still held 0.3 V.
- The supply's turn-on ramp depends on what its output capacitors held
  before: 33-34 ms 10-90 % from a discharged output, 28.5 ms starting at
  0.3 V (2026-09-20). Turn-on measurements discharge the output through
  the load switch first, so every run starts from the same state.

## Known limits

- Single specimen of each module type. No lot-to-lot statement.
- Ripple figures depend on probe grounding. All measurements use a spring
  ground at the output capacitor; a longer ground lead gives different
  numbers on the same hardware.
- 20 MHz bandwidth limit is on for ripple measurements, so content above
  that is not captured.
- Efficiency is claimed by the vendor but not measured here: the bench has
  no calibrated input and output current measurement.
- Load steps are resistive only, switched low-side. No inductive or dynamic
  load profile.
- Room temperature, no thermal control and no soak time before a run.
- Source noise floor is recorded but not subtracted from the DUT results.
- OWON readouts are display values: voltage matches the setpoint at steady
  state (checked 2 to 10 V); current agrees with a DMM-measured 5.14 R load
  to within 2 % once settled, but needs more than 1 s to settle after a load
  change. Static readings are taken 2 s after the last change. An earlier
  1 R discrepancy was a crocodile clip, not the ammeter.
- OWON output reaches 5 V within about 100 ms of OUTPut ON (10-90 % in
  roughly 45 ms, exponential tail; scope, manual measurement 2026-09-20).
  A DUT "turn-on" triggered over SCPI therefore sees a ~50 ms input ramp,
  not a step. The supply's own measurement readout lags the output by
  about 1 s and updates about 3 times per second; it is used for static
  values only. An earlier "1 s ramp" read from that readout was the lag,
  not the output.
- Anything that did not reproduce across runs is listed here rather than
  averaged away.

## Status

Work in progress - instrument bring-up.

- [x] PSU (OWON SPE3102): serial link, `*IDN?`, setpoints, OVP/OCP, output with readback (2026-09-20)
- [x] Scope (R&S RTM2034): LAN socket, `*IDN?`, error queue, screenshot (2026-09-20)
- [x] Load switch: Pico firmware, `LOAD ON` / `LOAD OFF` / `STEP`, verified at the module LED
      and with a 5.14 R load through the module (2026-09-20)
- [x] One measurement taken by hand, then reproduced by script and compared: supply
      turn-on ramp, 10-90 % rise 33.2 ms (scope MEAS) vs 33.7 ms (numpy on the same
      record); six script runs 28-37 ms, spread explained by residual output charge
      (2026-09-20)
- [ ] Source noise floor (measurement 0)
- [ ] Full sequence (measurements 1-4)
- [ ] HTML report and comparison page

## Sources

- SPE3102 SCPI command set: taken from the
  [owon-psu](https://github.com/robbederks/owon-psu-control) library (MIT),
  which targets the SPE3103 / SPE6103, and confirmed command by command on
  this SPE3102 (firmware V5.2.0). Not from the OWON programming manual.
- Converter input voltage limits: LM2596 and MP1584EN datasheets.
- Module claims: marketplace listings, see "Pass criteria with source".

## Usage

```
pip install -r requirements.txt

python -m bench.psu --scan                       # serial ports with USB VID/PID
python -m bench.psu --idn                        # find the supply, print *IDN?
python -m bench.psu --status                     # setpoints, limits, output, readings
python -m bench.psu --ovp 6 --ocp 1 --volt 5 --curr 0.5 --on
python -m bench.psu --off

python -m bench.load --idn                       # Pico load switch
python -m bench.load --on / --off / --step 200

python -m bench.scope --idn                      # RTM2034 over LAN
python -m bench.scope --screenshot reports/screenshots/name.png
```

Ports, addresses, USB identities and limits live in `bench/config.py`.

---

Code drafted with AI assistance; setup, measurements and verification are mine.
