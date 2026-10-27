"""T_tru weighted voting v0.2: cost of attack, concentration, and the reputation budget (信任2.0).

Abstract population model only: no consensus protocol is run and nothing touches a real system.
v0.2 follows review/信任2.0_重构说明_审查.md: per-class capping (the uncertified-class cap now holds
exactly, with feasibility checks), exact minimum bribery cost (knapsack DP), the license value K as
the first sensitivity axis, a licensed-only consortium (PoA, 1:1) baseline, a corrected Sybil
search, deterministic seeds. v0.1: ttru_sim_v01.py, results_v01/.

Population ("mixed", synthetic): 100 nodes
  L  licensed institutions (20)   larger stakes, each holds a license worth K (stake units)
  U  uncertified companies (50)
  A  small / anonymous nodes (30) small stakes
Stakes: Pareto(alpha) x class base, normalized to total 1. "consortium" = the 20 L nodes only.

Weighting schemes (voting shares, sum 1):
  one_node    1:1 voting
  stake       stake-proportional
  stake_tau   stake^tau, per-node cap (water-filling)
  ttru        base b_i = c_i * stake^tau; the uncertified class (U + A) gets min(its natural share,
              u_max) of the total, the licensed class the rest; inside each class the per-node cap
              holds (water-filling). Feasibility: n_L * cap >= 1 - u_max (else ValueError).
              Reputation (part 3): T_i = b_i * r_i * z_i, removed weight not redistributed, total
              removal at most b_rep.

Part 1 (static, r = 1): concentration (Nakamoto coefficient at 1/3, max share) and the minimum cost
of controlling a share theta of the voting weight by corrupting existing nodes. Node i costs what it
loses when proven guilty: its stake (slashed) + K if licensed. Exact minimum over node sets (0/1
knapsack on a 1/20000 weight grid). theta = 1/3, and 0.30 = (1 - b_rep)/3 (the threshold that holds
when soft evidence may be framed). Swept over K.
Part 2 (open admission only): cost of reaching 1/3 with new identities; uncertified identities cost
id_cost each, licensed ones K + id_cost; stake bought at price 1.
Part 3 (reputation): v0.1 (reputation inside the cap, redistributed) vs v0.2 (after the cap, budget).
Part 4: sensitivity of ttru to cap, u_max, tau (feasibility checked).
Run:  python ttru/ttru_sim.py
"""
import csv
import os
from dataclasses import dataclass, replace

import numpy as np

OUT = os.path.join(os.path.dirname(__file__), "results")
GRID = 20000


@dataclass
class Pop:
    n_L: int = 20
    n_U: int = 50
    n_A: int = 30
    alpha: float = 1.16
    base_L: float = 3.0
    base_U: float = 1.0
    base_A: float = 0.2
    license_K: float = 0.02               # value of one license, in stake units (total stake = 1)
    id_cost: float = 1e-4                 # cost of registering one uncertified identity


@dataclass
class Scheme:
    tau: float = 0.7
    cap: float = 0.05
    c_unc: float = 0.5
    u_max: float = 0.25
    b_rep: float = 0.10


def population(p: Pop, seed: int, consortium: bool = False):
    rng = np.random.default_rng([seed, 1])
    cls = np.array(["L"] * p.n_L + ["U"] * p.n_U + ["A"] * p.n_A)
    base = np.where(cls == "L", p.base_L, np.where(cls == "U", p.base_U, p.base_A))
    s = base * (1.0 + rng.pareto(p.alpha, cls.size))
    s = s / s.sum()
    if consortium:
        keep = cls == "L"
        return cls[keep], s[keep] / s[keep].sum()
    return cls, s


def cap_normalize(w, cap, total=1.0):
    """Shares proportional to w summing to `total`, each at most cap (water-filling)."""
    w = np.asarray(w, float)
    if cap * len(w) < total - 1e-12:
        raise ValueError(f"infeasible cap: {len(w)} x {cap} < {total}")
    fixed = np.zeros(len(w), bool)
    out = w / w.sum() * total
    for _ in range(len(w)):
        free = ~fixed
        out = np.where(fixed, cap, w * (total - cap * fixed.sum()) / w[free].sum())
        over = (out > cap + 1e-12) & free
        if not over.any():
            return out
        fixed |= over
    return np.where(fixed, cap, out)


