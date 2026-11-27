"""Where the extra end-to-end latency under late messages comes from (DESIGN.md 15.57): from kept run logs.

For every batch of a run: the time it waits from its creation in a mempool to the creation of the block in which it
is first committed, and from there to that commit. The blocks are grouped by their position in the epoch (rounds since the
round at which node 0 entered the epoch, so that 23 is the terminal block and 24 the block after it; without epochs,
the round modulo 25, as a reference). Per arm, over its
runs: the mean wait and the mean commit time of a batch, the share of the batches and of the total wait by position,
the mean time from the creation of one block to the next by position, and the rounds without a block.

Run from prototype/benchmark/:  python3 latediag.py <label>=<glob of .tgz> ...
    python3 latediag.py baseline='results-final/lc_logs/baseline-e25-*.tgz' e25='results-final/lc_logs/trust2-e25-*.tgz' \
        e0='results-final/lc_logs/trust2-e0-*.tgz'
Standard library only."""
import glob
import os
import re
import shutil
import sys
import tarfile
import tempfile
from collections import defaultdict
from datetime import datetime
from multiprocessing import Pool
from statistics import mean, median

STAMP = re.compile(r"^\[(\S+)Z ")
CREATED = re.compile(r"\] Created B(\d+)(?: -> (\S+))?$")
COMMITTED = re.compile(r"\] Committed B(\d+)(?: -> (\S+))?$")
BATCH = re.compile(r"\] Batch (\S+) contains \d+ B$")
ENTERED = re.compile(r"\] Entered epoch (\d+) at round (\d+)")
CYCLE = 25                                   # an epoch of 25 rounds: 24 blocks on the ledger, then the block after the terminal one


def run(path):
    """Per batch of the run: (position of its block, wait before the block, block to commit); and the blocks."""
    d = tempfile.mkdtemp()
    with tarfile.open(path) as tar:
        tar.extractall(d)
    created, payload, born, done, entered = {}, defaultdict(list), {}, {}, []
    for log in glob.glob(d + "/logs/node-*.log"):
        node0 = log.endswith("/node-0.log")
        with open(log) as fh:
            for line in fh:
                if "] Created B" in line:
                    m = CREATED.search(line.rstrip())
                    if m:
                        t = datetime.fromisoformat(STAMP.match(line).group(1)).timestamp()
                        if m.group(2):
                            payload[int(m.group(1))].append(m.group(2))
                        else:
                            created[int(m.group(1))] = t
                elif "] Committed B" in line:
                    m = COMMITTED.search(line.rstrip())
                    if m and m.group(2):
                        t = datetime.fromisoformat(STAMP.match(line).group(1)).timestamp()
                        if t < done.get(m.group(2), (1e18, 0))[0]:
                            done[m.group(2)] = (t, int(m.group(1)))
                elif "] Batch " in line:
                    m = BATCH.search(line.rstrip())
                    if m:
                        born[m.group(1)] = datetime.fromisoformat(STAMP.match(line).group(1)).timestamp()
                elif node0 and "] Entered epoch " in line:
                    m = ENTERED.search(line)
                    entered.append(int(m.group(2)))
    shutil.rmtree(d, ignore_errors=True)
    entered.sort()
    first = min(created) if created else 0

    def position(r):
        if not entered:
            return r % CYCLE
        start = max([e for e in entered if e <= r], default=None)
        return max(0, min(r - 2, CYCLE - 1)) if start is None else min(r - start, CYCLE - 1)   # 23: terminal, 24: after it

    # A batch may be in the payload of several blocks (a proposer that has not seen the first one includes it again):
    # it is counted once, with the block of its first commit.
    batches, again, waits = [], sum(len(v) for v in payload.values()), defaultdict(list)
    for x, (t, r) in done.items():
        if x in born and r in created:
            batches.append((position(r), created[r] - born[x], t - created[r]))
            waits[r].append(created[r] - born[x])
    # Per handover: the pause in which no block carries a batch (from the last block with a payload before the
    # epoch to the first one in it), and the batches of that first block with the sum of their waits.
    with_payload = sorted(r for r in created if payload.get(r))
    handovers = []
    for e in entered:
        before = [r for r in with_payload if r < e]
        after = [r for r in with_payload if r >= e]
        if before and after:
            handovers.append((created[after[0]] - created[before[-1]], len(waits[after[0]]), sum(waits[after[0]]),
                              after[0] - before[-1]))
    rounds = sorted(created)
    gaps = [(position(a), created[b] - created[a], b - a) for a, b in zip(rounds, rounds[1:])]
    return dict(path=os.path.basename(path), batches=batches, gaps=gaps, blocks=len(rounds),
                top=rounds[-1] if rounds else 0, first=first, handovers=len(entered),
                empty=sum(1 for r in rounds if not payload.get(r)), inclusions=again, pauses=handovers)


