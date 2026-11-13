#!/bin/bash
# The simulations cited in the paper (§6.5), rerun on the final code: the adopted scheme (SIM_SCHEME=h1p), threshold
# ln 10^2, CapNorm that rejects, the G2 rule without a queue and G1 queued entities that keep leading (prototype
# DESIGN.md §15.30, §15.31). One step at a time; V12b keeps few workers (its runs are large).
# Run from the repository root:  bash sim2/experiments/run_final.sh [step ...]
# Steps: v12 gamma:silent gamma:frame gamma:chaos sens ablation v12b:long v12b:n100 v12b:rev (default: all, in order).
# Writes "done" to sim2/results/run_final.done at the end.
set -e
cd "$(dirname "$0")/../.."
export SIM_SCHEME=h1p
PY=${PY:-.venv/bin/python}
STEPS=${*:-v12 gamma:silent gamma:frame gamma:chaos sens ablation v12b:long v12b:n100 v12b:rev}
rm -f sim2/results/run_final.done
for step in $STEPS; do
    echo "$(date) $step"
    case $step in
        v12) SIM_PROCS=8 $PY -m sim2.experiments.dirTtruV12 all ;;
        gamma:*) SIM_PROCS=8 $PY -m sim2.experiments.dirTtruGamma "${step#gamma:}" ;;
        sens) SIM_PROCS=8 $PY -m sim2.experiments.dirTtruSens all ;;
        ablation) SIM_PROCS=8 $PY -m sim2.experiments.dirTtruAblation all ;;
        v12b:*) SIM_PROCS=3 $PY -m sim2.experiments.dirTtruV12b "${step#v12b:}" ;;
        *) echo "unknown step $step"; exit 1 ;;
    esac
done
echo "$(date) done"
echo done > sim2/results/run_final.done
