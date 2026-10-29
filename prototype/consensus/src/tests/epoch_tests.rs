use super::*;
use crate::common::{committee, EPOCH};

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
