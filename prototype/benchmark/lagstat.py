"""Epoch-handover lag and timed-out rounds from the node logs of one run: python3 lagstat.py logs"""
import re
import sys
from collections import defaultdict
from datetime import datetime
from glob import glob

ENTER = re.compile(r"\[(\S+)Z INFO  consensus::core\] Entered epoch (\d+)")
TIMEOUT = re.compile(r"\[(\S+)Z WARN  consensus::core\] Timeout reached for round (\d+)")


def ts(s):
    return datetime.fromisoformat(s).timestamp()


if __name__ == "__main__":
    entries = defaultdict(dict)                 # epoch -> node -> time
    timeouts = {}
    for path in glob(f"{sys.argv[1]}/node-*.log"):
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
        timeouts[node] = rounds
    nodes = len(timeouts)
    last = max((e for e, d in entries.items() if len(d) == nodes), default=0)
    worst = (0.0, None, None)
    missing = []
    for e, d in sorted(entries.items()):
        if len(d) < nodes:
            missing.append(f"e{e}:{nodes - len(d)}")
            continue
        first = min(d.values())
        for n, t in d.items():
            if t - first > worst[0]:
                worst = (t - first, e, n)
    rounds = sorted(set().union(*timeouts.values()))
    print(f"  epochs reached by all: {last}; incomplete: {' '.join(missing) or '-'}")
    print(f"  worst handover lag: {worst[0]*1000:.0f} ms (epoch {worst[1]}, node-{worst[2]})")
    print(f"  rounds with a local timeout: {len(rounds)} {rounds[:12]}{' ...' if len(rounds) > 12 else ''}")
