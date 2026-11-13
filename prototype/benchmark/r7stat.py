"""The numbers of the paper's §6.2 from a normal-case run (x2 / r7_x2) and a throughput-latency run (xt / r7_xt).

- CPU overhead: rounds per second without injected delay (CPU-bound), medians over the runs, Trust 2.0 against the
  baseline, and whether the ranges of the runs overlap.
- With delay (base, wide): end-to-end latency, medians, relative change.
- The curve: among the input rates where no run of either build had a timeout, the change in end-to-end latency;
  per committee size and build, the highest such rate.
Run from prototype/benchmark/:  python3 r7stat.py results-p5/r7_x2.csv results-p5/r7_xt.csv
"""
import csv
import sys
from collections import defaultdict
from statistics import median


def load(path):
    with open(path) as fh:
        return list(csv.DictReader(fh))


def normal_case(rows):
    cell = defaultdict(list)
    for r in rows:
        cell[int(r["nodes"]), r["net"], r["build"]].append(r)
    print("## Normal case (%d runs)" % len(rows))
    for n in (4, 10, 31):
        b = [float(r["rounds_per_s"]) for r in cell[n, "none", "baseline"]]
        t = [float(r["rounds_per_s"]) for r in cell[n, "none", "trust2"]]
        overlap = max(b) >= min(t) and max(t) >= min(b)
        print("n=%-2d no delay: rounds/s %.1f -> %.1f (%+.1f%%), baseline %s, trust2 %s, ranges %s"
              % (n, median(b), median(t), (median(t) / median(b) - 1) * 100, sorted(b), sorted(t),
                 "overlap" if overlap else "do not overlap"))
    changes = []
    for n in (4, 10, 31):
        for net in ("none", "base", "wide"):
            b = median(float(r["e2e_latency_ms"]) for r in cell[n, net, "baseline"])
            t = median(float(r["e2e_latency_ms"]) for r in cell[n, net, "trust2"])
            to = [int(r["timeouts"]) for r in cell[n, net, "baseline"] + cell[n, net, "trust2"]]
            tps = [int(r["e2e_tps"]) for r in cell[n, net, "baseline"] + cell[n, net, "trust2"]]
            print("n=%-2d %-4s e2e %g / %g ms (%+.1f%%), timeouts max %d, e2e tx/s %d-%d"
                  % (n, net, b, t, (t / b - 1) * 100, max(to), min(tps), max(tps)))
            if net != "none":
                changes.append((t / b - 1) * 100)
    print("with delay: e2e change %+.1f%% to %+.1f%%" % (min(changes), max(changes)))


def curve(rows):
    cell = defaultdict(list)
    for r in rows:
        cell[int(r["nodes"]), int(r["rate"]), r["build"]].append(r)
    print("\n## Throughput-latency (%d runs)" % len(rows))
    changes = []
    for n in (4, 10, 31):
        rates = sorted({k[1] for k in cell if k[0] == n})
        best = {}
        for rate in rates:
            line = []
            clean = True
            for build in ("baseline", "trust2"):
                runs = cell[n, rate, build]
                kept = [r for r in runs if int(r["e2e_tps"]) > 0]
                to = [int(r["timeouts"]) for r in runs]
                if max(to) == 0:
                    best[build] = rate
                else:
                    clean = False
                lat = [int(r["e2e_latency_ms"]) for r in kept]
                tps = [int(r["e2e_tps"]) for r in kept]
                line.append("%s %s tx/s %s ms timeouts %s" % (
                    build, "%d" % median(tps) if tps else "-", "%d" % median(lat) if lat else "-", to))
            if clean:
                b = median(int(r["e2e_latency_ms"]) for r in cell[n, rate, "baseline"])
                t = median(int(r["e2e_latency_ms"]) for r in cell[n, rate, "trust2"])
                changes.append((t / b - 1) * 100)
                line.append("change %+.1f%%" % ((t / b - 1) * 100))
            print("n=%-2d %7d: %s" % (n, rate, "; ".join(line)))
        print("n=%-2d highest rate without timeouts: baseline %s, trust2 %s" % (n, best.get("baseline"), best.get("trust2")))
    print("cells without timeouts in both builds: %d, latency change %+.1f%% to %+.1f%%"
          % (len(changes), min(changes), max(changes)))


if __name__ == "__main__":
    normal_case(load(sys.argv[1]))
    curve(load(sys.argv[2]))
