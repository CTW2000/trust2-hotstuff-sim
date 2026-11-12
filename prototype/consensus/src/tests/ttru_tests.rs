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
    /// A boundary case CapNorm rejects (gen_ttru_vectors.py, DESIGN.md §15.28): no base weights.
    #[serde(default)]
    rejected: bool,
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
        if case.rejected {
            assert!(b.is_err(), "{}: the roster should be rejected", case.name);
            continue;
        }
        let b = b.unwrap_or_else(|e| panic!("{}: rejected ({})", case.name, e));
        for (i, (x, y)) in b.iter().zip(&case.base).enumerate() {
            assert!((as_f64(*x) - y).abs() < 1e-9, "{} entity {}: {} vs {}", case.name, i, as_f64(*x), y);
        }
        let sum: u128 = b.iter().sum();
        assert!(ONE - sum < 1_000, "{}: weights sum to {}", case.name, as_f64(sum));
    }
}

#[test]
fn caps_hold() {
    for case in cases().into_iter().filter(|c| !c.rejected) {
        let cls = classes(&case);
        let (cap, u_max) = (from_ppm(case.cap_ppm), from_ppm(case.u_max_ppm));
        let b = base_weights(&cls, &case.weights, cap, u_max).unwrap();
        assert!(b.iter().all(|x| *x <= cap), "{}: entity cap", case.name);
        let unc: u128 = b.iter().zip(&cls).filter(|(_, c)| **c == Class::Uncertified).map(|(x, _)| *x).sum();
        assert!(unc <= u_max, "{}: class cap", case.name);
    }
}

#[test]
fn table_rounds_and_suspends() {
    let case = &cases()[0];
    let b = base_weights(&classes(case), &case.weights, from_ppm(case.cap_ppm), from_ppm(case.u_max_ppm)).unwrap();
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
fn infeasible_rosters_are_rejected() {
    // DESIGN.md §15.28: the cap is never relaxed. Four licensed entities cannot share 1.0 under a 0.10 cap.
    let (cap5, cap10, u_max) = (from_ppm(50_000), from_ppm(100_000), from_ppm(250_000));
    let b = base_weights(&[Class::Licensed; 4], &[1, 2, 3, 4], cap10, u_max);
    assert_eq!(b, Err(Infeasible::Cap { licensed: true, entities: 4, share_ppm: 1_000_000 }));

    // Review Q1, input 1: the uncertified share is 1%, so 15 licensed entities have to hold 99% under 5%; the
    // condition is n_L cap >= 1 - U with the U actually given, not 1 - u_max.
    let classes: Vec<Class> = [vec![Class::Licensed; 15], vec![Class::Uncertified]].concat();
    let b = base_weights(&classes, &[vec![99; 15], vec![15]].concat(), cap5, u_max);
    assert_eq!(b, Err(Infeasible::Cap { licensed: true, entities: 15, share_ppm: 990_000 }));

    // Input 2: one licensed entity of positive weight among 15 cannot hold 75%. Before, the shares summed to 30% and
    // the table's normalization gave the uncertified class 83%.
    let classes: Vec<Class> = [vec![Class::Licensed; 15], vec![Class::Uncertified; 5]].concat();
    let weights = [vec![75], vec![0; 14], vec![5; 5]].concat();
    let b = base_weights(&classes, &weights, cap5, u_max);
    assert_eq!(b, Err(Infeasible::Cap { licensed: true, entities: 1, share_ppm: 750_000 }));

    // No licensed entity of positive weight, or no weight at all.
    let b = base_weights(&[Class::Licensed, Class::Uncertified], &[0, 5], cap10, u_max);
    assert_eq!(b, Err(Infeasible::NoLicensed));
    assert_eq!(base_weights(&[Class::Licensed; 3], &[0, 0, 0], cap10, u_max), Err(Infeasible::Empty));
}

#[test]
fn zero_weight_members_get_nothing_and_do_not_count_for_the_cap() {
    // 20 licensed entities of weight 1 and two of weight 0 under a 5% cap: the 20 hold 100%, the two get 0.
    let weights = [vec![1; 20], vec![0, 0]].concat();
    let b = base_weights(&[Class::Licensed; 22], &weights, from_ppm(50_000), from_ppm(250_000)).unwrap();
    assert!(b[..20].iter().all(|x| *x == ONE / 20));
    assert_eq!(&b[20..], &[0, 0]);
    let sum: u128 = b.iter().sum();
    assert!(ONE - sum < 1_000);
}
