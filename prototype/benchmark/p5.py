"""P5 experiment driver (prototype/DESIGN.md §14.3). Runs run_local.py over a matrix, one run at a time (the runner
holds the lab server's lock and resource limits), and appends one CSV row per run to results-p5/<experiment>.csv;
`report` summarizes every CSV into results-p5/<experiment>.md (median and range over the repetitions).
Run from prototype/benchmark/:  python3 p5.py x2 | x3 | p3 | x4 | xr | xt | report
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
from localstat import stats as local_stats
from stallstat import stats as stall_stats

OUT = "results-p5"
RATE, WARMUP = 10_000, 10
ROLES = (("Voting twice", "equivocator"), ("Lying about NR", "liar"), ("Censoring", "censor"),
         ("Proposing and voting for invalid blocks", "invalid"), ("Regressing the high QC", "regressor"),
         ("Framing:", "framer"), ("Silent leader:", "silent"), ("Filling suffix blocks", "filler"),
         ("Withholding the commit proof", "withholder"))


def roles(logs):
    """Node name -> role, from the experiment switches each node logged."""
    out = {}
    for path in glob(f"{logs}/node-*.log"):
        with open(path) as fh:
            text = fh.read()
        name = re.search(r"Node (\S+) successfully booted", text)
        if name:
            out[name.group(1)] = next((r for marker, r in ROLES if marker in text), "honest")
    if os.path.exists(f"{logs}/faulted.txt"):                # crash, restart, outage (DESIGN.md §15.22)
        with open(f"{logs}/faulted.txt") as fh:
            for who in fh.read().split("\n")[1:]:
                who = who.strip()
                if not who:
                    continue
                # The logs print keys cut to 16 characters, faulted.txt has them in full: mark the booted name, or the
                # full one for a node that never booted. (Before 2026-11-12 both were kept, so a faulted node counted
                # twice, once honest and once faulty, and faulty_share_end of such runs is not meaningful.)
                short = next((name for name in out if who.startswith(name)), who)
                out[short] = "faulted"
    return out


def ledger_events(logs, role, n, budget=0.1):
    """G1/G2 outcomes on node-0's ledger, split into honest and the others (absent nodes count as faulty)."""
    side = lambda who: "honest" if role.get(who) == "honest" else "faulty"
    with open(f"{logs}/node-0.log") as fh:
        text = fh.read()
    lines = [line.split("] ", 1)[1].strip() for line in text.splitlines() if "G1: " in line or "G2: " in line]
    base = {who: int(ppm) for who, ppm in re.findall(r"T_tru base weight of (\S+) is (\d+) ppm", text)}
    count = defaultdict(int)
    count_aptos_dict = {}
    r_ppm = {}
    # LeaderRule::Aptos (DESIGN.md §15.12): member-epochs at the failed and the inactive weight.
    for who, kind in re.findall(r"Aptos: (\S+) weight (failed|inactive) at epoch \d+", text):
        count_aptos = f"aptos_{kind}_{side(who)}"
        count_aptos_dict[count_aptos] = count_aptos_dict.get(count_aptos, 0) + 1
    for line in lines:
        m = re.match(r"G2: accusation of round \d+ led by (\S+)", line)
        if m:
            count[f"accusations_{side(m.group(1))}"] += 1
        m = re.match(r"G2: failed round \d+ led by (\S+)", line)
        if m:
            count[f"failed_facts_{side(m.group(1))}"] += 1
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
    # Weight cut from honest members by reputation at the end of the run, by base weight (equal if not logged).
    weight = lambda who: base.get(who, 1e6 / n) / 1e6
    count["honest_cut"] = round(sum(weight(who) * (1 - r / 1e6) for who, r in r_ppm.items() if side(who) == "honest"), 4)
    count.update(count_aptos_dict)
    # Voting share of the faulty members at the end: base * r, the total cut scaled down to the budget of 0.1.
    members = set(base) | set(r_ppm) | set(role)
    cut = {who: weight(who) * (1 - r_ppm.get(who, 1e6) / 1e6) for who in members}
    scale = min(1.0, budget / sum(cut.values())) if sum(cut.values()) > 0 else 1.0
    left = {who: weight(who) - cut[who] * scale for who in members}
    if any(side(who) == "faulty" for who in members) and sum(left.values()) > 0:
        count["faulty_share_end"] = round(sum(v for who, v in left.items() if side(who) == "faulty") / sum(left.values()), 4)
    if base and len(set(base.values())) > 1:
        count["base_max_ppm"] = max(base.values())
        count["base_min_ppm"] = min(base.values())
        count["faulty_base_ppm"] = sum(ppm for who, ppm in base.items() if side(who) == "faulty")
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


