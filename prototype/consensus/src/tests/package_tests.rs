use super::*;
use crate::common::{committee, keys, table_at, test_epoch_config, EPOCH};
use crate::messages::{timeout_digest, vote_digest, Block, Earlier, SignedTimeout, Vote, TC};
use crypto::{generate_keypair, SecretKey, Signature};
use rand::rngs::StdRng;
use rand::SeedableRng as _;
use std::time::Instant;

// Four equal members (each 250,000 of the 1,000,000 a weight table sums to; three are a quorum), epochs of 10 rounds: B10 is the terminal block of the first epoch, B11 its child,
// and the next epoch starts at round 12. Members 0 and 1 sign on both sides; 2 is honest on side a, 3 on side b.
const LENGTH: Round = 10;
const ALL: [usize; 4] = [0, 1, 2, 3];
const SIDE_A: [usize; 3] = [0, 1, 2];
const SIDE_B: [usize; 3] = [0, 1, 3];

fn epoch_of(round: Round) -> EpochNumber {
    if round <= LENGTH + 1 {
        EPOCH
    } else {
        EPOCH + 1
    }
}

/// A block of `round` on `qc`, naming the fixture tables of its epoch and the next and the start of its epoch.
fn block(qc: QC, tc: Option<TC>, round: Round, tag: u8) -> Block {
    let (author, secret) = &keys()[round as usize % 4];
    let mut block = Block::new_from_key_with_tc(qc, tc, *author, round, vec![Digest([tag; 32])], secret);
    block.epoch = epoch_of(round);
    block.table = table_at(block.epoch);
    block.start = if block.epoch == EPOCH { 0 } else { LENGTH };
    // The table chain: the next table is named from the end of the epoch on.
    block.next_table = if round >= block.start + LENGTH { table_at(block.epoch + 1) } else { Digest::default() };
    block.signature = Signature::new(&block.digest(), secret);
    block
}

fn qc_by(block: &Block, signers: &[usize]) -> QC {
    let keys = keys();
    let digest = vote_digest(block.epoch, &block.digest(), block.round);
    let votes = signers.iter().map(|&i| (keys[i].0, Signature::new(&digest, &keys[i].1))).collect();
    QC { hash: block.digest(), round: block.round, epoch: block.epoch, votes }
}

/// The TC of `round` (in its epoch) by `signers`, every one reporting `high_qc`.
fn tc_by(round: Round, high_qc: &QC, signers: &[usize]) -> TC {
    let keys = keys();
    let epoch = epoch_of(round);
    let digest = timeout_digest(epoch, round, high_qc.round, false);
    let votes = signers.iter().map(|&i| (keys[i].0, Signature::new(&digest, &keys[i].1), high_qc.round, false)).collect();
    TC { round, epoch, votes, high_qc: high_qc.clone() }
}

/// `records` extended by a block at each of `blocks` (round, TC it embeds), each certified by `signers`.
fn extend(records: &Records, blocks: Vec<(Round, Option<TC>)>, signers: &[usize], tag: u8) -> Records {
    let mut chain = records.chain.clone();
    let mut qc = records.high_qc.clone();
    for (round, tc) in blocks {
        let next = block(qc, tc, round, tag);
        qc = qc_by(&next, signers);
        chain.push(next);
    }
    Records { chain, high_qc: qc }
}

fn plain(rounds: std::ops::RangeInclusive<Round>) -> Vec<(Round, Option<TC>)> {
    rounds.map(|round| (round, None)).collect()
}

/// The chain both sides share: rounds 1 to 12, certified by everyone.
fn shared() -> Records {
    extend(&Records { chain: Vec::new(), high_qc: QC::genesis() }, plain(1..=12), &ALL, 0)
}

fn first() -> Table {
    first_table(&committee(), test_epoch_config(LENGTH))
}

fn packed(a: &Records, b: &Records) -> Package {
    pack(a, b, &committee(), test_epoch_config(LENGTH), true).unwrap().0
}

fn split_brain() -> BTreeSet<PublicKey> {
    vec![keys()[0].0, keys()[1].0].into_iter().collect()
}

/// Both sides go on from round 13 in the second epoch: two QCs of one view.
fn same_view_fork() -> (Records, Records) {
    let shared = shared();
    (extend(&shared, plain(13..=15), &SIDE_A, 1), extend(&shared, plain(13..=15), &SIDE_B, 2))
}