def report(label, runs):
    batches = [b for r in runs for b in r["batches"]]
    gaps = [g for r in runs for g in r["gaps"]]
    wait, cons = mean(b[1] for b in batches), mean(b[2] for b in batches)
    print(f"\n## {label}: {len(runs)} runs, {len(batches)} batches ({sum(r['inclusions'] for r in runs)} inclusions in blocks), {sum(r['blocks'] for r in runs)} blocks "
          f"({sum(r['empty'] for r in runs)} without a batch), {sum(r['handovers'] for r in runs)} epochs entered\n")
    print(f"Per batch: wait before its block {1000 * wait:.0f} ms (median {1000 * median(b[1] for b in batches):.0f}), "
          f"block to commit {1000 * cons:.0f} ms (median {1000 * median(b[2] for b in batches):.0f}); "
          f"per run, mean wait {', '.join(str(round(1000 * mean(b[1] for b in r['batches']))) for r in runs)}")
    pauses = [h for r in runs for h in r["pauses"]]
    if pauses:
        n_first, w_first = sum(h[1] for h in pauses), sum(h[2] for h in pauses)
        other = (sum(b[1] for b in batches) - w_first) / (len(batches) - n_first)
        excess = (w_first - n_first * other) / len(batches)
        long = [h for h in pauses if h[0] > 1.0]
        n_long, w_long = sum(h[1] for h in long), sum(h[2] for h in long)
        print(f"\nHandovers: {len(pauses)}; pause without a batch in any block: median {1000 * median(h[0] for h in pauses):.0f} ms, "
              f"mean {1000 * mean(h[0] for h in pauses):.0f} ms, longer than 1 s in {len(long)} "
              f"(rounds from the last block with a payload to the first: median {median(h[3] for h in pauses)}, max {max(h[3] for h in pauses)}). "
              f"The first block with a payload of an epoch holds {100 * n_first / len(batches):.1f}% of the batches and "
              f"{100 * w_first / sum(b[1] for b in batches):.1f}% of the total wait; elsewhere a batch waits {1000 * other:.0f} ms. "
              f"What these batches wait beyond that, spread over all batches: {1000 * excess:.0f} ms per batch, "
              f"of which {1000 * (w_long - n_long * other) / len(batches):.0f} ms from the {len(long)} pauses longer than 1 s "
              f"({', '.join(f'{h[0]:.2f}' for h in sorted(long))} s).")
    print("\n| position | blocks to the next | mean time to the next block ms | rounds skipped after it | batches % | "
          "mean wait ms | share of the total wait % | mean block-to-commit ms |")
    print("|---|---|---|---|---|---|---|---|")
    total = sum(b[1] for b in batches)
    for p in range(CYCLE):
        bs = [b for b in batches if b[0] == p]
        gs = [g for g in gaps if g[0] == p]
        if not bs and not gs:
            continue
        print(f"| {p} | {len(gs)} | {1000 * mean(g[1] for g in gs) if gs else 0:.0f} | "
              f"{sum(g[2] - 1 for g in gs)} | {100 * len(bs) / len(batches):.1f} | "
              f"{1000 * mean(b[1] for b in bs) if bs else 0:.0f} | {100 * sum(b[1] for b in bs) / total:.1f} | "
              f"{1000 * mean(b[2] for b in bs) if bs else 0:.0f} |")
    return wait, cons


if __name__ == "__main__":
    arms = [a.split("=", 1) for a in sys.argv[1:]]
    print("# Where a batch waits under late messages, by the position of its block in the epoch")
    summary = []
    with Pool(8) as pool:
        for label, pattern in arms:
            runs = pool.map(run, sorted(glob.glob(pattern)))
            summary.append((label, *report(label, runs)))
    print("\n## Summary\n\n| arm | wait before the block ms | block to commit ms | sum ms |\n|---|---|---|---|")
    for label, wait, cons in summary:
        print(f"| {label} | {1000 * wait:.0f} | {1000 * cons:.0f} | {1000 * (wait + cons):.0f} |")
