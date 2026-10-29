"""P5 experiment driver (prototype/DESIGN.md §14.3). Runs run_local.py over a matrix, one run at a time (the runner
holds the lab server's lock and resource limits), and appends one CSV row per run to results-p5/<experiment>.csv;
`report` summarizes every CSV into results-p5/<experiment>.md (median and range over the repetitions).
Run from prototype/benchmark/:  python3 p5.py x2 | x3 | p3 | report
"""
import csv
import os
import re
import subprocess
import sys
from collections import defaultdict
from glob import glob
from statistics import median

from benchmark.logs import LogParser
from lagstat import stats as lag_stats

OUT = "results-p5"
RATE, WARMUP = 10_000, 10
ROLES = (("Voting twice", "equivocator"), ("Lying about NR", "liar"), ("Censoring", "censor"),
         ("Proposing and voting for invalid blocks", "invalid"), ("Regressing the high QC", "regressor"),
         ("Framing:", "framer"))


def roles(logs):
    """Node name -> role, from the experiment switches each node logged."""
    out = {}
    for path in glob(f"{logs}/node-*.log"):
        with open(path) as fh:
            text = fh.read()
        name = re.search(r"Node (\S+) successfully booted", text)
        if name:
            out[name.group(1)] = next((r for marker, r in ROLES if marker in text), "honest")
    return out


def ledger_events(logs, role, n):
    """G1/G2 outcomes on node-0's ledger, split into honest and the others (absent nodes count as faulty)."""
    side = lambda who: "honest" if role.get(who) == "honest" else "faulty"
    with open(f"{logs}/node-0.log") as fh:
        lines = [line.split("] ", 1)[1].strip() for line in fh if "G1: " in line or "G2: " in line]
    count = defaultdict(int)
    r_ppm = {}
    for line in lines:
        m = re.match(r"G2: (\S+) excluded from leading", line)
        if m:
            count[f"g2_excluded_{side(m.group(1))}"] += 1
        m = re.match(r"G2: reputation of (\S+) is (\d+) ppm", line)
        if m:
            r_ppm[m.group(1)] = int(m.group(2))
            count[f"min_r_{side(m.group(1))}"] = min(count.get(f"min_r_{side(m.group(1))}", 10**6), int(m.group(2)))
        m = re.match(r"G2: omission of \S+ at round \d+ by (\S+)", line)
        if m:
            count[f"omissions_{side(m.group(1))}"] += 1
        m = re.match(r"G1: (\S+) level L(\d)", line)
        if m:
            count[f"g1_levels_{side(m.group(1))}"] += 1
        m = re.match(r"G1: (\S+) suspended", line)
        if m:
            count[f"g1_suspensions_{side(m.group(1))}"] += 1
    # Weight cut from honest members by reputation at the end of the run (equal base weights).
    count["honest_cut"] = round(sum(1 - r / 1e6 for who, r in r_ppm.items() if side(who) == "honest") / n, 4)
    return dict(count)


def otx_stats(logs):
    if not os.path.exists(f"{logs}/observer.log"):
        return {}
    out = subprocess.run(["python3", "otxstat.py", logs], capture_output=True, text=True).stdout
    m = re.search(r"victim accounts: (\d+) included, mean (\d+) ms, median (\d+) ms, max (\d+) ms", out)
    o = re.search(r"other accounts:  (\d+) included, mean (\d+) ms, median (\d+) ms, max (\d+) ms", out)
    res = {}
    if m:
        res.update(victim_mean_ms=int(m.group(2)), victim_median_ms=int(m.group(3)), victim_max_ms=int(m.group(4)))
    if o:
        res.update(other_mean_ms=int(o.group(2)), other_median_ms=int(o.group(3)), other_max_ms=int(o.group(4)))
    return res


def run(experiment, config, duration):
    args = ["python3", "run_local.py", "--rate", str(RATE), "--warmup", str(WARMUP), "--duration", str(duration)]
    for key, value in config.items():
        if key in ("scenario", "rep"):
            continue
        flag = "--" + key.replace("_", "-")
        if value is True:
            args.append(flag)
        elif value not in (False, None, 0, "0"):
            args += [flag, str(value)]
    print(" ".join(args[2:]), flush=True)
    done = subprocess.run(args, capture_output=True, text=True, timeout=duration + WARMUP + 600)
    if done.returncode != 0:
        print(done.stdout[-2000:], done.stderr[-2000:], flush=True)
        return None
    faults = int(config.get("faults", 0))
    parser = LogParser.process("logs", faults=faults, warmup=WARMUP)
    tps, _, _ = parser._consensus_throughput()
    e2e_tps, _, _ = parser._end_to_end_throughput()
    lag = lag_stats("logs")
    role = roles("logs")
    row = dict(config)
    row.update(
        consensus_tps=round(tps), consensus_latency_ms=round(parser._consensus_latency() * 1000),
        e2e_tps=round(e2e_tps), e2e_latency_ms=round(parser._end_to_end_latency() * 1000),
        timeouts=parser.timeouts, timeout_rounds=len(lag["timeout_rounds"]), top_round=lag["top_round"],
        rounds_per_s=round(lag["top_round"] / (duration + WARMUP), 1), epochs=lag["epochs"],
        lag_median_ms=round(lag["lag_median_ms"]), lag_max_ms=round(lag["lag_max_ms"]),
    )
    row.update(ledger_events("logs", role, int(config["nodes"])))
    row.update(otx_stats("logs"))
    os.makedirs(OUT, exist_ok=True)
    path = f"{OUT}/{experiment}.csv"
    rows = []
    if os.path.exists(path):
        with open(path) as fh:
            rows = list(csv.DictReader(fh))
    rows.append({k: str(v) for k, v in row.items()})
    keys = []
    for r in rows:
        keys += [k for k in r if k not in keys]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print({k: row[k] for k in ("consensus_tps", "consensus_latency_ms", "e2e_latency_ms", "timeouts")}, flush=True)
    return row


