"""Where the stalls of one run fall: python3 stallstat.py logs [epoch_length]

A stall is a round in which at least f+1 nodes timed out (the round needed a TC). For Trust 2.0 runs the offset of
each stall is taken from the nearest terminal block (from node-0's "Entered epoch" lines); for a baseline run, which
has no epochs, from the nearest multiple of epoch_length, as a reference for how stalls spread without handovers."""
import re
import sys
from collections import Counter, defaultdict
from glob import glob

TIMEOUT = re.compile(r"\[\S+Z WARN  consensus::core\] Timeout reached for round (\d+)")
ENTER = re.compile(r"\[\S+Z INFO  consensus::core\] Entered epoch (\d+) at round (\d+) \(terminal block B(\d+)\)")
COMMITTED = re.compile(r"\[\S+Z INFO  consensus::core\] Committed B(\d+)$")


def stats(logs, epoch_length=50):
    timed_out = defaultdict(set)                # round -> nodes that timed out in it
    terminals = set()
    committed = set()
    paths = glob(f"{logs}/node-*.log")
    for path in paths:
        node = int(re.search(r"node-(\d+)", path).group(1))
        with open(path) as fh:
            for line in fh:
                m = TIMEOUT.match(line)
                if m:
                    timed_out[int(m.group(1))].add(node)
                    continue
                m = ENTER.match(line)
                if m:
                    terminals.add(int(m.group(3)))
                    continue
                if node == 0:
                    m = COMMITTED.match(line.rstrip())
                    if m:
                        committed.add(int(m.group(1)))
    n = len(paths)
    f = (n - 1) // 3
    stalls = sorted(r for r, nodes in timed_out.items() if len(nodes) >= f + 1)
    top = max(committed, default=0)
    anchors = sorted(terminals) or list(range(epoch_length, top + epoch_length, epoch_length))
    offsets = Counter()
    for r in stalls:
        nearest = min(anchors, key=lambda a: abs(r - a))
        offsets[r - nearest] += 1
    near = sum(c for o, c in offsets.items() if -1 <= o <= 4)
    return dict(nodes=n, top=top, stalls=stalls, offsets=offsets, near=near, anchors=len(anchors),
                epochs=bool(terminals), missing=sorted(set(range(1, top + 1)) - committed))


if __name__ == "__main__":
    s = stats(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 50)
    kind = "terminal blocks" if s["epochs"] else "multiples of the epoch length (no epochs)"
    print(f"  top committed round {s['top']}; rounds without a committed block {len(s['missing'])}")
    print(f"  stalls (>= f+1 nodes timed out): {len(s['stalls'])}; anchors: {s['anchors']} {kind}")
    print(f"  stalls at offsets -1..+4 from an anchor: {s['near']} of {len(s['stalls'])}")
    print("  offset histogram: " + " ".join(f"{o:+d}:{c}" for o, c in sorted(s["offsets"].items())))
