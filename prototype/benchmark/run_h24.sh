#!/bin/bash
# DESIGN.md §15.24: cross-epoch forks (fork_epochs.jsonl), then the regression runs of p5.py h24. One run at a time.
cd "$(dirname "$0")"
for rep in 1 2 3 4 5 6; do
  python3 fork_local.py --scenario s1 --population equal --epoch-length 25 --prephase 20 --duration 60 --rep $rep --out fork_epochs.jsonl
  python3 fork_local.py --scenario s1 --population weighted --epoch-length 25 --prephase 20 --duration 60 --rep $rep --out fork_epochs.jsonl
  python3 fork_local.py --scenario s2 --population equal --epoch-length 25 --prephase 20 --duration 60 --k 30 --rep $rep --out fork_epochs.jsonl
done
python3 p5.py h24