def x2():
    """Normal case: baseline vs Trust 2.0 (epochs of 100 rounds), n = 4, 10, 31, three networks, three runs."""
    for rep in (1, 2, 3):
        for nodes in (4, 10, 31):
            for net in ("none", "base", "wide"):
                for build in ("baseline", "trust2"):
                    run("x2", dict(build=build, nodes=nodes, net=net, epoch_length=100, rep=rep), 30)


def x3():
    """Attacks at n = 31 on the base network, epochs of 50 rounds; the baseline only where it runs the same faults.
    Framing: colluders withhold votes and claim NR = 1, on top of 10% late messages (model P, 5 s), against a
    control with the late messages alone."""
    scenarios = [
        ("silent", dict(faults=3), ("baseline", "trust2")),
        ("late", dict(late_p=0.1), ("baseline", "trust2")),
        ("framers+late", dict(frame=7, late_p=0.1), ("trust2",)),
        ("liars", dict(lie_nr=3), ("trust2",)),
        ("equivocators", dict(equivocate=3), ("trust2",)),
    ]
    for rep in (1, 2):
        for name, faults, builds in scenarios:
            for build in builds:
                config = dict(scenario=name, build=build, nodes=31, net="base", epoch_length=50, rep=rep, **faults)
                run("x3", config, 90)


def p3():
    """Inclusion attestations at the simulator's time scale: base network, about two observed transactions per
    view, guard = one forward plus the largest delay (sim2/txlayer.py default)."""
    for rep in (1, 2):
        for censor in (0, 10):
            config = dict(scenario="censor" if censor else "control", build="trust2", nodes=31, net="base",
                          epoch_length=100, otx_rate=25, attest_guard=136, censor=censor,
                          censor_adjacent=censor > 0, rep=rep)
            run("p3", config, 90)


def report():
    for path in sorted(glob(f"{OUT}/*.csv")):
        with open(path) as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            continue
        metrics = [k for k in rows[0] if k not in ("scenario", "build", "nodes", "net", "epoch_length", "rep",
                                                   "faults", "frame", "lie_nr", "equivocate", "otx_rate",
                                                   "attest_guard", "censor", "censor_adjacent", "late_p")]
        keys = [k for k in rows[0] if k not in metrics and k != "rep"]
        groups = defaultdict(list)
        for r in rows:
            groups[tuple(r.get(k, "") for k in keys)].append(r)
        shown = [m for m in metrics if any(r.get(m) not in (None, "") for r in rows)]
        lines = [f"# {os.path.basename(path)[:-4]}", "", "Median over the runs (range in brackets).", "",
                 "| " + " | ".join(keys + shown) + " |", "|" + "---|" * (len(keys) + len(shown))]
        for key, group in groups.items():
            cells = list(key)
            for m in shown:
                values = [float(r[m]) for r in group if r.get(m) not in (None, "")]
                if not values:
                    cells.append("")
                elif min(values) == max(values):
                    cells.append(f"{median(values):g}")
                else:
                    cells.append(f"{median(values):g} [{min(values):g}–{max(values):g}]")
            lines.append("| " + " | ".join(cells) + " |")
        if os.path.basename(path) == "x2.csv":
            lines += compare_x2(rows)
        with open(path[:-4] + ".md", "w") as fh:
            fh.write("\n".join(lines) + "\n")
        print(f"{path[:-4]}.md: {len(groups)} rows")


def compare_x2(rows):
    """Trust 2.0 against the baseline per committee size and network: medians and the relative change."""
    cell = defaultdict(lambda: defaultdict(list))
    for r in rows:
        for m in ("consensus_tps", "consensus_latency_ms", "e2e_latency_ms", "timeouts"):
            cell[(int(r["nodes"]), r["net"])][(r["build"], m)].append(float(r[m]))
    lines = ["", "## Trust 2.0 against the baseline", "",
             "| n | network | consensus latency (ms): baseline / Trust 2.0 | change | end-to-end latency (ms) | change | "
             "throughput (tx/s) | timeouts |", "|---|---|---|---|---|---|---|---|"]
    for (n, net) in sorted(cell, key=lambda k: (k[0], ["none", "base", "wide"].index(k[1]))):
        c = cell[(n, net)]
        get = lambda b, m: median(c[(b, m)]) if c[(b, m)] else float("nan")
        row = [str(n), net]
        for m in ("consensus_latency_ms", "e2e_latency_ms"):
            b, t = get("baseline", m), get("trust2", m)
            row += [f"{b:g} / {t:g}", f"{(t - b) / b * 100:+.0f}%" if b else ""]
        row.append(f"{get('baseline', 'consensus_tps'):,.0f} / {get('trust2', 'consensus_tps'):,.0f}")
        row.append(f"{get('baseline', 'timeouts'):g} / {get('trust2', 'timeouts'):g}")
        lines.append("| " + " | ".join(row) + " |")
    return lines


if __name__ == "__main__":
    {"x2": x2, "x3": x3, "p3": p3, "report": report}[sys.argv[1]]()