def run(experiment, config, duration, keep_logs=None, extra=None):
    """One run_local.py run; keep_logs names a tarball of the run's logs under results-p5/<experiment>_logs/."""
    args = ["python3", "run_local.py", "--rate", str(RATE), "--warmup", str(WARMUP), "--duration", str(duration)]
    for key, value in config.items():
        if key in ("scenario", "rep"):
            continue
        flag = "--" + key.replace("_", "-")
        if value is True:
            args.append(flag)
        elif value not in (False, None, 0, "0") or key == "epoch_length":   # epoch length 0: a single epoch
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
        timeouts=parser.timeouts, client_misses=parser.misses, timeout_rounds=len(lag["timeout_rounds"]),
        top_round=lag["top_round"],
        rounds_per_s=round(lag["top_round"] / (duration + WARMUP), 1), epochs=lag["epochs"],
        lag_median_ms=round(lag["lag_median_ms"]), lag_max_ms=round(lag["lag_max_ms"]),
    )
    budget = 0.0 if config.get("g2_no_reputation") else 0.1    # the ablation of DESIGN.md §15.18 cuts nothing
    row.update(ledger_events("logs", role, int(config["nodes"]), budget))
    if keep_logs:
        stall = stall_stats("logs", int(config.get("epoch_length") or 25))
        row.update(stalls=len(stall["stalls"]), stalls_near=stall["near"], stall_anchors=stall["anchors"])
        os.makedirs(f"{OUT}/{experiment}_logs", exist_ok=True)
        subprocess.run(["tar", "czf", f"{OUT}/{experiment}_logs/{keep_logs}.tgz", "logs"], check=True)
    row.update(otx_stats("logs"))
    if extra:
        row.update(extra("logs"))
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
                          epoch_length=100, otx_rate=25, attest_guard=136, censor=censor, rep=rep)
            run("p3", config, 90)


def x4():
    """Epoch changes: Trust 2.0 with epochs of 20 rounds against the baseline, base network, n = 10 and 31."""
    for rep in (1, 2):
        for nodes in (10, 31):
            for build in ("baseline", "trust2"):
                run("x4", dict(build=build, nodes=nodes, net="base", epoch_length=20, rep=rep), 60)


def xa():
    """E-A (review 12.1 D8): the baseline now also commits as soon as it holds a commit proof (try_commit_via_qc),
    as the prototype does, so the two differ only in Trust 2.0. Rerun, with the current code on both sides, the
    comparisons that commit-after-timeout and the extra store reads can affect: the silent-leader and late-message
    scenarios of X3, and the local (CPU-bound) cells of X2."""
    for rep in (1, 2):
        for name, faults in (("silent", dict(faults=3)), ("late", dict(late_p=0.1))):
            for build in ("baseline", "trust2"):
                config = dict(scenario=name, build=build, nodes=31, net="base", epoch_length=50, rep=rep, **faults)
                run("xa_x3", config, 90)
    for rep in (1, 2, 3):
        for nodes in (4, 10, 31):
            for build in ("baseline", "trust2"):
                run("xa_x2", dict(build=build, nodes=nodes, net="none", epoch_length=100, rep=rep), 30)


def xb():
    """E-B (review 5.5): framing long enough to convict -- some 40 rounds or more per leader, where conviction needs
    about six consecutive accusations of a leader's rounds (ln 10^4 / ln 5) -- with each accusation fact on the ledger
    counted against the leader of its round. n = 10 with 2 framers (beta = 0.2, close to the 7 of 31 of X3) on top
    of 10% late messages, against a control with the late messages alone."""
    for rep in (1, 2):
        for name, faults in (("framers+late", dict(frame=2, late_p=0.1)), ("late", dict(late_p=0.1))):
            run("xb", dict(scenario=name, build="trust2", nodes=10, net="base", epoch_length=50, rep=rep, **faults), 240)


