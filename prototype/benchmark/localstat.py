"""Statistics of the targeted experiments of DESIGN.md §15.25 (mock review R2-R4), from the node logs of one run:
    python3 localstat.py logs

- ledgers: every node's ledger ("Ledger: B<round> <digest>") must be a prefix of every other's (safety);
- H2 refusals and H4 blocks left off the ledger: no such block may be on any node's ledger (suffix_on_ledger);
  their batches reach the ledger only if an honest leader includes them again in a block of its own
  (filled_batches_reincluded: on receipt of a block every node drops its batches from its proposal buffer, as in
  the code this prototype builds on), and their protected transactions stay pending and reach the ledger later
  (suffix_otxs_on_ledger of suffix_otxs);
- per node: rounds led ("Proposed B<round>"), and on node 0's ledger the AT accusation and omission facts against it,
  its G2 convictions (exclusions, queueing) with the time of the first one, its lowest reputation, and the highest
  value its CUSUM reached (ppm; the threshold ln 10^2 is 4605170, one fact adds ln 5 = 1609438).
Honest nodes are those without an experiment switch; nodes hit by a crash, restart or region outage count as honest
here (they are: the outage only delays their messages), reported apart as "region".
"""
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from glob import glob

LINE = re.compile(r"\[(\S+)Z (\w+) +(\S+)\] (.*)$")
SWITCHES = ("Voting twice", "Lying about NR", "Censoring", "Proposing and voting for invalid blocks",
            "Regressing the high QC", "Framing:", "Silent leader:", "Filling suffix blocks",
            "Withholding the commit proof")


def ts(s):
    return datetime.fromisoformat(s).timestamp()


def read(path):
    with open(path) as fh:
        for line in fh:
            m = LINE.match(line.rstrip())
            if m:
                yield ts(m.group(1)), m.group(4)


