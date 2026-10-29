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

// ---- G2: AT accusations (prototype/DESIGN.md §12) ---------------------------------------------------------

// The accusation in a TC of the first three fixture keys (all with the genesis QC) with these NR reports.
fn accusation(round: Round, nrs: &[bool]) -> Option<Accusation> {
    let reports: Vec<_> = nrs.iter().map(|nr| (QC::genesis(), *nr)).collect();
    Accusation::from_tc(&tc(round, &reports), &committee())
}

#[test]
fn accusation_from_tc_needs_nr_quorum() {
    // Three of four equal weights are above 2/3: all three signers must report NR = 1.
    let acc = accusation(2, &[true, true, true]).expect("NR quorum");
    assert_eq!((acc.round, acc.epoch, acc.votes.len()), (2, EPOCH, 3));
    assert!(acc.verify(&committee()).is_ok());
    assert!(accusation(2, &[true, true, false]).is_none());
}

#[test]
fn accusation_verification() {
    let acc = accusation(2, &[true, true, true]).unwrap();

    let mut short = acc.clone();
    short.votes.pop();
    assert!(matches!(short.verify(&committee()), Err(ConsensusError::AccusationRequiresQuorum(2))));

    // A timeout signed with NR = 0 does not count as a report of NR = 1.
    let (name, secret) = keys().remove(0);
    let nr0 = Timeout::new_from_key(QC::genesis(), 2, false, name, &secret);
    let mut lying = acc.clone();
    lying.votes[0] = (name, nr0.signature, 0);
    assert!(lying.verify(&committee()).is_err());

    let mut reuse = acc.clone();
    reuse.votes[2] = reuse.votes[0].clone();
    assert!(reuse.verify(&committee()).is_err());

    let mut other = acc.clone();
    other.epoch = EPOCH + 1;
    assert!(other.verify(&committee()).is_err());
}

#[test]
fn block_digest_covers_accusations() {
    let (name, secret) = leader();
    let acc = accusation(2, &[true, true, true]).unwrap();
    let with = Block::new_from_key_with_accusations(qc(), vec![acc], name, 3, &secret);
    let without = Block::new_from_key_with_accusations(qc(), vec![], name, 3, &secret);
    assert_ne!(with.digest(), without.digest());
    assert!(with.verify(&committee()).is_ok());

    let mut tampered = with.clone();
    tampered.accusations.clear();
    assert!(tampered.verify(&committee()).is_err());
}

#[test]
fn block_accusations_are_bounded() {
    let (name, secret) = leader();
    let acc = |round| accusation(round, &[true, true, true]).unwrap();
    let malformed = |b: Block| matches!(b.verify(&committee()), Err(ConsensusError::MalformedBlock(_)));

    // The same round twice.
    assert!(malformed(Block::new_from_key_with_accusations(qc(), vec![acc(2), acc(2)], name, 5, &secret)));
    // A round that is not before the block's.
    assert!(malformed(Block::new_from_key_with_accusations(qc(), vec![acc(5)], name, 5, &secret)));
    // Too many.
    let many: Vec<_> = (1..=MAX_ACCUSATIONS as Round + 1).map(acc).collect();
    assert!(malformed(Block::new_from_key_with_accusations(qc(), many, name, 100, &secret)));
    let enough: Vec<_> = (1..=MAX_ACCUSATIONS as Round).map(acc).collect();
    assert!(Block::new_from_key_with_accusations(qc(), enough, name, 100, &secret).verify(&committee()).is_ok());
}

// ---- G2: inclusion attestations (prototype/DESIGN.md §12.4) ------------------------------------------------

fn otx(account: u64, nonce: u64, tag: u8) -> Otx {
    Otx { account, nonce, data: [tag; 32] }
}

// Attestations of round `round` by the first three fixture keys, each listing the given observed transactions.
fn attestations(round: Round, lists: &[Vec<Digest>]) -> Vec<Attestation> {
    lists
        .iter()
        .zip(keys())
        .map(|(list, (name, secret))| Attestation::new_from_key(round, list.clone(), name, &secret))
        .collect()
}

fn omission(round: Round, block: Digest, x: &Otx, atts: &[Attestation]) -> OmitProof {
    OmitProof {
        round,
        epoch: EPOCH,
        block,
        otx: x.clone(),
        attestations: atts.iter().map(|a| (a.author, a.signature.clone(), a.otxs.clone())).collect(),
    }
}

