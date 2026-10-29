use super::*;
use crate::ttru::from_ppm;
use serde::Deserialize;

#[derive(Deserialize)]
struct Epoch {
    z: Vec<bool>,
    bars: Vec<bool>,
    base: Vec<f64>,
    queue: Vec<usize>,
    events: Vec<(String, usize, EpochNumber)>,
}

#[derive(Deserialize)]
struct Case {
    name: String,
    certified: Vec<bool>,
    weights: Vec<u64>,
    cap_ppm: u64,
    u_max_ppm: u64,
    script: Vec<(usize, String, EpochNumber, EpochNumber, bool, bool)>,
    epochs: Vec<Epoch>,
}

fn cases() -> Vec<Case> {
    serde_json::from_str(include_str!("g1_vectors.json")).expect("bad test vectors")
}

fn event(e: &(String, usize, EpochNumber)) -> G1Event {
    let (what, i, k) = (e.0.as_str(), e.1, e.2);
    match what {
        "L1" | "L2" | "L3" | "L4" => G1Event::Level(what[1..].parse().unwrap(), i, k),
        "queue" => G1Event::Queue(i, k),
        "suspend" => G1Event::Suspend(i, k),
        "release" => G1Event::Release(i, k),
        "evict" => G1Event::Evict(i, k),
        "downgrade" => G1Event::Downgrade(i, k),
        x => panic!("unknown event {}", x),
    }
}

/// Replays each simulator run: the same evidence, one table per epoch; every event, z, bar, queue and base
/// share must match.
#[test]
fn graded_punishment_matches_the_simulator() {
    for case in cases() {
        let classes: Vec<Class> = case
            .certified
            .iter()
            .map(|c| if *c { Class::Licensed } else { Class::Uncertified })
            .collect();
        let (cap, u_max) = (from_ppm(case.cap_ppm), from_ppm(case.u_max_ppm));
        let mut punishment = Punishment::new(classes, case.weights.clone(), cap, u_max, PunishConfig::default());
        for (i, kind, es, ec, malicious, fork) in &case.script {
            let kind = if kind == "live" { Kind::Liveness } else { Kind::Safety };
            punishment.record(*i, kind, *es, *ec, *malicious, *fork);
        }
        for (index, epoch) in case.epochs.iter().enumerate() {
            let k = index as EpochNumber + 1;
            let events = punishment.update(k).to_vec();
            let expected: Vec<G1Event> = epoch.events.iter().map(event).collect();
            assert_eq!(events, expected, "{} epoch {}: events", case.name, k);
            assert_eq!(punishment.z(), epoch.z, "{} epoch {}: z", case.name, k);
            assert_eq!(punishment.bars(), epoch.bars, "{} epoch {}: bars", case.name, k);
            assert_eq!(punishment.queue(), epoch.queue, "{} epoch {}: queue", case.name, k);
            for (i, (got, want)) in punishment.base().iter().zip(&epoch.base).enumerate() {
                let got = *got as f64 / ONE as f64;
                assert!((got - want).abs() < 1e-9, "{} epoch {} entity {}: base {} vs {}", case.name, k, i, got, want);
            }
        }
    }
}

#[test]
fn suspended_share_never_exceeds_l_max() {
    let l_max = PunishConfig::default().l_max;
    for case in cases() {
        let classes: Vec<Class> = case
            .certified
            .iter()
            .map(|c| if *c { Class::Licensed } else { Class::Uncertified })
            .collect();
        let (cap, u_max) = (from_ppm(case.cap_ppm), from_ppm(case.u_max_ppm));
        let mut punishment = Punishment::new(classes, case.weights.clone(), cap, u_max, PunishConfig::default());
        for (i, kind, es, ec, malicious, fork) in &case.script {
            let kind = if kind == "live" { Kind::Liveness } else { Kind::Safety };
            punishment.record(*i, kind, *es, *ec, *malicious, *fork);
        }
        for k in 1..=case.epochs.len() as EpochNumber {
            punishment.update(k);
            assert!(punishment.suspended_share(k) <= l_max, "{} epoch {}", case.name, k);
        }
    }
}
