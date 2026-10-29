use super::*;
use serde::Deserialize;

#[derive(Deserialize)]
struct Epoch {
    accused: Vec<Round>,
    events: Vec<(String, usize, Round)>,
    r_ppm: Vec<u64>,
    excluded: Vec<bool>,
    queue: Vec<usize>,
    table: Vec<f64>,
}

#[derive(Deserialize)]
struct Case {
    name: String,
    base: Vec<f64>,
    epoch_length: Round,
    lag: Round,
    epochs: Vec<Epoch>,
}

fn cases() -> Vec<Case> {
    serde_json::from_str(include_str!("g2_vectors.json")).expect("bad test vectors")
}

fn event(e: &(String, usize, Round)) -> Event {
    match e.0.as_str() {
        "exclude" => Event::Exclude(e.1, e.2),
        "release" => Event::Release(e.1, e.2),
        "queue" => Event::Queue(e.1, e.2),
        "drop" => Event::Drop(e.1, e.2),
        x => panic!("unknown event {}", x),
    }
}

#[test]
fn increments_are_the_log_likelihood_ratios() {
    let c = G2Config::default();
    assert!((c.up as f64 / 1e6 - (0.5f64 / 0.1).ln()).abs() < 1e-6);
    assert!((c.down as f64 / 1e6 - (0.5f64 / 0.9).ln()).abs() < 1e-6);
    assert!((c.threshold as f64 / 1e6 - 1e4f64.ln()).abs() < 1e-6);
}

/// Replays each simulator run: leaders by round robin over the members not excluded at the epoch's start,
/// the accusations of the epoch recorded before its change; every event, reputation, exclusion, queue and
/// table must match.
#[test]
fn rule_and_reputation_match_the_simulator() {
    for case in cases() {
        let base: Vec<u128> = case.base.iter().map(|b| (b * ONE as f64).round() as u128).collect();
        let n = base.len();
        let mut rep = Reputation::new(base, G2Config { lag: case.lag, ..G2Config::default() });
        let mut leaders = BTreeMap::new();
        for (i, epoch) in case.epochs.iter().enumerate() {
            let k = i as Round + 1;
            let eligible: Vec<usize> = (0..n).filter(|x| !rep.excluded()[*x]).collect();
            for u in (k - 1) * case.epoch_length + 1..=k * case.epoch_length {
                leaders.insert(u, eligible[u as usize % eligible.len()]);
            }
            for u in &epoch.accused {
                rep.record(*u, 1);
            }

            let horizon = k * case.epoch_length + 1 - case.lag;
            let events = rep.advance(horizon, |u, _| leaders.get(&u).copied()).to_vec();
            let expected: Vec<Event> = epoch.events.iter().map(event).collect();
            assert_eq!(events, expected, "{} epoch {}: events", case.name, k);
            assert_eq!(rep.r_ppm(), &epoch.r_ppm[..], "{} epoch {}: reputations", case.name, k);
            assert_eq!(rep.excluded(), &epoch.excluded[..], "{} epoch {}: exclusions", case.name, k);
            let queue: Vec<usize> = rep.queue().iter().map(|(x, _)| *x).collect();
            assert_eq!(queue, epoch.queue, "{} epoch {}: queue", case.name, k);
            let stakes = rep.stakes(&vec![true; n]);
            for (x, (got, want)) in stakes.iter().zip(&epoch.table).enumerate() {
                assert!(
                    (*got as f64 - want * 1e6).abs() <= 1.0,
                    "{} epoch {} member {}: stake {} vs {}",
                    case.name, k, x, got, want * 1e6
                );
            }
        }
    }
}

#[test]
fn budget_binds_in_some_case() {
    // The vectors must exercise the budget: some table where the cut weight would exceed B_rep.
    let b_rep = G2Config::default().b_rep as f64 / ONE as f64;
    let binding = cases().iter().any(|case| {
        case.epochs.iter().any(|e| {
            let cut: f64 = case.base.iter().zip(&e.r_ppm).map(|(b, r)| b * (1.0 - *r as f64 / 1e6)).sum();
            cut > b_rep + 1e-9
        })
    });
    assert!(binding);
}

#[test]
fn late_and_repeated_accusations_are_ignored() {
    let mut rep = Reputation::new(vec![ONE / 4; 4], G2Config::default());
    rep.record(5, 1);
    rep.record(5, 2); // the first accusation of a round counts
    assert_eq!(rep.accused.get(&5), Some(&1));
    rep.advance(10, |u, _| Some(u as usize % 4));
    rep.record(7, 1); // round 7 is processed already
    assert!(rep.accused.is_empty());
}
