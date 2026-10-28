"""Experiments for the v0.12 scheme (信任2.0_方案重构说明 v0.12): formula A base weights
b = CapNorm(stake) (no license value), graded G1 punishment with the 10% cap on suspended base share,
and the AT exclusion doubling (off / on). Same populations as dirTtru (n = 31: 10 licensed, 12
uncertified, 9 small; cap 0.10, u_max 0.25); colluders = the nodes of lowest stake per base weight until
the target base share. Recommended protocol as in dirTtruReview: P2, AT share > 2/3, CUSUM q = 0.5,
rho_bar = 0.1, D = 500, weight cap 0.5; r_min 0.7, step 0.1, recovery 0.02 per epoch of 100 views,
B_rep = 0.10; NR with data; R3.

Parts:
  frame    colluders claim NR = 1 and withhold votes in honest views, plus late messages (eps); two
           network geographies. Honest AT convictions, honest cut, colluder share against beta0/(1-B_rep).
  silent   colluding leaders send nothing; doubling off / on.
  chaos    GST at view 3000 of 5000 (independent delays, region outages, adversarial scheduling) with the
           framing adversary; doubling off / on: honest exclusions after GST, post-GST QC and commit rates.
  budget   framable evidence (failed proposer, P1 collector framing, rho_bar 0.01, no R3) against the
           budget bound, and AT.
  g1live   greedy NR liars (liveness-class G1): graded punishment (L1 -> L3) against the old rule (z = 0
           and a permanent bar at the first proof).
  g1safe   safety-class G1 injected at the weight layer (the simulator has no forks) with the framing
           adversary on top: iso (random misconfigurations, 10% per epoch), repeat (one honest entity three
           times), decoy (colluders get themselves suspended one by one), bug (a client fault puts E2 on
           >= 40% of the base weight in one epoch), fork (culprits above 1/3 evicted after governance).
  deposit  static, 500 populations each of n = 31 and n = 100: minimum deposit to reach a base share
           above theta for deposits proportional to base weight, equal per entity, proportional to raw
           stake, and licensed only.
Environment: SIM_PROCS (default 8), SIM_SEEDS (default 50; chaos, g1live and g1safe use half).
Run from the repository root:  python -m sim2.experiments.dirTtruV12 [frame|silent|chaos|budget|g1live|g1safe|deposit|all|report]
Out: results/dirTtru_v12_<part>.csv and results/dirTtru_v12.md.
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
from sim2.experiments.dirTtruReview import NETS, ci, fmt, framing, poisson_upper, wilson_upper
from sim2.experiments.ttru_perf import PreGSTNet, adv_targets, perf
from sim2.net import NetConfig, Network
from sim2.punish import GradedPunishment

OUT = os.path.join(os.path.dirname(__file__), "..", "results")
PROCS = int(os.environ.get("SIM_PROCS", "8"))
SEEDS = int(os.environ.get("SIM_SEEDS", "50"))
N, NL, NU, NA = 31, 10, 12, 9
CAP, UMAX, B_REP, D, L_MAX = 0.10, 0.25, 0.10, 500, 0.10
VIEWS = 2000


def setup(seed):
    cls, s = ttru.population(NL, NU, NA, seed)
    return cls, s, ttru.base_weights(cls, s, 0.0, 0.0, CAP, UMAX)


def build(cls, s, base, double=False, graded=True, injected=(), forks=(), old_g1=False, rho_bar=0.1, evidence="at",
          recompute="all"):
    rule = S.CusumExclusion(q=0.5, evidence=evidence, rho_bar=rho_bar, D=D, cap=0.5, Wq=500, cap_weights=base,
                            double=double, g1=old_g1)
    pun = GradedPunishment(cls, s, CAP, UMAX, l_max=L_MAX, injected=injected, forks=forks,
                           recompute=recompute) if graded else None
    vw = ttru.TtruWeights(base, epoch=100, r_min=0.7, b_rep=B_REP, rule=rule, punish=pun, g1=old_g1)
    if graded:
        rule.bars = vw.bars
    return rule, vw


def config(seed, rule, vw, byz, adv, views, protocol="P2", **kw):
    opts = dict(at_share=2 / 3, nr_requires_data=True, vote_monotone=True)
    opts.update(kw)
    return RunConfig(n=N, views=views, seed=seed, protocol=protocol, leader_rule=rule,
                     byzantine=list(np.flatnonzero(byz)), adversary=adv, vote_weights=vw, **opts)


def tables(st, vw):
    return st.__dict__["_ttru_cache"][id(vw)]


def honest_conv(st, end):
    return [u for ev, node, u in st.rule_log if ev == "exclude" and st.honest[node] and u < end]


def common(st, vw, byz, base):
    c = tables(st, vw)
    sh = np.array([t[byz].sum() for t in c["tables"]])
    cut = max(float(x[~byz].sum()) for x in c.get("cuts", [np.zeros(N)]))
    b0 = float(base[byz].sum())
    return dict(beta=b0, bound=b0 / (1 - B_REP), honest_cut_max=cut, colluder_share_max=float(sh.max()),
                colluder_share_end=float(sh[-3:].mean()), colluder_share_min=float(sh.min()))


def frame_job(args):
    target, eps, net, seed = args
    cls, s, base = setup(seed)
    byz = cheapest_set(base, s, target, max_share=0.30)
    rule, vw = build(cls, s, base)
    cfg = config(seed, rule, vw, byz, framing(), VIEWS)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=N, seed=seed, eps_late=eps, **NETS[net])), st, 1, VIEWS)
    end = VIEWS - 10
    hl = st.honest[st.leaders[1:end]]
    acc = np.array([S.bad_fact(st, u, u + cfg.lag, "at") for u in range(1, end)])
    return dict(part="frame", target=target, eps=eps, net=net, seed=seed, honest_led=int(hl.sum()),
                acc_honest=float(acc[hl].mean()), honest_conv=len(honest_conv(st, end)), **common(st, vw, byz, base))


def silent_job(args):
    target, eps, double, seed = args
    cls, s, base = setup(seed)
    byz = cheapest_set(base, s, target, max_share=0.30)
    rule, vw = build(cls, s, base, double=double)
    cfg = config(seed, rule, vw, byz, A.SilentLeader(1.0), VIEWS)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=N, seed=seed, eps_late=eps, **NETS["base"])), st, 1, VIEWS)
    end = VIEWS - 10
    first = {}
    for ev, node, u in st.rule_log:
        if ev == "exclude" and st.byz[node] and node not in first:
            first[node] = sum(1 for y in range(1, u + 1) if st.leaders[y] == node)
    return dict(part="silent", target=target, eps=eps, double=int(double), seed=seed,
                byz_convicted=len(first) / int(byz.sum()),
                leads_to_conviction=float(np.mean(list(first.values()))) if first else float("nan"),
                byz_lead_late=float(np.mean(st.byz[st.leaders[VIEWS // 2:end]])),
                commit=perf(st, 100, end)["commit"], honest_conv=len(honest_conv(st, end)), **common(st, vw, byz, base))


def chaos_job(args):
    netmode, double, seed = args
    gst, views = 3000, 5000
    cls, s, base = setup(seed)
    byz = cheapest_set(base, s, 0.2)
    rule, vw = build(cls, s, base, double=double)
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
    conv = honest_conv(st, end)
    excl = np.zeros(N, bool)
    last, post_max = 0, 0.0
    for ev, node, u in sorted(st.rule_log, key=lambda x: x[2]):
        if ev not in ("exclude", "release") or not st.honest[node]:
            continue
        excl[node] = ev == "exclude"
        last = max(last, u)
        if u >= gst:
            post_max = max(post_max, float(base[excl].sum()))
    if excl.any():
        last = end
    hl_post = [u for u in range(gst, end) if st.honest[st.leaders[u]]]
    return dict(part="chaos", net=netmode, double=int(double), seed=seed, gst=gst,
                honest_conv_pre=sum(u < gst for u in conv), honest_conv_post=sum(u >= gst for u in conv),
                honest_acc_post=int(sum(S.bad_fact(st, u, u + cfg.lag, "at") for u in hl_post)),
                last_honest_excl=last, honest_excl_post_max=post_max,
                qc_post=float(np.mean(st.qc_exists[gst + D + 20:end])),
                commit_post=perf(st, gst + D + 20, end)["commit"], **common(st, vw, byz, base))


def budget_job(args):
    evidence, seed = args
    cls, s, base = setup(seed)
    byz = cheapest_set(base, s, 0.2)
    rule, vw = build(cls, s, base, rho_bar=0.01, evidence=evidence)
    views = 4000
    cfg = RunConfig(n=N, views=views, seed=seed, protocol="P1", leader_rule=rule, byzantine=list(np.flatnonzero(byz)),
                    adversary=A.CollectorFraming(), vote_weights=vw)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0)), st, 1, views)
    c = tables(st, vw)
    return dict(part="budget", evidence=evidence, seed=seed,
                colluder_cut_max=max(float(x[byz].sum()) for x in c["cuts"]), **common(st, vw, byz, base))


G1NETS = {"S": {}, "eps0.05": dict(eps_late=0.05), "async300": dict(async_views=300, async_p=0.5, async_extra_ms=3000.0)}


def g1live_job(args):
    greedy, net, mode, seed = args
    views = 3000
    cls, s, base = setup(seed)
    byz = cheapest_set(base, s, 0.2)
    rule, vw = build(cls, s, base, graded=mode == "graded", old_g1=mode == "old")
    cfg = config(seed, rule, vw, byz, A.LieNRVote(greedy=greedy), views, track_signed=True)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, **G1NETS[net])),
                          st, 1, views)
    end = views - 10
    vw(st, end)
    K = S.liars(st, end)
    hl = st.honest[st.leaders[1:end]]
    acc = np.array([S.bad_fact(st, u, u + cfg.lag, "at") for u in range(1, end)])
    row = dict(part="g1live", greedy=greedy, net=net, mode=mode, seed=seed, n_byz=int(byz.sum()),
               caught=int((K & st.byz).sum()), honest_caught=int((K & st.honest).sum()),
               byz_lead_late=float(np.mean(st.byz[st.leaders[views // 2:end]])),
               honest_accused=float(acc[hl].mean()), qc_rate=float(np.mean(st.qc_exists[100:end])),
               commit=perf(st, 100, end)["commit"], **common(st, vw, byz, base))
    if mode == "graded":
        p = vw.punisher(st)
        lv = {}
        for ev, i, k in p.log:
            if ev.startswith("L"):
                lv[i] = max(lv.get(i, 0), int(ev[1]))
        z = np.array([t[byz] == 0 for t in tables(st, vw)["tables"][1:]])
        row.update(max_level=max(lv.values()) if lv else 0, honest_punished=sum(1 for i in lv if st.honest[i]),
                   byz_suspended_frac=float(z.mean()), suspended_max=max(h[0] for h in p.history))
    return row


def g1safe_job(args):
    scen, seed = args
    views, gap = 4000, 100
    cls, s, base = setup(seed)
    byz = cheapest_set(base, s, 0.2)
    rng = np.random.default_rng([seed, 99])
    injected, forks = [], []
    hon = np.flatnonzero(~byz)
    if scen == "iso":
        for e in range(2, 36):
            if rng.random() < 0.10:
                injected.append((int(rng.integers(N)), e, e, False))
    elif scen in ("repeat", "repeat_nr"):
        i = int(rng.choice(hon))
        injected = [(i, 3, 3, False), (i, 8, 8, False), (i, 13, 13, False)]
    elif scen == "decoy":
        dec = [int(i) for i in np.flatnonzero(byz)[np.argsort(base[byz])]]
        acc, chosen = 0.0, []
        for i in dec:
            chosen.append(i)
            acc += base[i]
            if acc > L_MAX + 0.02:
                break
        injected = [(i, 3 + j, 3 + j, True) for j, i in enumerate(chosen)]
    elif scen == "bug":
        acc = 0.0
        for i in hon[np.argsort(base[hon])[::-1]]:
            if acc >= 0.40:
                break
            injected.append((int(i), 10, 10, False))
            acc += base[i]
    elif scen == "fork":
        cul = list(np.flatnonzero(byz))
        acc = float(base[byz].sum())
        for i in hon[np.argsort(s[hon] / base[hon])]:
            if acc > 0.36:
                break
            cul.append(int(i))
            acc += base[i]
        forks = [(cul, 10)]
    rule, vw = build(cls, s, base, injected=injected, forks=forks, recompute="fork" if scen == "repeat_nr" else "all")
    cfg = config(seed, rule, vw, byz, framing(), views)
    st = State(cfg)
    engine_event.simulate(cfg, Network(NetConfig(n=N, seed=seed, regions=3, jitter_max_ms=2.0, eps_late=0.05)),
                          st, 1, views)
    end = views - 10
    vw(st, end)
    p = vw.punisher(st)
    T = tables(st, vw)["tables"]
    unc = cls != "L"
    lv = {}
    for ev, i, k in p.log:
        if ev.startswith("L"):
            lv.setdefault(ev, set()).add(i)
    b0 = float(base[byz].sum())
    return dict(part="g1safe", scen=scen, seed=seed, beta=b0, bound1=b0 / (1 - B_REP), bound2=b0 / (1 - B_REP - L_MAX),
                injected_share=float(base[[x[0] for x in injected]].sum()) if injected else 0.0,
                suspended_max=max(h[0] for h in p.history), queue_max=max(h[1] for h in p.history),
                wait_max=p.max_wait, evicted=int(p.evicted.sum()), evicted_share=float(base[p.evicted].sum()),
                infeasible=int(p.infeasible), cap_used=float(p.cap_used), n_L2=len(lv.get("L2", ())), n_L3=len(lv.get("L3", ())),
                n_L4=len(lv.get("L4", ())), downgraded=sum(1 for ev, _, _ in p.log if ev == "downgrade"),
                honest_evicted=int((p.evicted & ~byz).sum()),
                colluder_share_max=float(max(t[byz].sum() for t in T)),
                colluder_share_after=float(np.mean([t[byz].sum() for t in T[15:]])),
                unc_share_max=float(max(t[unc].sum() for t in T)), entity_share_max=float(max(t.max() for t in T)),
                qc_pre=float(np.mean(st.qc_exists[100:1000])), qc_post=float(np.mean(st.qc_exists[1100:2500])),
                qc_all=float(np.mean(st.qc_exists[100:end])), commit=perf(st, 100, end)["commit"],
                honest_cut_max=max(float(x[~byz].sum()) for x in tables(st, vw)["cuts"]))


def min_deposit(w, d, theta, grid=4000):
    units = np.floor(w * grid).astype(int)
    T = int(units.sum())
    dp = np.full(T + 1, np.inf)
    dp[0] = 0.0
    for u, c in zip(units, d):
        if u <= 0:
            continue
        cand = np.full(T + 1, np.inf)
        cand[u:] = dp[:-u] + c
        dp = np.minimum(dp, cand)
    need = int(np.floor(theta * grid)) + 1
    return float(dp[need:].min())


def deposit_job(args):
    name, seed = args
    nl, nu, na, cap = (10, 12, 9, 0.10) if name == "n31" else (20, 50, 30, 0.05)
    cls, s = ttru.population(nl, nu, na, seed)
    b = ttru.base_weights(cls, s, 0.0, 0.0, cap, UMAX)
    lic = np.where(cls == "L", b, 0.0)
    alloc = dict(prop=b, equal=np.full(len(b), 1.0 / len(b)), stake=s / s.sum(), lic_only=lic / lic.sum())
    row = dict(part="deposit", pop=name, seed=seed, cap=cap)
    for th, tn in ((1 / 3, "t33"), (0.30, "t30"), ((1 - B_REP - L_MAX) / 3, "t27")):
        for a, d in alloc.items():
            row[f"{a}_{tn}"] = min_deposit(b, d, th)
    return row


def write(name, rows):
    with open(os.path.join(OUT, name), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=sorted({k for r in rows for k in r}))
        w.writeheader()
        w.writerows(rows)


def jobs_of(part):
    half = max(1, SEEDS // 2)
    if part == "frame":
        return frame_job, [(tg, e, nt, s) for tg in (0.2, 0.25) for e in (0.1, 0.2, 0.3) for nt in NETS for s in range(SEEDS)]
    if part == "silent":
        return silent_job, [(tg, e, d, s) for tg in (0.2, 0.25) for e in (0.0, 0.1) for d in (False, True) for s in range(SEEDS)]
    if part == "chaos":
        return chaos_job, [(nm, d, s) for nm in ("iid", "outage", "adv") for d in (False, True) for s in range(half)]
    if part == "budget":
        return budget_job, [(ev, s) for ev in ("failed", "at") for s in range(SEEDS)]
    if part == "g1live":
        return g1live_job, [(g, nt, m, s) for g in (0.5, 1.0) for nt in G1NETS for m in ("old", "graded") for s in range(half)]
    if part == "g1safe":
        return g1safe_job, [(sc, s) for sc in ("iso", "repeat", "repeat_nr", "decoy", "bug", "fork") for s in range(half)]
    if part == "g1safe_nr":
        return g1safe_job, [("repeat_nr", s) for s in range(half)]
    return deposit_job, [(nm, s) for nm in ("n31", "n100") for s in range(500)]


def run(part):
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    fn, jobs = jobs_of(part)
    with Pool(PROCS) as pool:
        rows = pool.map(fn, jobs, chunksize=1)
    write(f"dirTtru_v12_{part}.csv", rows)
    print(f"{part}: {len(rows)} runs, {time.time() - t0:.0f}s", flush=True)


def load(part):
    p = os.path.join(OUT, f"dirTtru_v12_{part}.csv")
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


def m(g, c, d=3):
    return f"{np.nanmean([r[c] for r in g]):.{d}f}"


def report():
    L = ["# 新方案（v0.12）的协议级仿真\n",
         "公式 A：基础权重 = CapNorm(质押)，不计牌照价值；分级处罚（L1–L4、同时暂停份额上限 10%、L4 经治理确认）；"
         "AT 排除期加倍分\"关\"与\"开\"。其余同推荐协议：P2；AT 份额 > 2/3、CUSUM q=0.5、ρ̄=0.1、D=500、排除上限按权重 0.5；"
         "r_min=0.7、步长 0.1、每纪元（100 视图）恢复 0.02、B_rep=0.10；NR 含块；R3。n=31（10 家持牌、12 家未认证、9 个小节点），"
         "cap=0.10、u_max=0.25。区间为对人群的自助法 95% 区间。\n"]
    fr = load("frame")
    if fr:
        L += ["## 陷害：同伙谎报 NR、在诚实视图扣票，叠加独立迟到\n",
              "| 同伙份额 | 网络 | ε | 诚实视图被 AT 指控的比例 | 诚实定罪 / 千个诚实领导视图（合并 Poisson 95% 上界） | "
              "出现诚实定罪的人群（上界） | 诚实被降权重最大 | 同伙份额最大 / 单表界（最大超界） |", "|---|---|---|---|---|---|---|---|"]
        for tg in (0.2, 0.25):
            for nt in NETS:
                for e in (0.1, 0.2, 0.3):
                    g = [r for r in fr if (r["target"], r["net"], r["eps"]) == (tg, nt, e)]
                    if not g:
                        continue
                    k = sum(r["honest_conv"] > 0 for r in g)
                    tc, tv = sum(r["honest_conv"] for r in g), sum(r["honest_led"] for r in g)
                    over = max(r["colluder_share_max"] - r["bound"] for r in g)
                    L.append(f"| {m(g, 'beta', 2)} | {nt} | {e} | {fmt([r['acc_honest'] for r in g])} | "
                             f"{1000 * tc / tv:.3f}（≤ {1000 * poisson_upper(int(tc)) / tv:.3f}） | {k}/{len(g)}（{wilson_upper(k, len(g)):.3f}） | "
                             f"{fmt([r['honest_cut_max'] for r in g])} | {m(g, 'colluder_share_max')} / {m(g, 'bound')}（{over:+.4f}） |")
        tot = sum(r["honest_conv"] for r in fr)
        tv = sum(r["honest_led"] for r in fr)
        L.append(f"\n合计 {len(fr)} 次运行、{int(tv)} 个诚实领导视图，诚实定罪 {int(tot)} 次（每千视图 95% 上界 "
                 f"{1000 * poisson_upper(int(tot)) / tv:.4f}）。")
    sl = load("silent")
    if sl:
        L += ["\n## 沉默领导者（AT 排除期加倍：关 / 开）\n",
              "| 同伙份额 | ε | 加倍 | 同伙被定罪比例 | 定罪前的领导次数 | 后半段同伙当领导者的比例 | 提交比例 | 诚实定罪 | 同伙份额：基础 → 期末 |",
              "|---|---|---|---|---|---|---|---|---|"]
        for tg in (0.2, 0.25):
            for e in (0.0, 0.1):
                for d in (0, 1):
                    g = [r for r in sl if (r["target"], r["eps"], r["double"]) == (tg, e, d)]
                    if g:
                        L.append(f"| {m(g, 'beta', 2)} | {e} | {'开' if d else '关'} | {fmt([r['byz_convicted'] for r in g])} | "
                                 f"{fmt([r['leads_to_conviction'] for r in g], 1)} | {fmt([r['byz_lead_late'] for r in g])} | "
                                 f"{fmt([r['commit'] for r in g])} | {int(sum(r['honest_conv'] for r in g))} | "
                                 f"{m(g, 'beta')} → {m(g, 'colluder_share_end')} |")
    ch = load("chaos")
    if ch:
        L += ["\n## GST 之前的混乱期（GST = 视图 3000，共 5000 视图；同伙陷害；加倍：关 / 开）\n",
              "| 混乱期网络 | 加倍 | 诚实定罪：GST 前 / 后（总数） | GST 后诚实领导视图的 AT 指控 | 诚实被降权重最大 | "
              "同伙份额最大 / 单表界（最大超界） | 诚实被排除的最后视图（最大） | GST 后同时被排除的诚实权重（最大） | GST+D 后 QC 率 | GST+D 后提交比例 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for nm in ("iid", "outage", "adv"):
            for d in (0, 1):
                g = [r for r in ch if (r["net"], r["double"]) == (nm, d)]
                if g:
                    over = max(r["colluder_share_max"] - r["bound"] for r in g)
                    L.append(f"| {nm} | {'开' if d else '关'} | {int(sum(r['honest_conv_pre'] for r in g))} / {int(sum(r['honest_conv_post'] for r in g))} | "
                             f"{int(sum(r['honest_acc_post'] for r in g))} | {fmt([r['honest_cut_max'] for r in g])}（最大 {max(r['honest_cut_max'] for r in g):.3f}） | "
                             f"{m(g, 'colluder_share_max')} / {m(g, 'bound')}（{over:+.4f}） | {int(max(r['last_honest_excl'] for r in g))} | "
                             f"{max(r['honest_excl_post_max'] for r in g):.3f} | {fmt([r['qc_post'] for r in g])} | {fmt([r['commit_post'] for r in g])} |")
    bu = load("budget")
    if bu:
        L += ["\n## 预算界（P1 收集者陷害、ρ̄=0.01、不开 R3；B_rep = 0.10）\n",
              "| 证据 | 同伙份额最大 / 单表界（最大超界） | 诚实被降权重最大 | 同伙被降权重最大 |", "|---|---|---|---|"]
        for ev in ("failed", "at"):
            g = [r for r in bu if r["evidence"] == ev]
            if g:
                over = max(r["colluder_share_max"] - r["bound"] for r in g)
                L.append(f"| {'失败提议者（可被陷害）' if ev == 'failed' else 'AT（抗陷害）'} | {m(g, 'colluder_share_max', 4)} / "
                         f"{m(g, 'bound', 4)}（{over:+.5f}） | {fmt([r['honest_cut_max'] for r in g], 4)} | {fmt([r['colluder_cut_max'] for r in g], 4)} |")
    gl = load("g1live")
    if gl:
        L += ["\n## 活性类 G1（贪心 NR 说谎者）：分级处罚与旧规则（首次证实即清零）对比\n",
              "| 贪心比例 | 网络 | 规则 | 被证实的同伙 / 同伙数 | 被证实的诚实节点 | 同伙份额：基础 → 期末（最低） | 同伙被暂停的纪元比例 | "
              "最高级别 | 后半段同伙当领导者的比例 | 诚实视图被 AT 指控的比例 | QC 率 | 提交比例 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for gr in (0.5, 1.0):
            for nt in G1NETS:
                for mo in ("old", "graded"):
                    g = [r for r in gl if (r["greedy"], r["net"], r["mode"]) == (gr, nt, mo)]
                    if not g:
                        continue
                    gd = mo == "graded"
                    L.append(f"| {gr} | {nt} | {'分级' if gd else '旧规则'} | {m(g, 'caught', 1)} / {m(g, 'n_byz', 1)} | "
                             f"{int(sum(r['honest_caught'] for r in g))} | {m(g, 'beta')} → {m(g, 'colluder_share_end')}（{m(g, 'colluder_share_min')}） | "
                             f"{m(g, 'byz_suspended_frac') if gd else '—'} | {('L%d' % max(r['max_level'] for r in g)) if gd else '—'} | "
                             f"{m(g, 'byz_lead_late')} | {m(g, 'honest_accused', 4)} | {m(g, 'qc_rate')} | {m(g, 'commit')} |")
    gs = load("g1safe")
    if gs:
        names = dict(iso="孤立失误（每纪元 10%）", repeat="同一实体三次失误（逐出后重算上限）",
                     repeat_nr="同一实体三次失误（逐出后不重算）", decoy="诱饵暂停", bug="客户端缺陷（≥40% 权重）",
                     fork="分叉（罪犯 > 1/3）")
        extra = [r for r in load("g1safe_nr") if not any(x["scen"] == "repeat_nr" for x in gs)]
        gs = gs + extra
        L += ["\n## 注入安全类 G1（同伙同时陷害）\n",
              "| 场景 | 被注入份额 | 同时暂停份额最大 | 排队最长（纪元） | 定级 L2 / L3 / L4（实体数，均值） | 治理降级 | 被逐出（诚实） | "
              "CapNorm 不可行 | 同伙份额最大 / 界一 / 界二 | 未认证类份额最大 | 单实体份额最大 | QC 率：事件前 / 事件后 | 提交比例 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for sc in ("iso", "repeat", "repeat_nr", "decoy", "bug", "fork"):
            g = [r for r in gs if r["scen"] == sc]
            if not g:
                continue
            L.append(f"| {names[sc]} | {m(g, 'injected_share')} | {max(r['suspended_max'] for r in g):.3f} | {int(max(r['wait_max'] for r in g))} | "
                     f"{m(g, 'n_L2', 1)} / {m(g, 'n_L3', 1)} / {m(g, 'n_L4', 1)} | {m(g, 'downgraded', 1)} | "
                     f"{m(g, 'evicted', 1)}（{int(sum(r['honest_evicted'] for r in g))}） | {int(sum(r['infeasible'] for r in g))}/{len(g)} | "
                     f"{max(r['colluder_share_max'] for r in g):.3f} / {m(g, 'bound1')} / {m(g, 'bound2')}（逐次比较超界二最大 "
                     f"{max(r['colluder_share_max'] - r['bound2'] for r in g):+.4f}） | {max(r['unc_share_max'] for r in g):.3f} | "
                     f"{max(r['entity_share_max'] for r in g):.3f} | {m(g, 'qc_pre')} / {m(g, 'qc_post')} | {m(g, 'commit')} |")
        L.append("\n界一 = β0/(1−B_rep)，界二 = β0/(1−B_rep−L_max)（被暂停的是诚实权重时）。")
    de = load("deposit")
    if de:
        L += ["\n## 保证金分配（静态，每种规模 500 个人群，基础权重按公式 A）\n",
              "凑齐基础份额 > θ 所需的最低保证金（占全网保证金，中位数 [最小, 最大]）。引理：按权重成比例时 > θ；其他分配下 ≤ θ + cap。\n",
              "| 规模 | θ | 按权重成比例 | 按家平摊 | 按原始质押 | 只有持牌机构交 | 其他分配低于成比例的人群 |", "|---|---|---|---|---|---|---|"]
        q = lambda xs: f"{np.median(xs):.3f} [{np.min(xs):.3f}, {np.max(xs):.3f}]"  # noqa: E731
        for nm in ("n31", "n100"):
            g = [r for r in de if r["pop"] == nm]
            for tn, th in (("t33", 1 / 3), ("t30", 0.30), ("t27", (1 - B_REP - L_MAX) / 3)):
                cols = {a: [r[f"{a}_{tn}"] for r in g] for a in ("prop", "equal", "stake", "lic_only")}
                worse = sum(any(r[f"{a}_{tn}"] < r[f"prop_{tn}"] - 1e-9 for a in ("equal", "stake", "lic_only")) for r in g)
                L.append(f"| {nm} | {th:.3f} | {q(cols['prop'])} | {q(cols['equal'])} | {q(cols['stake'])} | {q(cols['lic_only'])} | {worse}/{len(g)} |")
    with open(os.path.join(OUT, "dirTtru_v12.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    parts = ("deposit", "g1safe", "g1live", "budget", "silent", "frame", "chaos") if which == "all" else (which,)
    if which != "report":
        for p in parts:
            run(p)
    report()
