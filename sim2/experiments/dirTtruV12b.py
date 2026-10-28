"""Supplementary experiments for the v0.12 scheme (验证 v0.13 §4.6 follow-up): long horizons, parameter
sensitivity of the graded G1 punishment, and n = 100. Same recommended protocol and graded punishment as
dirTtruV12 (P2, AT share > 2/3, CUSUM q = 0.5, rho_bar = 0.1, D = 500, weight cap 0.5; r_min 0.7, step 0.1,
recovery 0.02 per epoch of 100 views, B_rep = 0.10; NR with data; R3; AT doubling off; evictions recompute
CapNorm only for fork culprits; queued suspensions barred from leading). Colluders = cheapest nodes per base
weight up to a base share of 0.2; the framing adversary runs on top of every injected scenario.

Parts:
  long   n = 31, 10000 views (100 epochs: longer than the 32-epoch L3 suspension and the 64-epoch lookback),
         default punishment parameters (with the eviction of repeat offenders, see rev):
           live     greedy NR liars (liveness G1) cycling through suspensions;
           iso      random misconfigurations (10% per epoch, epochs 2..94);
           spaced   one honest entity, safety items at epochs 3 and 75 (gap > lookback): L2 both times;
           close    one honest entity at epochs 3, 40, 90: L2, L3, L3 (the first has left the lookback at 90);
           bug      client fault on >= 40% of the base weight at epoch 10: downgrade, queue, recovery;
           drepeat  colluders above l_max get themselves suspended and offend again every 6 epochs
                    (malicious): L2 -> L3 -> L4 and eviction.
  sens   n = 31, 10000 views, one parameter at a time around the defaults (l_max 0.10, suspensions 4 / 32
         epochs, chain window 32, lookback 64, governance delay 2):
           l_max      0.05 (< cap, outside the constraint), 0.10, 0.125, 0.14, 0.20 (>= 1 - B_rep - 3 u_max)
                      on iso, bug, decoy;
           sus        (2, 16), (4, 32), (8, 64) on live, iso, bug;
           win        chain window 8, 32, 64 on stagger (colluders above the cap offend one entity every
                      10 epochs, malicious) and iso;
           lookback   32, 64, 128 on live and flaky (one honest entity misconfigures with probability 0.05
                      per epoch);
           gov        governance delay 1, 2, 8 on bug and fork.
  rev    n = 31, 10000 views, the rule adopted on 2026-10-28 (repeat_evict = False: an L4 reached only through
         repeats, without malicious evidence or a fork, is downgraded by governance to L3 and queued instead of
         evicted) on iso, flaky and repeat; compared with the same populations of long and sens.
  n100   n = 100 (20 licensed, 50 uncertified, 30 small; cap 0.05) with the stake tail of dirTtru (Pareto
         alpha 1.16) and a heavier one (alpha 0.8): frame, silent, budget, g1live, g1safe (iso, repeat,
         decoy, bug, fork), with the adopted rule (no eviction of non-malicious repeat offenders). About 2.6 GB
         per run: keep SIM_PROCS small (5 on the 31 GB server) and run under a memory cap.
Environment: SIM_PROCS (default 8), SIM_SEEDS (default 24: long uses all, sens 2/3, n100 half).
Run from the repository root:  python -m sim2.experiments.dirTtruV12b [long|sens|rev|n100|all|report]
Out: results/dirTtru_v12b_<part>.csv and results/dirTtru_v12b.md.
"""
import csv
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

from sim2 import adversary as A
from sim2 import engine_event
from sim2 import schedule as S
from sim2 import ttru
from sim2.common import RunConfig, State
from sim2.experiments.dirTtru import cheapest_set
from sim2.experiments.dirTtruReview import NETS, fmt, framing, poisson_upper, wilson_upper
from sim2.experiments.ttru_perf import perf
from sim2.net import NetConfig, Network
from sim2.punish import GradedPunishment

OUT = os.path.join(os.path.dirname(__file__), "..", "results")
PROCS = int(os.environ.get("SIM_PROCS", "8"))
SEEDS = int(os.environ.get("SIM_SEEDS", "24"))
UMAX, B_REP, D = 0.25, 0.10, 500
POPS = {"n31": (10, 12, 9, 0.10), "n100": (20, 50, 30, 0.05)}
# long and sens ran with the eviction of non-malicious repeat offenders (repeat_evict = True, the rule before
# 2026-10-28); rev and n100 run the adopted rule (repeat_evict = False, now the GradedPunishment default)
DEFAULTS = dict(l_max=0.10, sus=(0, 0, 4, 32), win_chain=32, lookback=64, gov_delay=2, repeat_evict=True)
ADOPTED = dict(DEFAULTS, repeat_evict=False)
LONG = 10000
G1NET = dict(regions=3, jitter_max_ms=2.0, eps_late=0.05)


def setup(pop, seed, alpha=1.16):
    nl, nu, na, cap = POPS[pop]
    cls, s = ttru.population(nl, nu, na, seed, alpha=alpha)
    return cls, s, ttru.base_weights(cls, s, 0.0, 0.0, cap, UMAX), cap


