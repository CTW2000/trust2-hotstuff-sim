#!/bin/bash
# DESIGN.md §15.27 (mock review S1): targeted framing first (one 10 min run per target count), then the threshold
# check (silent leaders and framing with late messages at three thresholds). One run at a time.
cd "$(dirname "$0")"
python3 p5.py tgt
python3 p5.py thr
