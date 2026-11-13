#!/bin/bash
# R7 (DESIGN.md §15.30): the overhead, the normal case and the throughput-latency curve rerun under the final rules
# (next table an epoch ahead, epochs of 25 rounds, H2/H4/E2), then the CPU of the scope along the curve.
# One run at a time.
set -e
cd "$(dirname "$0")"
source ~/.cargo/env 2>/dev/null || true
(cd ../node && cargo build --release --features benchmark)
(cd ../baseline/node && cargo build --release --features benchmark)
(cd .. && cargo test -p consensus --release overhead -- --ignored --nocapture) > results-p5/r7_x1.txt 2>&1
python3 p5.py r7x2
python3 p5.py r7xt
python3 cpustat.py
