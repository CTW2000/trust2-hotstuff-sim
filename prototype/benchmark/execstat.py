"""The execution layer of a run (DESIGN.md §15.38): what the nodes executed and whether their states agree.

Every node that runs with --execute logs, for each block of its ledger with transactions,
    Executed B<round> -> <n> txs in <us> us, state <digest>
where the digest covers the result of every transaction so far. Two nodes that executed the same ledger log the same
digest at the same block; a difference is a divergence of the replicated state.

    python3 execstat.py [logs]
"""
import re
import sys
from glob import glob
from os.path import join

LINE = re.compile(r"Executed B(\d+) -> (\d+) txs in (\d+) us, state ([0-9a-f]{16})")


def stats(logs="logs"):
    nodes = {}
    for path in sorted(glob(join(logs, "node-*.log"))):
        with open(path) as fh:
            rows = [(int(r), int(n), int(us), d) for r, n, us, d in LINE.findall(fh.read())]
        if rows:
            nodes[path] = rows
    by_round = {}
    for rows in nodes.values():
        for r, _, _, d in rows:
            by_round.setdefault(r, set()).add(d)
    executed = [sum(n for _, n, _, _ in rows) for rows in nodes.values()]
    micros = sum(us for rows in nodes.values() for _, _, us, _ in rows)
    return dict(
        exec_nodes=len(nodes),
        exec_blocks=max((len(rows) for rows in nodes.values()), default=0),
        exec_txs=max(executed, default=0),
        exec_txs_min=min(executed, default=0),
        exec_us_per_tx=round(micros / max(sum(executed), 1), 3),
        exec_rounds_compared=sum(1 for ds in by_round.values() if ds),
        exec_state_mismatches=sum(1 for ds in by_round.values() if len(ds) > 1),
    )


if __name__ == "__main__":
    print(stats(sys.argv[1] if len(sys.argv) > 1 else "logs"))
