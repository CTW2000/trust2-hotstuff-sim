use super::*;
use crate::common::{committee, keys, qc, vote, EPOCH};
use crate::messages::{Accusation, Timeout};

#[test]
fn add_vote() {
    let mut aggregator = Aggregator::new();
    let result = aggregator.add_vote(vote(), &committee());
    assert!(result.is_ok());
    assert!(result.unwrap().is_none());
}

#[test]
fn make_qc() {
    let mut aggregator = Aggregator::new();
    let mut keys = keys();
    let qc = qc();
    let hash = qc.digest();
    let round = qc.round;

    // Add 2f+1 votes to the aggregator and ensure it returns the cryptographic
    // material to make a valid QC.
    let (public_key, secret_key) = keys.pop().unwrap();
    let vote = Vote::new_from_key(hash.clone(), round, public_key, &secret_key);
    let result = aggregator.add_vote(vote, &committee());
    assert!(result.is_ok());
    assert!(result.unwrap().is_none());

    let (public_key, secret_key) = keys.pop().unwrap();
    let vote = Vote::new_from_key(hash.clone(), round, public_key, &secret_key);
    let result = aggregator.add_vote(vote, &committee());
    assert!(result.is_ok());
    assert!(result.unwrap().is_none());

    let (public_key, secret_key) = keys.pop().unwrap();
    let vote = Vote::new_from_key(hash.clone(), round, public_key, &secret_key);
    match aggregator.add_vote(vote, &committee()) {
        Ok(Some(qc)) => assert!(qc.verify(&committee()).is_ok()),
        _ => assert!(false),
    }
}

#[test]
fn cleanup() {
    let mut aggregator = Aggregator::new();

    // Add a vote and ensure it is in the aggregator memory.
    let result = aggregator.add_vote(vote(), &committee());
    assert!(result.is_ok());
    assert_eq!(aggregator.votes_aggregators.len(), 1);
    assert!(aggregator.timeouts_aggregators.is_empty());

    // Clean up the aggregator.
    aggregator.cleanup(&2);
    assert!(aggregator.votes_aggregators.is_empty());
    assert!(aggregator.timeouts_aggregators.is_empty());
}

#[test]
fn make_tc_keeps_highest_qc_and_nr() {
    // R2: the TC carries the highest QC of its timeouts and every signer's NR report.
    let mut aggregator = Aggregator::new();
    let mut keys = keys();
    let reports = [(QC::genesis(), true), (qc(), false), (QC::genesis(), true)];
    let mut result = None;
    for (high_qc, nr) in reports.iter() {
        let (name, secret) = keys.pop().unwrap();
        let timeout = Timeout::new_from_key(high_qc.clone(), 2, *nr, name, &secret);
        result = aggregator.add_timeout(timeout, &committee()).unwrap();
    }
    let tc = result.expect("three timeouts make a TC");
    assert_eq!(tc.high_qc, qc());
    assert_eq!(tc.nr_weight(&committee()), 2);
    assert!(tc.verify(&committee()).is_ok());
}

#[test]
fn timeouts_of_two_epochs_do_not_mix() {
    // A node that enters the next epoch during a round already holds that round's timeouts of the old epoch;
    // the timeouts it gets afterwards are of the new one. A TC of both carries one epoch, so the signatures of
    // the other fail at every receiver and the TC, and the block that embeds it, are rejected.
    let mut aggregator = Aggregator::new();
    let mut next = committee();
    next.epoch = EPOCH + 1;
    let timeout_in = |epoch, (name, secret): &(PublicKey, crypto::SecretKey)| {
        let mut timeout = Timeout::new_from_key(QC::genesis(), 2, false, *name, secret);
        timeout.epoch = epoch;
        timeout.signature = Signature::new(&timeout.digest(), secret);
        timeout
    };
    let keys = keys();
    for key in &keys[..2] {
        assert!(aggregator.add_timeout(timeout_in(EPOCH, key), &committee()).unwrap().is_none());
    }
    assert!(aggregator.add_timeout(timeout_in(EPOCH + 1, &keys[2]), &next).unwrap().is_none());
    assert!(aggregator.add_timeout(timeout_in(EPOCH + 1, &keys[0]), &next).unwrap().is_none());
    let tc = aggregator
        .add_timeout(timeout_in(EPOCH + 1, &keys[1]), &next)
        .unwrap()
        .expect("three timeouts of the new epoch make a TC");
    assert!(tc.verify(&next).is_ok());
}