#[test]
fn a_package_is_verified_from_the_first_table_alone() {
    // The fork is in the second epoch, before its end. The package carries one link per epoch before it (the
    // terminal block B10 of the first epoch, which names the second table), the two commit proofs and the double
    // votes of members 0 and 1; the verifier is given the first table and the epoch length, and nothing else.
    let (a, b) = same_view_fork();
    let package = packed(&a, &b);
    assert_eq!((package.links.len(), package.branch.len(), package.evidence.len()), (1, 0, 2));
    assert_eq!(package.links[0].header.round, 10);

    let bytes = bincode::serialize(&package).unwrap();
    let received: Package = bincode::deserialize(&bytes).unwrap();
    let verdict = verify(&received, &first(), LENGTH).unwrap();
    assert_eq!((verdict.epoch, verdict.x_round, verdict.y_round), (EPOCH + 1, 13, 13));
    assert_eq!(verdict.culprits, split_brain());
    assert_eq!((verdict.weight, verdict.total), (500_000, 1_000_000));
    assert!(verdict.accountable());
}

#[test]
fn a_fork_through_a_tc_is_verified_too() {
    // Side a commits B13 with B14. Side b never sees them: its members time out in round 14 reporting the QC of
    // round 12, and B15 extends that QC with the TC. Members 0 and 1 voted for B14, which certifies round 13, and
    // signed the timeout reporting round 12: E3. B15's parent is below the view of X, so the branch is empty.
    let shared = shared();
    let a = extend(&shared, plain(13..=15), &SIDE_A, 1);
    let tc = tc_by(14, &shared.high_qc, &SIDE_B);
    let b = extend(&shared, vec![(15, Some(tc)), (16, None), (17, None)], &SIDE_B, 2);
    let (package, finding) = pack(&a, &b, &committee(), test_epoch_config(LENGTH), true).unwrap();
    assert_eq!(finding.case, crate::forensics::Case::C3);
    assert!(package.evidence.iter().all(|e| matches!(e, Evidence::Regression(..))));

    let verdict = verify(&package, &first(), LENGTH).unwrap();
    assert_eq!((verdict.x_round, verdict.y_round), (13, 15));
    assert_eq!(verdict.culprits, split_brain());
    assert!(verdict.accountable());
}

#[test]
fn the_branch_shows_that_x_is_not_an_ancestor_of_y() {
    // Side b commits B15 on its own B13 and B14. The package carries the header of B14, the only ancestor of Y above
    // the view of X: it names its parent of round 13, which is not X. Without it, or with X's own branch, the
    // verifier refuses.
    let shared = shared();
    let a = extend(&shared, plain(13..=14), &SIDE_A, 1);
    let a = Records { high_qc: a.high_qc.clone(), chain: a.chain };
    let b = extend(&shared, plain(13..=17), &SIDE_B, 2);
    // X = B13 of side a (committed with B14 whose QC is the high QC); Y: the first commit of b off a's chain is B13
    // too, so take a later one by hand.
    let mut package = packed(&a, &b);
    let later = b.commit_proofs().into_iter().find(|proof| proof.x.round == 15).unwrap();
    package.y = Commit::of(&later);
    package.branch = vec![b.chain[13].header()]; // B14 of side b
    assert!(verify(&package, &first(), LENGTH).is_ok());

    let mut cut = package.clone();
    cut.branch.pop();
    assert!(verify(&cut, &first(), LENGTH).unwrap_err().contains("stops"));

    let mut same_chain = package.clone();
    same_chain.x = Commit::of(&b.commit_proofs().into_iter().find(|proof| proof.x.round == 13).unwrap());
    assert!(verify(&same_chain, &first(), LENGTH).unwrap_err().contains("ancestor"));
}

