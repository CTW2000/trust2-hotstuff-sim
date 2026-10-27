"""Finite-memory correction D4-W (mean-field in n; see T3dyn §7.3 for the conditions).

Each node's rate estimate is r_hat = F / O with per-opportunity forgetting keep = 1 - 1/W.
In opportunity time r_hat is a fixed weighted sum of i.i.d. Bernoulli(r) inputs, because
forgetting happens only on the node's own opportunities. In slot time each opportunity lasts
1/G(r_hat), so the slot-time average weight is the HARMONIC mean
    G_time(r) = 1 / E[1/G(r_hat)].
The share map is Phi_W(lambda) = beta0 G_time(rho_nat) / (beta0 G_time(rho_nat) + (1-beta0) G_time(rho(lambda))).

Numerics (v2, after the independent review; v1 kept as d4_finite_memory_v1.py):
  * exponential profile: E[exp(+eta r_hat)] is computed EXACTLY as a product over the weights;
  * threshold profile: q_L(r) = P(r_hat >= theta) is computed by importance sampling with the
    Bernoulli rate tilted to max(r, theta); the relative standard error is reported.
"""
import math

import numpy as np

from d4_sim import KAPPA, RHO_NAT, mean_field_exp

LAM_DAGGER = (0.5 - RHO_NAT) / ((1 - RHO_NAT) * KAPPA)


def weights(W, horizon_factor=10):
    keep = 1.0 - 1.0 / W
    H = int(horizon_factor * W)  # keep^H ~ e^-10, negligible tail
    w = keep ** np.arange(H)
    return w / w.sum()  # r_hat = sum_k w_k x_k


def estimator_sigma(r, W):
    w = weights(W)
    return math.sqrt(r * (1 - r) * float((w ** 2).sum()))


# ---------- exponential profile: exact ----------
def G_time_exp(r, W, s):
    eta = s / ((1 - RHO_NAT) * KAPPA)
    w = weights(W)
    log_e = float(np.log1p(r * np.expm1(eta * w)).sum())  # log E[exp(eta r_hat)]
    return math.exp(eta * RHO_NAT - log_e)  # 1 / E[exp(eta (r_hat - rho_nat))]


# ---------- threshold profile: importance sampling ----------
_RNG = np.random.default_rng(2026)
_qcache = {}


def _cumulant(t, r, w):
    """Lambda(t) = log E[exp(t r_hat)] and its derivative, for r_hat = sum w_k Bern(r)."""
    e = np.exp(t * w)
    denom = 1 - r + r * e
    lam = float(np.log(denom).sum())
    deriv = float((w * r * e / denom).sum())
    return lam, deriv


