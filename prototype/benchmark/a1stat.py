"""How often honest leaders are accused under late messages (DESIGN.md §15.16): python3 a1stat.py <logs dir>...

Reads the run archives of `p5.py a1` (results-p5/a1_logs/*.tgz). Per run it rebuilds who led which round from the
"Created B<round>" line every leader logs, takes the accusations committed on node-0's ledger ("G2: accusation of
round R led by X"), the exclusions ("G2: X excluded from leading") and the final reputations, and reports, per arm:
  - the accused share of honest-led rounds (rounds of the last 20 left out: their accusations may not be on the
    ledger yet);
  - P(accused | the same leader's previous lead was accused) against P(accused | it was not): serial correlation;
  - runs of 2 and 3 consecutive accused leads of one honest leader (3 in a row convict at gamma = 10^2);
  - honest exclusions (convictions) and the honest weight cut at the end;
  - the convictions per 1000 honest-led rounds that the CUSUM (up ln 5, down ln(5/9), threshold ln 100) would give
    if accusations were independent at the measured rate (Monte Carlo), to set against the simulator.
Only the standard library is used."""
import math
import os
import random
import re
import shutil
import sys
import tarfile
import tempfile
from collections import defaultdict
from glob import glob

BOOT = re.compile(r"Node (\S+) successfully booted")
CREATED = re.compile(r"Created B(\d+)")
ACCUSED = re.compile(r"G2: accusation of round (\d+) led by (\S+)")
EXCLUDED = re.compile(r"G2: (\S+) excluded from leading")
REPUTATION = re.compile(r"G2: reputation of (\S+) is (\d+) ppm")
TIMEOUT = re.compile(r"Timeout reached for round (\d+)")
COMMITTED = re.compile(r"Committed B(\d+)")
TAIL = 20
UP, DOWN, THRESHOLD = math.log(5), math.log(5 / 9), math.log(100)


def run_stats(logs):
    names, roles, created = {}, {}, {}
    timed_out = defaultdict(set)
    for path in glob(os.path.join(logs, "node-*.log")):
        node = int(re.search(r"node-(\d+)\.log$", path).group(1))
        text = open(path, errors="replace").read()
        m = BOOT.search(text)
        if not m:
            continue
        names[node] = m.group(1)
        roles[node] = "framer" if "Framing:" in text else "honest"
        for r in CREATED.findall(text):
            created[int(r)] = node
        for r in TIMEOUT.findall(text):
            timed_out[int(r)].add(node)
    short = {name[:16]: node for node, name in names.items()}
    zero = open(os.path.join(logs, "node-0.log"), errors="replace").read()
    accused = {}
    for r, who in ACCUSED.findall(zero):
        accused[int(r)] = short.get(who[:16])
    excluded = [short.get(w[:16]) for w in EXCLUDED.findall(zero)]
    rep = {}
    for w, ppm in REPUTATION.findall(zero):
        rep[short.get(w[:16])] = int(ppm)
    leader = dict(created)
    for r, node in accused.items():
        leader.setdefault(r, node)
    # Accusations reach the ledger only through committed blocks: count rounds up to the last committed round.
    committed = max((int(x) for x in COMMITTED.findall(zero)), default=0)
    top = committed
    rounds = sorted(r for r in leader if r <= top - TAIL)
    honest = [r for r in rounds if roles.get(leader[r]) == "honest"]
    leads = defaultdict(list)
    for r in honest:
        leads[leader[r]].append(r in accused)
    after = {(True, True): 0, (True, False): 0, (False, True): 0, (False, False): 0}
    run2 = run3 = 0
    for seq in leads.values():
        for a, b in zip(seq, seq[1:]):
            after[(a, b)] += 1
        streak = 0
        for x in seq:
            streak = streak + 1 if x else 0
            run2 += streak == 2
            run3 += streak == 3
    f = (len(names) - 1) // 3
    stalled = {r for r, nodes in timed_out.items() if len(nodes) >= f + 1}
    # Where accusations of honest leaders come from: after a stalled round (entered by TC), or after a QC; and
    # whether the honest leader also led the round before (a lagging leader leading twice).
    after_stall = {(s_, a): 0 for s_ in (True, False) for a in (True, False)}
    repeat_lead = {(s_, a): 0 for s_ in (True, False) for a in (True, False)}
    for r in honest:
        after_stall[(r - 1 in stalled, r in accused)] += 1
        repeat_lead[(leader.get(r - 1) == leader[r], r in accused)] += 1
    n = len(names)
    cut = sum((1 - rep.get(node, 10**6) / 1e6) / n for node in names if roles[node] == "honest")
    return dict(top=top, created_top=max(leader, default=0), honest_led=len(honest), accused=sum(r in accused for r in honest), after=after,
                run2=run2, run3=run3, after_stall=after_stall, repeat_lead=repeat_lead, honest_excluded=sum(roles.get(x) == "honest" for x in excluded),
                framer_excluded=sum(roles.get(x) == "framer" for x in excluded), honest_cut=cut)


