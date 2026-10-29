"""Inclusion of observed transactions in one run (DESIGN.md §12.4): python3 otxstat.py logs

Submission times come from the observer's log, inclusion times from the first node that committed the
transaction; victims are the accounts divisible by 4 (the censoring nodes' targets). Also counts the
omission facts and leader exclusions on node-0's ledger.
"""
import re
import sys
from datetime import datetime
from glob import glob
from statistics import mean, median

SENT = re.compile(r"\[(\S+)Z .* Observed transaction (\S+) account (\d+)")
COMMITTED = re.compile(r"\[(\S+)Z .* Committed B\d+ -> observed transaction (\S+)")


def ts(s):
    return datetime.fromisoformat(s).timestamp()


def summary(delays):
    if not delays:
        return "none"
    return f"{len(delays)} included, mean {mean(delays):.0f} ms, median {median(delays):.0f} ms, max {max(delays):.0f} ms"


if __name__ == "__main__":
    logs = sys.argv[1]
    sent = {}
    with open(f"{logs}/observer.log") as fh:
        for line in fh:
            m = SENT.match(line)
            if m:
                sent[m.group(2)] = (ts(m.group(1)), int(m.group(3)) % 4 == 0)
    first = {}
    for path in glob(f"{logs}/node-*.log"):
        with open(path) as fh:
            for line in fh:
                m = COMMITTED.match(line)
                if m and (m.group(2) not in first or ts(m.group(1)) < first[m.group(2)]):
                    first[m.group(2)] = ts(m.group(1))
    victim = [1000 * (first[x] - t) for x, (t, v) in sent.items() if v and x in first]
    other = [1000 * (first[x] - t) for x, (t, v) in sent.items() if not v and x in first]
    missing = sum(1 for x in sent if x not in first)
    print(f"  observed transactions: {len(sent)} submitted, {missing} not included by the end of the run")
    print(f"  victim accounts: {summary(victim)}")
    print(f"  other accounts:  {summary(other)}")
    censors = set()
    for path in glob(f"{logs}/node-*.log"):
        with open(path) as fh:
            text = fh.read()
        name = re.search(r"Node (\S+) successfully booted", text)
        if name and "Censoring the observed transactions" in text:
            censors.add(name.group(1))
    with open(f"{logs}/node-0.log") as fh:
        g2 = [line.split("G2: ")[1].strip() for line in fh if "G2:" in line]
    side = lambda who: "censor" if who in censors else "honest"
    omissions = [line.split(" by ")[-1] for line in g2 if line.startswith("omission of")]
    exclusions = [line.split(" ")[0] for line in g2 if "excluded from leading" in line]
    count = lambda xs, k: sum(1 for x in xs if side(x) == k)
    print(f"  censoring nodes: {len(censors)}")
    print(f"  omission facts on the ledger: {len(omissions)} (against censors {count(omissions, 'censor')}, "
          f"honest {count(omissions, 'honest')})")
    print(f"  leader exclusions: {len(exclusions)} (censors {count(exclusions, 'censor')}, "
          f"honest {count(exclusions, 'honest')})")
