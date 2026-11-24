"""DESIGN.md 15.53: the leader rules under lateness, as the mock review M1 asks (R5-R9). Ten blocks; the runs of a
block share their node keys (--keys-dir), so a table gives every arm of the block the same leader sequence. In each
block, on the Trust 2.0 code, n = 31, base network, epochs of 25 rounds, 180 s after a warm-up of 10 s:

A  lateness (R5): the four leader rules (none, aptos, failed, trust2) x four models of lateness x four shares.
   Models: P, each consensus message late on its own; S, a sender late for whole slots of one second; B, bursts of
   congestion (5 s at 40% late, as often as the share needs); all three at 2%, 5%, 10%, 20%. Q, as P with
   queueing: a late message holds back the ones behind it on its link (--late-fifo), at 0.5%, 1%, 2%, 3%: with
   queueing nothing commits any more at 5% (two trial runs of 30 s, DESIGN.md 15.53).
B  vote routing x leader rule (R6): votes to the next leader or to all members (--broadcast-votes), the four rules,
   with three silent leaders, with 10% late messages (model P; the arm with votes to the next leader is A's), and
   with six framers on top of 10% late messages.
C  the failure threshold of the Aptos-style rule (R6): 5%, 20%, 30% beside the default 10% of A, at 10% lateness
   in models P and S.
D  the G2 threshold (R7): ln 10^2, ln 10^3, ln 10^4 beside the protocol's ln 300 of B, with three silent leaders.

Every run leaves results-rmain/facts/<tag>.json: who proposed which round, the accusations, failed-proposal facts,
exclusions and releases on node 0's ledger, the Aptos-style weights, the epochs entered, and the committee. The
statistics are in rmainstat.py. The logs of the aptos arms at 10% lateness (model P, both routings) and with framers
are kept for the check against the code of aptos-core.

A run whose facts file exists is skipped, so the batch can be started again after a stop; while the file
results-rmain/pause exists the batch waits before its next run (another experiment can use the server).
Run from prototype/benchmark/:
    mkdir -p results-rmain && (setsid nohup python3 rmain.py > results-rmain/run.log 2>&1 < /dev/null &)"""
import json
import os
import re
import shutil
import sys
import time
from glob import glob

os.environ["TTRU_OUT"] = "results-rmain"
import p5

OUT = "results-rmain"
BLOCKS = range(1, 11)
RULES = ("none", "aptos", "failed", "trust2")
MODELS = ("P", "S", "B", "Q")
SHARES = {"P": (2, 5, 10, 20), "S": (2, 5, 10, 20), "B": (2, 5, 10, 20), "Q": (0.5, 1, 2, 3)}
DURATION = 180
BASE = dict(build="trust2", nodes=31, net="base", epoch_length=25)
THRESHOLDS = {"1e2": 4_605_170, "1e3": 6_907_755, "1e4": 9_210_340}      # ln 300 = 5_703_782 is the default


def lateness(model, share):
    """The switches of run_local.py for a model of lateness at a share (percent) of late consensus messages."""
    p = share / 100
    if model == "P":
        return dict(late_p=p)
    if model == "S":
        return dict(late_p=p, late_slot=1)
    if model == "B":                                         # 5 s at 40% late every 5 * 0.4 / p seconds
        return dict(burst_period=round(5 * 0.4 / p, 1), burst_len=5, burst_late_p=0.4)
    if model == "Q":
        return dict(late_p=p, late_fifo=True)
    raise ValueError(model)


def cells(block):
    """(part, tag, config, keep the logs) of every run of a block, the rules rotating from block to block."""
    rules = RULES[block % 4:] + RULES[:block % 4]
    out = []
    for model in MODELS:
        for share in SHARES[model]:
            for rule in rules:
                keep = rule == "aptos" and (model, share) == ("P", 10)
                out.append(("A", f"A-{model}{share}-{rule}", dict(scenario=f"{model}{share}", leader_rule=rule,
                                                                  **lateness(model, share)), keep))
    for name, faults in (("silent", dict(silent=3)), ("late", dict(late_p=0.1)),
                         ("framers", dict(frame=6, late_p=0.1))):
        for votes in ("next", "all"):
            if (name, votes) == ("late", "next"):
                continue                                     # A-P10
            for rule in rules:
                config = dict(scenario=f"{name}-{votes}", leader_rule=rule, **faults)
                if votes == "all":
                    config["broadcast_votes"] = True
                out.append(("B", f"B-{name}-{votes}-{rule}", config, rule == "aptos" and name != "silent"))
    for percent in (5, 20, 30):
        for model in ("P", "S"):
            out.append(("C", f"C-{model}10-aptos{percent}", dict(scenario=f"{model}10-aptos{percent}",
                                                                leader_rule="aptos", aptos_failure_percent=percent,
                                                                **lateness(model, 10)), False))
    for name, threshold in THRESHOLDS.items():
        out.append(("D", f"D-silent-trust2-{name}", dict(scenario=f"silent-{name}", leader_rule="trust2",
                                                        g2_threshold=threshold, silent=3), False))
    return out


