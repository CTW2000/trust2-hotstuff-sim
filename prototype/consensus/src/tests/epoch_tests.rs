use super::*;
use crate::common::{committee, keys, EPOCH};
use crate::leader::leader;
use crate::messages::{Accusation, Evidence, OmitProof, Otx, SignedTimeout, Timeout, Vote, QC};

fn config(length: Round) -> EpochConfig {
    EpochConfig {
        length,
        entity_cap_ppm: 1_000_000,
        class_cap_ppm: 1_000_000,
        l_max_ppm: 100_000,
        governance_malicious: false,
    }
}

fn block(epoch: EpochNumber, round: Round) -> Block {
    Block {
        epoch,
        round,
        ..Block::default()
    }
}

#[test]
fn first_table_is_capnorm_of_the_base_weights() {
    let epochs = Epochs::new(&committee(), config(10));
    assert_eq!(epochs.epoch(), EPOCH);
    let table = epochs.current();
    assert_eq!(table.epoch, EPOCH);
    assert!(table.authorities.values().all(|a| a.stake == 250_000));
    assert_eq!(table.quorum_threshold(), 666_667);
}

#[test]
fn class_cap_limits_uncertified_members() {
    // Two of four equal members uncertified, class cap 25%: they share 0.25, the licensed share 0.75.
    let mut roster = committee();
    let mut names: Vec<_> = roster.authorities.keys().cloned().collect();
    names.sort();
    for name in &names[..2] {
        roster.authorities.get_mut(name).unwrap().certified = false;
    }
    let epochs = Epochs::new(&roster, EpochConfig { class_cap_ppm: 250_000, ..config(10) });
    let table = epochs.current();
    assert_eq!(table.stake(&names[0]) + table.stake(&names[1]), 250_000);
    assert_eq!(table.stake(&names[2]), 375_000);
}

#[test]
fn terminal_blocks_and_handover() {
    // H1: the terminal block of epoch e is its first block at or after round s_e + length.
    let mut epochs = Epochs::new(&committee(), config(10));
    assert!(!epochs.is_terminal(&block(EPOCH, 9)));
    assert!(epochs.is_terminal(&block(EPOCH, 10)));
    assert!(!epochs.is_terminal(&block(EPOCH + 1, 10)));

    // H3: entering the next epoch; its terminal round counts from the previous terminal block.
    epochs.enter_next(&block(EPOCH, 12));
    assert_eq!(epochs.epoch(), EPOCH + 1);
    assert_eq!(epochs.current().epoch, EPOCH + 1);
    assert!(!epochs.is_terminal(&block(EPOCH, 30)));
    assert!(!epochs.is_terminal(&block(EPOCH + 1, 21)));
    assert!(epochs.is_terminal(&block(EPOCH + 1, 22)));

    // Recent tables stay available for synchronization; old ones are dropped.
    for i in 0..20 {
        epochs.enter_next(&block(EPOCH + 1 + i, 30 + 10 * i as Round));
    }
    assert_eq!(epochs.epoch(), EPOCH + 21);
    assert!(epochs.get(EPOCH + 6).is_some() && epochs.get(EPOCH + 5).is_none());

    // A QC may end the epoch once its round is past the terminal threshold.
    assert!(!epochs.may_end(30 + 10 * 19 + 10));
    assert!(epochs.may_end(30 + 10 * 19 + 11));
}

#[test]
fn no_handover_with_zero_length() {
    let epochs = Epochs::new(&committee(), config(0));
    assert!(!epochs.is_terminal(&block(EPOCH, 1_000_000)));
}

// A block of `epoch` at `round` carrying accusations of the given rounds (signatures are not checked here).
fn accusing(epoch: EpochNumber, round: Round, accused: &[Round]) -> Block {
    let accusations = accused
        .iter()
        .map(|r| Accusation { round: *r, epoch, votes: Vec::new() })
        .collect();
    Block { epoch, round, accusations, ..Block::default() }
}

