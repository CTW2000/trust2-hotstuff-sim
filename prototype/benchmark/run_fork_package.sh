#!/bin/bash
# DESIGN.md §15.35: cross-epoch forks under the handover rules of §15.34, each followed by the evidence package of
# the fork and its stand-alone verification (fork_local.py runs `node package` and `node verify` after `node forensics`).
# One run at a time.
set -e
cd "$(dirname "$0")"
for rep in ${REPS:-1}; do
  python3 fork_local.py --scenario s1 --population equal --epoch-length 25 --prephase 20 --duration 60 --rep $rep --out fork_package.jsonl
  python3 fork_local.py --scenario s1 --population weighted --epoch-length 25 --prephase 20 --duration 60 --rep $rep --out fork_package.jsonl
  python3 fork_local.py --scenario s2 --population equal --epoch-length 25 --prephase 20 --duration 60 --k 30 --rep $rep --out fork_package.jsonl
done
