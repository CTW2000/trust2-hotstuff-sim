"""Benign faults of honest nodes (DESIGN.md §15.22): python3 a7stat.py <logs dir>...

Reads the run archives of `p5.py a7` (results-p5/a7_logs/<scenario>-<rule>-<rep>.tgz). Each run's logs/faulted.txt names
the fault ("crash at 40 s for 20 s") and the nodes it hit. Per run it reports, for the faulted nodes and for the
other honest nodes separately: G2 exclusions on node 0's ledger, accused rounds, the lowest reputation, and member-
epochs at the Aptos failed weight; and for the faulted nodes how many rounds they led before the fault, during it,
and after it ended (a node that leads again after the fault is back in the leader draw). Per arm (scenario, rule):
the sums over the runs. Only the standard library is used."""
import os
import re
import shutil
import sys
import tarfile
import tempfile
from collections import defaultdict
from datetime import datetime
from glob import glob

BOOT = re.compile(r"Node (\S+) successfully booted")
STAMP = re.compile(r"^\[(\S+?)Z ")
CREATED = re.compile(r"Created B(\d+)$")
COMMITTED = re.compile(r"Committed B(\d+)$")
ACCUSED = re.compile(r"G2: accusation of round \d+ led by (\S+)")
EXCLUDED = re.compile(r"G2: (\S+) excluded from leading")
REPUTATION = re.compile(r"G2: reputation of (\S+) is (\d+) ppm")
APTOS = re.compile(r"Aptos: (\S+) weight (failed|inactive) at epoch \d+")
FAULT = re.compile(r"(\w+) at ([\d.]+) s for ([\d.]+) s")


def when(line):
    m = STAMP.match(line)
    return datetime.fromisoformat(m.group(1)).timestamp() if m else None


def run_stats(logs):
    with open(os.path.join(logs, "faulted.txt")) as fh:
        lines = fh.read().split("\n")
    kind, at, length = FAULT.match(lines[0]).groups()
    faulted = {x.strip() for x in lines[1:] if x.strip()}
    names, leads, start = {}, defaultdict(list), None
    for path in glob(os.path.join(logs, "node-*.log")):
        text = open(path, errors="replace").read()
        m = BOOT.search(text)
        if not m:
            continue
        name = m.group(1)
        names[path] = name
        for line in text.splitlines():
            t = when(line)
            if t is None:
                continue
            start = t if start is None else min(start, t)
            if CREATED.search(line):
                leads[name].append(t)
    begin, end = start + float(at), start + float(at) + (float(length) if kind != "crash" else 1e9)
    zero = open(os.path.join(logs, "node-0.log"), errors="replace").read()
    side = lambda who: "faulted" if who in faulted else "honest"
    out = defaultdict(int)
    for who in ACCUSED.findall(zero):
        out[f"accused_{side(who)}"] += 1
    for who in EXCLUDED.findall(zero):
        out[f"excluded_{side(who)}"] += 1
    low = {}
    for who, ppm in REPUTATION.findall(zero):
        low[who] = min(low.get(who, 10**6), int(ppm))
    for s in ("faulted", "honest"):
        vals = [v for w, v in low.items() if side(w) == s]
        out[f"min_r_{s}"] = min(vals) if vals else 10**6
    for who, what in APTOS.findall(zero):
        out[f"aptos_{what}_{side(who)}"] += 1
    for who in faulted:
        for t in leads.get(who, []):
            out["leads_before" if t < begin else "leads_during" if t < end else "leads_after"] += 1
    committed = [int(x) for x in COMMITTED.findall(zero)]
    out["committed_top"] = max(committed, default=0)
    out["kind"] = kind
    return dict(out)


def main():
    arms = defaultdict(list)
    for d in sys.argv[1:]:
        for tgz in sorted(glob(os.path.join(d, "*.tgz"))):
            arm = re.sub(r"-\d+\.tgz$", "", os.path.basename(tgz))
            tmp = tempfile.mkdtemp(dir="/tmp")
            try:
                with tarfile.open(tgz) as t:
                    t.extractall(tmp, members=[m for m in t.getmembers()
                                               if re.search(r"(node-\d+\.log|faulted\.txt)$", m.name)])
                arms[arm].append(run_stats(os.path.join(tmp, "logs")))
            finally:
                shutil.rmtree(tmp)
    keys = ["accused_faulted", "accused_honest", "excluded_faulted", "excluded_honest", "min_r_faulted",
            "min_r_honest", "aptos_failed_faulted", "aptos_failed_honest", "aptos_inactive_faulted",
            "aptos_inactive_honest", "leads_before", "leads_during", "leads_after", "committed_top"]
    print("arm | runs | " + " | ".join(keys))
    for arm, rows in sorted(arms.items()):
        cells = []
        for k in keys:
            vals = [r.get(k, 0) for r in rows]
            cells.append(str(min(vals)) if k.startswith("min_r") else "/".join(str(v) for v in vals))
        print(f"{arm} | {len(rows)} | " + " | ".join(cells))


if __name__ == "__main__":
    main()