def stats(logs):
    faulted = set()
    try:
        with open(f"{logs}/faulted.txt") as fh:
            faulted = {w.strip() for w in fh.read().split("\n")[1:] if w.strip()}
    except FileNotFoundError:
        pass
    names, roles, ledgers, led = {}, {}, {}, defaultdict(int)
    h2 = h4 = h4_filled = 0
    off_batches, committed_batches = set(), set()
    off_rounds, ledger_rounds = set(), set()
    off_otxs, ledger_otxs = set(), set()
    start = None
    for path in sorted(glob(f"{logs}/node-*.log")):
        node = int(re.search(r"node-(\d+)", path).group(1))
        ledger, role = [], "honest"
        for t, msg in read(path):
            start = t if start is None else min(start, t)
            if msg.startswith("Node ") and "successfully booted" in msg:
                names[node] = msg.split()[1]
            elif any(msg.startswith(s) for s in SWITCHES):
                role = "byzantine"
            elif msg.startswith("Ledger: "):
                _, rnd, digest = msg.split()
                ledger.append((int(rnd[1:]), digest))
                ledger_rounds.add(int(rnd[1:]))
            elif msg.startswith("Proposed B"):
                led[node] += 1
            elif "(H2)" in msg:
                h2 += 1
            elif "not on the ledger (H4)" in msg:
                h4 += 1
                if not msg.endswith(" 0 batches"):
                    h4_filled += 1
            elif msg.startswith("Off the ledger "):
                block, what = msg[len("Off the ledger "):].split(" -> ")
                off_rounds.add(int(block[1:]))
                if what.startswith("observed transaction "):
                    off_otxs.add(what.split()[-1])
                else:
                    off_batches.add(what)
            elif msg.startswith("Committed B") and " -> " in msg:
                what = msg.split(" -> ")[1]
                if what.startswith("observed transaction "):
                    ledger_otxs.add(what.split()[-1])
                else:
                    committed_batches.add(what)
        ledgers[node] = ledger
        name = names.get(node, str(node))
        # The logs print keys cut to 16 characters; faulted.txt has them in full.
        in_region = any(full.startswith(name) for full in faulted)
        roles[node] = "region" if role == "honest" and in_region else role

    # Safety: the ledgers are prefixes of one another.
    longest = max(ledgers.values(), key=len) if ledgers else []
    conflicts = sum(1 for led_ in ledgers.values() for a, b in zip(led_, longest) if a != b)

    # G2 on node 0's ledger, by leader name.
    by_name = {v: k for k, v in names.items()}
    g2 = defaultdict(lambda: dict(accusations=0, omissions=0, exclusions=0, queued=0, first_conviction_s=None,
                                  min_r_ppm=1_000_000, peak_ppm=0))
    for t, msg in read(f"{logs}/node-0.log"):
        m = re.match(r"G2: accusation of round \d+ led by (\S+)", msg)
        if m:
            g2[m.group(1)]["accusations"] += 1
            continue
        m = re.match(r"G2: omission of \S+ at round \d+ by (\S+)", msg)
        if m:
            g2[m.group(1)]["omissions"] += 1
            continue
        m = re.match(r"G2: (\S+) (excluded from leading|convicted, queued) at round \d+", msg)
        if m:
            entry = g2[m.group(1)]
            entry["exclusions" if m.group(2).startswith("excluded") else "queued"] += 1
            if entry["first_conviction_s"] is None:
                entry["first_conviction_s"] = round(t - start, 1)
            continue
        m = re.match(r"G2: CUSUM peak of (\S+) is (\d+) ppm", msg)
        if m:
            entry = g2[m.group(1)]
            entry["peak_ppm"] = max(entry["peak_ppm"], int(m.group(2)))
            continue
        m = re.match(r"G2: reputation of (\S+) is (\d+) ppm", msg)
        if m:
            entry = g2[m.group(1)]
            entry["min_r_ppm"] = min(entry["min_r_ppm"], int(m.group(2)))

    out = dict(ledger_nodes=len(ledgers), ledger_conflicts=conflicts,
               ledger_min=min((len(x) for x in ledgers.values()), default=0), ledger_max=len(longest),
               h2_refused=h2, h4_off_ledger=h4, h4_filled=h4_filled, suffix_on_ledger=len(off_rounds & ledger_rounds),
               filled_batches=len(off_batches), filled_batches_reincluded=len(off_batches & committed_batches),
               suffix_otxs=len(off_otxs), suffix_otxs_on_ledger=len(off_otxs & ledger_otxs))
    for group in ("honest", "region"):
        nodes = [n for n, r in roles.items() if r == group]
        rows = [g2[names[n]] for n in nodes if n in names]
        convicted = [r for r in rows if r["exclusions"] or r["queued"]]
        firsts = [r["first_conviction_s"] for r in convicted if r["first_conviction_s"] is not None]
        out.update({
            f"{group}_nodes": len(nodes),
            f"{group}_leads": sum(led[n] for n in nodes),
            f"{group}_accusations": sum(r["accusations"] for r in rows),
            f"{group}_omissions": sum(r["omissions"] for r in rows),
            f"{group}_convictions": sum(r["exclusions"] + r["queued"] for r in rows),
            f"{group}_convicted_nodes": len(convicted),
            f"{group}_first_conviction_s": min(firsts) if firsts else None,
            f"{group}_min_r_ppm": min((r["min_r_ppm"] for r in rows), default=1_000_000),
            f"{group}_max_accusations_per_node": max((r["accusations"] for r in rows), default=0),
            f"{group}_max_facts_per_node": max((r["accusations"] + r["omissions"] for r in rows), default=0),
            f"{group}_cusum_peak_ppm": max((r["peak_ppm"] for r in rows), default=0),
        })
    return out


if __name__ == "__main__":
    print(json.dumps(stats(sys.argv[1] if len(sys.argv) > 1 else "logs"), indent=1))