def build(cls, s, base, cap, graded=True, old_g1=False, rho_bar=0.1, evidence="at", injected=(), forks=(), pk=None):
    rule = S.CusumExclusion(q=0.5, evidence=evidence, rho_bar=rho_bar, D=D, cap=0.5, Wq=500, cap_weights=base,
                            g1=old_g1)
    pun = GradedPunishment(cls, s, cap, UMAX, injected=injected, forks=forks, **(pk or DEFAULTS)) if graded else None
    vw = ttru.TtruWeights(base, epoch=100, r_min=0.7, b_rep=B_REP, rule=rule, punish=pun, g1=old_g1)
    if graded:
        rule.bars = vw.bars
    return rule, vw


def config(n, seed, rule, vw, byz, adv, views, protocol="P2", **kw):
    opts = dict(at_share=2 / 3, nr_requires_data=True, vote_monotone=True)
    opts.update(kw)
    return RunConfig(n=n, views=views, seed=seed, protocol=protocol, leader_rule=rule,
                     byzantine=list(np.flatnonzero(byz)), adversary=adv, vote_weights=vw, **opts)


def tables(st, vw):
    return st.__dict__["_ttru_cache"][id(vw)]


def honest_conv(st, end):
    return [u for ev, node, u in st.rule_log if ev == "exclude" and st.honest[node] and u < end]


def common(st, vw, byz, base):
    c = tables(st, vw)
    sh = np.array([t[byz].sum() for t in c["tables"]])
    cut = max(float(x[~byz].sum()) for x in c.get("cuts", [np.zeros(len(base))]))
    b0 = float(base[byz].sum())
    return dict(beta=b0, bound=b0 / (1 - B_REP), honest_cut_max=cut, colluder_share_max=float(sh.max()),
                colluder_share_end=float(sh[-3:].mean()), colluder_share_min=float(sh.min()))


# ---- protocol experiments at any size (n100) ---------------------------------------------------------------
def frame_job(args):
    pop, alpha, target, eps, seed = args
    cls, s, base, cap = setup(pop, seed, alpha)
    n, views = len(cls), 2000
    byz = cheapest_set(base, s, target, max_share=0.30)
    rule, vw = build(cls, s, base, cap)
    cfg = config(n, seed, rule, vw, byz, framing(), views)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=n, seed=seed, eps_late=eps, **NETS["base"])), st, 1, views)
    end = views - 10
    hl = st.honest[st.leaders[1:end]]
    acc = np.array([S.bad_fact(st, u, u + cfg.lag, "at") for u in range(1, end)])
    return dict(part="n100", exp="frame", pop=pop, alpha=alpha, target=target, eps=eps, seed=seed,
                honest_led=int(hl.sum()), acc_honest=float(acc[hl].mean()), honest_conv=len(honest_conv(st, end)),
                commit=perf(st, 100, end)["commit"], **common(st, vw, byz, base))


