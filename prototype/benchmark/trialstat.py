"""Statistics of the trial of DESIGN.md 15.58 (handovertrial.py): the holder of the commit proof proposes the first
block of an epoch (--proof-holder-leads).

Per arm, median [min, max] over the blocks (epochstat.py: rounds per second, timed-out rounds per 1000, end-to-end
latency, stalls). Paired by block (rmainstat.py: median of the relative differences, 90% bootstrap interval, exact
signed-rank test, Holm within a table; equivalent only if the interval lies within +-15%): under late messages each
Trust 2.0 arm against the baseline and the arm with the switch against the one without; with silent leaders the arm
with the switch against the one without. The pauses at the handovers come from the logs (latediag.py).

Run from prototype/benchmark/:  python3 trialstat.py [results-trial] > results-trial/trialstat.md
Standard library only."""
import csv
import random
import sys

import epochstat as e


def arm(r):
    if r["build"] == "baseline":
        return "baseline"
    return f"e{r['epoch_length']}" + ("-holder" if r.get("proof_holder_leads") == "True" else "")


def report(out):
    rnd = random.Random(58)
    with open(f"{out}/trial.csv") as fh:
        rows = list(csv.DictReader(fh))
    pick = lambda scenario, name: [r for r in rows if r["scenario"] == scenario and arm(r) == name]
    print(f"# The holder of the commit proof proposes the first block of an epoch (DESIGN.md 15.58): {len(rows)} runs, "
          f"blocks {sorted({int(r['rep']) for r in rows})}\n")
    print("Median [min, max] over the runs of an arm. e25: epochs of 25 rounds; -holder: with the switch; e0: a single epoch.")

    print("\n## 10% late messages\n")
    late = ["baseline", "e25", "e25-holder", "e0"]
    e.table(out, "The arms", [(a, pick("late", a)) for a in late])
    e.compare(out, "Trust 2.0 against the baseline",
              [(f"{a} against the baseline", pick("late", a), pick("late", "baseline")) for a in late[1:]], rnd)
    e.compare(out, "With the switch against without", [("e25-holder against e25", pick("late", "e25-holder"), pick("late", "e25"))], rnd)

    print("\n## Three silent leaders\n")
    e.table(out, "The arms", [(a, pick("silent", a)) for a in ("e25", "e25-holder")], silent=True)
    e.compare(out, "With the switch against without", [("e25-holder against e25", pick("silent", "e25-holder"), pick("silent", "e25"))], rnd)


if __name__ == "__main__":
    report(sys.argv[1] if len(sys.argv) > 1 else "results-trial")
