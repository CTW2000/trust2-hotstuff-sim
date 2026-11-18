"""The numbers of the paper's evaluation section from the unified final reruns (DESIGN.md §15.40), in one report.

Reads the results folder (results-final/ by default, or the folder given as the first argument) and prints, in the
order of the paper: overhead and the throughput-latency curve (r7stat.py), scale, the cost of the synced safety
state, two-table counting, the database workloads and their saturation, late messages (stats_a4.py), silent
leaders, the leader rules (cmpgstat.py), and the forks with their evidence packages. The other batches (the local
experiments, G1, the accusation rates) are summarized by `p5.py report` into <folder>/<batch>.md and by the .stat
files the run wrote; this script lists them at the end. A batch that is missing is reported as such.

Run from prototype/benchmark/:  python3 final_numbers.py [results-final] > results-final/NUMBERS.txt
"""
import csv
import json
import os
import subprocess
import sys
from collections import defaultdict
from statistics import median

OUT = sys.argv[1] if len(sys.argv) > 1 else "results-final"


def rows_of(name):
    path = os.path.join(OUT, name)
    if not os.path.exists(path):
        print(f"(missing: {path})")
        return []
    with open(path) as fh:
        return list(csv.DictReader(fh))


def values(rows, metric):
    return [float(r[metric]) for r in rows if r.get(metric) not in (None, "")]


def show(values_):
    if not values_:
        return "-"
    return f"{median(values_):g} [{min(values_):g}-{max(values_):g}]" if min(values_) != max(values_) else f"{median(values_):g}"


def change(new, old):
    return f"{100 * (median(new) / median(old) - 1):+.1f}%" if new and old and median(old) else "-"


def compare(rows, cell_keys, arm_key, arms, metrics, label=None):
    """Per cell: each metric as reference arm -> other arm, with the relative change of the medians."""
    cells = defaultdict(lambda: defaultdict(list))
    for r in rows:
        cells[tuple(r.get(k, "") for k in cell_keys)][r.get(arm_key, "")].append(r)
    for cell in sorted(cells, key=lambda c: [float(x) if x.replace(".", "", 1).isdigit() else x for x in c]):
        ref, other = cells[cell][arms[0]], cells[cell][arms[1]]
        parts = []
        for metric in metrics:
            a, b = values(ref, metric), values(other, metric)
            parts.append(f"{metric} {show(a)} -> {show(b)} ({change(b, a)})")
        name = ", ".join(f"{k}={v}" for k, v in zip(cell_keys, cell))
        print(f"  {name} (runs {len(ref)}+{len(other)}): " + "; ".join(parts))
    if label:
        print(f"  ({label})")


def script(*args):
    done = subprocess.run([sys.executable, *args], capture_output=True, text=True, env=dict(os.environ, TTRU_OUT=OUT))
    print(done.stdout.rstrip() or "(no output)")
    if done.returncode != 0:
        print(done.stderr[-1500:])


def section(title):
    print(f"\n{'=' * 100}\n{title}\n{'=' * 100}")


def forks(name, across_epochs):
    path = os.path.join(OUT, name)
    if not os.path.exists(path):
        print(f"(missing: {path})")
        return
    runs = [json.loads(line) for line in open(path) if line.strip()]
    groups = defaultdict(list)
    for run in runs:
        groups[run["scenario"], run["population"]].append(run)
    print(f"{name}: {len(runs)} runs")
    for (scenario, population), group in sorted(groups.items()):
        forked = [run for run in group if any(p.get("fork") for p in run["pairs"])]
        found = [dict(p, byzantine=run.get("byzantine")) for run in group for p in run["pairs"] if p.get("fork")]
        line = (f"  {scenario} {population}: runs {len(group)}, forked {len(forked)}; adjudications {len(found)}, "
                f"all Byzantine members named in {sum(p['culprits_byzantine'] == p['byzantine'] for p in found)}, "
                f"honest blamed {sum(p['honest_blamed'] for p in found)}, "
                f"evidence E1 {sum(1 for p in found if p.get('e1'))} / E3 {sum(1 for p in found if p.get('e3'))} / "
                f"E4 {sum(1 for p in found if p.get('e4'))} adjudications, cases {sorted(set(p.get('case') for p in found))}, "
                f"no attribution {sum(1 for p in found if p['culprits'] == 0)}, "
                f"share {show([p['share'] for p in found if p['culprits']])}, licensed {show([p['licensed'] for p in found if p['culprits']])}")
        print(line)
    if not across_epochs:
        return
    pairs = [p for run in runs for p in run["pairs"] if p.get("fork")]
    print(f"  epochs of the fork: {show([p['e_star'] for p in pairs if 'e_star' in p])}; tables agree in "
          f"{sum(1 for p in pairs if p.get('tables_agree'))} of {len(pairs)} adjudications")
    packages = [p["package"] for p in pairs if p.get("package")]
    verified = [p["verify"] for p in pairs if p.get("verify")]
    print(f"  packages: {len(packages)}, bytes {show([p['bytes'] for p in packages])}, links {show([p['links'] for p in packages])}; "
          f"accepted {sum(1 for v in verified if v.get('accepted'))} of {len(verified)}, same as forensics "
          f"{sum(1 for v in verified if v.get('same_as_forensics'))}, honest blamed {sum(v.get('honest_blamed', 0) for v in verified)}, "
          f"culprit weight {show([round(100 * v['weight'] / v['total'], 1) for v in verified if v.get('total')])}%")
    h2 = [p["epochs"][k] for p in pairs for k in ("h2_a_judges_b", "h2_b_judges_a") if p.get("epochs")]
    e2 = [p["epochs"][k] for p in pairs for k in ("e2_a_judges_b", "e2_b_judges_a") if p.get("epochs")]
    print(f"  H2 scan over {len(h2)} directions: blocks {sum(d['blocks'] for d in h2)}, declaring the judge's table "
          f"{sum(d['same_table'] for d in h2)}, of those off the judge's terminal block {sum(d['off_terminal'] for d in h2)}; "
          f"runs with such blocks {sum(1 for run in runs if any(p.get('epochs') and (p['epochs']['h2_a_judges_b']['off_terminal'] or p['epochs']['h2_b_judges_a']['off_terminal']) for p in run['pairs']))}")
    print(f"  E2 scan: blocks {sum(d['blocks'] for d in e2)}, declaring another table {sum(d['other_table'] for d in e2)}, "
          f"honest voters an own-table judgment would name {sum(d['own_voters_honest'] for d in e2)}, "
          f"honest voters named by the declared table {sum(d['named_voters_honest'] for d in e2)}")



