//! T_tru weight table (方案说明 v0.12 §2): T_i = CapNorm(w_i) · r_i · z_i.
//!
//! Everything is integer fixed point (1.0 = `ONE`), so that every node derives the same table bit for bit.
//! CapNorm gives every entity at most `cap` and the uncertified class at most `u_max` of the weight (and no
//! more than its raw share, or than its entities can hold under the cap), as `base_weights` in sim2/ttru.py with
//! K = 0; the test vectors in tests/ttru_vectors.json come from that function (prototype/scripts/gen_ttru_vectors.py).

use serde::{Deserialize, Serialize};

#[cfg(test)]
#[path = "tests/ttru_tests.rs"]
pub mod ttru_tests;

/// Fixed-point 1.0.
pub const ONE: u128 = 1_000_000_000_000_000_000;
/// Parts per million (reputation r and the caps are given in ppm).
pub const PPM: u128 = 1_000_000;
/// Sum of the integer stakes of a weight table.
pub const STAKE_TOTAL: u128 = 1_000_000;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Class {
    /// Certified and licensed: bound to its beneficial owner, subject only to the entity cap.
    Licensed,
    /// Not certified: together at most `u_max` of the weight.
    Uncertified,
}

/// Shares proportional to `v` that sum to `total`, none above `cap` (water filling, as `cap_normalize` in
/// sim2/ttru.py). If no assignment respects the cap (n · cap < total), the cap is relaxed to the smallest
/// feasible value, total / n rounded up: the governance default of the scheme (方案 §3.3).
pub fn cap_normalize(v: &[u128], cap: u128, total: u128) -> Vec<u128> {
    let n = v.len() as u128;
    if n == 0 || total == 0 {
        return vec![0; v.len()];
    }
    let cap = cap.max((total + n - 1) / n);
    let mut fixed = vec![false; v.len()];
    loop {
        let n_fixed = fixed.iter().filter(|f| **f).count() as u128;
        let rest = total.saturating_sub(cap * n_fixed);
        let free_sum: u128 = v
            .iter()
            .zip(&fixed)
            .filter(|(_, f)| !**f)
            .map(|(x, _)| *x)
            .sum();
        let out: Vec<u128> = v
            .iter()
            .zip(&fixed)
            .map(|(x, f)| match (f, free_sum) {
                (true, _) => cap,
                (false, 0) => 0,
                (false, _) => x * rest / free_sum,
            })
            .collect();
        let mut changed = false;
        for (i, o) in out.iter().enumerate() {
            if !fixed[i] && *o > cap {
                fixed[i] = true;
                changed = true;
            }
        }
        if !changed {
            return out;
        }
    }
}

/// CapNorm of the chain's base weights `w` (stake, equal weights or governance-set weights): the uncertified
/// class gets min(its raw share, u_max, n_U · cap), the licensed class the rest, and each class is cap-normalized
/// within its share, so the shares always sum to 1. If the licensed class cannot hold its share under the cap, its
/// cap is relaxed (cap_normalize); with no licensed entity the uncertified class is the whole weight, relaxed
/// likewise. `cap` and `u_max` are fixed point (ONE = 1.0). The weights must sum to at most u64::MAX.
pub fn base_weights(classes: &[Class], w: &[u64], cap: u128, u_max: u128) -> Vec<u128> {
    assert_eq!(classes.len(), w.len());
    let total: u128 = w.iter().map(|x| *x as u128).sum();
    assert!(total <= u64::MAX as u128, "base weights too large");
    let in_class = |c: Class| -> Vec<u128> {
        w.iter()
            .zip(classes)
            .filter(|(_, k)| **k == c)
            .map(|(x, _)| *x as u128)
            .collect()
    };
    let (lic, unc) = (in_class(Class::Licensed), in_class(Class::Uncertified));
    let unc_share = match (total, lic.len()) {
        (0, _) => 0,
        (_, 0) => ONE,
        _ => (unc.iter().sum::<u128>() * ONE / total).min(u_max).min(unc.len() as u128 * cap),
    };
    let mut lic_w = cap_normalize(&lic, cap, ONE - unc_share).into_iter();
    let mut unc_w = cap_normalize(&unc, cap, unc_share).into_iter();
    classes
        .iter()
        .map(|c| match c {
            Class::Licensed => lic_w.next().unwrap(),
            Class::Uncertified => unc_w.next().unwrap(),
        })
        .collect()
}

/// The weight table of an epoch: T_i = base_i · r_i · z_i, normalized to integer stakes summing to about
/// STAKE_TOTAL (floor rounding). `r_ppm` is the reputation in ppm (r_min ≤ r ≤ 1), `z` the suspension
/// switch (false while suspended or evicted). The cut weight Σ base_i (1 - r_i) is at most `b_rep` (fixed
/// point): beyond it every cut shrinks in proportion, and cut weight is not redistributed (as TtruWeights
/// in sim2/ttru.py).
pub fn table(base: &[u128], r_ppm: &[u64], z: &[bool], b_rep: u128) -> Vec<u64> {
    assert!(base.len() == r_ppm.len() && base.len() == z.len());
    let mut cut: Vec<u128> = base
        .iter()
        .zip(r_ppm)
        .map(|(b, r)| b * (PPM - *r as u128) / PPM)
        .collect();
    let total_cut: u128 = cut.iter().sum();
    if total_cut > b_rep {
        for c in cut.iter_mut() {
            *c = *c * b_rep / total_cut; // at most 10^18 · 10^18, within u128
        }
    }
    let t: Vec<u128> = base
        .iter()
        .zip(&cut)
        .zip(z)
        .map(|((b, c), z)| if *z { b - c } else { 0 })
        .collect();
    let sum: u128 = t.iter().sum();
    t.iter()
        .map(|x| match sum {
            0 => 0,
            _ => (x * STAKE_TOTAL / sum) as u64,
        })
        .collect()
}

/// Converts a share in ppm to fixed point.
pub fn from_ppm(ppm: u64) -> u128 {
    ppm as u128 * (ONE / PPM)
}
