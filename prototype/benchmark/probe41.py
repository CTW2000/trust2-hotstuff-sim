"""DESIGN.md 15.41: does the safety state in a file of its own remove the cost of the synced write under load?
The cells of the throughput-latency curve where the first final run was far off, both builds, and the CPU-bound
case without delays (baseline, Trust 2.0, Trust 2.0 without the sync)."""
import os
os.environ["TTRU_OUT"] = "results-probe41"
import p5


def main():
    for rep in (1, 2):
        for nodes, rate in ((10, 100_000), (10, 150_000), (31, 30_000), (31, 40_000), (4, 200_000)):
            for build in ("baseline", "trust2"):
                p5.run("probe_xt", dict(build=build, nodes=nodes, net="base", rate=rate, epoch_length=25, rep=rep), 30)
    for rep in (1, 2):
        for nodes in (4, 10, 31):
            for build, no_sync in (("baseline", False), ("trust2", False), ("trust2", True)):
                p5.run("probe_none", dict(build=build, nodes=nodes, net="none", epoch_length=25, no_sync=no_sync,
                                          rep=rep), 30)


if __name__ == "__main__":
    main()
