use super::*;
use crate::common::{committee, keys, qc, vote};
use crate::messages::Timeout;

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
