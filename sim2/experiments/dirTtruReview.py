"""Parameter review of the recommended protocol with more populations and confidence intervals
(信任2.0_协议级验证 §3.1, §3.3, §4; 写论文之前的复核).

Recommended protocol: P2; AT accusation at share > 2/3, CUSUM q = 0.5, rho_bar = 0.1, gamma = 1e4, D = 500,
weight-based exclusion cap 0.5; T_tru weights with r_min = 0.7, step 0.1, recovery 0.02 per epoch
(100 views), B_rep = 0.10; NR = no usable proposal (header and block); R3 (vote_monotone) on; no soft
evidence, no forwarding. Same populations as dirTtru (n = 31); colluders = the cheapest set reaching a
base share target (about 0.24 or 0.28).

Parts (each cell: mean with a 95% bootstrap interval over populations; for "populations with at least one
honest conviction" the count and the Wilson 95% upper bound of the rate):
  frame   colluders claim NR = 1 in honest leaders' views and withhold their votes there, on top of every
          message being late with probability eps (5 s); networks "base" (3 regions) and "wide" (8 regions,
          120 ms per unit distance, 20 ms jitter). Honest AT convictions, honest weight cut, colluder share.
  silent  colluding leaders send nothing; leaderships until conviction, colluders convicted, colluder share.
  chaos   GST at view 3000 of 5000 with independent extra delays, region outages or adversarial scheduling
          before GST, and the framing adversary; honest weight cut against B_rep, colluder share against the
          bound, last view of an honest exclusion.
  budget  dirTtru.budget_job: framable evidence (failed proposer, P1 collector framing) against the budget
          bound beta0 / (1 - B_rep), and AT for comparison.

Environment: SIM_PROCS (default 8), SIM_SEEDS (default 50; chaos uses half).
Run from the repository root:  python -m sim2.experiments.dirTtruReview [frame|silent|chaos|budget|all]
Out: results/dirTtru_review_<part>.csv and results/dirTtru_review.md.
"""
import csv
import math
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
from sim2.experiments.dirTtru import N, budget_job, cheapest_set, setup
from sim2.experiments.ttru_perf import PreGSTNet, adv_targets
from sim2.net import NetConfig, Network

OUT = os.path.join(os.path.dirname(__file__), "..", "results")
PROCS = int(os.environ.get("SIM_PROCS", "8"))
SEEDS = int(os.environ.get("SIM_SEEDS", "50"))
VIEWS, B_REP, D = 2000, 0.10, 500
NETS = {"base": dict(regions=3, jitter_max_ms=2.0), "wide": dict(regions=8, region_c1_ms=120.0, jitter_max_ms=20.0)}


def rule_and_weights(base):
    rule = S.CusumExclusion(q=0.5, evidence="at", rho_bar=0.1, D=D, cap=0.5, Wq=500, cap_weights=base)
    return rule, ttru.TtruWeights(base, epoch=100, r_min=0.7, b_rep=B_REP, rule=rule)


def config(seed, rule, vw, byz, adv, views):
    return RunConfig(n=N, views=views, seed=seed, protocol="P2", leader_rule=rule, byzantine=list(np.flatnonzero(byz)),
                     adversary=adv, vote_weights=vw, at_share=2 / 3, nr_requires_data=True, vote_monotone=True)


def framing():
    return A.Compose([A.LieNR(), A.WithholdVotesOnHonest()])


def weights_summary(st, vw, byz):
    cache = st.__dict__["_ttru_cache"][id(vw)]
    shares = np.array([t[byz].sum() for t in cache["tables"]])
    return (max(float(c[~byz].sum()) for c in cache.get("cuts", [np.zeros(len(byz))])),
            float(shares.max()), float(shares[-3:].mean()))


def honest_convictions(st, end):
    return [u for ev, node, u in st.rule_log if ev == "exclude" and st.honest[node] and u < end]


