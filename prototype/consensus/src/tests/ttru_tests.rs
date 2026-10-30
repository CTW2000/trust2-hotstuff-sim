use super::*;
use serde::Deserialize;

#[derive(Deserialize)]
struct Case {
    name: String,
    certified: Vec<bool>,
    weights: Vec<u64>,
    cap_ppm: u64,
    u_max_ppm: u64,
    base: Vec<f64>,
    /// A boundary case where a cap gives way (gen_ttru_vectors.py).
    #[serde(default)]
    relaxed: bool,
}

fn cases() -> Vec<Case> {
    serde_json::from_str(include_str!("ttru_vectors.json")).expect("bad test vectors")
}

fn classes(case: &Case) -> Vec<Class> {
    case.certified
        .iter()
        .map(|c| if *c { Class::Licensed } else { Class::Uncertified })
        .collect()
}

fn as_f64(x: u128) -> f64 {
    x as f64 / ONE as f64
}

#[test]
fn base_weights_match_the_simulator() {
    for case in cases() {
        let b = base_weights(&classes(&case), &case.weights, from_ppm(case.cap_ppm), from_ppm(case.u_max_ppm));
        for (i, (x, y)) in b.iter().zip(&case.base).enumerate() {
            assert!((as_f64(*x) - y).abs() < 1e-9, "{} entity {}: {} vs {}", case.name, i, as_f64(*x), y);
        }
        let sum: u128 = b.iter().sum();
        assert!(ONE - sum < 1_000, "{}: weights sum to {}", case.name, as_f64(sum));
    }
}

#[test]
fn caps_hold() {
    for case in cases().into_iter().filter(|c| !c.relaxed) {
        let cls = classes(&case);
        let (cap, u_max) = (from_ppm(case.cap_ppm), from_ppm(case.u_max_ppm));
        let b = base_weights(&cls, &case.weights, cap, u_max);
        assert!(b.iter().all(|x| *x <= cap), "{}: entity cap", case.name);
        let unc: u128 = b.iter().zip(&cls).filter(|(_, c)| **c == Class::Uncertified).map(|(x, _)| *x).sum();
        assert!(unc <= u_max, "{}: class cap", case.name);
    }
}

#[test]
fn table_rounds_and_suspends() {
    let case = &cases()[0];
    let b = base_weights(&classes(case), &case.weights, from_ppm(case.cap_ppm), from_ppm(case.u_max_ppm));
    let n = b.len();
    let full = table(&b, &vec![1_000_000; n], &vec![true; n], ONE);
    let total: u64 = full.iter().sum();
    assert!(STAKE_TOTAL as u64 - total < n as u64);
    for (x, y) in full.iter().zip(&b) {
        assert!((*x as f64 - as_f64(*y) * 1e6).abs() <= 1.0);
    }

    // A suspended entity gets no stake; the others' relative shares are unchanged (no CapNorm recomputation).
    let mut z = vec![true; n];
    z[0] = false;
    let t = table(&b, &vec![1_000_000; n], &z, ONE);
    assert_eq!(t[0], 0);
    let scale = 1.0 / (1.0 - as_f64(b[0]));
    assert!((t[1] as f64 - as_f64(b[1]) * 1e6 * scale).abs() <= 1.0);

    // Reputation 0.7 scales an entity's table weight before normalization.
    let mut r = vec![1_000_000; n];
    r[1] = 700_000;
    let t = table(&b, &r, &vec![true; n], ONE);
    assert!((t[1] as f64 / full[1] as f64 - 0.7 / (1.0 - 0.3 * as_f64(b[1]))).abs() < 1e-3);
}

#[test]
fn infeasible_cap_is_relaxed() {
    // Four licensed entities cannot share 1.0 under a 0.10 cap: the cap is relaxed to 0.25.
    let b = base_weights(&[Class::Licensed; 4], &[1, 2, 3, 4], from_ppm(100_000), from_ppm(250_000));
    assert!(b.iter().all(|x| *x == ONE / 4));
}
