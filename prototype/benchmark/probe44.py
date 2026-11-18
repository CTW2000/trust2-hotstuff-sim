"""DESIGN.md 15.43: after the fix of the table chain, Trust 2.0 is still about 12% slower than the baseline under 10%
late messages, in a single epoch as well. Is that the synced safety state? The cells of lc with epochs, three arms
alternating: the baseline, Trust 2.0, Trust 2.0 without the sync. The logs are kept for the stall counts.
Run from prototype/benchmark/:  nohup python3 probe44.py > results-probe44/run.log 2>&1 &"""
import os
os.environ["TTRU_OUT"] = "results-probe44"
import p5


def main():
    for rep in range(1, 11):
        for build, no_sync in (("baseline", False), ("trust2", False), ("trust2", True)):
            p5.run("probe_late_sync", dict(scenario="late", build=build, nodes=31, net="base", epoch_length=25, rep=rep,
                                           late_p=0.1, no_sync=no_sync), 90,
                   keep_logs=f"{build}-{'nosync' if no_sync else 'sync'}-{rep}")


if __name__ == "__main__":
    main()
