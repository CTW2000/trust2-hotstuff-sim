"""Epoch-handover lag and timed-out rounds from the node logs of one run: python3 lagstat.py logs"""
import re
import sys
from collections import defaultdict
from datetime import datetime
from glob import glob
from statistics import median

ENTER = re.compile(r"\[(\S+)Z INFO  consensus::core\] Entered epoch (\d+)")
TIMEOUT = re.compile(r"\[(\S+)Z WARN  consensus::core\] Timeout reached for round (\d+)")
COMMITTED = re.compile(r"\[\S+Z INFO  consensus::core\] Committed B(\d+)$")


def ts(s):
    return datetime.fromisoformat(s).timestamp()


def stats(logs):
    """Handover lags (slowest minus fastest node per epoch change), timed-out rounds and the highest committed round."""
    entries = defaultdict(dict)                 # epoch -> node -> time
    timeouts = {}
    top = 0
    for path in glob(f"{logs}/node-*.log"):
        node = int(re.search(r"node-(\d+)", path).group(1))
        rounds = set()
        with open(path) as fh:
            for line in fh:
                m = ENTER.match(line)
                if m:
                    entries[int(m.group(2))][node] = ts(m.group(1))
                    continue
                m = TIMEOUT.match(line)
                if m:
                    rounds.add(int(m.group(2)))
                    continue
                m = COMMITTED.match(line.rstrip())
                if m:
                    top = max(top, int(m.group(1)))
        timeouts[node] = rounds
    nodes = len(timeouts)
    complete = {e: d for e, d in entries.items() if len(d) == nodes}
    lags = sorted((max(d.values()) - min(d.values())) * 1000 for d in complete.values())
    worst = max(((max(d.values()) - min(d.values()), e, max(d, key=d.get)) for e, d in complete.items()),
                default=(0.0, None, None))
    rounds = sorted(set().union(*timeouts.values())) if timeouts else []
    return dict(epochs=max(complete, default=0), incomplete=sorted(e for e in entries if e not in complete),
                lag_median_ms=median(lags) if lags else 0.0, lag_max_ms=lags[-1] if lags else 0.0,
                worst_epoch=worst[1], worst_node=worst[2], timeout_rounds=rounds, top_round=top)


if __name__ == "__main__":
    s = stats(sys.argv[1])
    print(f"  epochs reached by all: {s['epochs']}; incomplete: {' '.join(f'e{e}' for e in s['incomplete']) or '-'}")
    print(f"  worst handover lag: {s['lag_max_ms']:.0f} ms (epoch {s['worst_epoch']}, node-{s['worst_node']}); "
          f"median {s['lag_median_ms']:.0f} ms")
    r = s["timeout_rounds"]
    print(f"  rounds with a local timeout: {len(r)} {r[:12]}{' ...' if len(r) > 12 else ''}; top round {s['top_round']}")
