"""What the last `k` booted nodes hold together in one run (DESIGN.md §14.7): python3 entstat.py logs k

Their base shares and how many blocks they created come from each node's own log, the punishments from node-0's.
"""
import re
import sys
from glob import glob

if __name__ == "__main__":
    logs, k = sys.argv[1], int(sys.argv[2])
    created, names = {}, {}
    for path in glob(f"{logs}/node-*.log"):
        i = int(re.search(r"node-(\d+)", path).group(1))
        with open(path) as fh:
            text = fh.read()
        created[i] = len(set(re.findall(r"Created B(\d+)", text)))
        names[i] = re.search(r"Node (\S+) successfully booted", text).group(1)
    with open(f"{logs}/node-0.log") as fh:
        log = fh.read()
    base = dict(re.findall(r"T_tru base weight of (\S+) is (\d+) ppm", log))
    owner = sorted(names)[-k:]
    print(f"  base share of the {k} nodes: {sum(int(base[names[i]]) for i in owner) / 1e4:.2f}%")
    print(f"  blocks created by them: {sum(created[i] for i in owner)} of {sum(created.values())}")
    for i in sorted(names):
        events = re.findall(rf"G1: {re.escape(names[i])} (suspended|level L\d|evicted) at epoch (\d+)", log)
        if events:
            print(f"    node-{i}: {' '.join(e.split()[-1] + '@' + n for e, n in events[:6])}")
