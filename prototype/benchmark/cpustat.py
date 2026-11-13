"""CPU used by the 12-core scope, and how often the quota throttled it, at points of the throughput-latency curve
(R7, DESIGN.md §15.30): is the knee of r7_xt where the server runs out of CPU?

Each cell is one Trust 2.0 run of run_local.py (base network, epochs of 25 rounds, 30 s after a 10 s warm-up). Once
the nodes are up and warmed up, the cgroup v2 `cpu.stat` of their systemd scope is read 5 s into the measured part
and again 20 s later: cores = usage / 20 s, throttled = share of the scheduler periods in which the quota ran out.
Linux only. Run from prototype/benchmark/:  python3 cpustat.py
"""
import csv
import os
import subprocess
import sys
import time

OUT = "results-p5/r7_cpu.csv"
# (nodes, input rate): the highest rate of r7_xt without timeouts and the rates past the knee.
CELLS = [(4, 200_000), (4, 350_000), (4, 400_000), (10, 100_000), (10, 150_000), (10, 175_000),
         (31, 40_000), (31, 50_000), (31, 60_000), (31, 70_000)]
WARMUP, DURATION, SKIP, WINDOW = 10, 30, 5, 20


def node_pids():
    done = subprocess.run(["pgrep", "-f", os.path.abspath(os.path.join("..", "target", "release", "node"))],
                          capture_output=True, text=True)
    return [int(p) for p in done.stdout.split()]


def cpu_stat(pid):
    with open(f"/proc/{pid}/cgroup") as fh:
        path = fh.read().strip().split("::", 1)[1]
    with open(f"/sys/fs/cgroup{path}/cpu.stat") as fh:
        return path, {k: int(v) for k, v in (line.split() for line in fh)}


def measure(nodes, rate):
    args = ["python3", "run_local.py", "--build", "trust2", "--nodes", str(nodes), "--net", "base",
            "--epoch-length", "25", "--rate", str(rate), "--warmup", str(WARMUP), "--duration", str(DURATION)]
    run = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        start = time.time()
        while len(node_pids()) < nodes:
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
    return dict(nodes=nodes, rate=rate, scope=scope,
                cores=round((after["usage_usec"] - before["usage_usec"]) / (WINDOW * 1e6), 2),
                throttled_pct=round(100 * (after["nr_throttled"] - before["nr_throttled"]) / periods, 1) if periods else "")


def main():
    cells = CELLS if len(sys.argv) == 1 else [tuple(int(x) for x in c.split(":")) for c in sys.argv[1:]]
    rows = []
    for nodes, rate in cells:
        row = measure(nodes, rate)
        print(row, flush=True)
        rows.append(row)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
