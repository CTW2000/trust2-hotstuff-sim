#!/bin/bash
# The final reruns for the paper (DESIGN.md §15.30), on the server, one phase at a time so that nothing competes with
# the CPU-sensitive runs: R7 (normal case, throughput-latency, CPU of the scope), the leader-rule comparison (Table 4)
# and the G1 runs on the final binary, then every simulation the paper cites (sim2/experiments/run_final.sh, from
# ~/t2final). Writes results-p5/final_all.done at the end.
set -e
cd "$(dirname "$0")"
source ~/.cargo/env 2>/dev/null || true
(cd ../node && cargo build --release --features benchmark)
(cd ../baseline/node && cargo build --release --features benchmark)
rm -f results-p5/final_all.done
echo "$(date) r7"
python3 p5.py r7x2
python3 p5.py r7xt
python3 cpustat.py
echo "$(date) cmpg"
python3 p5.py cmpg
echo "$(date) g1"
g1() { name=$1; shift; python3 run_local.py "$@" > results-p5/$name.out 2>&1; python3 g1stat.py logs > results-p5/$name.stat 2>&1; }
g1 fin_g1_a --nodes 31 --rate 10000 --duration 90 --epoch-length 25 --equivocate 3 --lie-nr 3
g1 fin_g1_b --nodes 31 --rate 10000 --duration 120 --epoch-length 25 --invalid-block 3 --regress 3
g1 fin_g1_c --nodes 4 --rate 10000 --duration 60 --epoch-length 25 --equivocate 1
echo "$(date) simulations"
(cd ~/t2final && PY=~/hotstuff_sim/venv/bin/python bash sim2/experiments/run_final.sh)
echo "$(date) ALLDONE"
touch results-p5/final_all.done