def weights(name, cls, s, sc: Scheme, r=None, K=0.0):
    n = len(s)
    if name == "one_node":
        return np.full(n, 1.0 / n)
    if name == "stake":
        return s / s.sum()
    if name == "stake_tau":
        return cap_normalize(s ** sc.tau, sc.cap)
    if name == "ttru_value":                              # base weight = forfeitable value (stake + license)
        b = s + np.where(cls == "L", K, 0.0)
    else:
        c = np.where(cls == "L", 1.0, sc.c_unc)
        b = c * s ** sc.tau * (1.0 if r is None else r)   # r given: v0.1 (reputation inside the caps)
    unc = cls != "L"
    if not unc.any():
        return cap_normalize(b, sc.cap)
    U = min(b[unc].sum() / b.sum(), sc.u_max)
    w = np.zeros(n)
    w[~unc] = cap_normalize(b[~unc], sc.cap, 1.0 - U)
    w[unc] = cap_normalize(b[unc], sc.cap, U)
    assert w[unc].sum() <= sc.u_max + 1e-9 and w.max() <= sc.cap + 1e-9
    return w


def nakamoto(w, theta=1 / 3):
    return int(np.searchsorted(np.cumsum(np.sort(w)[::-1]), theta, side="right") + 1)


def bribe_exact(w, cost, theta):
    """Minimum total cost of a node set with weight >= theta (0/1 knapsack, weights on a 1/GRID
    grid rounded up, so the returned cost is a lower bound up to one grid step per node)."""
    T = int(np.ceil(theta * GRID))
    units = np.minimum(np.ceil(w * GRID).astype(int), T)
    dp = np.full(T + 1, np.inf)
    dp[0] = 0.0
    idx = np.arange(T + 1)
    for u, c in zip(units, cost):
        if u <= 0:
            continue
        new = dp.copy()
        np.minimum.at(new, np.minimum(idx + u, T), dp + c)
        dp = new
    return float(dp[T])


def ttru_v2(base, r, z, b_rep):
    """T_i = b_i r_i z_i, removed weight not redistributed, total removal at most b_rep; shares."""
    cut = base * (1.0 - r)
    if cut.sum() > b_rep:
        cut *= b_rep / cut.sum()
    t = (base - cut) * z
    return t / t.sum()


def part1(p: Pop, sc: Scheme, Ks=(0.0, 0.01, 0.02, 0.05, 0.10), seeds=20):
    rows = []
    for K in Ks:
        for seed in range(seeds):
            for pop in ("mixed", "consortium"):
                cls, s = population(p, seed, consortium=(pop == "consortium"))
                cost = s + np.where(cls == "L", K, 0.0)
                schemes = ("one_node", "stake", "stake_tau", "ttru", "ttru_value") if pop == "mixed" else ("one_node", "ttru")
                for name in schemes:
                    w = weights(name, cls, s, sc, K=K)
                    rows.append(dict(K=K, seed=seed, population=pop, scheme=name, nakamoto=nakamoto(w),
                                     max_share=float(w.max()), uncert_share=float(w[cls != "L"].sum()),
                                     bribe_33=bribe_exact(w, cost, 1 / 3), bribe_30=bribe_exact(w, cost, 0.30)))
    return rows


def sybil_cost(name, cls, s, sc: Scheme, p: Pop, theta=1 / 3):
    """Open admission: cheapest new-identity attack reaching theta (grid search; licensed identities
    each get stake S_L, uncertified identities share S_U)."""
    n = len(s)
    if name == "one_node":
        return int(np.ceil(theta * n / (1 - theta))) * p.id_cost
    if name == "stake":
        return theta / (1 - theta)
    best = np.inf
    SL = np.geomspace(1e-3, 1.0, 25)
    SU = np.concatenate([[0.0], np.geomspace(1e-3, 3.0, 20)])
    ks = (10, 100, 1000, 3000)
    ms = (0,) if name == "stake_tau" else tuple(range(0, 31))
    for m in ms:
        for k in ks:
            for su in SU:
                for sl in (SL if m else (0.0,)):
                    if su == 0.0 and m == 0:
                        continue
                    cls2 = np.concatenate([cls, np.array(["L"] * m + ["U"] * k)])
                    s2 = np.concatenate([s, np.full(m, sl), np.full(k, max(su, 1e-9) / k)])
                    try:
                        w = weights(name, cls2, s2, sc)
                    except ValueError:
                        continue
                    if w[n:].sum() >= theta:
                        best = min(best, m * (p.license_K + sl) + su + (m + k) * p.id_cost)
                        break
    return best


