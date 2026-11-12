//! T_tru weight table (方案说明 v0.12 §2): T_i = CapNorm(w_i) · r_i · z_i.
//!
//! Everything is integer fixed point (1.0 = `ONE`), so that every node derives the same table bit for bit.
//! CapNorm gives every entity at most `cap` and the uncertified class at most `u_max` of the weight (and no
//! more than its raw share, or than its entities can hold under the cap), as `base_weights` in sim2/ttru.py with
//! K = 0; the test vectors in tests/ttru_vectors.json come from that function (prototype/scripts/gen_ttru_vectors.py).
//! A roster on which the caps cannot hold is rejected, never relaxed (DESIGN.md §15.28): only entities with a
//! positive weight count, and the licensed ones must be able to hold the licensed share under the cap.

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

/// Why a roster has no CapNorm table: the caps cannot hold, so the roster is rejected (DESIGN.md §15.28).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Infeasible {
    /// No member has a positive base weight.
    Empty,
    /// No licensed entity has a positive weight: the uncertified class would take all of it, beyond u_max.
    NoLicensed,
    /// The positive-weight entities of a class cannot hold its share under the entity cap.
    Cap { licensed: bool, entities: usize, share_ppm: u128 },
}

impl std::fmt::Display for Infeasible {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            Infeasible::Empty => write!(f, "no member has a positive base weight"),
            Infeasible::NoLicensed => write!(f, "no licensed entity has a positive base weight"),
            Infeasible::Cap { licensed, entities, share_ppm } => write!(
                f,
                "{} {} entities with a positive weight cannot hold {} ppm under the entity cap",
                entities,
                if *licensed { "licensed" } else { "uncertified" },
                share_ppm
            ),
        }
    }
}

/// Shares proportional to `v` that sum to `total`, none above `cap` (water filling, as `cap_normalize` in
/// sim2/ttru.py); entries of weight 0 get 0. None if the positive entries cannot hold `total` under the cap
/// (their count times cap is less than total): the caller rejects the roster, the cap is never relaxed.
pub fn cap_normalize(v: &[u128], cap: u128, total: u128) -> Option<Vec<u128>> {
    if total == 0 {
        return Some(vec![0; v.len()]);
    }
    let positive = v.iter().filter(|x| **x > 0).count() as u128;
    if positive * cap < total {
        return None;
    }
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
            return Some(out);
        }
    }
}

/// CapNorm of the chain's base weights `w` (stake, equal weights or governance-set weights): the uncertified
/// class gets min(its raw share, u_max, n_U · cap), with n_U its entities of positive weight, the licensed class
/// the rest, and each class is cap-normalized within its share, so the shares sum to 1 (up to floor rounding).
/// Rejected (Err) if no member or no licensed entity has a positive weight, or if the licensed entities of
/// positive weight cannot hold 1 - U under the cap (n_L · cap < 1 - U, with U the uncertified share actually
/// given, not u_max). `cap` and `u_max` are fixed point (ONE = 1.0). The weights must sum to at most u64::MAX.
pub fn base_weights(classes: &[Class], w: &[u64], cap: u128, u_max: u128) -> Result<Vec<u128>, Infeasible> {
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
    let positive = |v: &[u128]| v.iter().filter(|x| **x > 0).count();
    if total == 0 {
        return Err(Infeasible::Empty);
    }
    if positive(&lic) == 0 {
        return Err(Infeasible::NoLicensed);
    }
    let unc_share = (unc.iter().sum::<u128>() * ONE / total).min(u_max).min(positive(&unc) as u128 * cap);
    let lic_share = ONE - unc_share;
    let lic_w = cap_normalize(&lic, cap, lic_share).ok_or(Infeasible::Cap {
        licensed: true,
        entities: positive(&lic),
        share_ppm: lic_share * PPM / ONE,
    })?;
    let unc_w = cap_normalize(&unc, cap, unc_share).ok_or(Infeasible::Cap {
        licensed: false,
        entities: positive(&unc),
        share_ppm: unc_share * PPM / ONE,
    })?;
    let (mut lic_w, mut unc_w) = (lic_w.into_iter(), unc_w.into_iter());
    Ok(classes
        .iter()
        .map(|c| match c {
            Class::Licensed => lic_w.next().unwrap(),
            Class::Uncertified => unc_w.next().unwrap(),
        })
        .collect())
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
