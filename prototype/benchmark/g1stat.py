"""G1 evidence and punishments in one run (DESIGN.md §13): python3 g1stat.py logs

Roles come from the nodes' parameter logs (experiment switches); events from node-0's ledger.
"""
import re
import sys
from collections import Counter, defaultdict
from glob import glob

ROLES = (("Voting twice", "equivocator"), ("Lying about NR", "NR liar"), ("Censoring", "censor"),
         ("Proposing and voting for invalid blocks", "invalid block"), ("Regressing the high QC", "regressor"))

if __name__ == "__main__":
    logs = sys.argv[1]
    role = {}
    for path in glob(f"{logs}/node-*.log"):
        with open(path) as fh:
            text = fh.read()
        name = re.search(r"Node (\S+) successfully booted", text)
        if name:
            role[name.group(1)] = next((r for marker, r in ROLES if marker in text), "honest")
    with open(f"{logs}/node-0.log") as fh:
        g1 = [line.split("G1: ")[1].strip() for line in fh if "G1: " in line]
    ledger = Counter((line.split("(")[0], role.get(line.split("(")[1].split(",")[0], "?"))
                     for line in g1 if "on the ledger" in line)
    events = defaultdict(list)
    for line in g1:
        m = re.match(r"(\S+) (level L\d|queued for suspension|suspended|released|evicted|downgraded by governance) "
                     r"at epoch (\d+)", line)
        if m:
            events[m.group(1)].append((m.group(2), int(m.group(3))))
    print(f"  nodes: {Counter(role.values())}")
    print(f"  evidence on the ledger (type, culprit role): {dict(ledger)}")
    punished = Counter(role.get(who, "?") for who in events)
    print(f"  punished entities by role: {dict(punished)}")
    for who, evs in sorted(events.items(), key=lambda x: role.get(x[0], "?")):
        seq = " ".join(f"{e.split()[-1] if e.startswith('level') else e.split()[0]}@{k}" for e, k in evs[:14])
        print(f"    {role.get(who, '?'):12s} {who}: {seq}")
    # Concurrently suspended entities over the epochs (from node-0's events).
    current, peak = set(), 0
    timeline = sorted(((k, e, who) for who, evs in events.items() for e, k in evs
                       if e in ("suspended", "released", "evicted")), key=lambda x: (x[0], x[1] != "released"))
    for k, e, who in timeline:
        if e == "suspended":
            current.add(who)
        else:
            current.discard(who)
        peak = max(peak, len(current))
    print(f"  most entities suspended at once: {peak}")
