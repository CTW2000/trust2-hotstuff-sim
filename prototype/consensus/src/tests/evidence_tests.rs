use super::*;
use crate::common::{committee, keys, test_epoch_config, EPOCH};
use crate::aggregator::Aggregator;
use crate::epoch::Epochs;
use crate::messages::table_digest;
use crate::messages::Timeout;
use crypto::SecretKey;

fn qc_of(round: Round) -> QC {
    QC { hash: Digest([round as u8; 32]), round, epoch: EPOCH, votes: Vec::new() }
}

fn key(i: usize) -> (PublicKey, SecretKey) {
    keys().remove(i)
}

fn block(qc_round: Round, round: Round) -> Block {
    let (name, secret) = key(3);
    Block::new_from_key(qc_of(qc_round), name, round, Vec::new(), &secret)
}

fn vote(block: &Block, i: usize) -> Vote {
    let (name, secret) = key(i);
    Vote::new_from_key(block.digest(), block.round, name, &secret)
}

fn timeout(round: Round, high_qc_round: Round, nr: bool, i: usize) -> SignedTimeout {
    let (name, secret) = key(i);
    SignedTimeout::from(&Timeout::new_from_key(qc_of(high_qc_round), round, nr, name, &secret))
}

fn kinds(found: &[Evidence]) -> Vec<String> {
    found.iter().map(|e| format!("{:?}", e)[..2].to_string()).collect()
}

#[test]
fn honest_traffic_gives_no_evidence() {
    // Votes for valid blocks, then timeouts with high QCs at least as high and NR = 0 after voting; NR = 1
    // only in a round without a vote.
    let mut detector = Detector::new();
    let b2 = block(1, 2);
    let b3 = block(2, 3);
    let mut found = Vec::new();
    found.extend(detector.block(&b2));
    for i in 0..3 {
        found.extend(detector.vote(vote(&b2, i)));
        found.extend(detector.vote(vote(&b2, i))); // the same vote again (from a QC, say)
        found.extend(detector.timeout(timeout(2, 1, false, i)));
    }
    found.extend(detector.block(&b3));
    for i in 0..3 {
        found.extend(detector.vote(vote(&b3, i)));
        found.extend(detector.timeout(timeout(4, 2, true, i))); // no vote in round 4
    }
    assert!(found.is_empty(), "{:?}", found);
}

#[test]
fn honest_vote_after_a_tc_gives_no_evidence() {
    // 5.4: after round 4 times out (honest NR = 1 reports with high QC 2), the leader of round 5 extends that QC with
    // the TC of round 4 -- not adjacent, but vouched for. Honest votes for it are neither E2 nor E3 nor NR.
    let mut detector = Detector::new();
    let (name, secret) = key(3);
    let tc = TC {
        round: 4,
        epoch: EPOCH,
        votes: (0..3).map(|i| (key(i).0, crypto::Signature::default(), 2, true)).collect(),
        high_qc: qc_of(2),
    };
    let b5 = Block::new_from_key_with_tc(qc_of(2), Some(tc), name, 5, Vec::new(), &secret);
    let mut found = detector.block(&b5);
    for i in 0..3 {
        found.extend(detector.timeout(timeout(4, 2, true, i)));
        found.extend(detector.vote(vote(&b5, i)));
    }
    assert!(found.is_empty(), "{:?}", found);
}

#[test]
fn cleanup_forgets_rounds_before_the_floor() {
    // The round-based cleanup drops the detection state (votes, timeouts, blocks, certificates) of rounds below
    // the floor, so it does not grow with the round number between (or without) handovers.
    let mut detector = Detector::new();
    let b2 = block(1, 2);
    detector.block(&b2);
    detector.vote(vote(&b2, 0));
    detector.timeout(timeout(2, 1, false, 1));
    detector.qc(&qc_of(2));
    assert!(!detector.votes.is_empty() && !detector.timeouts.is_empty());
    assert!(!detector.blocks.is_empty() && !detector.certificates.is_empty());
    detector.cleanup(3);
    assert!(detector.votes.is_empty() && detector.timeouts.is_empty());
    assert!(detector.blocks.is_empty() && detector.certificates.is_empty());
}

#[test]
fn double_vote_is_reported_once_per_epoch() {
    let mut detector = Detector::new();
    let (a, b) = (block(1, 2), Block { payload: vec![Digest([9; 32])], ..block(1, 2) });
    assert!(detector.vote(vote(&a, 0)).is_empty());
    let found = detector.vote(vote(&b, 0));
    assert_eq!(kinds(&found), vec!["E1"]);
    assert!(found[0].verify().is_ok());
    let (c, d) = (block(4, 5), Block { payload: vec![Digest([9; 32])], ..block(4, 5) });
    detector.vote(vote(&c, 0));
    assert!(detector.vote(vote(&d, 0)).is_empty()); // the same culprit, class and epoch
}

#[test]
fn nr_contradiction_in_either_order() {
    let b = block(1, 2);
    let mut detector = Detector::new();
    detector.vote(vote(&b, 0));
    let found = detector.timeout(timeout(2, 1, true, 0));
    assert_eq!(kinds(&found), vec!["NR"]);
    assert!(found[0].verify().is_ok());

    let mut detector = Detector::new();
    detector.timeout(timeout(2, 1, true, 0));
    let qc = QC { hash: b.digest(), round: 2, epoch: EPOCH, votes: vec![(key(0).0, vote(&b, 0).signature)] };
    let found = detector.qc(&qc);
    assert_eq!(kinds(&found), vec!["NR"]);
    assert!(found[0].verify().is_ok());
}