def xc():
    """E-C (review 12.6): the T_tru weighted path end to end -- unequal base weights (log-normal, sigma 1, fixed
    seed), 10 of 31 members uncertified (class cap 25%), entity cap 5% (<= L_max 10%) -- in the normal case, with 3
    silent leaders and with 3 equivocators; base network."""
    weighted = dict(stakes="lognormal:1", uncertified=10, entity_cap_ppm=50_000, class_cap_ppm=250_000)
    for rep in (1, 2):
        for name, faults in (("normal", {}), ("silent", dict(faults=3)), ("equivocators", dict(equivocate=3))):
            config = dict(scenario=name, build="trust2", nodes=31, net="base", epoch_length=50, rep=rep,
                          **weighted, **faults)
            run("xc", config, 60)


def xe():
    """Entity binding (方案说明 §0): one owner runs 5 of 31 nodes, entity cap 5%. Bound into one entity they share the
    cap and the punishments; counted as separate entities they hold 5/31 and only the signer is punished. Normal
    case and one double-voting node (of the 5), base network."""
    for rep in (1, 2):
        for name, bound in (("separate", {}), ("bound", dict(entity_size=5))):
            for faults in ({}, dict(equivocate=1)):
                scenario = name + ("+equivocator" if faults else "")
                run("xe", dict(scenario=scenario, build="trust2", nodes=31, net="base", epoch_length=50, rep=rep,
                               **bound, **faults), 60)


def xr():
    """Silent leaders and late messages again, five runs per build: keys are new in each run, so the draw gives another
    leader schedule each time, and the two runs of X3 understate the spread."""
    for rep in range(1, 6):
        for name, faults in (("silent", dict(faults=3)), ("late", dict(late_p=0.1))):
            for build in ("baseline", "trust2"):
                run("xr", dict(scenario=name, build=build, nodes=31, net="base", epoch_length=50, rep=rep, **faults), 90)


# Input rates of the throughput-latency curve, from a probe: up to and past the knee.
XT_RATES = {4: (50_000, 100_000, 200_000, 300_000, 350_000, 400_000),
            10: (25_000, 50_000, 100_000, 150_000, 175_000, 200_000),
            31: (20_000, 30_000, 40_000, 50_000, 60_000, 70_000)}


def xt(experiment="xt", epoch_length=100):
    """Throughput against latency: the input rate up to and past the knee, base network, both builds, three runs. The
    rates come from a probe; nodes and clients share one server, so the knee is where it runs out of CPU."""
    for rep in (1, 2, 3):
        for nodes, sweep in XT_RATES.items():
            for rate in sweep:
                for build in ("baseline", "trust2"):
                    run(experiment, dict(build=build, nodes=nodes, net="base", rate=rate, epoch_length=epoch_length,
                                         rep=rep), 30)


def r7x2():
    """R7 (DESIGN.md §15.30): the normal case of x2 under the final rules -- the next table known an epoch ahead,
    epochs of 25 rounds, H2/H4/E2 -- so that the overhead in the paper is measured on the scheme it describes."""
    for rep in (1, 2, 3):
        for nodes in (4, 10, 31):
            for net in ("none", "base", "wide"):
                for build in ("baseline", "trust2"):
                    run("r7_x2", dict(build=build, nodes=nodes, net=net, epoch_length=25, rep=rep), 30)


def r7spot():
    """R7 (DESIGN.md §15.30): after the changes of §15.31-§15.32 (paths that fault-free runs never take), the normal
    case of r7_x2 at n = 31 once more on the final binary, to confirm it."""
    for rep in (1, 2, 3):
        for net in ("none", "base"):
            run("r7_spot", dict(build="trust2", nodes=31, net=net, epoch_length=25, rep=rep), 30)


def r7len():
    """R7 diagnosis (DESIGN.md §15.30): the CPU-bound rounds per second of Trust 2.0 at n = 31 against the epoch
    length -- 25 (r7_x2), 100 and a single epoch -- on the final binary."""
    for rep in (1, 2, 3):
        for length in (100, 0):
            run("r7_len", dict(build="trust2", nodes=31, net="none", epoch_length=length, rep=rep), 30)


def r7xt():
    """R7 (DESIGN.md §15.30): the throughput-latency curve of xt under the final rules, the same rates."""
    xt("r7_xt", 25)