#[test]
fn silent_leader_loses_leadership_and_reputation() {
    // G2 (DESIGN.md §12.2): every round led by one member is accused. Once six accusations are processed it
    // is convicted at an epoch change: it no longer leads, and its reputation drops to 0.9 until the
    // exclusion (500 rounds) ends; the others are untouched.
    let mut epochs = Epochs::new(&committee(), config(10));
    let silent = leader(epochs.current(), 1);
    let idx = epochs.members.iter().position(|(name, _)| *name == silent).unwrap();
    let mut excluded_epochs = Vec::new();
    for k in 1..=80 {
        let table = epochs.current().clone();
        let end = 10 * k;
        let accused: Vec<Round> = (end - 9..=end).filter(|u| leader(&table, *u) == silent).collect();
        if !table.authorities[&silent].leader {
            assert!(accused.is_empty(), "an excluded member led a round");
        }
        epochs.record(&accusing(table.epoch, end, &accused));
        epochs.enter_next(&block(table.epoch, end));
        if !epochs.current().authorities[&silent].leader {
            excluded_epochs.push(k);
        }
        let r = epochs.reputation.r_ppm();
        assert!(r.iter().enumerate().all(|(i, x)| i == idx || *x == 1_000_000), "an honest member was cut");
    }

    // Convicted at the third epoch change (rounds <= 21 processed: six accusations), excluded for 500 rounds.
    assert_eq!(excluded_epochs.first(), Some(&3));
    assert!(excluded_epochs.windows(2).take(49).all(|w| w[1] == w[0] + 1));
    assert!(excluded_epochs.len() < 80, "the exclusion never ended");

    // The cut stake: base 0.25 at r = 0.9 against 0.25 for the others (within the budget).
    let mut epochs = Epochs::new(&committee(), config(10));
    for k in 1..=3 {
        let table = epochs.current().clone();
        let accused: Vec<Round> = (10 * k - 9..=10 * k).filter(|u| leader(&table, *u) == silent).collect();
        epochs.record(&accusing(table.epoch, 10 * k, &accused));
        epochs.enter_next(&block(table.epoch, 10 * k));
    }
    assert_eq!(epochs.reputation.r_ppm()[idx], 900_000);
    let table = epochs.current();
    assert_eq!(table.stake(&silent), (225_000_000_000u64 / 975_000) as Stake);
    assert!((0..100).all(|u| leader(table, u) != silent));
}

#[test]
fn first_round_of_an_epoch_keeps_the_previous_leader() {
    // The votes for the commit proof of the last epoch (for the child of its terminal block) went to the
    // leader the old table gives the next round; that round, the first of the new epoch, stays with it even
    // when the new table changes who may lead (DESIGN.md §12.2).
    let mut epochs = Epochs::new(&committee(), config(10));
    let silent = leader(epochs.current(), 1);
    for k in 1..=3 {
        let table = epochs.current().clone();
        let accused: Vec<Round> = (10 * k - 9..=10 * k).filter(|u| leader(&table, *u) == silent).collect();
        epochs.record(&accusing(table.epoch, 10 * k, &accused));
        epochs.enter_next(&block(table.epoch, 10 * k));
    }
    let new = epochs.current().clone();
    let old = epochs.get(new.epoch - 1).unwrap().clone();
    assert!(old.authorities[&silent].leader && !new.authorities[&silent].leader);
    // The schedules differ after the first round (the old one has four leaders, the new one three) ...
    assert!((33..60).any(|u| leader(&old, u) != leader(&new, u)));
    // ... but the first round of the new epoch, 32, keeps the old leader.
    assert_eq!(leader(&new, 32), leader(&old, 32));
}

fn with_otxs(round: Round, otxs: Vec<Otx>) -> Block {
    Block { epoch: EPOCH, round, otxs, ..Block::default() }
}

