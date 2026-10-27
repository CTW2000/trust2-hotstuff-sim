"""Simulation check of Theorem D4 (T3-dyn): Byzantine role share under graded reputation.

Model (matches T3dyn_动态陷害率前沿.md, section 1 and Theorem D4):
  * n equal-weight validators; the first f0 = floor(beta0 * n + 1/2) are the colluders B0.
    All outputs record the ACTUAL colluder share f0/n (column `beta0`), not the nominal value.
  * Each slot: leader L ~ p_t and framing-role holder R ~ p_t, drawn independently.
  * Honest leader fails w.p. rho_nat, plus (if it did not fail naturally) w.p. kappa
    when R is a colluder: fail prob = rho_nat + (1 - rho_nat) * kappa * 1{R in B0}.
    The record does not show who framed (anonymous framing).
  * Colluder leaders fail only naturally (r_B = rho_nat).
  * Rule (symmetric, stationary): each node keeps a forgetting estimate of its own
    attributed failure rate, r_hat_j = F_j / O_j, updated on its own opportunities with
    memory W opportunities. Share p(j) is proportional to G(r_hat_j).
      - exponential profile: G(r) = exp(-eta * r), sensitivity s = eta * (1 - rho_nat) * kappa
      - threshold profile:   G(r) = 1000 if r < theta else 1
  * The share is recomputed every n slots (activation delay d = n slots), and the slots
    inside a batch are simulated in a vectorised way (forgetting applied per batch: O(k/W) bias).
  * Modelling simplifications: the role holder is drawn independently of the leader and may be
    the leader itself; exclusion (stopping) is not simulated, only shares.

Output: CSV files with the measured time-average of lambda_t = p_t(B0) over the second
half of each run, plus the mean-field prediction.
"""
import argparse
import csv
import math
import os
import time
from multiprocessing import Pool

import numpy as np

RHO_NAT = 0.01
KAPPA = 1.0
Q = 0.5


def mean_field_exp(beta0, s, iters=100000):
    """Smallest fixed point >= beta0 of lambda = beta0 / (beta0 + (1-beta0) e^{-s lambda})."""
    lam = beta0
    for _ in range(iters):
        new = beta0 / (beta0 + (1 - beta0) * math.exp(-s * lam))
        if abs(new - lam) < 1e-13:
            break
        lam = new
    return lam


def mean_field_threshold(beta0, theta, kappa=KAPPA, ratio=1000.0):
    """Threshold profile: honest nodes fall to the low tier iff rho(lambda) >= theta."""
    lam = beta0
    for _ in range(1000):
        rho_h = RHO_NAT + (1 - RHO_NAT) * kappa * lam
        g_h = 1.0 if rho_h >= theta else ratio
        g_b = ratio  # colluders fail at rho_nat < theta
        new = beta0 * g_b / (beta0 * g_b + (1 - beta0) * g_h)
        if abs(new - lam) < 1e-13:
            break
        lam = new
    return lam


def colluder_count(beta0, n):
    """Round half up (Python's round() is banker's rounding, which mislabelled earlier runs)."""
    return int(math.floor(beta0 * n + 0.5))


