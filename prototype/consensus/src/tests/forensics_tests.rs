use super::*;
use crate::common::{committee, keys, EPOCH};
use crate::messages::{Block, Timeout, Vote, QC, TC};
use crypto::{Digest, PublicKey};

// Four members of stake 1 (quorum 3): 0 and 1 are the split-brain members, 2 is honest on side a, 3 on side b.
const SIDE_A: [usize; 3] = [0, 1, 2];
const SIDE_B: [usize; 3] = [0, 1, 3];

fn key(i: usize) -> PublicKey {
    keys()[i].0
}

fn qc_by(block: &Block, signers: &[usize]) -> QC {
    let keys = keys();
    let votes = signers
        .iter()
        .map(|&i| {
            let vote = Vote::new_from_key(block.digest(), block.round, keys[i].0, &keys[i].1);
            (vote.author, vote.signature)
        })
        .collect();
    QC { hash: block.digest(), round: block.round, epoch: EPOCH, votes }
}

/// The TC of `round` signed by `signers`, every one reporting `high_qc`.
fn tc_by(round: Round, high_qc: &QC, signers: &[usize]) -> TC {
    let keys = keys();
    let votes = signers
        .iter()
        .map(|&i| {
            let timeout = Timeout::new_from_key(high_qc.clone(), round, false, keys[i].0, &keys[i].1);
            (keys[i].0, timeout.signature, high_qc.round, false)
        })
        .collect();
    TC { round, epoch: EPOCH, votes, high_qc: high_qc.clone() }
}

/// A chain from `start` with a block at each round of `blocks` (round, TC it embeds), each certified by `signers`;
/// `tag` tells the payloads of the two sides apart.
fn chain(start: QC, blocks: Vec<(Round, Option<TC>)>, signers: &[usize], tag: u8) -> Records {
    let keys = keys();
    let mut qc = start;
    let mut chain = Vec::new();
    for (round, tc) in blocks {
        let (author, secret) = &keys[round as usize % keys.len()];
        let block = Block::new_from_key_with_tc(qc.clone(), tc, *author, round, vec![Digest([tag; 32])], secret);
        qc = qc_by(&block, signers);
        chain.push(block);
    }
    Records { chain, high_qc: qc }
}

fn plain(rounds: &[Round]) -> Vec<(Round, Option<TC>)> {
    rounds.iter().map(|&r| (r, None)).collect()
}

fn culprits(finding: &Finding) -> Vec<PublicKey> {
    let mut out: Vec<_> = finding.culprits.iter().cloned().collect();
    out.sort();
    out
}

fn expected() -> Vec<PublicKey> {
    let mut out = vec![key(0), key(1)];
    out.sort();
    out
}

#[test]
fn commit_proofs_need_adjacent_rounds() {
    let a = chain(QC::genesis(), plain(&[1, 2, 4, 5, 6]), &SIDE_A, 1);
    let proofs: Vec<Round> = a.commit_proofs().iter().map(|p| p.x.round).collect();
    // (1, 2) is a commit proof with QC(2) inside block 4; (2, 4) is not adjacent; (4, 5) with QC(5) inside 6;
    // (5, 6) with QC(6) = the highest QC.
    assert_eq!(proofs, vec![1, 4, 5]);
}

#[test]
fn one_chain_has_no_conflict() {
    let a = chain(QC::genesis(), plain(&[1, 2, 3, 4]), &SIDE_A, 1);
    let b = Records { chain: a.chain[..3].to_vec(), high_qc: a.chain[3].qc.clone() };
    assert!(first_conflict(&a, &b).is_none());
}

#[test]
fn same_view_fork_is_double_votes() {
    // Case A: both sides commit a block of round 1.
    let a = chain(QC::genesis(), plain(&[1, 2, 3]), &SIDE_A, 1);
    let b = chain(QC::genesis(), plain(&[1, 2, 3]), &SIDE_B, 2);
    let (cx, cy) = first_conflict(&a, &b).unwrap();
    let finding = judge(&cx, &cy, &b, true);
    assert_eq!(finding.case, Case::A);
    assert_eq!(culprits(&finding), expected());
    assert_eq!(finding.evidence.len(), 2);
    assert!(finding.evidence.iter().all(|e| matches!(e, Evidence::DoubleVote(..)) && e.verify().is_ok()));
    assert!(finding.missing.is_none());
}

