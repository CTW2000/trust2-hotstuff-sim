use super::*;
use crate::common::{committee, EPOCH};
use crate::leader::leader;
use crate::messages::Accusation;

fn config(length: Round) -> EpochConfig {
    EpochConfig {
        length,
        entity_cap_ppm: 1_000_000,
        class_cap_ppm: 1_000_000,
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