def frame_job(args):
    target, eps, net, seed = args
    cls, s, base, cost = setup(seed, 1.0)
    byz = cheapest_set(base, cost, target, max_share=0.30)
    rule, vw = rule_and_weights(base)
    cfg = config(seed, rule, vw, byz, framing(), VIEWS)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=N, seed=seed, eps_late=eps, **NETS[net])), st, 1, VIEWS)
    end = VIEWS - 10
    hl = st.honest[st.leaders[1:end]]
    acc = np.array([S.bad_fact(st, u, u + cfg.lag, "at") for u in range(1, end)])
    conv = honest_convictions(st, end)
    cut, smax, send = weights_summary(st, vw, byz)
    b0 = float(base[byz].sum())
    return dict(part="frame", target=target, eps=eps, net=net, seed=seed, beta=b0, bound=b0 / (1 - B_REP),
                honest_led=int(hl.sum()), acc_honest=float(acc[hl].mean()), honest_conv=len(conv),
                conv_per_1000=1000.0 * len(conv) / max(1, int(hl.sum())), honest_cut_max=cut,
                colluder_share_max=smax, colluder_share_end=send)


def silent_job(args):
    target, eps, seed = args
    cls, s, base, cost = setup(seed, 1.0)
    byz = cheapest_set(base, cost, target, max_share=0.30)
    rule, vw = rule_and_weights(base)
    cfg = config(seed, rule, vw, byz, A.SilentLeader(1.0), VIEWS)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=N, seed=seed, eps_late=eps, **NETS["base"])), st, 1, VIEWS)
    end = VIEWS - 10
    first = {}
    for ev, node, u in st.rule_log:
        if ev == "exclude" and st.byz[node] and node not in first:
            first[node] = sum(1 for y in range(1, u + 1) if st.leaders[y] == node)
    cut, smax, send = weights_summary(st, vw, byz)
    b0 = float(base[byz].sum())
    return dict(part="silent", target=target, eps=eps, net="base", seed=seed, beta=b0, bound=b0 / (1 - B_REP),
                byz_convicted=len(first) / int(byz.sum()),
                leads_to_conviction=float(np.mean(list(first.values()))) if first else float("nan"),
                honest_conv=len(honest_convictions(st, end)), honest_cut_max=cut,
                colluder_share_max=smax, colluder_share_end=send)


def chaos_job(args):
    netmode, seed = args
    gst, views = 3000, 5000
    cls, s, base, cost = setup(seed, 1.0)
    byz = cheapest_set(base, cost, 0.2)
    rule, vw = rule_and_weights(base)
    cfg = config(seed, rule, vw, byz, framing(), views)
    st = State(cfg)
    if netmode == "iid":
        net = Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, async_views=gst, async_p=0.5,
                                async_extra_ms=3000.0))
    else:
        ncfg = NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, outage_p=0.02 if netmode == "outage" else 0.0)
        net = PreGSTNet(ncfg, netmode, gst, st, adv_targets(base, byz))
    engine_event.simulate(cfg, net, st, 1, views)
    end = views - 10
    conv = honest_convictions(st, end)
    excl, last_excl = set(), 0                 # last view at which some honest replica is still excluded
    for ev, node, u in st.rule_log:
        if not st.honest[node]:
            continue
        if ev == "exclude":
            excl.add(node)
            last_excl = max(last_excl, u)
        elif ev == "release" and node in excl:
            excl.discard(node)
            last_excl = max(last_excl, u)
    if excl:
        last_excl = end
    hl_post = [u for u in range(gst, end) if st.honest[st.leaders[u]]]
    acc_post = sum(S.bad_fact(st, u, u + cfg.lag, "at") for u in hl_post)
    cut, smax, send = weights_summary(st, vw, byz)
    b0 = float(base[byz].sum())
    return dict(part="chaos", net=netmode, seed=seed, beta=b0, bound=b0 / (1 - B_REP), gst=gst,
                honest_conv_pre=sum(u < gst for u in conv), honest_conv_post=sum(u >= gst for u in conv),
                honest_cut_max=cut, colluder_share_max=smax, colluder_share_end=send, last_honest_excl=last_excl,
                honest_acc_post=int(acc_post), qc_post=float(np.mean(st.qc_exists[gst + D + 20:end])))


def ci(xs, reps=2000):
    xs = np.asarray([x for x in xs if not (isinstance(x, float) and math.isnan(x))], float)
    if xs.size == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(0)
    bs = rng.choice(xs, (reps, xs.size)).mean(axis=1)
    return float(xs.mean()), float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))