#[test]
fn omission_proofs_are_checked_on_the_ledger() {
    // G2 (DESIGN.md §12.4): an omission proof of round 5 counts only if the committed block of round 5 is the
    // one it names and leaves the transaction out without an exemption, and it was not included earlier.
    let otx = |account, nonce, tag| Otx { account, nonce, data: [tag; 32] };
    let (x, rival) = (otx(1, 1, 0), otx(1, 1, 1));
    let counts = |earlier: Vec<Block>, b5: Option<Block>, named: Option<Digest>| -> bool {
        let mut epochs = Epochs::new(&committee(), config(100));
        for b in earlier.iter().chain(b5.iter()) {
            epochs.record(b);
        }
        let block = named.or_else(|| b5.as_ref().map(|b| b.digest())).unwrap_or_default();
        let proof = OmitProof { round: 5, epoch: EPOCH, block, otx: x.clone(), attestations: Vec::new() };
        epochs.record(&Block { epoch: EPOCH, round: 7, omissions: vec![proof], ..Block::default() });
        epochs.reputation.facts().contains_key(&5)
    };
    let b5 = with_otxs(5, vec![otx(2, 1, 0)]);
    assert!(counts(vec![], Some(b5.clone()), None));
    assert!(!counts(vec![], Some(b5.clone()), Some(Digest::default())), "another block");
    assert!(!counts(vec![], None, Some(b5.digest())), "no committed block of the round");
    assert!(!counts(vec![], Some(with_otxs(5, vec![x.clone()])), None), "included");
    let full: Vec<_> = (0..MAX_OTXS as u64).map(|n| otx(9, n, 0)).collect();
    assert!(!counts(vec![], Some(with_otxs(5, full)), None), "full block");
    assert!(!counts(vec![], Some(with_otxs(5, vec![rival.clone()])), None), "conflicting transaction in it");
    assert!(!counts(vec![with_otxs(3, vec![x.clone()])], Some(b5.clone()), None), "included earlier");
    assert!(!counts(vec![with_otxs(4, vec![rival])], Some(b5), None), "conflict included earlier");
}

#[test]
fn g1_evidence_suspends_or_bars_at_an_epoch_change() {
    // P4 (DESIGN.md §13): a double vote on the ledger suspends its signer for 4 epochs (z = 0: no stake, no
    // leading) once L_max leaves room; an NR self-contradiction bars from leading for one epoch.
    let mut epochs = Epochs::new(&committee(), EpochConfig { l_max_ppm: 300_000, ..config(10) });
    let (cheat, liar) = (keys().remove(0), keys().remove(1));
    let vote = |hash: u8, round, key: &(PublicKey, crypto::SecretKey)| {
        Vote::new_from_key(Digest([hash; 32]), round, key.0, &key.1)
    };
    let e1 = Evidence::DoubleVote(vote(1, 5, &cheat), vote(2, 5, &cheat));
    let nr = Evidence::NrContradiction(
        vote(1, 6, &liar),
        SignedTimeout::from(&Timeout::new_from_key(QC::genesis(), 6, true, liar.0, &liar.1)),
    );
    let carrying = Block { epoch: EPOCH, round: 8, evidence: vec![e1, nr], ..Block::default() };
    epochs.record(&carrying);

    let old = epochs.current().clone();
    epochs.enter_next(&block(EPOCH, 10));
    let table = epochs.current().clone();
    assert_eq!(table.stake(&cheat.0), 0);
    // The first round (12) stays with the old table's leader, suspended or not.
    assert_eq!(table.handover, Some((12, leader(&old, 12))));
    assert!(!table.authorities[&cheat.0].leader);
    assert!(table.stake(&liar.0) > 0 && !table.authorities[&liar.0].leader);
    assert!((13..100).all(|u| { let l = leader(&table, u); l != cheat.0 && l != liar.0 }));

    // The bar lasts one epoch, the suspension four.
    epochs.enter_next(&block(EPOCH + 1, 20));
    assert!(epochs.current().authorities[&liar.0].leader);
    assert_eq!(epochs.current().stake(&cheat.0), 0);
    for k in 3..=5 {
        epochs.enter_next(&block(EPOCH + k - 1, 10 * k as Round));
    }
    assert_eq!(epochs.current().stake(&cheat.0), 250_000);
    assert!(epochs.current().authorities[&cheat.0].leader);
}
