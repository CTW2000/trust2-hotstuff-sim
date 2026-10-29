use super::*;
use crate::common::{block, committee, keys, qc, EPOCH};
use crypto::SecretKey;
use crypto::generate_keypair;
use rand::rngs::StdRng;
use rand::SeedableRng as _;

#[test]
fn verify_valid_qc() {
    assert!(qc().verify(&committee()).is_ok());
}

#[test]
fn verify_qc_authority_reuse() {
    // Modify QC to reuse one authority.
    let mut qc = qc();
    let _ = qc.votes.pop();
    let vote = qc.votes[0].clone();
    qc.votes.push(vote.clone());

    // Verify the QC.
    match qc.verify(&committee()) {
        Err(ConsensusError::AuthorityReuse(name)) => assert_eq!(name, vote.0),
        _ => assert!(false),
    }
}

#[test]
fn verify_qc_unknown_authority() {
    let mut qc = qc();

    // Modify QC to add one unknown authority.
    let mut rng = StdRng::from_seed([1; 32]);
    let (unknown, _) = generate_keypair(&mut rng);
    let (_, sig) = qc.votes.pop().unwrap();
    qc.votes.push((unknown, sig));

    // Verify the QC.
    match qc.verify(&committee()) {
        Err(ConsensusError::UnknownAuthority(name)) => assert_eq!(name, unknown),
        _ => assert!(false),
    }
}

#[test]
fn verify_qc_insufficient_stake() {
    // Modify QC to remove one authority.
    let mut qc = qc();
    let _ = qc.votes.pop();

    // Verify the QC.
    match qc.verify(&committee()) {
        Err(ConsensusError::QCRequiresQuorum) => assert!(true),
        _ => assert!(false),
    }
}

// ---- Trust 2.0 protocol rules (prototype/DESIGN.md, P1) ----------------------------------------------------

// A TC for `round` from the first three fixture keys, with the given (high QC round, NR) per signer.
fn tc(round: Round, reports: &[(QC, bool)]) -> TC {
    let keys = keys();
    let mut high_qc = QC::genesis();
    let votes = reports
        .iter()
        .zip(keys.iter())
        .map(|((qc, nr), (name, secret))| {
            if qc.round > high_qc.round {
                high_qc = qc.clone();
            }
            let timeout = Timeout::new_from_key(qc.clone(), round, *nr, *name, secret);
            (*name, timeout.signature, qc.round, *nr)
        })
        .collect();
    TC { round, epoch: EPOCH, votes, high_qc }
}

fn leader() -> (PublicKey, SecretKey) {
    keys().pop().unwrap()
}

#[test]
fn block_digest_covers_tc() {
    // R1: a vote for the block also commits to the TC it embeds.
    let (name, secret) = leader();
    let reports = [(qc(), false), (qc(), true), (QC::genesis(), true)];
    let with_tc = Block::new_from_key_with_tc(qc(), Some(tc(2, &reports)), name, 3, Vec::new(), &secret);
    let without_tc = Block::new_from_key_with_tc(qc(), None, name, 3, Vec::new(), &secret);
    assert_ne!(with_tc.digest(), without_tc.digest());

    let mut other_reports = reports.clone();
    other_reports[2].1 = false;
    let other_tc = Block::new_from_key_with_tc(qc(), Some(tc(2, &other_reports)), name, 3, Vec::new(), &secret);
    assert_ne!(with_tc.digest(), other_tc.digest());
    assert!(with_tc.verify(&committee()).is_ok());

    // Swapping the TC after signing invalidates the block signature.
    let mut tampered = with_tc.clone();
    tampered.tc = Some(tc(2, &other_reports));
    assert!(tampered.verify(&committee()).is_err());
}

#[test]
fn signatures_carry_the_epoch() {
    // R1: votes, blocks and timeouts of another epoch are rejected, and the epoch is in the signed message.
    let mut b = block();
    b.epoch = EPOCH + 1;
    match b.verify(&committee()) {
        Err(ConsensusError::WrongEpoch { expected, received }) => {
            assert_eq!((expected, received), (EPOCH, EPOCH + 1))
        }
        _ => panic!("block of another epoch accepted"),
    }
    let (name, secret) = leader();
    let vote = Vote::new_from_key(block().digest(), 1, name, &secret);
    assert!(vote.verify(&committee()).is_ok());
    let mut other = vote.clone();
    other.epoch = EPOCH + 1;
    assert_ne!(vote.digest(), other.digest());
    assert!(other.verify(&committee()).is_err());
}

#[test]
fn timeout_signs_nr() {
    // R1/N6: NR is part of the signed timeout; flipping it breaks the signature.
    let (name, secret) = leader();
    let timeout = Timeout::new_from_key(qc(), 2, true, name, &secret);
    assert!(timeout.verify(&committee()).is_ok());
    let mut flipped = timeout.clone();
    flipped.nr = false;
    assert!(flipped.verify(&committee()).is_err());
}

#[test]
fn timeout_high_qc_must_be_older() {
    // R5: the high QC of a timeout is from an earlier round.
    let (name, secret) = leader();
    let timeout = Timeout::new_from_key(qc(), 1, false, name, &secret);
    match timeout.verify(&committee()) {
        Err(ConsensusError::MalformedTimeout(author)) => assert_eq!(author, name),
        _ => panic!("timeout with a high QC of its own round accepted"),
    }
}

#[test]
fn verify_tc_with_reports() {
    // R2: per-signer (high QC round, NR) and the highest QC itself.
    let reports = [(qc(), false), (qc(), true), (QC::genesis(), true)];
    let tc = tc(2, &reports);
    assert!(tc.verify(&committee()).is_ok());
    assert_eq!(tc.high_qc_rounds(), vec![1, 1, 0]);
    assert_eq!(tc.nr_weight(&committee()), 2);

    // A changed NR report no longer matches the signer's signature.
    let mut tampered = tc.clone();
    tampered.votes[0].3 = true;
    assert!(tampered.verify(&committee()).is_err());

    // The embedded QC must be the highest reported one.
    let mut wrong_qc = tc.clone();
    wrong_qc.high_qc = QC::genesis();
    match wrong_qc.verify(&committee()) {
        Err(ConsensusError::MalformedTC(round)) => assert_eq!(round, 2),
        _ => panic!("TC without its highest QC accepted"),
    }
}
