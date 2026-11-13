//! Ledger replay vectors (tests/replay_vectors.json, prototype/scripts/gen_replay_vectors.py; GPT review v9 Q2):
//! short committed ledgers replayed block by block, as `Core::commit` does (H4: blocks after a terminal block are
//! left out; H1: the terminal block moves the ledger to the next epoch), against the reference replay of
//! prototype/SPEC.md (prototype/scripts/replay_ref.py). Everything must match exactly: entities and base shares,
//! the terminal blocks, at each of them the rounds processed, the G2 and G1 events, CUSUM statistics,
//! reputations, exclusions, suspensions, bars and the G1 queue, every weight table, and the leader of every round.

use super::*;
use crate::messages::{Accusation, Evidence, SignedTimeout, Vote};
use crypto::Signature;
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Deserialize)]
struct Member {
    stake: Stake,
    certified: bool,
    entity: Option<u32>,
}

#[derive(Deserialize)]
struct VectorBlock {
    round: Round,
    epoch: EpochNumber,
    #[serde(default)]
    accusations: Vec<(Round, EpochNumber)>,
    /// (member, "E1" or "E-NR", the epoch the culprit signed in)
    #[serde(default)]
    evidence: Vec<(usize, String, EpochNumber)>,
}

#[derive(Deserialize)]
struct Handover {
    epoch: EpochNumber,
    terminal: Round,
    done: Round,
    g2_events: Vec<Value>,
    cusum: Vec<i64>,
    r_ppm: Vec<u64>,
    excluded: Vec<bool>,
    g1_events: Vec<Value>,
    z: Vec<bool>,
    bars: Vec<bool>,
    g1_queue: Vec<usize>,
    table: EpochNumber,
}

#[derive(Deserialize)]
struct Table {
    epoch: EpochNumber,
    stake: Vec<Stake>,
    leader: Vec<bool>,
    handover: Option<(Round, usize)>,
}

#[derive(Deserialize)]
struct Case {
    name: String,
    roster: Vec<Member>,
    length: Round,
    cap_ppm: u64,
    u_max_ppm: u64,
    l_max_ppm: u64,
    reference_length: Round,
    origin: EpochNumber,
    blocks: Vec<VectorBlock>,
    entities: Vec<usize>,
    base: Vec<String>,
    handovers: Vec<Handover>,
    tables: Vec<Table>,
    leaders: Vec<usize>,
}

fn cases() -> Vec<Case> {
    serde_json::from_str(include_str!("replay_vectors.json")).expect("bad replay vectors")
}

/// Member i of a vector, in key order.
fn key(i: usize) -> PublicKey {
    PublicKey([i as u8 + 1; 32])
}

fn roster(case: &Case) -> Committee {
    let members = case
        .roster
        .iter()
        .enumerate()
        .map(|(i, m)| (key(i), m.stake, format!("127.0.0.1:{}", i).parse().unwrap()))
        .collect();
    let mut committee = Committee::new(members, case.origin);
    for (i, m) in case.roster.iter().enumerate() {
        let a = committee.authorities.get_mut(&key(i)).unwrap();
        a.certified = m.certified;
        a.entity = m.entity;
    }
    committee
}

fn config(case: &Case) -> EpochConfig {
    EpochConfig {
        length: case.length,
        reference_length: case.reference_length,
        entity_cap_ppm: case.cap_ppm,
        class_cap_ppm: case.u_max_ppm,
        l_max_ppm: case.l_max_ppm,
        governance_malicious: false,
        leader_rule: LeaderRule::Trust2,
        g2_threshold: 0,
        g2_no_reputation: false,
        aptos_failure_percent: 0,
    }
}

/// A committed block with the accusations and evidence of the vector; Epochs does not check signatures (the core
/// verifies a block before it gets there).
fn block(b: &VectorBlock) -> Block {
    let accusations = b
        .accusations
        .iter()
        .map(|(round, epoch)| Accusation { round: *round, epoch: *epoch, votes: Vec::new() })
        .collect();
    let evidence = b
        .evidence
        .iter()
        .map(|(m, kind, signed)| {
            let author = key(*m);
            let vote = |hash: u8| Vote {
                hash: Digest([hash; 32]),
                round: b.round - 1,
                epoch: *signed,
                author,
                signature: Signature::default(),
            };
            match kind.as_str() {
                "E1" => Evidence::DoubleVote(vote(1), vote(2)),
                "E-NR" => Evidence::NrContradiction(
                    vote(1),
                    SignedTimeout {
                        author,
                        signature: Signature::default(),
                        epoch: *signed,
                        round: b.round - 1,
                        high_qc_round: 0,
                        nr: true,
                    },
                ),
                other => panic!("unknown evidence {}", other),
            }
        })
        .collect();
    Block { round: b.round, epoch: b.epoch, accusations, evidence, ..Block::default() }
}