def f25():
    """The adopted scheme (DESIGN.md §15.11): the next table known an epoch ahead and epochs of 25 rounds. Rerun what
    the handover can affect -- late messages and silent leaders (the baseline's silent runs of xr stand: it has no
    epochs), the weighted path, entity binding, long framing and long censorship -- and spot-check the normal case."""
    late = dict(late_p=0.1)
    for rep in range(1, 11):
        for build in ("baseline", "trust2"):
            run("f25_late", dict(scenario="late", build=build, nodes=31, net="base", epoch_length=25, rep=rep, **late), 90)
    for rep in range(1, 6):
        run("f25_silent", dict(scenario="silent", build="trust2", nodes=31, net="base", epoch_length=25, rep=rep,
                               faults=3), 90)
    for rep in (1, 2, 3):
        for build in ("baseline", "trust2"):
            run("f25_x2", dict(build=build, nodes=31, net="base", epoch_length=25, rep=rep), 30)
    weighted = dict(stakes="lognormal:1", uncertified=10, entity_cap_ppm=50_000, class_cap_ppm=250_000)
    for rep in (1, 2):
        for name, faults in (("normal", {}), ("silent", dict(faults=3)), ("equivocators", dict(equivocate=3))):
            run("f25_xc", dict(scenario=name, build="trust2", nodes=31, net="base", epoch_length=25, rep=rep,
                               **weighted, **faults), 60)
        for name, bound in (("separate", {}), ("bound", dict(entity_size=5))):
            for faults in ({}, dict(equivocate=1)):
                scenario = name + ("+equivocator" if faults else "")
                run("f25_xe", dict(scenario=scenario, build="trust2", nodes=31, net="base", epoch_length=25, rep=rep,
                                   **bound, **faults), 60)
        for name, faults in (("framers+late", dict(frame=2, late_p=0.1)), ("late", dict(late_p=0.1))):
            run("f25_xb", dict(scenario=name, build="trust2", nodes=10, net="base", epoch_length=25, rep=rep,
                               **faults), 240)
        run("f25_censor", dict(scenario="censor", build="trust2", nodes=31, net="base", epoch_length=25, otx_rate=25,
                               attest_guard=136, censor=10, rep=rep), 300)


def cmp():
    """Leader rules on the same Trust 2.0 code (DESIGN.md §15.12): none (leaders by base weight), aptos (Aptos
    LeaderReputation, aptos-core defaults), failed (Trust 2.0 with failed-proposer facts) and trust2. n = 31, base
    network, epochs of 25 rounds, the four rules interleaved within each repetition.
    - silent: 3 Byzantine silent leaders (they vote and time out, but never propose);
    - late: 10% late messages, no faults;
    - framers+late: 6 colluders withhold their votes and claim NR = 1, on top of 10% late messages."""
    scenarios = (("silent", dict(silent=3), 90), ("late", dict(late_p=0.1), 90),
                 ("framers+late", dict(frame=6, late_p=0.1), 180))
    for rep in range(1, 6):
        for name, faults, duration in scenarios:
            for rule in ("none", "aptos", "failed", "trust2"):
                run("cmp", dict(scenario=name, build="trust2", nodes=31, net="base", epoch_length=25, rep=rep,
                                leader_rule=rule, **faults), duration)


def cmpg():
    """The comparison of leader rules (cmp) again after the G2 threshold changed from ln 10^4 to ln 10^2 (DESIGN.md
    §15.13): the four rules at the new threshold and, in the silent scenario, Trust 2.0 at the old one as well
    (g2_threshold = 9_210_340), interleaved within each repetition. Same scenarios and durations as cmp."""
    old = 9_210_340
    scenarios = (("silent", dict(silent=3), 90), ("late", dict(late_p=0.1), 90),
                 ("framers+late", dict(frame=6, late_p=0.1), 180))
    for rep in range(1, 6):
        for name, faults, duration in scenarios:
            runs = [(rule, 0) for rule in ("none", "aptos", "failed", "trust2")]
            if name == "silent":
                runs.append(("trust2", old))
            for rule, threshold in runs:
                run("cmpg", dict(scenario=name, build="trust2", nodes=31, net="base", epoch_length=25, rep=rep,
                                 leader_rule=rule, g2_threshold=threshold, **faults), duration)



