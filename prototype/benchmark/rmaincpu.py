"""CPU used by the nodes in cells of the batch of DESIGN.md 15.53 (rmain.py): is the server short of CPU there?

One run per cell with the settings of the batch (Trust 2.0 code, n = 31, base network, epochs of 25 rounds,
10,000 tx/s, the keys of block 1), 60 s after a warm-up of 10 s. As in cpustat.py, the cgroup v2 `cpu.stat` of the
scope of the nodes is read 5 s into the measured part and again 40 s later: cores = usage / 40 s, throttled = share
of the scheduler periods in which the quota of 12 cores ran out. Linux only.
Run from prototype/benchmark/ after the batch:  python3 rmaincpu.py  (writes results-rmain/cpu.csv)"""
import csv
import os
import subprocess
import time

from cpustat import cpu_stat, node_pids
from rmain import lateness

OUT = "results-rmain/cpu.csv"
NODES, RATE, WARMUP, DURATION, SKIP, WINDOW = 31, 10_000, 10, 60, 5, 40
CELLS = [("no lateness", "trust2", {}),
         ("P2", "trust2", lateness("P", 2)), ("P10", "trust2", lateness("P", 10)), ("P20", "trust2", lateness("P", 20)),
         ("S20", "trust2", lateness("S", 20)), ("B20", "trust2", lateness("B", 20)), ("Q2", "trust2", lateness("Q", 2)),
         ("P10", "aptos", lateness("P", 10)),
         ("late-all", "trust2", dict(late_p=0.1, broadcast_votes=True)),
         ("silent-all", "trust2", dict(silent=3, broadcast_votes=True)),
         ("framers-all", "trust2", dict(frame=6, late_p=0.1, broadcast_votes=True))]


def measure(scenario, rule, config):
    args = ["python3", "run_local.py", "--build", "trust2", "--nodes", str(NODES), "--net", "base",
            "--epoch-length", "25", "--rate", str(RATE), "--warmup", str(WARMUP), "--duration", str(DURATION),
            "--keys-dir", os.path.abspath("results-rmain/keys/block-1"), "--leader-rule", rule]
    for key, value in config.items():
        flag = "--" + key.replace("_", "-")
        args += [flag] if value is True else [flag, str(value)]
    run = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        start = time.time()
        while len(node_pids()) < NODES:
            if run.poll() is not None or time.time() - start > 300:
                raise RuntimeError("the nodes did not start")
            time.sleep(0.2)
        time.sleep(WARMUP + SKIP)
        pid = node_pids()[0]
        scope, before = cpu_stat(pid)
        time.sleep(WINDOW)
        _, after = cpu_stat(pid)
    finally:
        run.wait(timeout=DURATION + WARMUP + 600)
    periods = after["nr_periods"] - before["nr_periods"]
    return dict(scenario=scenario, leader_rule=rule,
                cores=round((after["usage_usec"] - before["usage_usec"]) / (WINDOW * 1e6), 2),
                throttled_pct=round(100 * (after["nr_throttled"] - before["nr_throttled"]) / periods, 1) if periods else "",
                scope=scope)


if __name__ == "__main__":
    rows = []
    for cell in CELLS:
        rows.append(measure(*cell))
        print(rows[-1], flush=True)
        with open(OUT, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
