use super::*;
use crate::common::{committee, keys, unsigned_otx, EPOCH};
use crate::config::Parameters;
use crypto::Signature;
use crate::leader::leader;
use crate::messages::{Accusation, Evidence, OmitProof, Otx, SignedTimeout, Timeout, Vote, MAX_OTXS, QC};

fn config(length: Round) -> EpochConfig {
    EpochConfig {
        length,
        reference_length: 0,
        entity_cap_ppm: 1_000_000,
        class_cap_ppm: 1_000_000,
        l_max_ppm: 100_000,
        governance_malicious: false,
        leader_rule: Default::default(),
        g2_threshold: 0,
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
fn single_epoch_mode_has_no_handover() {
    // length == 0 is a single-epoch run: no handover ever happens, which the round-based cleanup relies on.
    assert!(Epochs::new(&committee(), config(0)).single_epoch());
    assert!(!Epochs::new(&committee(), config(10)).single_epoch());
}

#[test]
fn single_epoch_ledger_keeps_only_a_window() {
    // A single-epoch run has no handover to process the ledger facts and then forget them, so committed blocks and
    // accusation facts are kept only for the last SINGLE_EPOCH_LEDGER_WINDOW rounds -- decided by the ledger itself,
    // so every node keeps the same. An omission proof for a recent round is still checked against its committed
    // block. A multi-epoch run keeps everything until its handover, as before.
    let rounds = SINGLE_EPOCH_LEDGER_WINDOW + 500;
    let accused = |round: Round| Block {
        accusations: vec![Accusation { round: round - 1, epoch: EPOCH, votes: Vec::new() }],
        ..block(EPOCH, round)
    };
    let mut single = Epochs::new(&committee(), config(0));
    let mut multi = Epochs::new(&committee(), config(10 * rounds));
    for round in 1..=rounds {
        single.record(&accused(round));
        multi.record(&accused(round));
    }
    let oldest = *single.committed.keys().next().unwrap();
    assert!(oldest >= rounds - SINGLE_EPOCH_LEDGER_WINDOW, "oldest committed round kept: {}", oldest);
    assert!(single.committed.len() as Round <= SINGLE_EPOCH_LEDGER_WINDOW + 1);
    assert!(single.reputation.facts().len() as Round <= SINGLE_EPOCH_LEDGER_WINDOW + 1);
    assert_eq!(multi.committed.len() as Round, rounds);

    let x = unsigned_otx(1, 1, 0);
    let recent = rounds - 10;
    let proof = OmitProof {
        round: recent,
        epoch: EPOCH,
        block: single.committed[&recent].digest.clone(),
        otx: x,
        attestations: Vec::new(),
    };
    assert!(single.omission_holds(&proof));
}

#[test]
fn cap_above_l_max_is_refused() {
    // 6.9: the scheme requires cap <= L_max, and a node refuses to start without it.
    let parameters = |cap, l_max| Parameters { entity_cap_ppm: cap, l_max_ppm: l_max, ..Parameters::default() };
    assert!(Parameters::default().check().is_ok());
    assert!(parameters(100_000, 100_000).check().is_ok());
    assert!(parameters(100_001, 100_000).check().is_err());
}

#[test]
fn every_member_fits_under_l_max() {
    // 6.9: four members cannot respect a 5% cap, so CapNorm gives each of them 25%, above the 10% L_max. L_max rises
    // with it: a double vote suspends its signer, instead of leaving it queued for good, ahead of everyone else.
    let mut epochs = Epochs::new(&committee(), EpochConfig { entity_cap_ppm: 50_000, ..config(10) });
    let cheat = keys().remove(0);
    let vote = |hash: u8| Vote::new_from_key(Digest([hash; 32]), 5, cheat.0, &cheat.1);
    let evidence = vec![Evidence::DoubleVote(vote(1), vote(2))];
    epochs.record(&Block { epoch: EPOCH, round: 8, evidence, ..Block::default() });
    epochs.enter_next(&block(EPOCH, 10));
    epochs.enter_next(&block(EPOCH + 1, 20)); // H1': the table of the epoch after next
    assert_eq!(epochs.current().stake(&cheat.0), 0);
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
fn early_entry_then_the_ledger_catches_up() {
    // H1' and H3 (DESIGN.md §15.10): holding the terminal block, the first of the epoch past its end, a node enters
    // the next epoch before its ledger gets there. The ledger's arrival then computes the table two epochs ahead
    // without entering again; only after that can the following epoch be entered early.
    let mut epochs = Epochs::new(&committee(), config(10));
    let first_table = epochs.current().clone();
    let past = |epoch, round, parent| Block {
        epoch,
        round,
        qc: QC { hash: Digest::default(), round: parent, epoch, votes: Vec::new() },
        ..Block::default()
    };
    assert!(epochs.get(EPOCH + 1).is_some());
    assert!(!epochs.enter_early(&past(EPOCH, 11, 10)), "not the first block past the end");
    assert!(!epochs.enter_early(&past(EPOCH, 9, 8)), "not past the end");
    assert!(epochs.enter_early(&past(EPOCH, 10, 9)));
    assert_eq!(epochs.epoch(), EPOCH + 1);
    assert_eq!(epochs.current().handover, Some((12, leader(&first_table, 12))));
    assert!(!epochs.enter_early(&past(EPOCH + 1, 20, 19)), "the table after next is not known yet");

    assert!(epochs.is_terminal(&past(EPOCH, 10, 9)));
    assert!(!epochs.enter_next(&past(EPOCH, 10, 9)));
    assert_eq!(epochs.epoch(), EPOCH + 1);
    assert!(epochs.get(EPOCH + 2).is_some());
    assert!(epochs.enter_early(&past(EPOCH + 1, 20, 19)));
    assert_eq!(epochs.epoch(), EPOCH + 2);
}

#[test]
fn durations_keep_their_rounds_at_another_epoch_length() {
    // DESIGN.md §15.11: the defaults are for epochs of 100 rounds; at 25 rounds an epoch-counted duration is four
    // times as many epochs, and the recovery per epoch a quarter; at the reference length nothing changes.
    let at = |length| scaled(&EpochConfig { reference_length: 100, ..config(length) });
    let (punish, g2) = at(25);
    let (base, base_g2) = (PunishConfig::default(), G2Config::default());
    assert_eq!((punish.lead_bar, punish.sign_window), (4 * base.lead_bar, 4 * base.sign_window));
    assert_eq!((punish.suspend_l2, punish.suspend_l3), (4 * base.suspend_l2, 4 * base.suspend_l3));
    assert_eq!((punish.chain_window, punish.lookback), (4 * base.chain_window, 4 * base.lookback));
    assert_eq!(punish.governance_delay, 4 * base.governance_delay);
    assert_eq!(g2.recover_ppm, base_g2.recover_ppm / 4);
    assert_eq!((g2.lag, g2.exclusion), (base_g2.lag, base_g2.exclusion));
    let (same, same_g2) = at(100);
    assert_eq!((same.suspend_l2, same_g2.recover_ppm), (base.suspend_l2, base_g2.recover_ppm));
    assert_eq!(at(0).0.suspend_l3, base.suspend_l3);
}

#[test]
fn g2_threshold_switch() {
    // DESIGN.md §15.13: 0 keeps the protocol's threshold; another value replaces it and nothing else.
    assert_eq!(scaled(&config(25)).1.threshold, G2Config::default().threshold);
    let (_, g2) = scaled(&EpochConfig { g2_threshold: 9_210_340, ..config(25) });
    assert_eq!(g2.threshold, 9_210_340);
    assert_eq!((g2.up, g2.down, g2.exclusion), (G2Config::default().up, G2Config::default().down, 500));
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
fn accusations_count_against_the_leader_of_their_own_table() {
    // 5.3: an accusation counts against the leader of its round in the table of the epoch it was made in, which is the
    // table the accusers went by, not the one of the epoch the round falls in. They differ here: the second epoch
    // change excludes the silent leader from the table after next (H1'), and that table hands its rounds to others.
    let mut epochs = Epochs::new(&committee(), config(10));
    let silent = leader(epochs.current(), 1);
    for k in 1..=3 {
        let table = epochs.current().clone();
        let accused: Vec<Round> = (10 * k - 9..=10 * k).filter(|u| leader(&table, *u) == silent).collect();
        epochs.record(&accusing(table.epoch, 10 * k, &accused));
        epochs.enter_next(&block(table.epoch, 10 * k));
    }
    let new = epochs.epoch();
    let old = new - 1;
    let (old_table, new_table) = (&epochs.tables[&old], &epochs.tables[&new]);
    assert!(!new_table.authorities[&silent].leader);

    let first = epochs.first_rounds[&new];
    let round = (first..first + 20).find(|u| leader(old_table, *u) != leader(new_table, *u)).unwrap();
    let index = |name| epochs.members.binary_search_by_key(&name, |(n, _)| *n).ok();
    let of = |accused_in| leader_index(&epochs.tables, &epochs.first_rounds, &epochs.members, round, accused_in);
    assert_eq!(of(Some(old)), index(leader(old_table, round)));
    assert_eq!(of(None), index(leader(new_table, round)));
    assert_ne!(of(Some(old)), of(None));
}

#[test]
fn silent_leader_loses_leadership_and_reputation() {
    // G2 (DESIGN.md §12.2): every round led by one member is accused. Once three accusations are processed it
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
            // Only the first round of an epoch can be its: it keeps the leader of the previous table.
            let first = table.handover.map(|(first, _)| first);
            assert!(accused.iter().all(|u| Some(*u) == first), "an excluded member led a round");
        }
        epochs.record(&accusing(table.epoch, end, &accused));
        epochs.enter_next(&block(table.epoch, end));
        if !epochs.current().authorities[&silent].leader {
            excluded_epochs.push(k);
        }
        let r = epochs.reputation.r_ppm();
        assert!(r.iter().enumerate().all(|(i, x)| i == idx || *x == 1_000_000), "an honest member was cut");
    }

    // Convicted at the second epoch change (rounds <= 11 processed: three accusations at γ = 10², §15.13), excluded
    // for 500 rounds from the table after next (H1').
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
    let table = epochs.get(epochs.epoch() + 1).unwrap();
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
    let otx = unsigned_otx;
    let (x, rival) = (otx(1, 3, 0), otx(1, 3, 1));
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
    let full: Vec<_> = (1..=MAX_OTXS as u64).map(|n| otx(9, n, 0)).collect();
    assert!(counts(vec![], Some(with_otxs(5, full)), None), "a full block excuses nothing");
    assert!(!counts(vec![], Some(with_otxs(5, vec![rival.clone()])), None), "conflicting transaction in it");
    assert!(!counts(vec![with_otxs(3, vec![x.clone()])], Some(b5.clone()), None), "included earlier");
    assert!(!counts(vec![with_otxs(4, vec![rival])], Some(b5.clone()), None), "conflict included earlier");
    assert!(!counts(vec![with_otxs(3, vec![otx(1, 7, 0)])], Some(b5.clone()), None), "nonce spent earlier");
    assert!(counts(vec![with_otxs(3, vec![otx(1, 2, 0)])], Some(b5), None), "a lower nonce spends nothing above it");
    assert!(counts(vec![], Some(with_otxs(5, vec![otx(1, 7, 0)])), None), "a higher nonce in the block excuses nothing");
}

#[test]
fn the_watermark_outlives_the_blocks_it_covers() {
    // The ledger keeps no record per transaction: once a round is processed, one number per owner stands for it.
    let mut epochs = Epochs::new(&committee(), config(10));
    epochs.record(&with_otxs(3, vec![unsigned_otx(1, 5, 0), unsigned_otx(1, 2, 0), unsigned_otx(2, 1, 0)]));
    for k in 1..=3 {
        epochs.enter_next(&block(EPOCH + k - 1, 10 * k as Round));
    }
    assert!(epochs.committed.is_empty());
    assert_eq!(epochs.watermark.len(), 2);
    assert_eq!(epochs.watermark[&unsigned_otx(1, 0, 0).owner], 5);
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

    // H1': the ledger up to the terminal block of this epoch decides the table of the epoch after next.
    epochs.enter_next(&block(EPOCH, 10));
    assert!(epochs.current().stake(&cheat.0) > 0);
    assert_eq!(epochs.get(EPOCH + 2).unwrap().stake(&cheat.0), 0);
    let old = epochs.current().clone();
    epochs.enter_next(&block(EPOCH + 1, 20));
    let table = epochs.current().clone();
    assert_eq!(table.stake(&cheat.0), 0);
    // The first round (22) stays with the old table's leader, suspended or not.
    assert_eq!(table.handover, Some((22, leader(&old, 22))));
    assert!(!table.authorities[&cheat.0].leader);
    assert!(table.stake(&liar.0) > 0 && !table.authorities[&liar.0].leader);
    assert!((23..100).all(|u| { let l = leader(&table, u); l != cheat.0 && l != liar.0 }));

    // The bar lasts one epoch, the suspension four.
    epochs.enter_next(&block(EPOCH + 2, 30));
    assert!(epochs.current().authorities[&liar.0].leader);
    assert_eq!(epochs.current().stake(&cheat.0), 0);
    for k in 4..=6 {
        epochs.enter_next(&block(EPOCH + k - 1, 10 * k as Round));
    }
    assert_eq!(epochs.current().stake(&cheat.0), 250_000);
    assert!(epochs.current().authorities[&cheat.0].leader);
}

/// The committee with its first two members, by key, bound into one entity.
fn with_entity() -> (Committee, Vec<PublicKey>) {
    let mut roster = committee();
    let mut names: Vec<_> = roster.authorities.keys().cloned().collect();
    names.sort();
    for name in &names[..2] {
        roster.authorities.get_mut(name).unwrap().entity = Some(7);
    }
    (roster, names)
}

#[test]
fn an_entity_shares_one_cap() {
    // Each of four members is below a cap of 40%, but the two of one owner hold 50% together: the cap applies to
    // them as one, and the rest goes to the others. A base weight split over more nodes earns nothing.
    let (roster, names) = with_entity();
    let epochs = Epochs::new(&roster, EpochConfig { entity_cap_ppm: 400_000, ..config(10) });
    let table = epochs.current();
    assert_eq!(table.stake(&names[0]), 200_000);
    assert_eq!(table.stake(&names[1]), 200_000);
    assert_eq!(table.stake(&names[2]), 300_000);
    assert_eq!(table.stake(&names[3]), 300_000);

    let epochs = Epochs::new(&committee(), EpochConfig { entity_cap_ppm: 400_000, ..config(10) });
    assert!(epochs.current().authorities.values().all(|a| a.stake == 250_000));
}

#[test]
fn an_entity_splits_its_weight_by_base_weight() {
    // Weights 2 and 1 of an entity capped at 50%; what the rounding leaves stays in the table.
    let (mut roster, names) = with_entity();
    roster.authorities.get_mut(&names[0]).unwrap().stake = 2;
    let epochs = Epochs::new(&roster, EpochConfig { entity_cap_ppm: 500_000, ..config(10) });
    let table = epochs.current();
    assert_eq!(table.stake(&names[0]), 333_334);
    assert_eq!(table.stake(&names[1]), 166_666);
    assert_eq!(table.authorities.values().map(|a| a.stake as u64).sum::<u64>(), 1_000_000);
}

#[test]
fn punishment_falls_on_the_whole_entity() {
    // One member double votes: every member of its entity is suspended, and only them. The entity holds 20%, so
    // this is not yet a correlated fault above 1/3.
    let (mut roster, names) = with_entity();
    for name in &names[2..] {
        roster.authorities.get_mut(name).unwrap().stake = 4;
    }
    let mut epochs = Epochs::new(&roster, EpochConfig { l_max_ppm: 500_000, ..config(10) });
    let cheat = keys().into_iter().find(|(name, _)| *name == names[1]).unwrap();
    let vote = |hash: u8| Vote::new_from_key(Digest([hash; 32]), 5, cheat.0, &cheat.1);
    let evidence = vec![Evidence::DoubleVote(vote(1), vote(2))];
    epochs.record(&Block { epoch: EPOCH, round: 8, evidence, ..Block::default() });
    epochs.enter_next(&block(EPOCH, 10));
    epochs.enter_next(&block(EPOCH + 1, 20)); // H1': the table of the epoch after next
    let table = epochs.current();
    for name in &names[..2] {
        assert_eq!(table.stake(name), 0);
        assert!(!table.authorities[name].leader);
    }
    for name in &names[2..] {
        assert!(table.stake(name) > 0 && table.authorities[name].leader);
    }
}

#[test]
fn accusations_of_its_members_add_up_on_the_entity() {
    // Accusations of rounds led by either member count against the one entity, and both stop leading.
    let (roster, names) = with_entity();
    let mut epochs = Epochs::new(&roster, config(10));
    for k in 1..=6 {
        let table = epochs.current().clone();
        let end = 10 * k;
        let accused: Vec<Round> = (end - 9..=end).filter(|u| names[..2].contains(&leader(&table, *u))).collect();
        epochs.record(&accusing(table.epoch, end, &accused));
        epochs.enter_next(&block(table.epoch, end));
    }
    let table = epochs.current();
    assert!(names[..2].iter().all(|name| !table.authorities[name].leader));
    assert!(names[2..].iter().all(|name| table.authorities[name].leader));
    assert_eq!(epochs.reputation.r_ppm().len(), 3);
}

// The leader rules of the prototype comparison (DESIGN.md §15.12).

fn with_rule(rule: LeaderRule) -> EpochConfig {
    EpochConfig { leader_rule: rule, ..config(10) }
}

fn event(proposer: Option<usize>, failed: &[usize], voters: &[usize]) -> AptosEvent {
    AptosEvent { proposer, failed: failed.to_vec(), voters: voters.to_vec() }
}

#[test]
fn aptos_weights_follow_the_heuristic() {
    // ProposerAndVoterHeuristic::get_weights: failed above 10% of the proposer rounds (strictly), else active if it
    // proposed or voted, else inactive. Member 0: 1 failure in 10 rounds (10%, active); member 1: 2 in 10 (failed);
    // member 2 only votes, in the last block (active); member 3 does nothing (inactive).
    let mut epochs = Epochs::new(&committee(), with_rule(LeaderRule::Aptos));
    for k in 0..9 {
        epochs.history.push_back(event(Some(0), &[], &[]));
        if k < 8 {
            epochs.history.push_back(event(Some(1), &[], &[]));
        }
    }
    epochs.history.push_back(event(None, &[0, 1, 1], &[]));
    epochs.history.push_back(event(None, &[], &[2]));
    assert_eq!(epochs.aptos_weights(), vec![aptos::ACTIVE, aptos::FAILED, aptos::ACTIVE, aptos::INACTIVE]);

    // The voter window is n blocks: a vote further back no longer counts.
    for _ in 0..4 {
        epochs.history.push_back(event(Some(0), &[], &[]));
    }
    assert_eq!(epochs.aptos_weights()[2], aptos::INACTIVE);
}

#[test]
fn aptos_records_the_proposer_the_skipped_leaders_and_the_voters() {
    let mut epochs = Epochs::new(&committee(), with_rule(LeaderRule::Aptos));
    let table = epochs.current().clone();
    let author = leader(&table, 5);
    let (proposer, failed) = {
        let index = |name| epochs.members.binary_search_by_key(&name, |(n, _)| *n).unwrap();
        (index(author), vec![index(leader(&table, 3)), index(leader(&table, 4))])
    };
    let voters: Vec<_> = epochs.members.iter().take(3).map(|(name, _)| (*name, Signature::default())).collect();
    let qc = QC { round: 2, epoch: EPOCH, votes: voters, ..QC::default() };
    epochs.record(&Block { qc, author, ..block(EPOCH, 5) });
    let recorded = epochs.history.back().unwrap();
    assert_eq!(recorded.proposer, Some(proposer));
    assert_eq!(recorded.failed, failed);
    assert_eq!(recorded.voters, vec![0, 1, 2]);
    // No G2 facts under this rule.
    assert!(epochs.reputation.facts().is_empty());
}

#[test]
fn aptos_leaders_are_drawn_by_reputation_times_voting_weight() {
    // A member whose rounds all fail is demoted to weight 1 in the next tables; the voting weights do not change.
    let mut epochs = Epochs::new(&committee(), with_rule(LeaderRule::Aptos));
    let failing = leader(epochs.current(), 1);
    for k in 1..=4 {
        let table = epochs.current().clone();
        let mut parent = 10 * k - 10;
        for round in 10 * k - 9..=10 * k {
            if leader(&table, round) == failing && round != 10 * k {
                continue; // skipped: recorded as failed by the next block
            }
            let author = leader(&table, round);
            let qc = QC { round: parent, epoch: table.epoch, ..QC::default() };
            epochs.record(&Block { qc, author, ..block(table.epoch, round) });
            parent = round;
        }
        epochs.enter_next(&block(table.epoch, 10 * k));
    }
    let table = epochs.current();
    assert!(table.authorities.values().all(|a| a.stake == 250_000 && a.leader));
    assert_eq!(table.authorities[&failing].lead, aptos::FAILED * 250_000);
    let led = (0..2_000).filter(|u| leader(table, *u) == failing).count();
    assert!(led < 20, "a demoted member led {} of 2000 rounds", led);
}

#[test]
fn failed_rounds_are_the_facts_of_the_framable_rule() {
    // LeaderRule::Failed: the rounds a committed block skips are bad facts against their leaders; AT accusations
    // are not. A member whose rounds all fail is excluded as under AT evidence.
    let mut epochs = Epochs::new(&committee(), with_rule(LeaderRule::Failed));
    let table = epochs.current().clone();
    let qc = QC { round: 2, epoch: EPOCH, ..QC::default() };
    let accusation = Accusation { round: 1, epoch: EPOCH, votes: Vec::new() };
    epochs.record(&Block { qc, accusations: vec![accusation], ..block(EPOCH, 5) });
    assert_eq!(epochs.reputation.facts().keys().copied().collect::<Vec<_>>(), vec![3, 4]);

    let mut epochs = Epochs::new(&committee(), with_rule(LeaderRule::Failed));
    let failing = leader(&table, 1);
    let mut excluded = false;
    for k in 1..=10 {
        let table = epochs.current().clone();
        let mut parent = 10 * k - 10;
        for round in 10 * k - 9..=10 * k {
            if leader(&table, round) == failing && round != 10 * k {
                continue;
            }
            let qc = QC { round: parent, epoch: table.epoch, ..QC::default() };
            epochs.record(&Block { qc, ..block(table.epoch, round) });
            parent = round;
        }
        epochs.enter_next(&block(table.epoch, 10 * k));
        excluded |= !epochs.current().authorities[&failing].leader;
        let r = epochs.reputation.r_ppm();
        let i = epochs.members.binary_search_by_key(&failing, |(n, _)| *n).unwrap();
        assert!(r.iter().enumerate().all(|(k, x)| k == i || *x == 1_000_000), "another member was cut");
    }
    assert!(excluded, "a member whose rounds all fail was never excluded");
}

#[test]
fn no_rule_keeps_everyone_leading() {
    let mut epochs = Epochs::new(&committee(), with_rule(LeaderRule::None));
    let silent = leader(epochs.current(), 1);
    for k in 1..=4 {
        let table = epochs.current().clone();
        let accused: Vec<Round> = (10 * k - 9..=10 * k).filter(|u| leader(&table, *u) == silent).collect();
        let qc = QC { round: 10 * k - 9, epoch: table.epoch, ..QC::default() };
        epochs.record(&Block { qc, ..accusing(table.epoch, 10 * k, &accused) });
        epochs.enter_next(&block(table.epoch, 10 * k));
    }
    assert!(epochs.reputation.facts().is_empty());
    assert!(epochs.current().authorities.values().all(|a| a.leader && a.lead == 0 && a.stake == 250_000));
}