def part3(p: Pop, sc: Scheme, seed, formula, evidence, adversary, beta0=0.25, epochs=300, r_min=0.7,
          kappa=1.0, p_g2=0.2, step=0.1, recover=0.01):
    cls, s = population(p, seed)
    base = weights("ttru", cls, s, sc)
    cost = s + np.where(cls == "L", p.license_K, 0.0)
    byz = np.zeros(len(s), bool)
    acc = 0.0
    for i in np.argsort(cost / base):        # the adversary corrupts the cheapest weight first
        if acc >= beta0:
            break
        byz[i] = True
        acc += base[i]
    code = {"framable": 1, "resistant": 2}[evidence] * 10 + {"frame_only": 1, "misbehave_soft": 2}[adversary]
    rng = np.random.default_rng([seed, 3, code, 0 if formula == "v1" else 1])
    r = np.ones(len(s))
    z = np.ones(len(s))
    traj = []
    for _ in range(epochs):
        if formula == "v1":                   # reputation inside the caps, removed weight redistributed
            w = weights("ttru", cls, s, sc, r)
        else:
            w = ttru_v2(base, r, z, sc.b_rep)
        beta = float(w[byz].sum())
        traj.append(beta)
        bad = np.zeros(len(s), bool)
        if evidence == "framable":
            bad |= (~byz) & (rng.random(len(s)) < kappa * beta)
        if adversary == "misbehave_soft":
            bad |= byz & (rng.random(len(s)) < p_g2)
        r = np.where(bad, np.maximum(r_min, r - step), np.minimum(1.0, r + recover))
    return np.array(traj)