def a6():
    """Trade-off of detection speed against honest demotion for the leader rules (DESIGN.md §15.20; mock review A6):
    the Aptos-style rule at failure thresholds 10% (aptos-core), 30% and 50%, and Trust 2.0 at gamma 10^4, 10^2 (the
    protocol) and 20, alternating, 3 times each, n = 31, base, 25-round epochs, in three scenarios: 3 Byzantine silent
    leaders (90 s), 20% late messages (90 s), and 6 framers with 10% late (180 s)."""
    rules = [("aptos", dict(aptos_failure_percent=p)) for p in (10, 30, 50)]
    rules += [("trust2", dict(g2_threshold=t)) for t in (9_210_340, 0, 2_995_732)]
    scenarios = [("silent", dict(silent=3), 90), ("late20", dict(late_p=0.2), 90),
                 ("framers+late", dict(frame=6, late_p=0.1), 180)]
    for rep in range(1, 4):
        for name, extra, duration in scenarios:
            for rule, knob in rules:
                run("a6", dict(scenario=name, build="trust2", nodes=31, net="base", epoch_length=25, rep=rep,
                               leader_rule=rule, **knob, **extra), duration)


def a7():
    """Benign faults of honest nodes (DESIGN.md §15.22; mock review A7): Trust 2.0 against the Aptos-style rule, n = 31,
    base, 25-round epochs, 150 s, 3 times each, alternating: 3 nodes crash at 40 s for good; 3 nodes restart after
    20 s down (maintenance); a region of 6 nodes is cut off for 10 s at 40 s. No Byzantine nodes: every exclusion and
    weight cut of the other honest nodes is a false demotion; those of the faulted nodes are what the rule does to a
    member that was really unavailable. Logs in results-p5/a7_logs/ (a7stat.py)."""
    scenarios = [("crash", dict(fault="crash", fault_nodes=3, fault_at=40, fault_for=0)),
                 ("restart", dict(fault="restart", fault_nodes=3, fault_at=40, fault_for=20)),
                 ("outage", dict(fault="outage", fault_nodes=6, fault_at=40, fault_for=10))]
    for rep in range(1, 4):
        for name, fault in scenarios:
            for rule in ("trust2", "aptos"):
                run("a7", dict(scenario=name, build="trust2", nodes=31, net="base", epoch_length=25, rep=rep,
                               leader_rule=rule, **fault), 150, keep_logs=f"{name}-{rule}-{rep}")


def a5():
    """Overhead on the final code (DESIGN.md §15.23; mock review A5): the normal case (the cells of x2, 3 runs), the
    input rate up to and past the knee (the rates of xt, 2 runs) for both builds, and inclusion attestations by
    observed-transaction rate (0 to 100 per second, n = 31, base, 2 runs, 60 s; Trust 2.0 only, the baseline has none)."""
    for rep in (1, 2, 3):
        for nodes in (4, 10, 31):
            for net in ("none", "base", "wide"):
                for build in ("baseline", "trust2"):
                    run("a5_x2", dict(build=build, nodes=nodes, net=net, epoch_length=100, rep=rep), 30)
    rates = {4: (50_000, 100_000, 200_000, 300_000, 350_000, 400_000),
             10: (25_000, 50_000, 100_000, 150_000, 175_000, 200_000),
             31: (20_000, 30_000, 40_000, 50_000, 60_000, 70_000)}
    for rep in (1, 2):
        for nodes, sweep in rates.items():
            for rate in sweep:
                for build in ("baseline", "trust2"):
                    run("a5_xt", dict(build=build, nodes=nodes, net="base", rate=rate, epoch_length=100, rep=rep), 30)
    for rep in (1, 2):
        for otx in (0, 10, 25, 50, 100):
            run("a5_otx", dict(scenario="control", build="trust2", nodes=31, net="base", epoch_length=100,
                               otx_rate=otx, attest_guard=136, rep=rep), 60)


def a3():
    """Ablation (DESIGN.md §15.18; mock review A3): what reputation in the voting power adds to excluding from leading.
    The protocol against g2_no_reputation (convictions only exclude, B_rep = 0), alternating, n = 31, base, 25-round
    epochs: 3 Byzantine silent leaders (5 x 90 s), and 6 framers with 10% late (3 x 180 s)."""
    for rep in range(1, 6):
        for ablate in (False, True):
            run("a3", dict(scenario="silent", build="trust2", nodes=31, net="base", epoch_length=25, rep=rep, silent=3,
                           g2_no_reputation=ablate), 90)
    for rep in range(1, 4):
        for ablate in (False, True):
            run("a3", dict(scenario="framers+late", build="trust2", nodes=31, net="base", epoch_length=25, rep=rep,
                           frame=6, late_p=0.1, g2_no_reputation=ablate), 180)


