#!/bin/bash
# DESIGN.md §15.25: R2 again with protected transactions (and the stricter H4 statistics of localstat.py), then the
# R4 knee with the CPU sampled every 10 s. One run at a time.
cd "$(dirname "$0")"
python3 p5.py r2
(while true; do echo "$(date +%T) $(top -bn1 | sed -n 3p)"; sleep 10; done) > results-p5/r4k_cpu.log &
SAMPLER=$!
python3 p5.py r4k
kill $SAMPLER