def tail_prob(r, W, theta, samples=20000, chunk=2000):
    """P(r_hat >= theta) for true rate r; returns (estimate, relative standard error).

    Exponential tilting of the weighted sum: each input k is tilted to
    r_k = r e^{t w_k} / (1 - r + r e^{t w_k}) with t chosen so that E_t[r_hat] = theta.
    The likelihood ratio exp(Lambda(t) - t r_hat) is then bounded on {r_hat >= theta},
    which keeps the variance small (v1 tilted every input by the same rate and had ~45% error).
    """
    key = (round(r, 6), W, theta)
    if key in _qcache:
        return _qcache[key]
    w = weights(W)
    H = len(w)
    t = 0.0
    if r < theta:
        lo, hi = 0.0, 1.0
        while _cumulant(hi, r, w)[1] < theta:
            hi *= 2
        for _ in range(80):
            mid = (lo + hi) / 2
            if _cumulant(mid, r, w)[1] < theta:
                lo = mid
            else:
                hi = mid
        t = (lo + hi) / 2
    lam, _ = _cumulant(t, r, w)
    e = np.exp(t * w)
    rk = r * e / (1 - r + r * e)
    vals = []
    for _ in range(samples // chunk):
        x = _RNG.random((chunk, H)) < rk
        rh = x.astype(np.float64) @ w
        vals.append(np.where(rh >= theta, np.exp(lam - t * rh), 0.0))
    v = np.concatenate(vals)
    est = float(v.mean())
    rse = float(v.std() / math.sqrt(len(v)) / est) if est > 0 else float("inf")
    _qcache[key] = (est, rse)
    return est, rse


def self_test():
    """Compare tilted IS with plain Monte Carlo where the tail is not too small."""
    for r, W, theta in [(0.05, 50, 0.1), (0.06, 200, 0.1)]:
        est, rse = tail_prob(r, W, theta)
        w = weights(W)
        hits, total = 0, 0
        for _ in range(50):
            x = _RNG.random((4000, len(w))) < r
            hits += int(((x.astype(np.float64) @ w) >= theta).sum())
            total += 4000
        print(f"self-test r={r} W={W}: IS {est:.3e} (rse {rse:.1%}) vs plain MC {hits / total:.3e} (n={total})")


class ThresholdProfile:
    """G_time on a rate grid with log-linear interpolation of the tail probability."""

    def __init__(self, W, theta, r_max=0.4, step=0.0025, K=1000.0):
        self.W, self.theta, self.K = W, theta, K
        self.grid = np.unique(np.concatenate([[RHO_NAT], np.arange(step, r_max + 1e-12, step)]))
        q = np.array([tail_prob(r, W, theta)[0] for r in self.grid])
        self.logq = np.log(np.maximum(q, 1e-300))

    def q(self, r):
        return float(np.exp(np.interp(r, self.grid, self.logq)))

    def G(self, r):
        return self.K / (1.0 + (self.K - 1.0) * self.q(r))


def fixed_point(beta0, G, iters=2000, tol=1e-9):
    lam = beta0
    g_b = G(RHO_NAT)
    for _ in range(iters):
        rho_h = RHO_NAT + (1 - RHO_NAT) * KAPPA * lam
        new = beta0 * g_b / (beta0 * g_b + (1 - beta0) * G(rho_h))
        if abs(new - lam) < tol:
            break
        lam = new
    return lam


def collapse_point(G, lo=0.001, hi=0.33, step=0.0005, level=LAM_DAGGER):
    """Smallest beta0 on a fine grid whose fixed point reaches `level` (lambda dagger)."""
    b = lo
    while b <= hi:
        if fixed_point(b, G) >= level:
            return b
        b += step
    return float("nan")


def main():
    lines = ["## D4-W 有限记忆修正（v2：重要性抽样 / 精确乘积）\n\n",
             "崩塌点定义为平均场不动点首次达到 λ†（q=0.5 时为 0.495）的 β0（网格 0.0005）。\n\n",
             "| θ | W | 崩塌点 β0 | 该点诚实失败率 ρ | 估计标准差 σ_W | 余量 z=(θ−ρ)/σ_W | 该点 q_L 相对误差 |\n",
             "|---|---|---|---|---|---|---|\n"]
    for theta, W in [(0.1, 50), (0.1, 200), (0.1, 800), (0.2, 200)]:
        prof = ThresholdProfile(W, theta)
        bc = collapse_point(prof.G)
        rho = RHO_NAT + (1 - RHO_NAT) * KAPPA * bc
        sig = estimator_sigma(rho, W)
        _, rse = tail_prob(rho, W, theta)
        lines.append(f"| {theta} | {W} | {bc:.4f} | {rho:.4f} | {sig:.4f} | {(theta - rho) / sig:.2f} | {rse:.1%} |\n")
        print(lines[-1], end="", flush=True)
    lines.append("\n## 指数剖面（W=200）：s_crit（λ* 首次达到 λ†，网格 0.01）\n\n"
                 "| β0 | 平均场（W=∞） | D4-W（精确） |\n|---|---|---|\n")
    for beta0 in [0.1, 0.2, 0.3]:
        s_mf = s_w = float("nan")
        for i in range(0, 801):
            s = i / 100
            if math.isnan(s_mf) and mean_field_exp(beta0, s) >= LAM_DAGGER:
                s_mf = s
            if math.isnan(s_w) and fixed_point(beta0, lambda r: G_time_exp(r, 200, s)) >= LAM_DAGGER:
                s_w = s
            if not (math.isnan(s_mf) or math.isnan(s_w)):
                break
        lines.append(f"| {beta0} | {s_mf:.2f} | {s_w:.2f} |\n")
        print(lines[-1], end="", flush=True)
    with open("figures/finite_memory_tables.md", "w") as fp:
        fp.writelines(lines)


if __name__ == "__main__":
    main()