def main():
    section("Commit and progress")
    for name in ("progress.log",):
        path = os.path.join(OUT, name)
        print(open(path).read().rstrip() if os.path.exists(path) else f"(missing: {path})")

    section("§6.2 Overhead: normal case and throughput-latency curve (r7stat.py)")
    script("r7stat.py", os.path.join(OUT, "r7_x2.csv"), os.path.join(OUT, "r7_xt.csv"))
    cpu = rows_of("r7_cpu.csv")
    for r in cpu:
        print(f"  cpu: n={r['nodes']} rate={r['rate']} cores={r['cores']} throttled={r['throttled_pct']}%")

    section("§6.2 Scale: baseline -> Trust 2.0")
    scale = rows_of("scale.csv")
    compare(scale, ("nodes",), "build", ("baseline", "trust2"), ("consensus_latency_ms", "e2e_latency_ms", "rounds_per_s", "timeouts"))

    section("§6.3 Synced safety state: with the sync (no_sync empty or False) -> without")
    sync = rows_of("sync.csv")
    for r in sync:
        r["no_sync"] = "True" if r.get("no_sync") in ("True", "1") else "False"
    compare(sync, ("net", "nodes"), "no_sync", ("True", "False"), ("rounds_per_s", "consensus_latency_ms", "e2e_latency_ms", "timeouts"),
            "reference arm: without the sync; the change is the cost of the sync")

    section("§6.3 Two-table counting: H5 on -> off")
    h5 = rows_of("h5live.csv")
    for r in h5:
        r["no_h5"] = "True" if r.get("no_h5") in ("True", "1") else "False"
    compare(h5, ("scenario",), "no_h5", ("False", "True"), ("rounds_per_s", "timeouts", "stalls", "stalls_near", "e2e_latency_ms"))

    section("§6.3 Database workloads: baseline -> Trust 2.0")
    wl = rows_of("wl.csv")
    compare(wl, ("workload", "nodes"), "build", ("baseline", "trust2"),
            ("consensus_latency_ms", "e2e_latency_ms", "e2e_tps", "exec_us_per_tx", "exec_state_mismatches", "timeouts"))
    for key in ("exec_us_per_tx", "exec_state_mismatches", "exec_txs"):
        print(f"  all runs, {key}: {show(values(wl, key))}")
    print(f"  runs: {len(wl)}; columns: {sorted(wl[0].keys()) if wl else '-'}")
    section("§6.3 Saturation under the workloads: baseline -> Trust 2.0")
    compare(rows_of("wlsat.csv"), ("workload", "rate"), "build", ("baseline", "trust2"),
            ("e2e_tps", "e2e_latency_ms", "consensus_latency_ms", "timeouts", "exec_us_per_tx", "exec_state_mismatches"))

    section("§6.2/§6.4 Late messages: effect sizes (stats_a4.py; batches f25_late and lc)")
    script("stats_a4.py")

    section("§6.4 Silent leaders, both builds (fin_silent): baseline -> Trust 2.0")
    compare(rows_of("fin_silent.csv"), ("scenario",), "build", ("baseline", "trust2"), ("timeouts", "rounds_per_s", "e2e_latency_ms"))

    section("§6.4 Leader rules (cmpgstat.py)")
    script("cmpgstat.py", os.path.join(OUT, "cmpg.csv"))

    section("§6.4 Leader rules with votes to all members (cmpgstat.py on cmpb.csv)")
    script("cmpgstat.py", os.path.join(OUT, "cmpb.csv"))

    section("§6.5 Forks within one epoch")
    forks("fork.jsonl", False)
    section("§6.5 Forks across epochs, with evidence packages")
    forks("fork_package.jsonl", True)

    section("Other batches: see the tables of `p5.py report` and the .stat files")
    for name in sorted(os.listdir(OUT)) if os.path.isdir(OUT) else []:
        if name.endswith((".md", ".stat", ".txt")) and name != "NUMBERS.txt":
            print(f"  {os.path.join(OUT, name)}")


if __name__ == "__main__":
    main()