#[test]
fn a_tampered_package_is_refused() {
    let (a, b) = same_view_fork();
    let package = packed(&a, &b);
    let refused = |package: &Package| verify(package, &first(), LENGTH).unwrap_err();

    // A link of the table chain is missing: the table of the fork's epoch is not certified.
    let mut short = package.clone();
    short.links.pop();
    assert!(refused(&short).contains("does not reach"));

    // A link made of a block before the end of its epoch: such a block names no next table (DESIGN.md §15.43).
    let mut early = package.clone();
    early.links[0].header = a.chain[0].header();
    early.links[0].qc = a.chain[1].qc.clone();
    assert!(refused(&early).contains("before the end of its epoch"));

    // Another table than the one the certified block names.
    let mut other_table = package.clone();
    other_table.links[0].next.stakes[3].1 = 5;
    assert!(refused(&other_table).contains("not the one the certified block names"));

    // A QC of the chain without a quorum.
    let mut light = package.clone();
    light.links[0].qc.votes.truncate(2);
    assert!(refused(&light).contains("table chain"));

    // A commit proof whose QC is signed for another block.
    let mut wrong = package.clone();
    wrong.x.qc_x_plus = package.y.qc_x_plus.clone();
    assert!(refused(&wrong).contains("does not certify"));

    // The same block twice.
    let mut same = package.clone();
    same.y = same.x.clone();
    assert!(refused(&same).contains("same block"));

    // Evidence against an honest member: its vote on side a and a vote it never signed.
    let mut framed = package.clone();
    let (name, secret) = &keys()[2];
    let x = &package.x.x;
    let signed = Vote { hash: x.digest(), round: x.round, epoch: x.epoch, author: *name, signature: Signature::default() };
    let signed = Vote { signature: Signature::new(&signed.digest(), secret), ..signed };
    let forged = Vote { hash: package.y.x.digest(), signature: signed.signature.clone(), ..signed.clone() };
    framed.evidence.push(Evidence::DoubleVote(signed, forged));
    assert!(refused(&framed).contains("does not hold"));
}

#[test]
fn a_package_without_enough_evidence_is_not_accountable() {
    // The package is well formed but names one culprit only: it is accepted, and the verdict says that the culprit
    // holds 1/4 of the table, not above 1/3.
    let (a, b) = same_view_fork();
    let mut package = packed(&a, &b);
    package.evidence.truncate(1);
    let verdict = verify(&package, &first(), LENGTH).unwrap();
    assert_eq!((verdict.culprits.len(), verdict.weight, verdict.total), (1, 250_000, 1_000_000));
    assert!(!verdict.accountable());
}

#[test]
fn past_the_end_of_an_epoch_a_qc_is_checked_under_both_tables() {
    // H5 in the verifier: B10 is at the end of the first epoch (start 0, 10 rounds). Its QC by members 0-2 holds a
    // quorum of the first table; in a next table where member 3 has 5 of 8 it holds 3 of 8. The header states the
    // start of the epoch, so the verifier can tell that the round is past the end.
    let shared = shared();
    let mut b10 = shared.chain[9].clone();
    let table = first().committee();
    let mut next = Committee { epoch: EPOCH + 1, ..committee() };
    next.authorities.get_mut(&keys()[3].0).unwrap().stake = 5;
    b10.next_table = table_digest(&next);
    b10.signature = Signature::new(&b10.digest(), &keys()[10 % 4].1);
    let header = b10.header();

    let three = qc_by(&b10, &SIDE_A);
    assert!(certified(&header, &three, &table, Some(&next), LENGTH).unwrap_err().contains("no quorum of the next table"));
    assert!(certified(&header, &three, &table, None, LENGTH).unwrap_err().contains("no next table"));
    assert!(certified(&header, &three, &table, Some(&next), 2 * LENGTH).is_ok(), "before the end of a longer epoch");
    assert!(certified(&header, &qc_by(&b10, &ALL), &table, Some(&next), LENGTH).is_ok());
}

#[test]
fn a_cross_epoch_contradiction_is_accepted_as_evidence() {
    // E4 in a package: member 0 voted at round 13 in the second epoch and signed a timeout of round 14 in the first.
    let (a, b) = same_view_fork();
    let mut package = packed(&a, &b);
    let (name, secret) = &keys()[0];
    let x = &package.x.x;
    let vote = Vote { hash: x.digest(), round: x.round, epoch: x.epoch, author: *name, signature: Signature::default() };
    let vote = Vote { signature: Signature::new(&vote.digest(), secret), ..vote };
    let timeout = SignedTimeout {
        author: *name,
        signature: Signature::new(&timeout_digest(EPOCH, 14, 11, false), secret),
        epoch: EPOCH,
        round: 14,
        high_qc_round: 11,
        nr: false,
    };
    package.evidence = vec![Evidence::CrossEpoch(vote, Earlier::Timeout(timeout))];
    let verdict = verify(&package, &first(), LENGTH).unwrap();
    assert_eq!(verdict.culprits.into_iter().collect::<Vec<_>>(), vec![*name]);
}

// ---- cost (DESIGN.md §15.35): run with `cargo test -p consensus --release package_cost -- --ignored --nocapture`

fn members(n: usize) -> Vec<(PublicKey, SecretKey)> {
    let mut rng = StdRng::from_seed([7; 32]);
    (0..n).map(|_| generate_keypair(&mut rng)).collect()
}

