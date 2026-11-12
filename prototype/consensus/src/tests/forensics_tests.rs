use super::*;
use crate::common::{committee, keys, EPOCH};
use crate::config::EpochNumber;
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

/// A chain from `start` with a block at each (round, epoch), certified by QCs whose signatures do not matter here.
fn chain_in(start: QC, blocks: &[(Round, EpochNumber)], tag: u8) -> Records {
    let keys = keys();
    let mut qc = start;
    let mut chain = Vec::new();
    for &(round, epoch) in blocks {
        let (author, secret) = &keys[round as usize % keys.len()];
        let mut block = Block::new_from_key(qc.clone(), *author, round, vec![Digest([tag; 32])], secret);
        block.epoch = epoch;
        qc = QC { hash: block.digest(), round, epoch, votes: Vec::new() };
        chain.push(block);
    }
    Records { chain, high_qc: qc }
}

fn rounds_in(rounds: std::ops::RangeInclusive<Round>, epoch: EpochNumber) -> Vec<(Round, EpochNumber)> {
    rounds.map(|r| (r, epoch)).collect()
}

/// Epochs of 10 rounds; the sides share rounds 1..=fork-1, then each has its own blocks up to round 15. The first epoch
/// ends at its first block of round >= 10 (B10), and the next starts at round 12.
fn forked_at(fork: Round) -> (Records, Records) {
    let shared = chain_in(QC::genesis(), &rounds_in(1..=fork - 1, EPOCH), 0);
    let side = |tag| {
        let mut blocks = Vec::new();
        for r in fork..=15 {
            blocks.push((r, if r <= 11 { EPOCH } else { EPOCH + 1 }));
        }
        let own = chain_in(shared.high_qc.clone(), &blocks, tag);
        Records { chain: [shared.chain.clone(), own.chain].concat(), high_qc: own.high_qc }
    };
    (side(1), side(2))
}

#[test]
fn a_fork_is_judged_in_the_first_epoch_both_sides_committed_off_the_other() {
    // Theorem 5: forked at round 8, before the terminal block, both sides commit off the other's chain in the first
    // epoch already (round 8 onwards), so e* is the first epoch even though both go on into the next one.
    let (a, b) = forked_at(8);
    let (epoch, cx, cy) = conflict_by_epoch(&a, &b).unwrap();
    assert_eq!(epoch, EPOCH);
    assert_eq!((cx.x.epoch, cy.x.epoch, cx.x.round), (EPOCH, EPOCH, 8));

    // Forked at round 13, after both entered the next epoch on the same terminal block: e* is the next epoch.
    let (a, b) = forked_at(13);
    let (epoch, cx, _) = conflict_by_epoch(&a, &b).unwrap();
    assert_eq!((epoch, cx.x.round), (EPOCH + 1, 13));
}

#[test]
fn replayed_ledgers_share_the_table_of_the_fork_epoch() {
    // H1': W_{e*} depends on the ledger up to G_{e*-2} only, so both sides replay the same table for e*. Each side's
    // ledger reaches its own terminal block B10 of the first epoch; the suffix block B11 stays off the ledger (H4).
    let config = crate::common::test_epoch_config(10);
    let (a, b) = forked_at(8);
    let (ta, tb) = (replay_tables(&a, &committee(), config), replay_tables(&b, &committee(), config));
    assert_eq!(table_digest(&ta[&EPOCH]), table_digest(&tb[&EPOCH]));
    assert!(ta.contains_key(&(EPOCH + 2)), "the table two epochs ahead is computed at the terminal block");
    assert_eq!(terminals(&a, &committee(), config), vec![(EPOCH, 10)]);
    assert_eq!(terminals(&b, &committee(), config), vec![(EPOCH, 10)]);
    let sweep = e2_sweep(&a, &ta, &b);
    assert_eq!((sweep.blocks, sweep.own_blocks, sweep.named_blocks), (0, 0, 0), "no TC in these chains");
}

#[test]
fn only_h2_keeps_out_the_next_epoch_blocks_of_the_other_branch() {
    // Forked at round 8: each side commits its own B10 and goes on into the next epoch (rounds 12-15) on it. The next
    // epoch's table is the same on both sides (H1'), so b's blocks of that epoch, naming it, pass the table check of a
    // judge on a; none has a's B10 as an ancestor, so H2 alone keeps them out.
    let config = crate::common::test_epoch_config(10);
    let name_the_table = |records: &mut Records, table: &Digest| {
        for block in records.chain.iter_mut().filter(|x| x.epoch == EPOCH + 1) {
            block.table = table.clone();
        }
    };
    let (a, mut b) = forked_at(8);
    let ta = replay_tables(&a, &committee(), config);
    name_the_table(&mut b, &table_digest(&ta[&(EPOCH + 1)]));
    let sweep = h2_sweep(&a, &committee(), config, &ta, &b);
    assert_eq!((sweep.blocks, sweep.same_table, sweep.off_terminal), (4, 4, 4));
    assert_eq!(sweep.epochs, Some((EPOCH + 1, EPOCH + 1)));

    // Forked at round 13, after the shared terminal block B10: b's blocks of the next epoch extend it, H2 lets them in.
    let (a, mut b) = forked_at(13);
    let ta = replay_tables(&a, &committee(), config);
    name_the_table(&mut b, &table_digest(&ta[&(EPOCH + 1)]));
    let sweep = h2_sweep(&a, &committee(), config, &ta, &b);
    assert_eq!((sweep.blocks, sweep.same_table, sweep.off_terminal), (3, 3, 0));
}
