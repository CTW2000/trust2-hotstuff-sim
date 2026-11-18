"""DESIGN.md 15.43: one of the five runs of Trust 2.0 at n = 100 in the unified run at 003b34e had timeouts (two
rounds). The same cell with the fix of the table chain: 2,000 tx/s, base network, epochs of 25 rounds, 40 s; ten
runs of Trust 2.0 and five of the baseline, alternating.
Run from prototype/benchmark/:  nohup python3 probe46.py > results-probe46/run.log 2>&1 &"""
import os
os.environ["TTRU_OUT"] = "results-probe46"
os.environ["TTRU_MAX_NODES"] = "100"
import p5


def main():
    p5.RATE = 2_000
    for rep in range(1, 11):
        builds = ("baseline", "trust2") if rep <= 5 else ("trust2",)
        for build in builds:
            p5.run("probe_scale100", dict(build=build, nodes=100, net="base", epoch_length=25, rep=rep), 40)


if __name__ == "__main__":
    main()