def write(name, rows):
    with open(os.path.join(OUT, name), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main():
    os.makedirs(OUT, exist_ok=True)
    p, sc = Pop(), Scheme()
    rows = part1(p, sc)
    write("part1_static.csv", rows)
    m = lambda K, pop, name, c: float(np.mean([r[c] for r in rows if (r["K"], r["population"], r["scheme"]) == (K, pop, name)]))
    names = [("mixed", "one_node", "混合人群 · 1:1 投票"), ("mixed", "stake", "混合人群 · 纯质押"),
             ("mixed", "stake_tau", "混合人群 · 质押^τ+上限"), ("mixed", "ttru", "混合人群 · T_tru"),
             ("mixed", "ttru_value", "混合人群 · T_tru（基础权重=可没收价值）"),
             ("consortium", "one_node", "纯持牌联盟 · 1:1（PoA）"), ("consortium", "ttru", "纯持牌联盟 · T_tru")]
    print(f"## 第一部分：控制 1/3 投票权的最低收买成本（精确，20 个人群均值；全网质押 = 1）\n")
    print(f"参数：τ={sc.tau}，单节点上限 {sc.cap:.0%}，未认证类上限 {sc.u_max:.0%}，B_rep={sc.b_rep:.0%}\n")
    Ks = sorted({r["K"] for r in rows})
    print("| 场景 · 加权方式 | " + " | ".join(f"K={K}" for K in Ks) + " | Nakamoto | 最大份额 | 未认证类份额 |")
    print("|---|" + "---|" * len(Ks) + "---|---|---|")
    for pop, name, label in names:
        cells = [f"{m(K, pop, name, 'bribe_33'):.3f}" for K in Ks]
        print(f"| {label} | " + " | ".join(cells) + f" | {m(Ks[0], pop, name, 'nakamoto'):.1f} | "
              f"{m(Ks[0], pop, name, 'max_share'):.3f} | {m(Ks[0], pop, name, 'uncert_share'):.2f} |")
    print("\n相对纯质押（混合人群，门槛 1/3 / 0.30）：")
    for K in Ks:
        print(f"- K={K}: T_tru {m(K, 'mixed', 'ttru', 'bribe_33') / m(K, 'mixed', 'stake', 'bribe_33'):.2f}× / "
              f"{m(K, 'mixed', 'ttru', 'bribe_30') / m(K, 'mixed', 'stake', 'bribe_30'):.2f}×；"
              f"相对 1:1 {m(K, 'mixed', 'ttru', 'bribe_33') / m(K, 'mixed', 'one_node', 'bribe_33'):.1f}×；"
              f"T_tru 门槛 0.30 时 {m(K, 'mixed', 'ttru', 'bribe_30'):.3f}")

    print("\n## 第二部分：开放准入时注册新身份达到 1/3 的成本（K=0.02，前 3 个人群）\n")
    print("| 加权方式 | 成本 |")
    print("|---|---|")
    syb = []
    for name in ("one_node", "stake", "stake_tau", "ttru"):
        vals = [sybil_cost(name, *population(p, seed), sc, p) for seed in range(3)]
        syb.append(dict(scheme=name, sybil=float(np.mean(vals))))
        print(f"| {name} | {np.mean(vals):.3f} |")
    write("part2_sybil.csv", syb)

    print("\n## 第三部分：信誉放在上限之内（v0.1）还是之后加预算（v0.2）\n")
    print(f"r_min=0.7，B_rep={sc.b_rep:.0%}，300 个纪元，10 个人群\n")
    print("| 公式 | 证据 | 对手 | 初始 | 末段 | 最高 |")
    print("|---|---|---|---|---|---|")
    out3 = []
    for formula in ("v1", "v2"):
        for ev in ("framable", "resistant"):
            for adv in ("frame_only", "misbehave_soft"):
                T = np.mean([part3(p, sc, k, formula, ev, adv) for k in range(10)], axis=0)
                out3.append(dict(formula=formula, evidence=ev, adversary=adv, start=float(T[0]),
                                 end=float(T[-50:].mean()), peak=float(T.max())))
                print(f"| {formula} | {ev} | {adv} | {T[0]:.3f} | {T[-50:].mean():.3f} | {T.max():.3f} |")
    write("part3_formula.csv", out3)

    print("\n## 第四部分：T_tru 参数敏感性（K=0.02；不可行的组合标出）\n")
    print("| 参数 | 取值 | Nakamoto | 最大份额 | 未认证类份额 | 收买成本（1/3） |")
    print("|---|---|---|---|---|---|")
    out4 = []
    for label, field, vals in (("单节点上限", "cap", (0.03, 0.04, 0.05, 0.08)), ("未认证类上限", "u_max", (0.15, 0.25, 0.30)),
                               ("τ", "tau", (0.5, 0.7, 1.0))):
        for val in vals:
            sc2 = replace(sc, **{field: val})
            try:
                res = []
                for seed in range(10):
                    cls, s = population(p, seed)
                    w = weights("ttru", cls, s, sc2)
                    res.append((nakamoto(w), w.max(), w[cls != "L"].sum(),
                                bribe_exact(w, s + np.where(cls == "L", p.license_K, 0.0), 1 / 3)))
                a = np.mean(res, axis=0)
                out4.append(dict(param=field, value=val, nakamoto=a[0], max_share=a[1], uncert=a[2], bribe=a[3]))
                print(f"| {label} | {val} | {a[0]:.1f} | {a[1]:.3f} | {a[2]:.2f} | {a[3]:.3f} |")
            except ValueError as e:
                print(f"| {label} | {val} | 不可行：{e} | | | |")
    write("part4_sweep.csv", out4)
    figures(rows, sc)


def figures(rows, sc):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    f = "/System/Library/Fonts/STHeiti Medium.ttc"
    if os.path.exists(f):
        font_manager.fontManager.addfont(f)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
    plt.rcParams["axes.unicode_minus"] = False
    Ks = sorted({r["K"] for r in rows})
    fig, ax = plt.subplots(1, 2, figsize=(10.5, 3.8))
    for pop, name, label, st in (("mixed", "one_node", "混合 · 1:1", ":"), ("mixed", "stake", "混合 · 纯质押", "--"),
                                 ("mixed", "ttru", "混合 · 认证系数×质押^τ", "-"), ("mixed", "ttru_value", "混合 · T_tru（权重=可没收价值）", "-"),
                                 ("consortium", "one_node", "纯持牌 · 1:1", "-.")):
        ys = [np.mean([r["bribe_33"] for r in rows if (r["K"], r["population"], r["scheme"]) == (K, pop, name)]) for K in Ks]
        ax[0].plot(Ks, ys, st, marker="o", label=label)
    ax[0].set_xlabel("单张牌照价值 K（全网质押 = 1）")
    ax[0].set_ylabel("控制 1/3 投票权的最低收买成本")
    ax[0].set_title("作恶成本随牌照价值的变化")
    ax[0].legend(fontsize=8)
    br = np.linspace(0.0, 0.4, 81)
    for b0 in (0.20, 0.25, 0.30):
        ax[1].plot(br, b0 / (1 - br), label=f"β0 = {b0:.2f}")
    ax[1].axhline(1 / 3, color="k", ls="--", lw=1)
    ax[1].text(0.005, 0.34, "安全界 1/3", fontsize=8)
    ax[1].set_xlabel("信誉预算 B_rep")
    ax[1].set_ylabel("最坏情况下拜占庭投票份额")
    ax[1].set_title("信誉预算与安全")
    ax[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_cost_and_budget.png"), dpi=160)


if __name__ == "__main__":
    main()
