#!/bin/bash
# DESIGN.md §15.25 (mock review R2-R4): handover under disturbance, inclusion attestations under load, CUSUM over long
# runs. One run at a time.
cd "$(dirname "$0")"
python3 p5.py r2
python3 p5.py r4
python3 p5.py r3