def simulate(n, beta0, profile, param, memory, batches, seed, kappa=KAPPA, ratio=1000.0):
    """Returns (half-run mean, half-run std, final-10% mean, trace) of lambda_t = p_t(B0)."""
    rng = np.random.default_rng(seed)
    f0 = colluder_count(beta0, n)
    is_byz = np.zeros(n, dtype=bool)
    is_byz[:f0] = True
    # Prior: every node starts with a natural-rate estimate worth `memory` opportunities.
    F = np.full(n, RHO_NAT * memory)
    O = np.full(n, float(memory))
    keep = 1.0 - 1.0 / memory  # per-opportunity forgetting factor
    lam_trace = np.empty(batches)
    for b in range(batches):
        r_hat = F / O
        if profile == "exp":
            eta = param / ((1 - RHO_NAT) * kappa)  # param is the sensitivity s
            w = np.exp(-eta * (r_hat - r_hat.min()))
        else:
            w = np.where(r_hat < param, ratio, 1.0)  # param is theta
        p = w / w.sum()
        lam_trace[b] = p[is_byz].sum()
        # Simulate n slots with this share vector.
        leaders = rng.choice(n, size=n, p=p)
        roles = rng.choice(n, size=n, p=p)
        natural = rng.random(n) < RHO_NAT
        framed = is_byz[roles] & (rng.random(n) < kappa)
        fail = natural | (~is_byz[leaders] & framed)
        k = np.bincount(leaders, minlength=n).astype(float)
        x = np.bincount(leaders, weights=fail.astype(float), minlength=n)
        decay = keep ** k
        F = F * decay + x
        O = O * decay + k
    half = batches // 2
    tail = max(1, batches // 10)
    return (float(lam_trace[half:].mean()), float(lam_trace[half:].std()),
            float(lam_trace[-tail:].mean()), lam_trace)


def _exp_job(args):
    n, beta, s, memory, batches, seed = args
    m, sd, fin, _ = simulate(n, beta, "exp", s, memory, batches, seed)
    return [n, beta, s, seed, m, sd, fin, mean_field_exp(beta, s)]


def _thr_job(args):
    n, memory, theta, beta, batches, seed = args
    m, sd, fin, _ = simulate(n, beta, "thr", theta, memory, batches, seed)
    return [n, memory, theta, beta, seed, m, sd, fin, mean_field_threshold(beta, theta)]


def actual_betas(nominal, n):
    """Distinct actual colluder shares f0/n reachable from the nominal grid (f0 >= 1)."""
    return sorted({colluder_count(b, n) / n for b in nominal if colluder_count(b, n) >= 1})


def run_exp_sweep(out_dir, ns, betas, s_values, memory, batches, seeds, pool):
    path = os.path.join(out_dir, "exp_sweep.csv")
    jobs = [(n, colluder_count(b, n) / n, s, memory, batches, seed)
            for n in ns for b in betas for s in s_values for seed in range(seeds)]
    rows = pool.map(_exp_job, jobs, chunksize=4)
    with open(path, "w", newline="") as fp:
        wr = csv.writer(fp)
        wr.writerow(["n", "beta0", "s", "seed", "lambda_mean", "lambda_std", "lambda_final", "mean_field"])
        wr.writerows(rows)
    print(f"  exp sweep done ({len(rows)} runs)", flush=True)
    return path


def run_threshold_sweep(out_dir, ns, thetas, nominal_betas, memories, batches, seeds, pool):
    path = os.path.join(out_dir, "threshold_sweep.csv")
    jobs = [(n, memory, theta, beta, batches, seed)
            for n in ns for memory in memories for theta in thetas
            for beta in actual_betas(nominal_betas, n) for seed in range(seeds)]
    rows = pool.map(_thr_job, jobs, chunksize=4)
    with open(path, "w", newline="") as fp:
        wr = csv.writer(fp)
        wr.writerow(["n", "memory", "theta", "beta0", "seed", "lambda_mean", "lambda_std",
                     "lambda_final", "mean_field"])
        wr.writerows(rows)
    print(f"  threshold sweep done ({len(rows)} runs) -> {path}", flush=True)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    t0 = time.time()
    s_values = [round(0.25 * i, 2) for i in range(0, 25)]  # 0 .. 6
    nominal = [round(0.01 * i, 2) for i in range(1, 31)]  # 0.01 .. 0.30
    with Pool(args.workers) as pool:
        run_exp_sweep(args.out, ns=[20, 50, 100, 200], betas=[0.1, 0.2, 0.3],
                      s_values=s_values, memory=200, batches=3000, seeds=3, pool=pool)
        run_threshold_sweep(args.out, ns=[20, 50, 100, 200], thetas=[0.1, 0.2],
                            nominal_betas=nominal, memories=[200], batches=3000, seeds=3, pool=pool)
        memory_dir = os.path.join(args.out, "memory")
        os.makedirs(memory_dir, exist_ok=True)
        run_threshold_sweep(memory_dir, ns=[100], thetas=[0.1], nominal_betas=nominal,
                            memories=[50, 200, 800], batches=3000, seeds=3, pool=pool)
    print(f"full sweep took {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