fn g2_event(event: &Event) -> Value {
    match *event {
        Event::Exclude(k, u) => json!(["exclude", k, u]),
        Event::Release(k, u) => json!(["release", k, u]),
        Event::Full(k, u) => json!(["full", k, u]),
    }
}

fn g1_event(event: &G1Event) -> Value {
    match *event {
        G1Event::Level(l, i, k) => json!(["level", l, i, k as u64]),
        G1Event::Queue(i, k) => json!(["queue", i, k as u64]),
        G1Event::Suspend(i, k) => json!(["suspend", i, k as u64]),
        G1Event::Release(i, k) => json!(["release", i, k as u64]),
        G1Event::Evict(i, k) => json!(["evict", i, k as u64]),
        G1Event::Downgrade(i, k) => json!(["downgrade", i, k as u64]),
    }
}

fn check_handover(name: &str, epochs: &Epochs, h: &Handover, terminal: Round) {
    let at = format!("{}, terminal block of epoch {}", name, h.epoch);
    assert_eq!(terminal, h.terminal, "{}: terminal round", at);
    let (rep, pun) = (&epochs.reputation, &epochs.punishment);
    assert_eq!(rep.done(), h.done, "{}: rounds processed", at);
    let g2: Vec<Value> = rep.events().iter().map(g2_event).collect();
    assert_eq!(g2, h.g2_events, "{}: G2 events", at);
    assert_eq!(rep.cusum(), &h.cusum[..], "{}: CUSUM", at);
    assert_eq!(rep.r_ppm(), &h.r_ppm[..], "{}: reputations", at);
    assert_eq!(rep.excluded(), &h.excluded[..], "{}: exclusions", at);
    let g1: Vec<Value> = pun.events().iter().map(g1_event).collect();
    assert_eq!(g1, h.g1_events, "{}: G1 events", at);
    assert_eq!(pun.z(), h.z, "{}: z", at);
    assert_eq!(pun.bars(), h.bars, "{}: bars", at);
    assert_eq!(pun.queue(), h.g1_queue, "{}: G1 queue", at);
}

#[test]
fn ledger_replay_matches_the_reference() {
    for case in cases() {
        let name = case.name.as_str();
        let mut epochs = Epochs::new(&roster(&case), config(&case));
        assert_eq!(epochs.entity_of, case.entities, "{}: entities", name);
        let base: Vec<u128> = case.base.iter().map(|b| b.parse().unwrap()).collect();
        assert_eq!(epochs.punishment.base(), &base[..], "{}: base shares", name);

        // Replay as Core::commit does, keeping every table: Epochs keeps only the latest few.
        let mut tables: BTreeMap<EpochNumber, Committee> = epochs.tables().map(|t| (t.epoch, t.clone())).collect();
        let mut handovers = case.handovers.iter();
        for b in &case.blocks {
            let block = block(b);
            if epochs.after_terminal(&block) {
                continue;
            }
            epochs.record(&block);
            if epochs.is_terminal(&block) {
                epochs.enter_next(&block);
                let h = handovers.next().unwrap_or_else(|| panic!("{}: unexpected terminal block {}", name, b.round));
                check_handover(name, &epochs, h, b.round);
                tables.insert(epochs.epoch(), epochs.current().clone());
                tables.insert(h.table, epochs.get(h.table).expect("the new table").clone());
            }
        }
        assert!(handovers.next().is_none(), "{}: terminal blocks missing", name);

        assert_eq!(tables.len(), case.tables.len(), "{}: tables", name);
        for t in &case.tables {
            let table = &tables[&t.epoch];
            for (i, (stake, may_lead)) in t.stake.iter().zip(&t.leader).enumerate() {
                let a = &table.authorities[&key(i)];
                assert_eq!(a.stake, *stake, "{}: stake of member {} in W_{}", name, i, t.epoch);
                assert_eq!(a.leader, *may_lead, "{}: member {} may lead in W_{}", name, i, t.epoch);
            }
            assert_eq!(table.handover, t.handover.map(|(u, m)| (u, key(m))), "{}: handover of W_{}", name, t.epoch);
        }

        // The leader of every round, by the table of its epoch (an epoch starts at its handover round).
        let first = |e: &EpochNumber| if *e == case.origin { Some(0) } else { tables[e].handover.map(|(u, _)| u) };
        for (u, expected) in (1..).zip(&case.leaders) {
            let epoch = tables.keys().filter(|e| first(e).map_or(false, |f| f <= u)).max().unwrap();
            assert_eq!(leader(&tables[epoch], u), key(*expected), "{}: leader of round {}", name, u);
        }
    }
}