def a1b():
    """Whether heavy late messages stop 2-chain HotStuff itself (DESIGN.md §15.16): the a1 runs at 30% late committed
    nothing in 300 s. The baseline against Trust 2.0 at 25% and 30% late, alternating, 2 runs each, n = 31, base,
    25-round epochs, 120 s."""
    for rep in (1, 2):
        for late in (0.25, 0.3):
            for build in ("baseline", "trust2"):
                run("a1b", dict(scenario=f"late{int(late * 100)}", build=build, nodes=31, net="base", epoch_length=25,
                                rep=rep, late_p=late), 120)


def a1():
    """How often honest leaders are accused (AT) under late messages, with and without framing colluders, on the
    prototype (DESIGN.md §15.16; the mock review's A1: the simulator gave 0 at 10% late where the prototype shows
    0.15%-1.8%). n = 31, base, 25-round epochs. A first pass (180 s: late 10% with 0 and 7 framers, late 20% without)
    showed that 7 framers (share 0.226) at 20% late commit nothing, so accusations never reach the ledger; this pass
    keeps to arms that commit, 300 s each (late 10% without framers 180 s). Logs in results-p5/a1_logs/ (a1stat.py)."""
    arms = [(0.1, 7, 300, range(2, 7)), (0.2, 0, 300, range(2, 5)), (0.3, 0, 300, range(1, 4)),
            (0.2, 4, 300, range(1, 4)), (0.1, 0, 180, range(2, 4))]
    for late, frame, duration, reps in arms:
        for rep in reps:
            name = f"late{int(late * 100)}-frame{frame}"
            run("a1", dict(scenario=name, build="trust2", nodes=31, net="base", epoch_length=25, rep=rep, late_p=late,
                           frame=frame), duration, keep_logs=f"{name}-{rep}")


def lc():
    """Where the cost under 10% late messages comes from (DESIGN.md §15.14): the baseline, Trust 2.0 with 25-round
    epochs and Trust 2.0 in a single epoch (no handover), alternating, 10 times each, n = 31, base, 90 s. Each run's
    stalls (rounds where >= f+1 nodes timed out) are counted by their distance to a terminal block (multiples of 25
    without epochs), and its logs are kept in results-p5/lc_logs/ (not in the repository)."""
    for rep in range(1, 11):
        for build, length in (("baseline", 25), ("trust2", 25), ("trust2", 0)):
            run("lc", dict(scenario="late", build=build, nodes=31, net="base", epoch_length=length, rep=rep, late_p=0.1),
                90, keep_logs=f"{build}-e{length}-{rep}")


def g100():
    """Everything the G2 threshold can change, at the new one (ln 10^2; DESIGN.md §15.13): the comparison of leader
    rules (cmpg), then the parts of f25 where G2 convicts -- silent leaders (crashed, and on the weighted path), long
    framing with its control, long censorship. Runs without a conviction are the same at either threshold."""
    cmpg()
    for rep in range(1, 6):
        run("g100_silent", dict(scenario="silent", build="trust2", nodes=31, net="base", epoch_length=25, rep=rep,
                                faults=3), 90)
    weighted = dict(stakes="lognormal:1", uncertified=10, entity_cap_ppm=50_000, class_cap_ppm=250_000)
    for rep in (1, 2):
        run("g100_xc", dict(scenario="silent", build="trust2", nodes=31, net="base", epoch_length=25, rep=rep,
                            **weighted, faults=3), 60)
        for name, faults in (("framers+late", dict(frame=2, late_p=0.1)), ("late", dict(late_p=0.1))):
            run("g100_xb", dict(scenario=name, build="trust2", nodes=10, net="base", epoch_length=25, rep=rep,
                                **faults), 240)
        run("g100_censor", dict(scenario="censor", build="trust2", nodes=31, net="base", epoch_length=25, otx_rate=25,
                                attest_guard=136, censor=10, rep=rep), 300)


def h24():
    """H2, H4 and the E2 table rule (DESIGN.md §15.24): the normal case, 10% late messages and silent leaders with the
    new handover code, the baseline alternating, as in f25; and the weighted path with equivocators."""
    for rep in (1, 2, 3):
        for build in ("baseline", "trust2"):
            run("h24_x2", dict(build=build, nodes=31, net="base", epoch_length=25, rep=rep), 30)
    for rep in range(1, 6):
        for build in ("baseline", "trust2"):
            run("h24_late", dict(scenario="late", build=build, nodes=31, net="base", epoch_length=25, rep=rep,
                                 late_p=0.1), 90)
    for rep in (1, 2):
        run("h24_silent", dict(scenario="silent", build="trust2", nodes=31, net="base", epoch_length=25, rep=rep,
                               faults=3), 90)
        weighted = dict(stakes="lognormal:1", uncertified=10, entity_cap_ppm=50_000, class_cap_ppm=250_000)
        run("h24_xc", dict(scenario="equivocators", build="trust2", nodes=31, net="base", epoch_length=25, rep=rep,
                           equivocate=3, **weighted), 60)