#[test]
fn otx_ids_and_conflicts() {
    let (a, b, c) = (otx(1, 7, 0), otx(1, 7, 1), otx(1, 8, 0));
    assert_ne!(a.id(), b.id());
    assert_eq!(a.key(), b.key()); // same account and nonce: conflicting
    assert_ne!(a.key(), c.key());
}

#[test]
fn attestation_signs_its_list() {
    let x = otx(1, 1, 0).id();
    let att = &attestations(4, &[vec![x.clone()]])[0];
    assert!(att.verify(&committee()).is_ok());
    let mut longer = att.clone();
    longer.otxs.push(otx(2, 1, 0).id());
    assert!(longer.verify(&committee()).is_err());
    let mut other = att.clone();
    other.epoch = EPOCH + 1;
    assert!(other.verify(&committee()).is_err());
}

#[test]
fn omission_proof_verification() {
    let x = otx(1, 1, 0);
    let y = otx(2, 1, 0);
    let all = attestations(4, &[vec![x.id()], vec![x.id(), y.id()], vec![x.id()]]);
    let proof = omission(4, block().digest(), &x, &all);
    assert!(proof.verify(&committee()).is_ok());

    // Every attestation must list x.
    let some = attestations(4, &[vec![x.id()], vec![y.id()], vec![x.id()]]);
    assert!(omission(4, block().digest(), &x, &some).verify(&committee()).is_err());
    // More than 2/3 of the weight.
    assert!(matches!(
        omission(4, block().digest(), &x, &all[..2]).verify(&committee()),
        Err(ConsensusError::OmissionRequiresQuorum(4))
    ));
    // The signed list is the one carried.
    let mut tampered = proof.clone();
    tampered.attestations[0].2.push(y.id());
    assert!(tampered.verify(&committee()).is_err());
}

#[test]
fn block_digest_covers_otxs_and_omissions() {
    let (name, secret) = leader();
    let x = otx(1, 1, 0);
    let atts = attestations(2, &[vec![x.id()], vec![x.id()], vec![x.id()]]);
    let plain = Block::new_from_key_full(qc(), None, vec![], vec![], vec![], name, 3, vec![], &secret);
    let with_otx = Block::new_from_key_full(qc(), None, vec![], vec![x.clone()], vec![], name, 3, vec![], &secret);
    let proof = omission(2, block().digest(), &x, &atts);
    let with_omission = Block::new_from_key_full(qc(), None, vec![], vec![], vec![proof], name, 3, vec![], &secret);
    assert_ne!(plain.digest(), with_otx.digest());
    assert_ne!(plain.digest(), with_omission.digest());
    assert!(with_otx.verify(&committee()).is_ok() && with_omission.verify(&committee()).is_ok());
    let mut tampered = with_otx.clone();
    tampered.otxs.clear();
    assert!(tampered.verify(&committee()).is_err());
}

#[test]
fn block_otxs_and_omissions_are_bounded() {
    let (name, secret) = leader();
    let malformed = |b: Block| matches!(b.verify(&committee()), Err(ConsensusError::MalformedBlock(_)));
    let make = |otxs: Vec<Otx>, omissions: Vec<OmitProof>| {
        Block::new_from_key_full(qc(), None, vec![], otxs, omissions, name, 5, vec![], &secret)
    };

    let full: Vec<_> = (0..MAX_OTXS as u64).map(|n| otx(9, n, 0)).collect();
    assert!(make(full.clone(), vec![]).verify(&committee()).is_ok());
    let mut over = full;
    over.push(otx(9, 99, 0));
    assert!(malformed(make(over, vec![])));
    // At most one of two conflicting transactions.
    assert!(malformed(make(vec![otx(1, 1, 0), otx(1, 1, 1)], vec![])));

    let x = otx(1, 1, 0);
    let atts = attestations(5, &[vec![x.id()], vec![x.id()], vec![x.id()]]);
    // An omission of a round that is not before the block's.
    assert!(malformed(make(vec![], vec![omission(5, block().digest(), &x, &atts)])));
    // The same omission twice.
    let atts = attestations(4, &[vec![x.id()], vec![x.id()], vec![x.id()]]);
    let proof = omission(4, block().digest(), &x, &atts);
    assert!(malformed(make(vec![], vec![proof.clone(), proof])));
}
