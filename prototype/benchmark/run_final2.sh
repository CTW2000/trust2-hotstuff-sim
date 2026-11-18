#!/bin/bash
# The unified final reruns (DESIGN.md §15.40): every number of the evaluation section on one binary and one
# configuration (next table an epoch ahead, epochs of 25 rounds, threshold ln 10^2, H1-H5, the table chain, the
# synced safety state), one run at a time, on the lab server. Results go to results-final/ and leave results-p5/
# as it is. About a day in all.
#
#   nohup setsid bash run_final2.sh > /dev/null 2>&1 &
#
# Progress: results-final/progress.log (one line per batch); the output of the runs: results-final/run.log.
# results-final/ALLDONE is written at the end. A batch that fails is logged and the script goes on.
# TTRU_ONLY="scale sync" runs only the named phases; TTRU_COMMIT names the commit the copy was made from.
set -u
cd "$(dirname "$0")"
source ~/.cargo/env 2>/dev/null || true
export TTRU_OUT=results-final
mkdir -p $TTRU_OUT
rm -f $TTRU_OUT/ALLDONE
log() { echo "$(date '+%F %T') $*" | tee -a $TTRU_OUT/progress.log; }
step() { log "start: $*"; if "$@" >> $TTRU_OUT/run.log 2>&1; then log "end:   $*"; else log "FAILED: $*"; fi; }
want() { [ -z "${TTRU_ONLY:-}" ] || [[ " $TTRU_ONLY " == *" $1 "* ]]; }
p5() { python3 p5.py "$1"; }
g1() { name=$1; shift; python3 run_local.py "$@" > $TTRU_OUT/$name.out 2>&1; python3 g1stat.py logs > $TTRU_OUT/$name.stat 2>&1; }

log "commit ${TTRU_COMMIT:-unknown}"
(cd ../node && cargo build --release --features benchmark) >> $TTRU_OUT/run.log 2>&1 || { log "FAILED: build of the node"; exit 1; }
(cd ../baseline/node && cargo build --release --features benchmark) >> $TTRU_OUT/run.log 2>&1 || { log "FAILED: build of the baseline"; exit 1; }

# 1. Message sizes and verification times; size and verification time of an evidence package (n = 100, 25 epochs).
if want unit; then
  log "start: unit-test measurements"
  # Both builds, alternating, three times each: the table of the paper gives the medians.
  (cd ../baseline && cargo test -p consensus --release --no-run) >> $TTRU_OUT/run.log 2>&1
  for i in 1 2 3; do
    (cd .. && cargo test -p consensus --release overhead -- --ignored --nocapture) > $TTRU_OUT/x1_overhead_trust2_$i.txt 2>&1
    (cd ../baseline && cargo test -p consensus --release overhead -- --ignored --nocapture) > $TTRU_OUT/x1_overhead_baseline_$i.txt 2>&1
  done
  (cd .. && cargo test -p consensus --release package_cost -- --ignored --nocapture) > $TTRU_OUT/package_cost.txt 2>&1
  log "end:   unit-test measurements"
fi

# 2. Overhead and scale: the normal case on three networks, the throughput-latency curve, the CPU of the scope
#    along the curve, and larger committees.
if want overhead; then
  step p5 r7x2
  step p5 r7xt
  step python3 cpustat.py
  TTRU_REPS=5 step p5 scale
fi

# 3. The mechanisms added for accountability and the database workloads.
if want cost; then
  TTRU_REPS=5 step p5 sync
  TTRU_REPS=5 step p5 h5live
  TTRU_WL_BASELINE=1 TTRU_REPS=3 step p5 wl
  step p5 wlsat
fi

# 4. Faults and framing: late messages, silent leaders (both builds), the weighted path, entity binding, long
#    framing, censorship; where the cost under late messages comes from; the leader rules, with votes to the next
#    leader and with votes to all (DESIGN.md §15.42); the B_rep = 0 ablation.
if want faults; then
  step p5 f25
  step p5 silent2
  step p5 lc
  step p5 cmpg
  step p5 cmpb
  step p5 a3
fi

# 5. G1 on the prototype and the accusation rate of honest leaders in long runs.
if want g1; then
  log "start: g1"
  g1 fin_g1_a --nodes 31 --rate 10000 --duration 90 --epoch-length 25 --equivocate 3 --lie-nr 3
  g1 fin_g1_b --nodes 31 --rate 10000 --duration 120 --epoch-length 25 --invalid-block 3 --regress 3
  g1 fin_g1_c --nodes 4 --rate 10000 --duration 60 --epoch-length 25 --equivocate 1
  log "end:   g1"
  step p5 a1
  python3 a1stat.py $TTRU_OUT/a1_logs > $TTRU_OUT/a1_stat.txt 2>&1 || log "FAILED: a1stat"
fi

# 6. The local experiments: handover under disturbance, correlated lateness and outages (twice, for four runs of
#    each case), protected transactions under load, the threshold, targeted framing.
if want local; then
  step p5 r2
  step p5 r3
  step p5 r3
  step p5 r4
  step p5 r4k
  step p5 r34x
  step p5 thr
  step p5 thr2
  step p5 tgt
fi

# 7. Forks: within one epoch (two halves voting as usual, in disjoint rounds, and with the TC outside the block),
#    then across epochs, each followed by the evidence package and its stand-alone verification.
if want forks; then
  log "start: forks within one epoch"
  for rep in 1 2 3; do
    for population in equal weighted; do
      for scenario in s1 s2 s3; do
        python3 fork_local.py --scenario $scenario --population $population --duration 60 --rep $rep --out fork.jsonl >> $TTRU_OUT/run.log 2>&1 || log "FAILED: fork $scenario $population $rep"
      done
    done
  done
  log "end:   forks within one epoch"
  log "start: forks across epochs with packages"
  REPS="1 2 3 4 5 6" bash run_fork_package.sh >> $TTRU_OUT/run.log 2>&1 || log "FAILED: run_fork_package.sh"
  log "end:   forks across epochs with packages"
fi

python3 p5.py report >> $TTRU_OUT/run.log 2>&1 || log "FAILED: report"
log "ALLDONE"
touch $TTRU_OUT/ALLDONE