def r3():
    """Mock review R3 (DESIGN.md §15.25): CUSUM over long runs under correlated lateness -- sustained 20% late
    messages, bursts of congestion, and a recurring region outage of five honest nodes."""
    base = dict(build="trust2", nodes=31, net="base", epoch_length=25)
    cases = (("late20", dict(late_p=0.2)),
             ("bursts", dict(late_p=0.05, burst_period=30, burst_len=5, burst_late_p=0.4)),
             ("region", dict(fault="outage", fault_nodes=5, fault_at=20, fault_for=3, fault_every=30)),
             # Long enough for each cut-off node to be scheduled about three times: it is convicted, as an
             # unreachable leader should be; the cost must stay within the exclusion cap and the budget.
             ("region20", dict(fault="outage", fault_nodes=5, fault_at=20, fault_for=20, fault_every=120)))
    for rep in (1, 2):
        for name, case in cases:
            run("r3_long", dict(scenario=name, rep=rep, **base, **case), 600, extra=local_stats)


def r4():
    """Mock review R4 (DESIGN.md §15.25): inclusion attestations under load -- protected transactions at rising rates,
    in bursts, and sent to a single node each."""
    base = dict(build="trust2", nodes=31, net="base", epoch_length=25, attest_guard=136)
    cases = (("rate500", dict(otx_rate=500)), ("rate1000", dict(otx_rate=1000)), ("rate2000", dict(otx_rate=2000)),
             ("rate5000", dict(otx_rate=5000)),
             ("bursts", dict(otx_rate=200, otx_burst_size=5000, otx_burst_every=20)),
             ("fanout1", dict(otx_rate=2000, otx_fanout=1)))
    for name, case in cases:
        run("r4_load", dict(scenario=name, rep=1, **base, **case), 120, extra=local_stats)


def r4k():
    """Mock review R4, the knee (DESIGN.md §15.25): 1000 protected transactions per second, and 2000 again (run while
    run_r4k.sh samples the CPU) -- every node forwards each one to all the others on first receipt."""
    base = dict(build="trust2", nodes=31, net="base", epoch_length=25, attest_guard=136)
    run("r4_load", dict(scenario="rate1000", rep=1, **base, otx_rate=1000), 120, extra=local_stats)
    run("r4_load", dict(scenario="rate2000", rep=2, **base, otx_rate=2000), 120, extra=local_stats)


def r34x():
    """Mock review R3/R4 follow-up (DESIGN.md §15.25): one more 20 s region outage run with the per-node statistics
    (convictions, exclusion lengths, recovery), and protected transactions sent to a single node each at rates the
    prototype sustains (with the usual f+1 at 200/s for comparison)."""
    base = dict(build="trust2", nodes=31, net="base", epoch_length=25)
    for name, case in (("rate200", dict(otx_rate=200)), ("fanout1_200", dict(otx_rate=200, otx_fanout=1)),
                       ("fanout1_500", dict(otx_rate=500, otx_fanout=1))):
        run("r4_load", dict(scenario=name, rep=1, **base, attest_guard=136, **case), 120, extra=local_stats)
    run("r3_long", dict(scenario="region20", rep=3, **base, fault="outage", fault_nodes=5, fault_at=20, fault_for=20,
                        fault_every=120), 600, extra=local_stats)


def thr():
    """Mock review S1 (DESIGN.md §15.27): the G2 threshold was chosen in the simulator (§15.13); check the choice on
    the prototype in new runs, at ln 4, ln 10^2 and ln 10^4 -- three silent Byzantine leaders (how fast they are
    excluded) and six framing colluders with 20% late messages (whether honest leaders are convicted)."""
    base = dict(build="trust2", nodes=31, net="base", epoch_length=25)
    gammas = (("ln4", 1_386_294), ("ln1e2", 4_605_170), ("ln1e4", 9_210_340))
    for rep in (1, 2, 3):
        for name, g in gammas:
            run("thr_silent", dict(scenario=name, rep=rep, **base, silent=3, g2_threshold=g), 90, extra=local_stats)
    for rep in (1, 2):
        for name, g in gammas:
            run("thr_frame", dict(scenario=name, rep=rep, **base, frame=6, late_p=0.2, g2_threshold=g), 300,
                extra=local_stats)