/// A fork among `n` equal members in the last of `epochs` epochs of 25 rounds: every epoch before it is complete, the
/// sides share the first block of the last epoch and then each commits its own blocks. The f + 1 members that sign
/// on both sides are the culprits; each side has f honest members of its own.
fn fork_among(n: usize, epochs: u64) -> (Committee, EpochConfig, Records, Records) {
    const L: Round = 25;
    let keys = members(n);
    let nowhere: SocketAddr = "127.0.0.1:0".parse().unwrap();
    let roster = Committee::new(keys.iter().map(|(name, _)| (*name, 1, nowhere)).collect(), EPOCH);
    let config = test_epoch_config(L);
    let stakes = Epochs::new(&roster, config).current().clone();
    let table = |epoch: EpochNumber| table_digest(&Committee { epoch, ..stakes.clone() });
    let f = (n - 1) / 3;
    let side_a: Vec<usize> = (0..2 * f + 1).collect();
    let side_b: Vec<usize> = (0..f + 1).chain(2 * f + 1..n).collect();

    let grow = |records: &Records, rounds: Vec<(Round, u64)>, signers: &[usize], tag: u8| {
        let mut chain = records.chain.clone();
        let mut qc = records.high_qc.clone();
        for (round, e) in rounds {
            let (author, secret) = &keys[round as usize % n];
            let mut block = Block::new_from_key(qc, *author, round, vec![Digest([tag; 32])], secret);
            block.epoch = EPOCH + e as EpochNumber;
            block.table = table(block.epoch);
            block.start = e * L;
            block.next_table = if round >= block.start + L { table(block.epoch + 1) } else { Digest::default() };
            block.signature = Signature::new(&block.digest(), secret);
            let digest = vote_digest(block.epoch, &block.digest(), block.round);
            let votes = signers.iter().map(|&i| (keys[i].0, Signature::new(&digest, &keys[i].1))).collect();
            qc = QC { hash: block.digest(), round, epoch: block.epoch, votes };
            chain.push(block);
        }
        Records { chain, high_qc: qc }
    };
    // Epoch e (from 0): blocks from round e * L + 2 (1 in the first epoch) to its terminal block at (e + 1) * L and
    // the child of it.
    let mut rounds = Vec::new();
    for e in 0..epochs - 1 {
        let from = if e == 0 { 1 } else { e * L + 2 };
        rounds.extend((from..=(e + 1) * L + 1).map(|round| (round, e)));
    }
    let last = epochs - 1;
    let from = if last == 0 { 1 } else { last * L + 2 };
    rounds.push((from, last));
    let shared = grow(&Records { chain: Vec::new(), high_qc: QC::genesis() }, rounds, &side_a, 0);
    let own = |signers: &[usize], tag| grow(&shared, (from + 1..=from + 3).map(|round| (round, last)).collect(), signers, tag);
    (roster, config, own(&side_a, 1), own(&side_b, 2))
}

#[test]
#[ignore]
fn package_cost() {
    println!("| n | epochs | culprits | package (bytes) | table chain | commit proofs | evidence | pack (ms) | verify (ms) |");
    println!("|---|---|---|---|---|---|---|---|---|");
    for &n in &[4usize, 10, 31, 100] {
        for &epochs in &[1u64, 5, 25, 100] {
            let (roster, config, a, b) = fork_among(n, epochs);
            let started = Instant::now();
            let (package, _) = pack(&a, &b, &roster, config, true).unwrap();
            let pack_ms = started.elapsed().as_secs_f64() * 1e3;
            let size = |x: usize| x;
            let total = size(bincode::serialize(&package).unwrap().len());
            let links = size(bincode::serialize(&package.links).unwrap().len());
            let commits = size(bincode::serialize(&(&package.x, &package.y, &package.branch)).unwrap().len());
            let evidence = size(bincode::serialize(&package.evidence).unwrap().len());
            let first = first_table(&roster, config);
            let mut times: Vec<f64> = (0..5)
                .map(|_| {
                    let started = Instant::now();
                    let verdict = verify(&package, &first, config.length).unwrap();
                    assert!(verdict.accountable() && verdict.culprits.len() == (n - 1) / 3 + 1);
                    started.elapsed().as_secs_f64() * 1e3
                })
                .collect();
            times.sort_by(|x, y| x.partial_cmp(y).unwrap());
            println!(
                "| {} | {} | {} | {} | {} | {} | {} | {:.1} | {:.2} |",
                n,
                epochs,
                package.evidence.len(),
                total,
                links,
                commits,
                evidence,
                pack_ms,
                times[2]
            );
        }
    }
}
