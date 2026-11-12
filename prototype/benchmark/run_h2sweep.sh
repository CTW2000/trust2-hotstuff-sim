#!/bin/bash
# DESIGN.md §15.26: the cross-epoch forks of §15.24 again, now with the H2 sweep in the forensics report
# (fork_epochs_h2.jsonl). One run at a time.
cd "$(dirname "$0")"
for rep in 1 2 3 4 5 6; do
  python3 fork_local.py --scenario s1 --population equal --epoch-length 25 --prephase 20 --duration 60 --rep $rep --out fork_epochs_h2.jsonl
  python3 fork_local.py --scenario s1 --population weighted --epoch-length 25 --prephase 20 --duration 60 --rep $rep --out fork_epochs_h2.jsonl
  python3 fork_local.py --scenario s2 --population equal --epoch-length 25 --prephase 20 --duration 60 --k 30 --rep $rep --out fork_epochs_h2.jsonl
done