def cusum_rate(p, leads=200_000, seed=1):
    """Convictions per 1000 leads of one leader whose leads are accused independently with probability p."""
    rnd = random.Random(seed)
    s, conv = 0.0, 0
    for _ in range(leads):
        s = max(0.0, s + (UP if rnd.random() < p else DOWN))
        if s >= THRESHOLD:
            conv += 1
            s = 0.0
    return 1000 * conv / leads


def main():
    arms = defaultdict(list)
    for d in sys.argv[1:]:
        for tgz in sorted(glob(os.path.join(d, "*.tgz"))):
            arm = re.sub(r"-\d+\.tgz$", "", os.path.basename(tgz))
            tmp = tempfile.mkdtemp(dir="/tmp")
            try:
                with tarfile.open(tgz) as t:
                    t.extractall(tmp, members=[m for m in t.getmembers() if re.search(r"node-\d+\.log$", m.name)])
                arms[arm].append(run_stats(os.path.join(tmp, "logs")))
            finally:
                shutil.rmtree(tmp)
    print("arm | runs | committed top (created top) | honest-led rounds | accused (share) | P(acc|prev acc) / P(acc|prev not) | 2 / 3 in a row | "
          "honest convictions (per 1000) | framer convictions | honest cut max | CUSUM if independent (per 1000)")
    for arm, rows in sorted(arms.items()):
        h = sum(r["honest_led"] for r in rows)
        a = sum(r["accused"] for r in rows)
        aft = {k: sum(r["after"][k] for r in rows) for k in rows[0]["after"]}
        p_aa = aft[(True, True)] / max(1, aft[(True, True)] + aft[(True, False)])
        p_na = aft[(False, True)] / max(1, aft[(False, True)] + aft[(False, False)])
        conv = sum(r["honest_excluded"] for r in rows)
        p = a / max(1, h)
        st_ = {k: sum(r["after_stall"][k] for r in rows) for k in rows[0]["after_stall"]}
        rl = {k: sum(r["repeat_lead"][k] for r in rows) for k in rows[0]["repeat_lead"]}
        cond = lambda d, x: d[(x, True)] / max(1, d[(x, True)] + d[(x, False)])
        extra = (f" || P(acc | prev round stalled) {cond(st_, True):.4f} (n={st_[(True, True)] + st_[(True, False)]}) vs "
                 f"{cond(st_, False):.4f}; P(acc | same leader as prev round) {cond(rl, True):.4f} "
                 f"(n={rl[(True, True)] + rl[(True, False)]}) vs {cond(rl, False):.4f}")
        tops = "/".join(f"{r['top']}({r['created_top']})" for r in rows)
        print(f"{arm} | {len(rows)} | {tops} | {h} | {a} ({p:.4f}) | {p_aa:.3f} / {p_na:.4f} | "
              f"{sum(r['run2'] for r in rows)} / {sum(r['run3'] for r in rows)} | {conv} ({1000 * conv / max(1, h):.2f}) | "
              f"{sum(r['framer_excluded'] for r in rows)} | {max(r['honest_cut'] for r in rows):.4f} | "
              f"{cusum_rate(p):.3f}" + extra)


if __name__ == "__main__":
    main()
