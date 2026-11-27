"""DESIGN.md 15.56: what the epoch length costs and what it buys.

The unified rerun (15.55) found two costs at handovers, both with epochs of 25 rounds, that is, a table change every
three to four seconds: under 10% late messages the end-to-end latency is above the baseline, and with three silent
leaders H5 raises it. A handover happens once per epoch, so longer epochs should dilute both; they also make an
exclusion from leading take effect later (the table of an epoch is computed two epochs ahead). This batch measures
both sides. On the Trust 2.0 code, n = 31, base network, 10,000 tx/s, 180 s after a warm-up of 10 s; the runs of a
block share their node keys (--keys-dir), and the arms rotate from block to block:

late    10% late messages (each on its own): the baseline, and Trust 2.0 with epochs of 25, 50, 100, 400 rounds and
        with a single epoch (0: no handover).
silent  three Byzantine silent leaders: Trust 2.0 with epochs of 25, 50, 100, 400 rounds, with H5 and without it
        (--no-h5). With the keys of the block shared, the two arms of a length have the same leader sequence.

Every run leaves results-epoch/facts/<tag>-b<block>.json (a Trust 2.0 run: the facts of rmain.py; a baseline run: an
empty marker); the logs of block 1 are kept. The statistics are in epochstat.py.

Run from prototype/benchmark/, first one block as a pilot, then the others:
    mkdir -p results-epoch && (setsid nohup python3 epochlen.py 1 > results-epoch/run-1.log 2>&1 < /dev/null &)
    (setsid nohup python3 epochlen.py 2-8 > results-epoch/run-2-8.log 2>&1 < /dev/null &)
A run whose facts file exists is skipped; while results-epoch/pause exists the batch waits before its next run."""
import json
import os
import sys
import time

os.environ["TTRU_OUT"] = "results-epoch"
import p5
import rmain                                    # for its facts(); it sets TTRU_OUT for its own batch on import
from stallstat import stats as stall_stats

os.environ["TTRU_OUT"] = "results-epoch"
OUT = "results-epoch"
p5.OUT = OUT
LENGTHS = (25, 50, 100, 400)
DURATION = 180
BASE = dict(nodes=31, net="base")


def cells(block):
    """(tag, config) of every run of a block; the order of the arms rotates with the block."""
    late = [("late-baseline", dict(scenario="late", build="baseline", epoch_length=25, late_p=0.1))]
    late += [(f"late-e{length}", dict(scenario="late", build="trust2", epoch_length=length, late_p=0.1))
             for length in LENGTHS + (0,)]
    late = late[block % len(late):] + late[:block % len(late)]
    lengths = LENGTHS[block % len(LENGTHS):] + LENGTHS[:block % len(LENGTHS)]
    silent = []
    for length in lengths:
        for off in ((False, True) if block % 2 else (True, False)):
            silent.append((f"silent-e{length}-{'off' if off else 'on'}",
                           dict(scenario="silent", build="trust2", epoch_length=length, silent=3, no_h5=off)))
    return late + silent


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
            if only and not tag.startswith(only):
                continue
            path = f"{OUT}/facts/{tag}-b{block}.json"
            if os.path.exists(path):
                continue
            while os.path.exists(f"{OUT}/pause"):
                time.sleep(30)
            row = p5.run("epoch", dict(rep=block, keys_dir=keys, **BASE, **config), duration,
                         keep_logs=f"{tag}-b{block}" if block == 1 else None, extra=extra_for(config, path))
            if row is None:
                print(f"FAILED {tag} block {block}", flush=True)
    print("epochlen done", flush=True)


def blocks_of(arg):
    if "-" in arg:
        first, last = arg.split("-")
        return range(int(first), int(last) + 1)
    return [int(arg)]


if __name__ == "__main__":      # the pool of the log parser starts a fork server that imports this file again
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":         # short runs into results-epoch-smoke
        OUT = "results-epoch-smoke"
        os.environ["TTRU_OUT"] = OUT
        p5.OUT = OUT
        import shutil
        shutil.rmtree(OUT, ignore_errors=True)
        for tag in ("late-baseline", "late-e400", "late-e0", "silent-e50-off", "silent-e400-on"):
            main(blocks=(1,), duration=25, only=tag)
    else:
        main(blocks_of(sys.argv[1]) if len(sys.argv) > 1 else range(1, 9))