def thr2():
    """The framing half of thr() again with 10% late messages, as in the comparison of leader rules (§15.12): with
    20% the six colluders' withheld votes leave too few on time for a QC, nothing is committed and no fact reaches
    the ledger (thr_frame_late20.csv)."""
    base = dict(build="trust2", nodes=31, net="base", epoch_length=25)
    gammas = (("ln4", 1_386_294), ("ln1e2", 4_605_170), ("ln1e4", 9_210_340))
    for rep in (1, 2):
        for name, g in gammas:
            run("thr_frame", dict(scenario=name, rep=rep, **base, frame=6, late_p=0.1, g2_threshold=g), 300,
                extra=local_stats)


def tgt():
    """Mock review S1 (DESIGN.md §15.27): targeted framing before GST. Six colluders vote as usual except in the rounds
    the targets lead, where they withhold their votes and report NR = 1; the network holds back the consensus messages
    of T chosen honest nodes from 16 other honest nodes (all of them when fewer remain), so every round a target leads
    ends in an AT accusation. T = 3, 5, 10 -- 10 is the most for which the accusation forms, as the targets' own NR = 0
    must stay under 1/3. Prop. 1 predicts the colluders' vote share beta_0 / (1 - D)."""
    base = dict(build="trust2", nodes=31, net="base", epoch_length=25, frame=6)
    for t in (3, 5, 10):
        run("tgt_frame", dict(scenario=f"t{t}", rep=1, **base, fault="target", fault_nodes=t, target_victims=16),
            600, extra=local_stats)


def r2():
    """Mock review R2 (DESIGN.md §15.25): the handover under disturbance -- a region outage that keeps hitting epoch
    changes, Byzantine leaders that withhold the commit proof or fill suffix blocks, and both with late messages."""
    # Protected transactions at a low rate, so that the suffix blocks of the fillers carry some (they must stay
    # pending and reach the ledger in a later block).
    base = dict(build="trust2", nodes=31, net="base", epoch_length=25, otx_rate=200)
    outage = dict(fault="outage", fault_nodes=5, fault_at=15, fault_for=2, fault_every=7)
    byz = dict(withhold_proof=6, fill_suffix=3)              # 9 of 31 Byzantine (29%)
    cases = (("outage", outage), ("byzantine", byz), ("both", dict(late_p=0.1, **outage, **byz)))
    for rep in (1, 2):
        for name, case in cases:
            run("r2_handover", dict(scenario=name, rep=rep, **base, **case), 120, extra=local_stats)


def report():
    for path in sorted(glob(f"{OUT}/*.csv")):
        with open(path) as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            continue
        metrics = [k for k in rows[0] if k not in ("scenario", "build", "nodes", "net", "rate", "epoch_length", "rep",
                                                   "faults", "frame", "lie_nr", "equivocate", "otx_rate",
                                                   "attest_guard", "censor", "censor_adjacent", "late_p",
                                                   "stakes", "uncertified", "entity_cap_ppm", "class_cap_ppm",
                                                   "silent", "leader_rule", "g2_threshold",
                                                   "aptos_failure_percent", "g2_no_reputation", "fault",
                                                   "fault_nodes", "fault_at", "fault_for")]
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
        if os.path.basename(path) in ("x2.csv", "r7_x2.csv"):
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
    {"x2": x2, "x3": x3, "p3": p3, "x4": x4, "xa": xa, "xb": xb, "xc": xc, "xe": xe, "xr": xr, "xt": xt, "r7x2": r7x2, "r7spot": r7spot, "r7len": r7len, "r7xt": r7xt, "f25": f25,
     "cmp": cmp, "cmpg": cmpg, "h24": h24, "r2": r2, "r3": r3, "r4": r4, "r4k": r4k, "r34x": r34x, "thr": thr, "thr2": thr2, "tgt": tgt, "g100": g100, "lc": lc, "a1": a1, "a3": a3, "a6": a6, "a7": a7, "a5": a5, "a1b": a1b, "report": report}[sys.argv[1]]()
