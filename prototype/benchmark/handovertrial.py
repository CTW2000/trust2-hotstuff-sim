"""DESIGN.md 15.58, a trial: does the handover get shorter when the holder of the commit proof proposes the first
block of the epoch at whatever round the proof forms (--proof-holder-leads)? Without the switch the old leader is
kept only at the round terminal + 2, and a timeout right after the terminal block costs two more (15.57).

On the trial build, n = 31, base network, epochs of 25 rounds, 10,000 tx/s, 180 s after a warm-up of 10 s; the runs
of a block share their node keys, taken from the blocks of results-epoch/ when they are there, so that a run without
the switch repeats a run of 15.56:

late    10% late messages: the baseline; Trust 2.0 without the switch, with it, and with a single epoch.
silent  three Byzantine silent leaders: Trust 2.0 without the switch and with it (same keys, same leader sequence up
        to the first handover that the switch changes).

Every run keeps its logs (results-trial/trial_logs/) for latediag.py. A pilot of one block first:
    mkdir -p results-trial && (setsid nohup python3 handovertrial.py 1 > results-trial/run-1.log 2>&1 < /dev/null &)"""
import json
import os
import sys
import time

os.environ["TTRU_OUT"] = "results-trial"
import p5
import rmain                                    # for its facts(); it sets TTRU_OUT for its own batch on import
from stallstat import stats as stall_stats

os.environ["TTRU_OUT"] = "results-trial"
OUT = "results-trial"
p5.OUT = OUT
DURATION = 180
BASE = dict(nodes=31, net="base")


def cells(block):
    late = [("late-baseline", dict(scenario="late", build="baseline", epoch_length=25, late_p=0.1)),
            ("late-e25", dict(scenario="late", build="trust2", epoch_length=25, late_p=0.1)),
            ("late-e25-holder", dict(scenario="late", build="trust2", epoch_length=25, late_p=0.1, proof_holder_leads=True)),
            ("late-e0", dict(scenario="late", build="trust2", epoch_length=0, late_p=0.1))]
    late = late[block % len(late):] + late[:block % len(late)]
    silent = [("silent-e25", dict(scenario="silent", build="trust2", epoch_length=25, silent=3)),
              ("silent-e25-holder", dict(scenario="silent", build="trust2", epoch_length=25, silent=3, proof_holder_leads=True))]
    return late + (silent if block % 2 else silent[::-1])


def extra_for(config, path):
    def extra(logs):
        stall = stall_stats(logs, int(config["epoch_length"] or 25))
        out = dict(stalls=len(stall["stalls"]), stalls_near=stall["near"], stall_anchors=stall["anchors"])
        if config["build"] == "trust2":
            out.update(p5.local_stats(logs))
            out.update(rmain.facts(logs, path))
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                json.dump({}, fh)
        return out
    return extra


def main(blocks, duration=DURATION, only=None):
    for block in blocks:
        keys = os.path.abspath(f"{OUT}/keys/block-{block}")
        for tag, config in cells(block):
            if only and tag != only:
                continue
            path = f"{OUT}/facts/{tag}-b{block}.json"
            if os.path.exists(path):
                continue
            while os.path.exists(f"{OUT}/pause"):
                time.sleep(30)
            row = p5.run("trial", dict(rep=block, keys_dir=keys, **BASE, **config), duration,
                         keep_logs=f"{tag}-b{block}", extra=extra_for(config, path))
            if row is None:
                print(f"FAILED {tag} block {block}", flush=True)
    print("handovertrial done", flush=True)


def blocks_of(arg):
    if "-" in arg:
        first, last = arg.split("-")
        return range(int(first), int(last) + 1)
    return [int(arg)]


if __name__ == "__main__":      # the pool of the log parser starts a fork server that imports this file again
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":         # two short runs with the switch into results-trial-smoke
        OUT = "results-trial-smoke"
        os.environ["TTRU_OUT"] = OUT
        p5.OUT = OUT
        import shutil
        shutil.rmtree(OUT, ignore_errors=True)
        for tag in ("late-e25-holder", "silent-e25-holder"):
            main(blocks=(1,), duration=40, only=tag)
    else:
        main(blocks_of(sys.argv[1]) if len(sys.argv) > 1 else range(1, 5))
