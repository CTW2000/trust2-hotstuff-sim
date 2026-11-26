#!/bin/bash
# Short functional checks before the unified final rerun: builds, and one run of each kind the script has not run
# since the handover fixes. Results go to results-smokefinal/, not to results-final/.
cd "$(dirname "$0")"
source ~/.cargo/env
export TTRU_OUT=results-smokefinal
rm -rf $TTRU_OUT; mkdir -p $TTRU_OUT
say() { echo "=== $(date -u +%T) $*"; }
say build node;      (cd ../node && cargo build --release --features benchmark 2>&1 | tail -1)
say build baseline;  (cd ../baseline/node && cargo build --release --features benchmark 2>&1 | tail -1)
say release tests;   (cd .. && cargo test -p consensus --release --no-run 2>&1 | tail -1); (cd ../baseline && cargo test -p consensus --release --no-run 2>&1 | tail -1)
run() { say "$*"; python3 run_local.py "$@" 2>&1 | grep -E "Consensus TPS|End-to-end latency|Traceback|rror|timed out" | tail -4; }
run --build trust2 --nodes 4 --net base --epoch-length 25 --rate 10000 --warmup 5 --duration 20 --workload ycsb-a
run --build baseline --nodes 4 --net base --rate 10000 --warmup 5 --duration 20 --workload smallbank
run --build trust2 --nodes 31 --net base --epoch-length 25 --rate 10000 --warmup 5 --duration 20 --no-h5 --silent 3
run --build trust2 --nodes 10 --net none --epoch-length 25 --rate 10000 --warmup 5 --duration 15 --no-sync
run --build baseline --nodes 31 --net base --rate 10000 --warmup 5 --duration 20 --faults 3
say "n = 100"; TTRU_MAX_NODES=100 python3 run_local.py --build trust2 --nodes 100 --net base --epoch-length 25 --rate 2000 --warmup 10 --duration 30 2>&1 | grep -E "Consensus TPS|End-to-end latency|Traceback|rror|timed out" | tail -4
say "fork across epochs with a package"; python3 fork_local.py --scenario s1 --population equal --epoch-length 25 --prephase 20 --duration 40 --rep 0 --out smoke_fork.jsonl 2>&1 | tail -1 | cut -c1-1500
say "fork within one epoch, TC outside the block"; python3 fork_local.py --scenario s3 --population weighted --duration 40 --rep 0 --out smoke_fork.jsonl 2>&1 | tail -1 | cut -c1-900
say SMOKEDONE
