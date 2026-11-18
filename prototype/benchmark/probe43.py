"""DESIGN.md 15.43: does naming the next table only from the end of an epoch on remove the timeouts at the start of
an epoch? The two cases where the unified final run at 003b34e was far off: the CPU-bound case without delays (the
cells of r7_x2) and 10% late messages (the cells of lc with epochs), both builds, alternating. The logs of the late
runs are kept. Run from prototype/benchmark/:  nohup python3 probe43.py > results-probe43/run.log 2>&1 &"""
import os
os.environ["TTRU_OUT"] = "results-probe43"
import p5


def main():
    for rep in (1, 2, 3):
        for nodes in (4, 10, 31):
            for build in ("baseline", "trust2"):
                p5.run("probe_none", dict(build=build, nodes=nodes, net="none", epoch_length=25, rep=rep), 30)
    for rep in range(1, 11):
        for build in ("baseline", "trust2"):
            p5.run("probe_late", dict(scenario="late", build=build, nodes=31, net="base", epoch_length=25, rep=rep,
                                      late_p=0.1), 90, keep_logs=f"{build}-e25-{rep}")


if __name__ == "__main__":
    main()
