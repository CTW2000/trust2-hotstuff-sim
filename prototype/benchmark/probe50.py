"""DESIGN.md 15.45: what votes to all members cost at n = 100 without late messages, where they bring nothing: each
round has n * n vote messages instead of n, and with the forward up to n - 1 QCs more. Trust 2.0, 2,000 tx/s, base
network, epochs of 25 rounds, 40 s; the three ways of sending votes alternate inside each of five repetitions.
Besides the usual columns: CPU of the scope of the run (cores, share of throttled periods, as cpustat.py) and bytes
per second on the loopback interface, which carries all traffic of the run, over 20 s of the measured part.
Run from prototype/benchmark/:  nohup python3 probe50.py > results-probe50/run.log 2>&1 < /dev/null &"""
import os
os.environ["TTRU_OUT"] = "results-probe50"
os.environ["TTRU_MAX_NODES"] = "100"
import threading
import time

import cpustat
import p5

NODES, SKIP, WINDOW = 100, 5, 20
ARMS = (("next", False, False), ("all", True, False), ("fwd", True, True))


def lo_bytes():
    with open("/proc/net/dev") as fh:
        for line in fh:
            if line.strip().startswith("lo:"):
                return int(line.split(":", 1)[1].split()[0])
    return 0


class Sampler(threading.Thread):
    """CPU of the scope and loopback bytes over WINDOW seconds, from SKIP seconds into the measured part."""

    def __init__(self):
        super().__init__(daemon=True)
        self.result = {}

    def run(self):
        start = time.time()
        while len(cpustat.node_pids()) < NODES:
            if time.time() - start > 300:
                return
            time.sleep(0.2)
        time.sleep(p5.WARMUP + SKIP)
        try:
            pid = cpustat.node_pids()[0]
            _, cpu0 = cpustat.cpu_stat(pid)
            lo0, t0 = lo_bytes(), time.time()
            time.sleep(WINDOW)
            _, cpu1 = cpustat.cpu_stat(pid)
            lo1, t1 = lo_bytes(), time.time()
        except (IndexError, OSError):
            return
        periods = cpu1["nr_periods"] - cpu0["nr_periods"]
        self.result = dict(
            cores=round((cpu1["usage_usec"] - cpu0["usage_usec"]) / ((t1 - t0) * 1e6), 2),
            throttled_pct=round(100 * (cpu1["nr_throttled"] - cpu0["nr_throttled"]) / periods, 1) if periods else "",
            lo_mb_s=round((lo1 - lo0) / (t1 - t0) / 1e6, 1))


def main():
    p5.RATE = 2_000
    for rep in range(1, 6):
        for arm, broadcast, forward in ARMS:
            sampler = Sampler()
            sampler.start()
            p5.run("scale100_votes", dict(scenario="none", build="trust2", nodes=NODES, net="base", epoch_length=25,
                                          rep=rep, leader_rule="trust2", g2_threshold=0, broadcast_votes=broadcast,
                                          forward_qc=forward), 40,
                   extra=lambda logs: (sampler.join(timeout=30), sampler.result)[1])


if __name__ == "__main__":      # the pool of the log parser starts a fork server that imports this file again
    main()