def facts(logs, path):
    """What the statistics need from the logs of one run, written to `path`."""
    names, led, epochs = {}, {}, []
    for log in sorted(glob(f"{logs}/node-*.log")):
        node = int(re.search(r"node-(\d+)", log).group(1))
        rounds = []
        with open(log) as fh:
            for line in fh:
                if "] Proposed B" in line:
                    rounds.append(int(re.search(r"Proposed B(\d+)", line).group(1)))
                elif "successfully booted" in line:              # the mempool logs such a line too
                    m = re.search(r"Node (\S+) successfully booted", line)
                    if m:
                        names[node] = m.group(1)
                elif node == 0 and "] Entered epoch " in line:
                    m = re.search(r"Entered epoch (\d+) at round (\d+) \(terminal block B(\d+)\)", line)
                    epochs.append([int(m.group(1)), int(m.group(2)), int(m.group(3))])
        led[node] = rounds
    kinds = (("accusations", r"G2: accusation of round (\d+) led by (\S+)"),
             ("failed", r"G2: failed round (\d+) led by (\S+)"),
             ("omissions", r"G2: omission of \S+ at round (\d+) by (\S+)"))
    out = dict(names=names, led=led, epochs=epochs, accusations=[], failed=[], omissions=[], excluded=[], released=[],
               aptos=[], reputation=[])
    with open(f"{logs}/node-0.log") as fh:
        for line in fh:
            if "G2: " not in line and "Aptos: " not in line:
                continue
            msg = line.split("] ", 1)[1].strip()
            for key, pattern in kinds:
                m = re.match(pattern, msg)
                if m:
                    out[key].append([int(m.group(1)), m.group(2)])
            m = re.match(r"G2: (\S+) (excluded from leading|convicted, queued) at round (\d+)", msg)
            if m:
                out["excluded"].append([int(m.group(3)), m.group(1), m.group(2).split()[0]])
            m = re.match(r"G2: (\S+) may lead again at round (\d+)", msg)
            if m:
                out["released"].append([int(m.group(2)), m.group(1)])
            m = re.match(r"G2: reputation of (\S+) is (\d+) ppm", msg)
            if m:
                out["reputation"].append([m.group(1), int(m.group(2))])
            m = re.match(r"Aptos: (\S+) weight (failed|inactive) at epoch (\d+)", msg)
            if m:
                out["aptos"].append([int(m.group(3)), m.group(1), m.group(2)])
    switched = ("Voting twice", "Lying about NR", "Censoring", "Proposing and voting for invalid blocks",
                "Regressing the high QC", "Framing:", "Silent leader:", "Filling suffix blocks",
                "Withholding the commit proof")
    out["byzantine"] = []
    for log in sorted(glob(f"{logs}/node-*.log")):
        with open(log) as fh:
            head = fh.read(20_000)
        if any(f"] {s}" in head for s in switched):
            out["byzantine"].append(int(re.search(r"node-(\d+)", log).group(1)))
    for name in (".committee.json",):
        if os.path.exists(name):
            with open(name) as fh:
                out["committee"] = json.load(fh)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as fh:
        json.dump(out, fh)
    os.replace(path + ".tmp", path)
    return dict(facts=os.path.basename(path))


def main(blocks=BLOCKS, duration=DURATION, only=None):
    for block in blocks:
        keys = os.path.abspath(f"{OUT}/keys/block-{block}")
        for part, tag, config, keep in cells(block):
            if only and not tag.startswith(only):
                continue
            path = f"{OUT}/facts/{tag}-b{block}.json"
            if os.path.exists(path):
                continue
            while os.path.exists(f"{OUT}/pause"):
                time.sleep(30)
            extra = lambda logs, path=path: {**p5.local_stats(logs), **facts(logs, path)}
            row = p5.run(f"part{part}", dict(rep=block, keys_dir=keys, **BASE, **config), duration,
                         keep_logs=f"{tag}-b{block}" if keep and block <= 5 else None, extra=extra)
            if row is None:
                print(f"FAILED {tag} block {block}", flush=True)
    print("rmain done", flush=True)


if __name__ == "__main__":      # the pool of the log parser starts a fork server that imports this file again
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":         # two short runs into results-rmain-smoke
        OUT = "results-rmain-smoke"
        os.environ["TTRU_OUT"] = OUT
        p5.OUT = OUT
        shutil.rmtree(OUT, ignore_errors=True)
        main(blocks=(1,), duration=30, only="A-Q10-t")
        main(blocks=(1,), duration=30, only="A-S10-n")
    else:
        main()