#[test]
fn past_the_end_of_an_epoch_a_certificate_needs_a_quorum_of_both_tables() {
    // H5: three of four equal members are a quorum of the old table. In the next table the fourth holds 5 of 8, so
    // the three do not make a QC or a TC there; with the fourth they do.
    let keys = keys();
    let mut next = committee();
    next.epoch = EPOCH + 1;
    next.authorities.get_mut(&keys[3].0).unwrap().stake = 5;
    let hash = Digest([9; 32]);
    let vote = |i: usize| Vote::new_from_key(hash.clone(), 2, keys[i].0, &keys[i].1);
    let timeout = |i: usize| Timeout::new_from_key(QC::genesis(), 2, false, keys[i].0, &keys[i].1);

    let mut aggregator = Aggregator::new();
    for i in 0..3 {
        assert!(aggregator.add_vote_with(vote(i), &committee(), Some(&next)).unwrap().is_none());
        assert!(aggregator.add_timeout_with(timeout(i), &committee(), Some(&next)).unwrap().is_none());
    }
    let qc = aggregator.add_vote_with(vote(3), &committee(), Some(&next)).unwrap().expect("a QC of both tables");
    let tc = aggregator.add_timeout_with(timeout(3), &committee(), Some(&next)).unwrap().expect("a TC of both tables");
    assert!(qc.verify(&committee()).is_ok() && qc.has_quorum_in(&next));
    assert!(tc.verify(&committee()).is_ok() && tc.has_quorum_in(&next));

    // Under the old table alone the first three are enough, and they do not hold a quorum of the next.
    let mut aggregator = Aggregator::new();
    assert!(aggregator.add_vote(vote(0), &committee()).unwrap().is_none());
    assert!(aggregator.add_vote(vote(1), &committee()).unwrap().is_none());
    let qc = aggregator.add_vote(vote(2), &committee()).unwrap().expect("a QC of the old table");
    assert!(!qc.has_quorum_in(&next));
}

#[test]
fn accuser_makes_one_accusation_from_nr_timeouts() {
    // G2: NR = 1 timeouts above 2/3 of the weight make one AT accusation; NR = 0 ones do not count.
    let mut accuser = Accuser::new();
    let keys = keys();
    let timeout = |i: usize, nr: bool| Timeout::new_from_key(QC::genesis(), 2, nr, keys[i].0, &keys[i].1);
    assert!(accuser.add(&timeout(0, true), &committee()).is_none());
    assert!(accuser.add(&timeout(1, false), &committee()).is_none());
    assert!(accuser.add(&timeout(0, true), &committee()).is_none()); // the same signer again
    assert!(accuser.add(&timeout(2, true), &committee()).is_none());
    let accusation = accuser.add(&timeout(3, true), &committee()).expect("three NR = 1 reports");
    assert_eq!((accusation.round, accusation.votes.len()), (2, 3));
    assert!(accusation.verify(&committee()).is_ok());

    // Once made (here or from a TC), the round gives no second accusation.
    assert!(accuser.add(&timeout(1, true), &committee()).is_none());
    let other = Accusation { round: 3, ..accusation.clone() };
    assert!(accuser.note(&other));
    assert!(!accuser.note(&other));

    // Rounds before the cleanup round are forgotten.
    accuser.cleanup(3);
    assert!(accuser.makers.is_empty() && accuser.made.iter().all(|(_, r)| *r >= 3));
}