def silent_job(args):
    pop, alpha, target, seed = args
    cls, s, base, cap = setup(pop, seed, alpha)
    n, views = len(cls), 3000
    byz = cheapest_set(base, s, target, max_share=0.30)
    rule, vw = build(cls, s, base, cap)
    cfg = config(n, seed, rule, vw, byz, A.SilentLeader(1.0), views)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=n, seed=seed, **NETS["base"])), st, 1, views)
    end = views - 10
    first = {}
    for ev, node, u in st.rule_log:
        if ev == "exclude" and st.byz[node] and node not in first:
            first[node] = sum(1 for y in range(1, u + 1) if st.leaders[y] == node)
    return dict(part="n100", exp="silent", pop=pop, alpha=alpha, target=target, seed=seed,
                byz_convicted=len(first) / int(byz.sum()),
                leads_to_conviction=float(np.mean(list(first.values()))) if first else float("nan"),
                byz_lead_late=float(np.mean(st.byz[st.leaders[views // 2:end]])),
                commit=perf(st, 100, end)["commit"], honest_conv=len(honest_conv(st, end)), **common(st, vw, byz, base))


def budget_job(args):
    pop, alpha, evidence, seed = args
    cls, s, base, cap = setup(pop, seed, alpha)
    n, views = len(cls), 4000
    byz = cheapest_set(base, s, 0.2)
    rule, vw = build(cls, s, base, cap, graded=False, rho_bar=0.01, evidence=evidence)
    cfg = RunConfig(n=n, views=views, seed=seed, protocol="P1", leader_rule=rule, byzantine=list(np.flatnonzero(byz)),
                    adversary=A.CollectorFraming(), vote_weights=vw)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=n, seed=seed, regions=3, jitter_max_ms=2.0)), st, 1, views)
    c = tables(st, vw)
    return dict(part="n100", exp="budget", pop=pop, alpha=alpha, evidence=evidence, seed=seed,
                colluder_cut_max=max(float(x[byz].sum()) for x in c["cuts"]), **common(st, vw, byz, base))


def punisher_metrics(p, st, vw, byz, base, end):
    """Summary of a graded-punishment run."""
    lv = {}
    for ev, i, k in p.log:
        if ev.startswith("L"):
            lv[i] = max(lv.get(i, 0), int(ev[1]))
    T = tables(st, vw)["tables"]
    hon = ~byz
    hon_susp = [float(base[hon & (t == 0)].sum()) for t in T[1:]]
    b0 = float(base[byz].sum())
    l_max = p.l_max
    return dict(beta=b0, bound1=b0 / (1 - B_REP), bound2=b0 / (1 - B_REP - l_max),
                max_level=max(lv.values()) if lv else 0, honest_punished=sum(1 for i in lv if not byz[i]),
                suspended_max=max(h[0] for h in p.history), queue_max=max(h[1] for h in p.history), wait_max=p.max_wait,
                queue_end=p.history[-1][1], evicted=int(p.evicted.sum()), honest_evicted=int((p.evicted & hon).sum()),
                evicted_share=float(base[p.evicted].sum()), infeasible=int(p.infeasible), cap_used=float(p.cap_used),
                honest_susp_mean=float(np.mean(hon_susp)), honest_susp_max=float(np.max(hon_susp)),
                colluder_share_max=float(max(t[byz].sum() for t in T)),
                colluder_share_late=float(np.mean([t[byz].sum() for t in T[len(T) // 2:]])),
                byz_suspended_frac=float(np.mean([t[byz] == 0 for t in T[1:]])),
                honest_cut_max=max(float(x[hon].sum()) for x in tables(st, vw)["cuts"]),
                qc_all=float(np.mean(st.qc_exists[100:end])), commit=perf(st, 100, end)["commit"],
                byz_lead_late=float(np.mean(st.byz[st.leaders[len(st.leaders) // 2:end]])))


def live_job(args):
    part, label, pop, alpha, greedy, mode, views, pk, seed = args
    cls, s, base, cap = setup(pop, seed, alpha)
    n = len(cls)
    byz = cheapest_set(base, s, 0.2)
    rule, vw = build(cls, s, base, cap, graded=mode == "graded", old_g1=mode == "old", pk=pk)
    cfg = config(n, seed, rule, vw, byz, A.LieNRVote(greedy=greedy), views, track_signed=True)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=n, seed=seed, regions=3, jitter_max_ms=2.0)), st, 1, views)
    end = views - 10
    vw(st, end)
    K = S.liars(st, end)
    row = dict(part=part, label=label, exp="live", pop=pop, alpha=alpha, greedy=greedy, mode=mode, seed=seed,
               n_byz=int(byz.sum()), caught=int((K & st.byz).sum()), honest_caught=int((K & st.honest).sum()),
               **{k: str(v) for k, v in (pk or DEFAULTS).items()})
    if mode == "graded":
        p = vw.punisher(st)
        susp = [sum(1 for ev, j, _ in p.log if ev == "suspend" and j == i) for i in np.flatnonzero(byz)]
        row.update(punisher_metrics(p, st, vw, byz, base, end), suspensions_per_liar=float(np.mean(susp)))
    else:
        row.update(qc_all=float(np.mean(st.qc_exists[100:end])), commit=perf(st, 100, end)["commit"],
                   byz_lead_late=float(np.mean(st.byz[st.leaders[views // 2:end]])), **common(st, vw, byz, base))
    return row


def scenario(scen, cls, s, base, byz, cap, l_max, epochs, seed):
    """Injected safety G1 of one scenario: (items, forks, entities of interest, event epoch)."""
    rng = np.random.default_rng([seed, 99])
    n = len(cls)
    hon = np.flatnonzero(~byz)
    inj, forks, who, at = [], [], [], 0
    if scen == "iso":
        for e in range(2, epochs - 5):
            if rng.random() < 0.10:
                inj.append((int(rng.integers(n)), e, e, False))
    elif scen in ("repeat", "spaced", "close", "flaky"):
        i = int(rng.choice(hon))
        who = [i]
        if scen == "flaky":
            inj = [(i, e, e, False) for e in range(2, epochs - 5) if rng.random() < 0.05]
        else:
            inj = [(i, e, e, False) for e in dict(repeat=(3, 8, 13), spaced=(3, 75), close=(3, 40, 90))[scen]]
    elif scen in ("decoy", "drepeat"):
        acc = 0.0
        for i in [int(i) for i in np.flatnonzero(byz)[np.argsort(base[byz])]]:
            who.append(i)
            acc += base[i]
            if acc > l_max + 0.02:
                break
        offsets = (0,) if scen == "decoy" else (0, 6, 12)
        inj = [(i, 3 + j + o, 3 + j + o, True) for o in offsets for j, i in enumerate(who)]
        at = 3
    elif scen == "stagger":
        acc = 0.0
        for i in [int(i) for i in np.flatnonzero(byz)[np.argsort(base[byz])[::-1]]]:
            who.append(i)
            acc += base[i]
            if acc > cap + 0.03:
                break
        inj = [(i, 3 + 10 * j, 3 + 10 * j, True) for j, i in enumerate(who)]
        at = 3
    elif scen == "bug":
        acc = 0.0
        for i in hon[np.argsort(base[hon])[::-1]]:
            if acc >= 0.40:
                break
            inj.append((int(i), 10, 10, False))
            who.append(int(i))
            acc += base[i]
        at = 10
    elif scen == "fork":
        cul = list(np.flatnonzero(byz))
        acc = float(base[byz].sum())
        for i in hon[np.argsort(s[hon] / base[hon])]:
            if acc > 0.36:
                break
            cul.append(int(i))
            acc += base[i]
        forks = [(cul, 10)]
        who, at = [int(i) for i in cul], 10
    return inj, forks, who, at


def g1safe_job(args):
    part, label, pop, alpha, scen, views, pk, seed = args
    pk = pk or DEFAULTS
    cls, s, base, cap = setup(pop, seed, alpha)
    n = len(cls)
    byz = cheapest_set(base, s, 0.2)
    inj, forks, who, at = scenario(scen, cls, s, base, byz, cap, pk["l_max"], views // 100, seed)
    rule, vw = build(cls, s, base, cap, injected=inj, forks=forks, pk=pk)
    cfg = config(n, seed, rule, vw, byz, framing(), views)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=n, seed=seed, **G1NET)), st, 1, views)
    end = views - 10
    vw(st, end)
    p = vw.punisher(st)
    row = dict(part=part, label=label, exp=scen, pop=pop, alpha=alpha, seed=seed, n_items=len(inj),
               injected_share=float(base[sorted({x[0] for x in inj})].sum()) if inj else 0.0,
               **{k: str(v) for k, v in pk.items()}, **punisher_metrics(p, st, vw, byz, base, end))
    safe = [it for it in p.items if it["kind"] == "safe"]
    first = [it for it in safe if it["k"] == 0 and not it["fork"]]
    row["corr_first"] = sum(it["level"] >= 3 for it in first)       # first offences graded as correlated
    row["n_first"] = len(first)
    hon_first = [it for it in first if not byz[it["i"]]]
    row["corr_first_honest"] = sum(it["level"] >= 3 for it in hon_first)
    row["n_first_honest"] = len(hon_first)
    if who:
        lv = [max((it["level"] for it in safe if it["i"] == i), default=0) for i in who]
        row["who_share"] = float(base[who].sum())
        row["who_l3"] = float(np.mean([x >= 3 for x in lv]))
        row["who_evicted"] = float(np.mean(p.evicted[who]))
        row["who_levels"] = ";".join(",".join(f"L{lvl}" for ev, j, _ in p.log if j == i and ev.startswith("L")
                                              for lvl in [ev[1]]) for i in who[:1])
        sus = [k for ev, j, k in p.log if ev == "suspend" and j in who]
        rel = [k for ev, j, k in p.log if ev in ("release", "evict") and j in who]
        row["served_after"] = (max(sus) - at) if sus else -1         # last queued suspension takes effect
        row["recovered_after"] = (max(rel) - at) if rel else -1       # last release or eviction
        if scen in ("bug", "fork"):
            a, b = 100 * at, min(100 * (at + 30), end)
            row["qc_event"] = float(np.mean(st.qc_exists[a:b]))
            row["qc_before"] = float(np.mean(st.qc_exists[100:a]))
            row["commit_event"] = perf(st, a, b)["commit"]
    return row


def run_job(args):
    return (live_job if args[0] == "live" else g1safe_job)(args[1:])


# ---- job lists -----------------------------------------------------------------------------------------------
def pkv(**kw):
    d = dict(DEFAULTS)
    d.update(kw)
    return d


SENS = [("l_max", (0.05, 0.10, 0.125, 0.14, 0.20), ("iso", "bug", "decoy")),
        ("sus", ((0, 0, 2, 16), (0, 0, 4, 32), (0, 0, 8, 64)), ("live", "iso", "bug")),
        ("win_chain", (8, 32, 64), ("stagger", "iso")),
        ("lookback", (32, 64, 128), ("live", "flaky")),
        ("gov_delay", (1, 2, 8), ("bug", "fork"))]
SENS_SCEN = ("iso", "bug", "decoy", "live", "stagger", "flaky", "fork")


def label_of(key, v):
    return f"sus={v[2]}/{v[3]}" if key == "sus" else f"{key}={v}"


def jobs_of(part):
    J = []
    seeds = SEEDS if part == "long" else max(1, 2 * SEEDS // 3)
    if part == "long":
        J += [("live", "long", "default", "n31", 1.16, 1.0, "graded", LONG, DEFAULTS, s) for s in range(seeds)]
        J += [("g1", "long", "default", "n31", 1.16, sc, LONG, DEFAULTS, s)
              for sc in ("iso", "spaced", "close", "bug", "drepeat") for s in range(seeds)]
    elif part == "sens":
        cells = [("default", sc, DEFAULTS) for sc in SENS_SCEN]
        for key, values, scs in SENS:
            for v in values:
                if v != DEFAULTS[key]:
                    cells += [(label_of(key, v), sc, pkv(**{key: v})) for sc in scs]
        for label, sc, pk in cells:
            for s in range(seeds):
                if sc == "live":
                    J.append(("live", "sens", label, "n31", 1.16, 1.0, "graded", LONG, pk, s))
                else:
                    J.append(("g1", "sens", label, "n31", 1.16, sc, LONG, pk, s))
    elif part == "rev":
        J += [("g1", "rev", "no_repeat_evict", "n31", 1.16, sc, LONG, ADOPTED, sd)
              for sc, n in (("iso", SEEDS), ("flaky", seeds), ("repeat", seeds)) for sd in range(n)]
    return J


def n100_jobs():
    seeds = max(1, SEEDS // 2)
    J = []
    for a in (1.16, 0.8):
        J += [(frame_job, ("n100", a, tg, e, s)) for tg in (0.2, 0.25) for e in (0.1, 0.3) for s in range(seeds)]
        J += [(silent_job, ("n100", a, tg, s)) for tg in (0.2, 0.25) for s in range(seeds)]
        J += [(budget_job, ("n100", a, ev, s)) for ev in ("failed", "at") for s in range(seeds)]
        J += [(live_job, ("n100", "n100", "n100", a, 1.0, m, 3000, ADOPTED, s)) for m in ("old", "graded")
              for s in range(seeds)]
        J += [(g1safe_job, ("n100", "n100", "n100", a, sc, 4000, ADOPTED, s))
              for sc in ("iso", "repeat", "decoy", "bug", "fork") for s in range(seeds)]
    return J


def call(job):
    fn, args = job
    return fn(args)


def write(name, rows):
    with open(os.path.join(OUT, name), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=sorted({k for r in rows for k in r}))
        w.writeheader()
        w.writerows(rows)


def run(part):
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    if part == "n100":
        jobs = n100_jobs()
        jobs.sort(key=lambda j: j[0] is frame_job)               # long frame runs last
        with Pool(PROCS, maxtasksperchild=1) as pool:               # a fresh process per run returns its memory
            rows = pool.map(call, jobs, chunksize=1)
    else:
        with Pool(PROCS) as pool:
            rows = pool.map(run_job, jobs_of(part), chunksize=1)
    write(f"dirTtru_v12b_{part}.csv", rows)
    print(f"{part}: {len(rows)} runs, {time.time() - t0:.0f}s", flush=True)


# ---- report --------------------------------------------------------------------------------------------------
def load(part):
    p = os.path.join(OUT, f"dirTtru_v12b_{part}.csv")
    if not os.path.exists(p):
        return []
    rows = list(csv.DictReader(open(p)))
    for r in rows:
        for k, v in r.items():
            if v == "":
                r[k] = float("nan")
                continue
            try:
                r[k] = float(v)
            except ValueError:
                pass
    return rows


def m(g, c, d=3):
    return f"{np.nanmean([r[c] for r in g]):.{d}f}"


def mx(g, c, d=3):
    return f"{np.nanmax([r[c] for r in g]):.{d}f}"


def evicted_cell(g, sc, d=2):
    """Evicted entities (honest among them); fork culprits added beyond the colluders are labelled honest in
    the simulator but are culprits, so they are not counted as honest."""
    hon = "罪犯" if sc == "fork" else str(int(sum(r["honest_evicted"] for r in g)))
    return f"{m(g, 'evicted', d)}（{hon}）"


def bounds_cell(g):
    """Largest colluder share, per-run excess over bound one and bound two, smallest margin to 1/3."""
    e1 = max(r["colluder_share_max"] - r["bound1"] for r in g)
    e2 = max(r["colluder_share_max"] - r["bound2"] for r in g)
    return f"{mx(g, 'colluder_share_max')} / {e1:+.3f} / {e2:+.3f} / {min(1 / 3 - r['colluder_share_max'] for r in g):+.3f}"


def report():
    L = ["# 新方案（v0.12）补充仿真：长时程、参数敏感性、n=100\n",
         "推荐协议与分级处罚同 `dirTtru_v12.md`（AT 排除期加倍关闭；只在分叉逐出时重算 CapNorm；排队实体先取消出块资格）。"
         "同伙为单位基础权重质押最低的节点，基础份额 0.2；注入场景上叠加同伙陷害。区间为对人群的自助法 95% 区间。"
         "默认参数：L_max 0.10、暂停 4 / 32 个纪元、上链窗口 32、回看期 64、治理延迟 2 个纪元。\n"]
    lo = load("long")
    if lo:
        L += ["## 长时程（n=31，10000 个视图 = 100 个纪元，默认参数；按原规则：非恶意再犯也逐出）\n"]
        g = [r for r in lo if r["exp"] == "live"]
        if g:
            L += ["**活性类 G1（贪心 NR 说谎者）**\n",
                  "| 同伙被暂停的纪元比例 | 每个同伙被暂停次数 | 最高级别 | 被罚的诚实节点 | 同伙份额：基础 → 后半段均值（最大） | "
                  "同时暂停份额最大 | 排队最长（纪元） | 后半段同伙当领导者的比例 | 提交比例 | 同伙份额最大 / 超界一 / 超界二 / 距 1/3 |", "|---|---|---|---|---|---|---|---|---|---|",
                  f"| {fmt([r['byz_suspended_frac'] for r in g])} | {m(g, 'suspensions_per_liar', 1)} | L{int(max(r['max_level'] for r in g))} | "
                  f"{int(sum(r['honest_punished'] for r in g))} | {m(g, 'beta')} → {m(g, 'colluder_share_late')}（{mx(g, 'colluder_share_max')}） | "
                  f"{mx(g, 'suspended_max')} | {int(max(r['wait_max'] for r in g))} | {m(g, 'byz_lead_late')} | {fmt([r['commit'] for r in g])} | {bounds_cell(g)} |"]
        names = dict(iso="孤立失误（每纪元 10%）", spaced="同一诚实实体，纪元 3、75（间隔超过回看期）",
                     close="同一诚实实体，纪元 3、40、90", bug="客户端缺陷（≥40% 权重，纪元 10）",
                     drepeat="同伙诱饵每 6 个纪元再犯（恶意）")
        L += ["\n**注入安全类 G1**\n",
              "| 场景 | 目标实体的定级序列（示例） | 目标实体被逐出比例 | 被逐出（诚实） | 同时暂停份额最大 | 排队最长 / 期末仍排队 | "
              "全部生效 / 全部恢复（事件后纪元，最大） | 诚实被暂停或逐出的份额：均值 / 最大 | 同伙份额最大 / 超界一 / 超界二 / 距 1/3 | 提交比例 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for sc in ("iso", "spaced", "close", "bug", "drepeat"):
            g = [r for r in lo if r["exp"] == sc]
            if not g:
                continue
            seqs = sorted({r["who_levels"] for r in g if isinstance(r.get("who_levels"), str)})
            seq = " / ".join(seqs[:3]) if seqs else "—"
            hasw = [r for r in g if not np.isnan(r.get("who_evicted", float("nan")))]
            served = [r["served_after"] for r in hasw if r["served_after"] >= 0]
            rec = [r["recovered_after"] for r in hasw if r["recovered_after"] >= 0]
            L.append(f"| {names[sc]} | {seq} | {m(hasw, 'who_evicted', 2) if hasw else '—'} | "
                     f"{evicted_cell(g, sc, 1)} | {mx(g, 'suspended_max')} | "
                     f"{int(max(r['wait_max'] for r in g))} / {int(max(r['queue_end'] for r in g))} | "
                     f"{int(max(served)) if served else '—'} / {int(max(rec)) if rec else '—'} | "
                     f"{m(g, 'honest_susp_mean')} / {mx(g, 'honest_susp_max')} | "
                     f"{bounds_cell(g)} | {fmt([r['commit'] for r in g])} |")
        g = [r for r in lo if r["exp"] == "iso"]
        if g:
            nf, cf = sum(r["n_first_honest"] for r in g), sum(r["corr_first_honest"] for r in g)
            L.append(f"\n孤立失误场景中，诚实实体的首次失误共 {int(nf)} 次，因巧合被算作关联（定为 L3 及以上）{int(cf)} 次；"
                     f"{len(g)} 个人群中共有 {int(sum(r['honest_evicted'] for r in g))} 个诚实实体因再犯被逐出。")
        L.append("\n超界一、超界二为逐次比较的最大超出量：界一 = β0/(1−B_rep)，界二 = β0/(1−B_rep−L_max)；距 1/3 为同伙份额与 1/3 的最小差距。"
                 "\"诚实被暂停或逐出的份额\"含因再犯被逐出的诚实实体。")
    se = load("sens")
    if se:
        L += ["\n## 参数敏感性（n=31，10000 个视图，每次只改一个参数，其余为默认值；按原规则：非恶意再犯也逐出）\n"]
        titles = dict(l_max="同时暂停份额上限 L_max（约束：cap = 0.10 ≤ L_max < 1 − B_rep − 3u_max = 0.15）",
                      sus="暂停时长 L2 / L3（纪元）", win_chain="上链窗口 W（纪元；方案要求 W 不短于最长暂停期）",
                      lookback="回看期（纪元）", gov_delay="治理延迟（纪元）")
        ok = lambda x: isinstance(x, float) and not np.isnan(x)  # noqa: E731
        for key, values, scs in SENS:
            L += [f"\n**{titles[key]}**\n",
                  "| 取值 | 场景 | 同时暂停份额最大 | 排队最长 / 期末仍排队 | 全部生效 / 全部恢复（事件后纪元，最大） | "
                  "诚实被暂停或逐出的份额：均值 / 最大 | 同伙被暂停的纪元比例 | 首次失误定为关联：诚实（次） / 目标组（比例） | "
                  "被逐出（诚实） | 同伙份额最大 / 超界一 / 超界二 / 距 1/3 | 提交比例 |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
            for v in values:
                dflt = v == DEFAULTS[key]
                label = "default" if dflt else label_of(key, v)
                shown = f"{v[2]}/{v[3]}" if key == "sus" else f"{v}"
                for sc in scs:
                    g = [r for r in se if r["label"] == label and r["exp"] == sc]
                    if not g:
                        continue
                    served = [r["served_after"] for r in g if ok(r.get("served_after")) and r["served_after"] >= 0]
                    rec = [r["recovered_after"] for r in g if ok(r.get("recovered_after")) and r["recovered_after"] >= 0]
                    hf = sum(r["corr_first_honest"] for r in g if ok(r.get("corr_first_honest")))
                    hn = sum(r["n_first_honest"] for r in g if ok(r.get("n_first_honest")))
                    who = [r["who_l3"] for r in g if ok(r.get("who_l3"))]
                    corr = f"{int(hf)}/{int(hn)}" if sc in ("iso", "flaky") else "—"
                    corr += f" / {np.mean(who):.2f}" if sc == "stagger" and who else ""
                    L.append(f"| {shown}{'（默认）' if dflt else ''} | {sc} | {mx(g, 'suspended_max')} | "
                             f"{int(max(r['wait_max'] for r in g))} / {int(max(r['queue_end'] for r in g))} | "
                             f"{int(max(served)) if served else '—'} / {int(max(rec)) if rec else '—'} | "
                             f"{m(g, 'honest_susp_mean')} / {mx(g, 'honest_susp_max')} | {m(g, 'byz_suspended_frac')} | {corr} | "
                             f"{evicted_cell(g, sc)} | "
                             f"{bounds_cell(g)} | {fmt([r['commit'] for r in g])} |")
    rv = load("rev")
    if rv:
        L += ["\n## 非恶意再犯降为 L3（2026-10-28 采纳的规则，n=31，10000 个视图）\n",
              "只靠再犯升到 L4、没有恶意证据也没有分叉的，治理默认降为 L3、进入暂停队列；分叉与确认恶意的仍逐出。与原规则（再犯即逐出）的同一批人群对比。\n",
              "| 场景 | 规则 | 人群数 | 被逐出（诚实） | 同时暂停份额最大 | 排队最长 / 期末仍排队 | 诚实被暂停或逐出的份额：均值 / 最大 | "
              "同伙份额最大 / 超界一 / 超界二 / 距 1/3 | 提交比例 |", "|---|---|---|---|---|---|---|---|---|"]
        for sc in ("iso", "flaky", "repeat"):
            new = [r for r in rv if r["exp"] == sc]
            seeds = {r["seed"] for r in new}
            old = [r for r in lo if r["exp"] == sc and r["seed"] in seeds] or \
                  [r for r in se if r["label"] == "default" and r["exp"] == sc and r["seed"] in seeds]
            for name, g in (("原规则（再犯即逐出）", old), ("现行规则（非恶意再犯降为 L3）", new)):
                if g:
                    L.append(f"| {sc} | {name} | {len(g)} | {evicted_cell(g, sc, 2)} | {mx(g, 'suspended_max')} | "
                             f"{int(max(r['wait_max'] for r in g))} / {int(max(r['queue_end'] for r in g))} | "
                             f"{m(g, 'honest_susp_mean')} / {mx(g, 'honest_susp_max')} | {bounds_cell(g)} | {fmt([r['commit'] for r in g])} |")
    n1 = load("n100")
    if n1:
        L += ["\n## n=100（20 家持牌、50 家未认证、30 个小节点；cap = 0.05、u_max = 0.25）\n",
              "持股分布：帕累托尾 α = 1.16（同 n=31）与更重的尾 α = 0.8。\n"]
        for a in (1.16, 0.8):
            ga = [r for r in n1 if r["alpha"] == a]
            if not ga:
                continue
            L.append(f"\n### α = {a}\n")
            fr = [r for r in ga if r["exp"] == "frame"]
            if fr:
                L += ["**陷害（同伙谎报 NR、扣票，叠加独立迟到；2000 个视图）**\n",
                      "| 同伙份额 | ε | 诚实视图被 AT 指控的比例 | 诚实定罪 / 千个诚实领导视图（95% 上界） | 出现诚实定罪的人群 | "
                      "诚实被降权重最大 | 同伙份额最大 / 单表界（最大超界） | 提交比例 |", "|---|---|---|---|---|---|---|---|"]
                for tg in (0.2, 0.25):
                    for e in (0.1, 0.3):
                        g = [r for r in fr if (r["target"], r["eps"]) == (tg, e)]
                        if not g:
                            continue
                        k = sum(r["honest_conv"] > 0 for r in g)
                        tc, tv = sum(r["honest_conv"] for r in g), sum(r["honest_led"] for r in g)
                        over = max(r["colluder_share_max"] - r["bound"] for r in g)
                        L.append(f"| {m(g, 'beta', 2)} | {e} | {fmt([r['acc_honest'] for r in g])} | "
                                 f"{1000 * tc / tv:.3f}（≤ {1000 * poisson_upper(int(tc)) / tv:.3f}） | {k}/{len(g)}（{wilson_upper(k, len(g)):.3f}） | "
                                 f"{fmt([r['honest_cut_max'] for r in g])} | {m(g, 'colluder_share_max')} / {m(g, 'bound')}（{over:+.4f}） | "
                                 f"{fmt([r['commit'] for r in g])} |")
            sl = [r for r in ga if r["exp"] == "silent"]
            if sl:
                L += ["\n**沉默领导者（3000 个视图）**\n",
                      "| 同伙份额 | 同伙被定罪比例 | 定罪前的领导次数 | 后半段同伙当领导者的比例 | 提交比例 | 诚实定罪 | 同伙份额：基础 → 期末 |",
                      "|---|---|---|---|---|---|---|"]
                for tg in (0.2, 0.25):
                    g = [r for r in sl if r["target"] == tg]
                    if g:
                        L.append(f"| {m(g, 'beta', 2)} | {fmt([r['byz_convicted'] for r in g])} | {fmt([r['leads_to_conviction'] for r in g], 1)} | "
                                 f"{fmt([r['byz_lead_late'] for r in g])} | {fmt([r['commit'] for r in g])} | "
                                 f"{int(sum(r['honest_conv'] for r in g))} | {m(g, 'beta')} → {m(g, 'colluder_share_end')} |")
            bu = [r for r in ga if r["exp"] == "budget"]
            if bu:
                L += ["\n**预算界（P1 收集者陷害、ρ̄=0.01、不开 R3）**\n",
                      "| 证据 | 同伙份额最大 / 单表界（最大超界） | 诚实被降权重最大 | 同伙被降权重最大 |", "|---|---|---|---|"]
                for ev in ("failed", "at"):
                    g = [r for r in bu if r["evidence"] == ev]
                    if g:
                        over = max(r["colluder_share_max"] - r["bound"] for r in g)
                        L.append(f"| {'失败提议者（可被陷害）' if ev == 'failed' else 'AT（抗陷害）'} | {m(g, 'colluder_share_max', 4)} / "
                                 f"{m(g, 'bound', 4)}（{over:+.5f}） | {fmt([r['honest_cut_max'] for r in g], 4)} | "
                                 f"{fmt([r['colluder_cut_max'] for r in g], 4)} |")
            lv = [r for r in ga if r["exp"] == "live"]
            if lv:
                L += ["\n**活性类 G1（贪心 NR 说谎者，3000 个视图）**\n",
                      "| 规则 | 被证实的同伙 / 同伙数 | 被证实的诚实节点 | 同伙份额：基础 → 后半段（最大） | 同伙被暂停的纪元比例 | 最高级别 | "
                      "同时暂停份额最大 | 后半段同伙当领导者的比例 | 提交比例 |", "|---|---|---|---|---|---|---|---|---|"]
                for mo in ("old", "graded"):
                    g = [r for r in lv if r["mode"] == mo]
                    if not g:
                        continue
                    gd = mo == "graded"
                    late = m(g, "colluder_share_late") if gd else m(g, "colluder_share_end")
                    L.append(f"| {'分级' if gd else '旧规则'} | {m(g, 'caught', 1)} / {m(g, 'n_byz', 1)} | {int(sum(r['honest_caught'] for r in g))} | "
                             f"{m(g, 'beta')} → {late}（{mx(g, 'colluder_share_max')}） | {m(g, 'byz_suspended_frac') if gd else '—'} | "
                             f"{('L%d' % max(r['max_level'] for r in g)) if gd else '—'} | {mx(g, 'suspended_max') if gd else '—'} | "
                             f"{m(g, 'byz_lead_late')} | {fmt([r['commit'] for r in g])} |")
            gs = [r for r in ga if r["exp"] in ("iso", "repeat", "decoy", "bug", "fork")]
            if gs:
                names = dict(iso="孤立失误（每纪元 10%）", repeat="同一实体三次失误", decoy="诱饵暂停",
                             bug="客户端缺陷（≥40% 权重）", fork="分叉（罪犯 > 1/3）")
                L += ["\n**注入安全类 G1（4000 个视图）**\n",
                      "| 场景 | 被注入份额 | 同时暂停份额最大 | 排队最长（纪元） | 被逐出（诚实） | CapNorm 不可行 / 放宽后单家上限 | "
                      "同伙份额最大 / 超界一 / 超界二 / 距 1/3 | 提交比例 |", "|---|---|---|---|---|---|---|---|"]
                for sc in ("iso", "repeat", "decoy", "bug", "fork"):
                    g = [r for r in gs if r["exp"] == sc]
                    if g:
                        L.append(f"| {names[sc]} | {m(g, 'injected_share')} | {mx(g, 'suspended_max')} | {int(max(r['wait_max'] for r in g))} | "
                                 f"{evicted_cell(g, sc, 1)} | "
                                 f"{int(sum(r['infeasible'] for r in g))}/{len(g)} / {mx(g, 'cap_used')} | "
                                 f"{bounds_cell(g)} | {fmt([r['commit'] for r in g])} |")
    with open(os.path.join(OUT, "dirTtru_v12b.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    parts = ("long", "sens", "n100") if which == "all" else (which,)
    if which != "report":
        for p in parts:
            run(p)
    report()