#[test]
fn invalid_block_in_either_order() {
    let bad = block(1, 5); // round 5 on a QC of round 1, without a TC
    let mut detector = Detector::new();
    detector.block(&bad);
    let found = detector.vote(vote(&bad, 0));
    assert_eq!(kinds(&found), vec!["E2"]);
    assert!(found[0].verify().is_ok());

    let mut detector = Detector::new();
    detector.vote(vote(&bad, 0));
    let found = detector.block(&bad);
    assert_eq!(kinds(&found), vec!["E2"]);
}

#[test]
fn regression_in_either_order() {
    let b3 = block(2, 3); // a vote for it locks on round 2
    let mut detector = Detector::new();
    detector.block(&b3);
    detector.vote(vote(&b3, 0));
    assert!(detector.timeout(timeout(4, 2, false, 0)).is_empty());
    let found = detector.timeout(timeout(5, 1, false, 0));
    assert_eq!(kinds(&found), vec!["E3"]);
    assert!(found[0].verify().is_ok());

    let mut detector = Detector::new();
    detector.timeout(timeout(4, 1, false, 0));
    detector.vote(vote(&b3, 0)); // the block is not here yet
    let found = detector.block(&b3);
    assert_eq!(kinds(&found), vec!["E3"]);
    assert!(found[0].verify().is_ok());
}

/// The weight table of the fixture members with base weights `stakes` (in key order), in its first epoch.
fn table_with(stakes: [u32; 4]) -> Committee {
    let mut roster = committee();
    for ((name, _), stake) in keys().iter().zip(stakes) {
        roster.authorities.get_mut(name).unwrap().stake = stake;
    }
    Epochs::new(&roster, test_epoch_config(0)).current().clone()
}

/// The TC of round 4 that members 1, 2 and 3 make, each reporting high QC 2, under `table`.
fn tc_of_three(table: &Committee) -> TC {
    let mut aggregator = Aggregator::new();
    (1..4)
        .find_map(|i| {
            let (name, secret) = key(i);
            let timeout = Timeout::new_from_key(qc_of(2), 4, false, name, &secret);
            aggregator.add_timeout(timeout, table).unwrap()
        })
        .unwrap()
}

/// Block 5 extending QC 2 with `tc`, naming the table `table`.
fn block_naming(tc: TC, table: &Committee) -> Block {
    let (name, secret) = key(0);
    let mut block = Block::new_from_key_with_tc(qc_of(2), Some(tc), name, 5, Vec::new(), &secret);
    block.table = table_digest(table);
    block.signature = crypto::Signature::new(&block.digest(), &secret);
    block
}

#[test]
fn e2_judges_the_tc_by_the_table_the_block_names() {
    // E2 (theory §2.3): members 1-3 hold 3/4 of table A but only 3/10 of table B. Their TC is valid under A and not
    // under B. A block naming A with it is valid; a vote for it is no E2 under any table. A block naming B with it is
    // invalid: a vote for it is E2 to a judge holding B, while a judge without B gives no verdict, and A, which the
    // block does not name, is never used to judge it.
    let a = table_with([1, 1, 1, 1]);
    let b = table_with([7, 1, 1, 1]);
    let tc = tc_of_three(&a);
    assert!(tc.verify(&a).is_ok() && tc.verify(&b).is_err());

    let valid = block_naming(tc.clone(), &a);
    let e2 = |block: &Block| Evidence::InvalidBlock(vote(block, 2), block.header());
    for table in [None, Some(&a), Some(&b)] {
        assert!(!e2(&valid).holds_under(table));
    }

    let invalid = block_naming(tc, &b);
    assert!(e2(&invalid).holds_under(Some(&b)));
    assert!(!e2(&invalid).holds_under(None));
    assert!(!e2(&invalid).holds_under(Some(&a)));
    assert!(e2(&invalid).verify_with(|d| [&a, &b].iter().copied().find(|t| table_digest(t) == *d)).is_ok());
    assert!(e2(&invalid).verify_with(|d| [&a].iter().copied().find(|t| table_digest(t) == *d)).is_err());
}

#[test]
fn e2_gives_no_verdict_on_a_tc_of_the_previous_epoch() {
    // The first block of an epoch may carry a TC of the previous one, judged by that epoch's table, which the block
    // does not name: no verdict from the table check, whatever the table says.
    let b = table_with([7, 1, 1, 1]);
    let tc = tc_of_three(&table_with([1, 1, 1, 1]));
    let (name, secret) = key(0);
    let mut block = Block::new_from_key_with_tc(qc_of(2), Some(tc), name, 5, Vec::new(), &secret);
    block.epoch = EPOCH + 1;
    block.table = table_digest(&Committee { epoch: EPOCH + 1, ..b.clone() });
    block.signature = crypto::Signature::new(&block.digest(), &secret);
    let (voter, voter_secret) = key(2);
    let vote = Vote { epoch: EPOCH + 1, ..Vote::new_from_key(block.digest(), 5, voter, &voter_secret) };
    let next = Committee { epoch: EPOCH + 1, ..b };
    assert!(!Evidence::InvalidBlock(vote, block.header()).holds_under(Some(&next)));
}

#[test]
fn detector_finds_e2_only_with_the_named_table() {
    // The detector judges a block's TC by the table the block names, if it holds that table.
    let a = table_with([1, 1, 1, 1]);
    let b = table_with([7, 1, 1, 1]);
    let invalid = block_naming(tc_of_three(&a), &b);

    let mut without = Detector::new();
    without.set_tables([&a]);
    let mut found = without.block(&invalid);
    found.extend(without.vote(vote(&invalid, 2)));
    assert!(found.is_empty(), "{:?}", found);

    let mut with = Detector::new();
    with.set_tables([&a, &b]);
    let mut found = with.block(&invalid);
    found.extend(with.vote(vote(&invalid, 2)));
    assert_eq!(kinds(&found), vec!["E2"]);
}
