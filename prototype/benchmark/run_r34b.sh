#!/bin/bash
# DESIGN.md §15.25, second pass: R4 and R3 again with the CUSUM peaks and the facts per node (localstat.py), R4 with
# 1000/s added and the CPU sampled every 10 s, R3 with a long region outage added. The first pass is kept as *_v1.csv.
cd "$(dirname "$0")"
for f in r4_load r3_long; do
  [ -f results-p5/$f.csv ] && [ ! -f results-p5/${f}_v1.csv ] && mv results-p5/$f.csv results-p5/${f}_v1.csv
done
(while true; do echo "$(date +%T) $(top -bn1 | sed -n 3p)"; sleep 10; done) > results-p5/r4_cpu.log &
SAMPLER=$!
python3 p5.py r4
kill $SAMPLER
python3 p5.py r3
