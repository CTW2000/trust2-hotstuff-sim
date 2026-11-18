"""Where the leader of an accused round was when the others gave up on it (DESIGN.md 15.42), from the kept logs of
the runs of probe47.py under the trust2 rule. For every accusation on node-0's ledger against an honest leader: did
that leader still sit in the round before (it timed out there: it had not gathered the QC that moved the others on),
did it make no block for the round, did its block come late, or was the block in time. Also the rounds in which some
node timed out, to compare how often the two arms stall. Reads the tarballs; standard library only.
Run from prototype/benchmark/:  python3 votecls.py results-probe47/cmp_votes_logs/*-trust2-*.tgz
The arm is in the name of the tarball: next (votes to the next leader), all (to all members), fwd (to all members,
and the QC forwarded to the next leader, probe48.py).
"""
import os
import re
import sys
import tarfile
from datetime import datetime

import p5

TS = re.compile(r"^\[(\S+)Z ")
KINDS = ("leader in the round before", "leader made no block", "leader's block late", "leader's block in time")


def ts(line):
    return datetime.strptime(TS.match(line).group(1), "%Y-%m-%dT%H:%M:%S.%f").timestamp()


def load(path):
    name, role, tmo, made, acc = {}, {}, {}, {}, []
    with tarfile.open(path) as tar:
        for member in tar:
            m = re.search(r"node-(\d+)\.log$", member.name)
            if not m:
                continue
            i = int(m.group(1))
            tmo[i], made[i] = {}, {}
            text = tar.extractfile(member).read().decode(errors="replace")
            who = re.search(r"Node (\S+) successfully booted", text)
            if who:
                name[who.group(1)] = i
                role[who.group(1)] = next((r for marker, r in p5.ROLES if marker in text), "honest")
            for line in text.splitlines():
                if "Timeout reached for round" in line:
                    tmo[i].setdefault(int(line.rsplit(" ", 1)[1]), ts(line))
                elif "proposer] Created B" in line and "->" not in line:
                    made[i].setdefault(int(line.rsplit("B", 1)[1]), ts(line))
                elif i == 0 and "G2: accusation of round" in line:
                    m = re.search(r"round (\d+) led by (\S+)", line)
                    acc.append((int(m.group(1)), m.group(2)))
    return name, role, tmo, made, acc


def classify(path):
    name, role, tmo, made, acc = load(path)
    kinds = dict.fromkeys(KINDS, 0)
    for r, who in acc:
        if role.get(who, "honest") != "honest":
            continue
        leader = name[who]
        first = min((t[r] for t in tmo.values() if r in t), default=None)     # the first node to give up on round r
        block = made[leader].get(r)
        if r - 1 in tmo[leader]:
            kinds[KINDS[0]] += 1
        elif block is None:
            kinds[KINDS[1]] += 1
        elif first is not None and block > first - 0.5:                        # the timeout is 1 s
            kinds[KINDS[2]] += 1
        else:
            kinds[KINDS[3]] += 1
    stalled = len({r for t in tmo.values() for r in t})
    return kinds, stalled


def main(paths):
    total = {}
    print("| run | rounds with a timeout | " + " | ".join(KINDS) + " |")
    print("|---|---|" + "---|" * len(KINDS))
    for path in sorted(paths):
        m = re.match(r"(.+)-trust2-(all|next|fwd)-(\d+)\.tgz$", os.path.basename(path))
        if not m:
            continue
        kinds, stalled = classify(path)
        print(f"| {m.group(1)} {m.group(2)} {m.group(3)} | {stalled} | " + " | ".join(str(kinds[k]) for k in KINDS) + " |", flush=True)
        cell = total.setdefault((m.group(1), m.group(2)), dict.fromkeys(KINDS + ("stalled", "runs"), 0))
        for k in KINDS:
            cell[k] += kinds[k]
        cell["stalled"] += stalled
        cell["runs"] += 1
    print("\n| scenario | votes to | runs | rounds with a timeout | accusations of honest leaders | " + " | ".join(KINDS) + " |")
    print("|---|---|---|---|---|" + "---|" * len(KINDS))
    for (sc, arm), cell in sorted(total.items()):
        print(f"| {sc} | {arm} | {cell['runs']} | {cell['stalled']} | {sum(cell[k] for k in KINDS)} | "
              + " | ".join(str(cell[k]) for k in KINDS) + " |")


if __name__ == "__main__":
    main(sys.argv[1:])