#[test]
fn parent_at_the_view_of_x_is_double_votes() {
    // Case C2: side b certifies another block of round 1, then times out round 2 and commits round 3 on it.
    let a = chain(QC::genesis(), plain(&[1, 2, 3]), &SIDE_A, 1);
    let b1 = chain(QC::genesis(), plain(&[1]), &SIDE_B, 2);
    let tc = tc_by(2, &b1.high_qc, &SIDE_B);
    let rest = chain(b1.high_qc.clone(), vec![(3, Some(tc)), (4, None), (5, None)], &SIDE_B, 2);
    let b = Records { chain: [b1.chain, rest.chain].concat(), high_qc: rest.high_qc };
    let (cx, cy) = first_conflict(&a, &b).unwrap();
    assert_eq!((cx.x.round, cy.x.round), (1, 3));
    let finding = judge(&cx, &cy, &b, true);
    assert_eq!(finding.case, Case::C2);
    assert_eq!(culprits(&finding), expected());
    assert!(finding.evidence.iter().all(|e| matches!(e, Evidence::DoubleVote(..)) && e.verify().is_ok()));
}

#[test]
fn fork_through_a_tc_is_regression() {
    // Case C3 (DESIGN.md §15.15, S2): side a commits round 1 (QC(2) by 0, 1, 2); side b only times out until
    // round 4 -- the split-brain members sign the TC reporting the genesis -- then commits round 5 on the genesis.
    let a = chain(QC::genesis(), plain(&[1, 2, 3]), &SIDE_A, 1);
    let tc = tc_by(4, &QC::genesis(), &SIDE_B);
    let b = chain(QC::genesis(), vec![(5, Some(tc)), (6, None), (7, None)], &SIDE_B, 2);
    let (cx, cy) = first_conflict(&a, &b).unwrap();
    let finding = judge(&cx, &cy, &b, true);
    assert_eq!(finding.case, Case::C3);
    assert_eq!(finding.z_round, Some(5));
    assert_eq!(culprits(&finding), expected());
    assert_eq!(finding.evidence.len(), 2);
    assert!(finding.evidence.iter().all(|e| matches!(e, Evidence::Regression(..)) && e.verify().is_ok()));
}

#[test]
fn a_tc_outside_the_records_convicts_nobody() {
    // S3: the same fork, but side b's records do not keep the TC (it travelled outside the block).
    let a = chain(QC::genesis(), plain(&[1, 2, 3]), &SIDE_A, 1);
    let tc = tc_by(4, &QC::genesis(), &SIDE_B);
    let mut b = chain(QC::genesis(), vec![(5, Some(tc)), (6, None), (7, None)], &SIDE_B, 2);
    b.chain[0].tc = None;
    let (cx, cy) = first_conflict(&a, &b).unwrap();
    let finding = judge(&cx, &cy, &b, false);
    assert_eq!(finding.case, Case::C3);
    assert!(finding.culprits.is_empty());
    assert!(finding.evidence.is_empty());
    assert!(finding.missing.is_some());
}

#[test]
fn the_share_of_the_culprits() {
    let a = chain(QC::genesis(), plain(&[1, 2, 3]), &SIDE_A, 1);
    let b = chain(QC::genesis(), plain(&[1, 2, 3]), &SIDE_B, 2);
    let (cx, cy) = first_conflict(&a, &b).unwrap();
    let finding = judge(&cx, &cy, &b, true);
    assert!((share(&finding.culprits, &committee()) - 0.5).abs() < 1e-9);
}

#[test]
fn a_block_that_breaks_the_voting_rule_is_e2() {
    // The theorem's first step: side b certifies a block of round 5 on the genesis without a TC; its QC's signers
    // (0, 1, 3) have E2 whatever the cases below would give.
    let a = chain(QC::genesis(), plain(&[1, 2, 3]), &SIDE_A, 1);
    let b = chain(QC::genesis(), plain(&[5, 6, 7]), &SIDE_B, 2);
    let (cx, cy) = first_conflict(&a, &b).unwrap();
    let finding = judge(&cx, &cy, &b, true);
    assert_eq!(finding.case, Case::Invalid);
    assert_eq!(finding.z_round, Some(5));
    let mut expected: Vec<_> = SIDE_B.iter().map(|&i| key(i)).collect();
    expected.sort();
    assert_eq!(culprits(&finding), expected);
    assert!(finding.evidence.iter().all(|e| matches!(e, Evidence::InvalidBlock(..)) && e.verify().is_ok()));
}

#[test]
fn without_the_tc_in_the_block_the_e2_step_would_blame_honest_voters() {
    // Why `tc_in_block` matters (S3): a stored block that left its TC outside looks like it breaks the voting rule.
    let a = chain(QC::genesis(), plain(&[1, 2, 3]), &SIDE_A, 1);
    let tc = tc_by(4, &QC::genesis(), &SIDE_B);
    let mut b = chain(QC::genesis(), vec![(5, Some(tc)), (6, None), (7, None)], &SIDE_B, 2);
    b.chain[0].tc = None;
    let (cx, cy) = first_conflict(&a, &b).unwrap();
    assert_eq!(judge(&cx, &cy, &b, true).case, Case::Invalid);
    assert_eq!(judge(&cx, &cy, &b, false).case, Case::C3);
}