def wilson_upper(k, n, z=1.96):
    if n == 0:
        return float("nan")
    p = k / n
    return (p + z * z / (2 * n) + z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)


def poisson_upper(k, conf=0.975):
    """Upper end of the two-sided 95% interval of a Poisson mean given k events (bisection on the CDF)."""
    def cdf(lam):
        term = total = math.exp(-lam)
        for i in range(1, k + 1):
            term *= lam / i
            total += term
        return total
    lo, hi = 0.0, 10.0 + 10.0 * k
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cdf(mid) > 1 - conf else (lo, mid)
    return hi


def fmt(xs, d=3):
    m, lo, hi = ci(xs)
    return f"{m:.{d}f} [{lo:.{d}f}, {hi:.{d}f}]"


def write(name, rows):
    with open(os.path.join(OUT, name), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=sorted({k for r in rows for k in r}))
        w.writeheader()
        w.writerows(rows)


def run(part):
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    if part == "frame":
        jobs = [(tg, e, nt, s) for tg in (0.2, 0.25) for e in (0.1, 0.2, 0.3) for nt in NETS for s in range(SEEDS)]
        fn = frame_job
    elif part == "silent":
        jobs = [(tg, e, s) for tg in (0.2, 0.25) for e in (0.0, 0.1) for s in range(SEEDS)]
        fn = silent_job
    elif part == "chaos":
        jobs = [(nm, s) for nm in ("iid", "outage", "adv") for s in range(max(1, SEEDS // 2))]
        fn = chaos_job
    else:
        jobs = [(ev, False, B_REP, s) for ev in ("failed", "at") for s in range(SEEDS)]
        fn = budget_job
    with Pool(PROCS) as pool:
        rows = pool.map(fn, jobs, chunksize=1)
    write(f"dirTtru_review_{part}.csv", rows)
    print(f"{part}: {len(rows)} runs, {time.time() - t0:.0f}s", flush=True)
    return rows


def report():
    def load(part):
        p = os.path.join(OUT, f"dirTtru_review_{part}.csv")
        if not os.path.exists(p):
            return []
        rows = list(csv.DictReader(open(p)))
        for r in rows:
            for k, v in r.items():
                try:
                    r[k] = float(v)
                except ValueError:
                    pass
        return rows

    L = ["# 推荐协议的参数复核（更多人群，带 95% 区间）\n",
         "推荐协议：P2；AT 份额 > 2/3、CUSUM q=0.5、ρ̄=0.1、γ=10⁴、D=500、排除上限按权重 0.5；T_tru：r_min=0.7、"
         "步长 0.1、每纪元恢复 0.02、B_rep=0.10；NR 含块；R3 开启；不用软证据、不转发。n=31。"
         "区间为对人群的自助法 95% 区间；\"出现诚实定罪的人群\"给出个数与 Wilson 95% 上界。\n"]
    fr = load("frame")
    if fr:
        L += ["## 陷害：同伙谎报 NR、在诚实视图扣票，叠加独立迟到\n",
              "| 同伙份额 | 网络 | ε | 诚实视图被 AT 指控的比例 | 诚实定罪 / 千个诚实领导视图（合并 Poisson 95% 上界） | "
              "出现诚实定罪的人群（上界） | 诚实被降权重最大（预算 0.10） | 同伙份额最大 / 单表界 |", "|---|---|---|---|---|---|---|---|"]
        for tg in (0.2, 0.25):
            for nt in NETS:
                for e in (0.1, 0.2, 0.3):
                    g = [r for r in fr if (r["target"], r["net"], r["eps"]) == (tg, nt, e)]
                    if not g:
                        continue
                    k = sum(r["honest_conv"] > 0 for r in g)
                    over = max(r["colluder_share_max"] - r["bound"] for r in g)
                    tot_c, tot_v = sum(r["honest_conv"] for r in g), sum(r["honest_led"] for r in g)
                    L.append(f"| {np.mean([r['beta'] for r in g]):.2f} | {nt} | {e} | {fmt([r['acc_honest'] for r in g])} | "
                             f"{1000 * tot_c / tot_v:.3f}（≤ {1000 * poisson_upper(int(tot_c)) / tot_v:.3f}） | "
                             f"{k}/{len(g)}（{wilson_upper(k, len(g)):.3f}） | "
                             f"{fmt([r['honest_cut_max'] for r in g])} | "
                             f"{np.mean([r['colluder_share_max'] for r in g]):.3f} / {np.mean([r['bound'] for r in g]):.3f}"
                             f"（最大超界 {over:+.4f}） |")
    sl = load("silent")
    if sl:
        L += ["\n## 沉默领导者\n",
              "| 同伙份额 | ε | 同伙被定罪比例 | 定罪前的领导次数 | 诚实定罪（总数） | 同伙份额：期末 / 基础 |",
              "|---|---|---|---|---|---|"]
        for tg in (0.2, 0.25):
            for e in (0.0, 0.1):
                g = [r for r in sl if (r["target"], r["eps"]) == (tg, e)]
                if g:
                    L.append(f"| {np.mean([r['beta'] for r in g]):.2f} | {e} | {fmt([r['byz_convicted'] for r in g])} | "
                             f"{fmt([r['leads_to_conviction'] for r in g], 1)} | {int(sum(r['honest_conv'] for r in g))} | "
                             f"{np.mean([r['colluder_share_end'] for r in g]):.3f} / {np.mean([r['beta'] for r in g]):.3f} |")
    ch = load("chaos")
    if ch:
        L += ["\n## GST 之前的混乱期（GST = 视图 3000，共 5000 视图；同伙陷害）\n",
              "| 混乱期网络 | 诚实 AT 定罪记账：GST 前 / 后（总数） | GST 后诚实领导视图的 AT 指控（总数） | 诚实被降权重最大（预算 0.10） | "
              "同伙份额最大 / 单表界（最大超界） | 诚实节点被排除的最后视图（最大） | GST+D 之后的 QC 率 |", "|---|---|---|---|---|---|---|"]
        for nm in ("iid", "outage", "adv"):
            g = [r for r in ch if r["net"] == nm]
            if g:
                over = max(r["colluder_share_max"] - r["bound"] for r in g)
                L.append(f"| {nm} | {int(sum(r['honest_conv_pre'] for r in g))} / {int(sum(r['honest_conv_post'] for r in g))} | "
                         f"{int(sum(r.get('honest_acc_post', 0) for r in g))} | "
                         f"{fmt([r['honest_cut_max'] for r in g])}（最大 {max(r['honest_cut_max'] for r in g):.3f}） | "
                         f"{np.mean([r['colluder_share_max'] for r in g]):.3f} / {np.mean([r['bound'] for r in g]):.3f}"
                         f"（{over:+.4f}） | {int(max(r['last_honest_excl'] for r in g))} | {fmt([r['qc_post'] for r in g])} |")
    bu = load("budget")
    if bu:
        L += ["\n## 预算界（沿用 dirTtru.budget_job 的设置：P1 收集者陷害、ρ̄=0.01、不开 R3；预算界本身与协议无关；B_rep = 0.10）\n",
              "| 证据 | 同伙份额最大 / 单表界（最大超界） | 诚实被降权重最大 | 同伙被降权重最大 |", "|---|---|---|---|"]
        for ev in ("failed", "at"):
            g = [r for r in bu if r["evidence"] == ev]
            if g:
                over = max(r["share_max"] - r["bound"] for r in g)
                L.append(f"| {'失败提议者（可被陷害）' if ev == 'failed' else 'AT（抗陷害）'} | "
                         f"{np.mean([r['share_max'] for r in g]):.4f} / {np.mean([r['bound'] for r in g]):.4f}（{over:+.5f}） | "
                         f"{fmt([r['honest_removed_max'] for r in g], 4)} | {fmt([r['colluder_removed_max'] for r in g], 4)} |")
    with open(os.path.join(OUT, "dirTtru_review.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    parts = ("frame", "silent", "chaos", "budget") if which == "all" else (which,)
    if which != "report":
        for p in parts:
            run(p)
    report()
