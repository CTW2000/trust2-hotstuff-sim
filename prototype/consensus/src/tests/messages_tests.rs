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
fn attestation_list_is_bounded_and_distinct() {
    // 8.7 / 12.8: a correctly signed attestation is still rejected if its list is too long or repeats an entry.
    // The bound keeps one attestation (and the omission proofs built from it) small; distinct entries make "the
    // weight listing x" the same counted per entry (Inclusion::omissions) or per author (OmitProof::verify).
    let (name, secret) = keys().remove(0);
    let distinct: Vec<Digest> = (0..MAX_ATTESTATION_OTXS as u64).map(|n| otx(1, n, 0).id()).collect();
    assert!(Attestation::new_from_key(4, distinct.clone(), name, &secret).verify(&committee()).is_ok());

    let mut over = distinct;
    over.push(otx(1, MAX_ATTESTATION_OTXS as u64, 0).id());
    assert!(matches!(
        Attestation::new_from_key(4, over, name, &secret).verify(&committee()),
        Err(ConsensusError::MalformedAttestation(4))
    ));

    let x = otx(1, 1, 0).id();
    assert!(matches!(
        Attestation::new_from_key(4, vec![x.clone(), x], name, &secret).verify(&committee()),
        Err(ConsensusError::MalformedAttestation(4))
    ));
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

// ---- G1 evidence (prototype/DESIGN.md §13) ------------------------------------------------------------------

fn qc_of(round: Round) -> QC {
    QC { hash: Digest([round as u8; 32]), round, epoch: EPOCH, votes: Vec::new() }
}

fn signed_timeout(round: Round, high_qc_round: Round, nr: bool, key: &(PublicKey, SecretKey)) -> SignedTimeout {
    let timeout = Timeout::new_from_key(qc_of(high_qc_round), round, nr, key.0, &key.1);
    SignedTimeout::from(&timeout)
}

#[test]
fn double_vote_evidence() {
    let key = keys().remove(0);
    let a = Vote::new_from_key(Digest([1; 32]), 5, key.0, &key.1);
    let b = Vote::new_from_key(Digest([2; 32]), 5, key.0, &key.1);
    let evidence = Evidence::DoubleVote(a.clone(), b.clone());
    assert!(evidence.verify().is_ok());
    assert_eq!((evidence.culprit(), evidence.epoch(), evidence.is_safety()), (key.0, EPOCH, true));

    assert!(Evidence::DoubleVote(a.clone(), a.clone()).verify().is_err()); // the same block
    let other_round = Vote::new_from_key(Digest([2; 32]), 6, key.0, &key.1);
    assert!(Evidence::DoubleVote(a.clone(), other_round).verify().is_err());
    let other = keys().remove(1);
    let someone_else = Vote::new_from_key(Digest([2; 32]), 5, other.0, &other.1);
    assert!(Evidence::DoubleVote(a.clone(), someone_else).verify().is_err());
    let mut forged = b;
    forged.signature = a.signature.clone();
    assert!(Evidence::DoubleVote(a, forged).verify().is_err());
}

#[test]
fn invalid_block_evidence() {
    let (leader_key, voter) = (leader(), keys().remove(0));
    // Round 5 extends a QC of round 1 without a TC: no honest node votes for it.
    let bad = Block::new_from_key(qc_of(1), leader_key.0, 5, Vec::new(), &leader_key.1);
    let vote = Vote::new_from_key(bad.digest(), 5, voter.0, &voter.1);
    assert!(Evidence::InvalidBlock(vote, bad.header()).verify().is_ok());

    // A block of the next round after its QC is valid; a vote for another block proves nothing.
    let good = Block::new_from_key(qc_of(4), leader_key.0, 5, Vec::new(), &leader_key.1);
    let vote = Vote::new_from_key(good.digest(), 5, voter.0, &voter.1);
    assert!(Evidence::InvalidBlock(vote.clone(), good.header()).verify().is_err());
    assert!(Evidence::InvalidBlock(vote, bad.header()).verify().is_err());
}

#[test]
fn regression_evidence() {
    let (leader_key, voter) = (leader(), keys().remove(0));
    // A vote at round 3 for a block certifying round 2, then a timeout at round >= 3 reporting hq 1 < 2.
    let block = Block::new_from_key(qc_of(2), leader_key.0, 3, Vec::new(), &leader_key.1);
    let vote = Vote::new_from_key(block.digest(), 3, voter.0, &voter.1);
    let e3 = |timeout| Evidence::Regression(vote.clone(), block.header(), timeout);
    assert!(e3(signed_timeout(4, 1, false, &voter)).verify().is_ok());
    assert!(e3(signed_timeout(3, 1, false, &voter)).verify().is_ok()); // the same round
    assert!(e3(signed_timeout(4, 2, false, &voter)).verify().is_err()); // hq not below j
    assert!(e3(signed_timeout(2, 1, false, &voter)).verify().is_err()); // the timeout is earlier
    assert!(e3(signed_timeout(4, 1, false, &leader_key)).verify().is_err()); // someone else's timeout
}

#[test]
fn nr_contradiction_evidence() {
    let voter = keys().remove(0);
    let vote = Vote::new_from_key(Digest([1; 32]), 5, voter.0, &voter.1);
    let evidence = Evidence::NrContradiction(vote.clone(), signed_timeout(5, 4, true, &voter));
    assert!(evidence.verify().is_ok());
    assert!(!evidence.is_safety());
    assert!(Evidence::NrContradiction(vote.clone(), signed_timeout(5, 4, false, &voter)).verify().is_err());
    assert!(Evidence::NrContradiction(vote.clone(), signed_timeout(6, 4, true, &voter)).verify().is_err());
    let mut flipped = signed_timeout(5, 4, false, &voter);
    flipped.nr = true; // NR is in the signed message
    assert!(Evidence::NrContradiction(vote, flipped).verify().is_err());
}

#[test]
fn block_digest_covers_evidence() {
    let (name, secret) = leader();
    let voter = keys().remove(0);
    let a = Vote::new_from_key(Digest([1; 32]), 5, voter.0, &voter.1);
    let b = Vote::new_from_key(Digest([2; 32]), 5, voter.0, &voter.1);
    let evidence = vec![Evidence::DoubleVote(a, b)];
    let with = Block::new_from_key_evidence(qc(), evidence.clone(), name, 6, &secret);
    let without = Block::new_from_key_evidence(qc(), vec![], name, 6, &secret);
    assert_ne!(with.digest(), without.digest());
    assert!(with.verify(&committee()).is_ok());
    let mut tampered = with.clone();
    tampered.evidence.clear();
    assert!(tampered.verify(&committee()).is_err());
    let many = vec![evidence[0].clone(); MAX_EVIDENCE + 1];
    let over = Block::new_from_key_evidence(qc(), many, name, 6, &secret);
    assert!(matches!(over.verify(&committee()), Err(ConsensusError::MalformedBlock(_))));
}

#[test]
fn block_header_hashes_to_the_block_digest() {
    // N1: evidence carries the header of the block it is about. The header must hash to the block's digest -- the
    // culprit's vote is a signature on that digest -- for every field the digest covers.
    let (name, secret) = leader();
    let voter = keys().remove(0);
    let a = Vote::new_from_key(Digest([1; 32]), 5, voter.0, &voter.1);
    let b = Vote::new_from_key(Digest([2; 32]), 5, voter.0, &voter.1);
    let otx = Otx { account: 1, nonce: 1, data: [3; 32] };
    let block = Block {
        tc: Some(tc(5, &[(qc(), false), (qc(), true), (qc(), false)])),
        accusations: vec![Accusation { round: 3, epoch: EPOCH, votes: Vec::new() }],
        otxs: vec![otx.clone()],
        omissions: vec![OmitProof { round: 2, epoch: EPOCH, block: Digest([4; 32]), otx, attestations: Vec::new() }],
        evidence: vec![Evidence::DoubleVote(a, b)],
        payload: vec![Digest([5; 32])],
        ..Block::new_from_key(qc(), name, 6, Vec::new(), &secret)
    };
    assert_eq!(block.header().digest(), block.digest());
    let mut moved = block.header();
    moved.evidence.clear();
    assert_ne!(moved.digest(), block.digest());
}

#[test]
fn reporting_a_block_as_evidence_does_not_nest() {
    // N1: a block may report (in its evidence) a block that reports a block ... Evidence keeps only the reported
    // block's header -- its own evidence as digests -- so every such block stays the same size and deserializes:
    // an honest node can always report a block it accepted, and no message nests deep enough to hurt the stack.
    // (Before, evidence embedded the whole block, so each report added a level; with a depth limit, a block at the
    // limit was accepted but the honest block reporting it could no longer be deserialized by anyone.)
    let (name, secret) = leader();
    let voter = keys().remove(0);
    let mut block = Block::default();
    let mut sizes = Vec::new();
    for _ in 0..50 {
        let vote = Vote::new_from_key(block.digest(), block.round, voter.0, &voter.1);
        block = Block::new_from_key_evidence(qc(), vec![Evidence::InvalidBlock(vote, block.header())], name, 6, &secret);
        let bytes = bincode::serialize(&block).unwrap();
        let back: Block = bincode::deserialize(&bytes).expect("every report deserializes");
        assert_eq!(back.digest(), block.digest());
        sizes.push(bytes.len());
    }
    assert!(sizes[1..].iter().all(|s| *s == sizes[1]), "size must not grow with the reporting depth: {:?}", sizes);
}

#[test]
fn handover_leader_may_propose_without_weight() {
    // The first round of an epoch keeps the old table's leader even when the new table suspends it (it holds
    // the commit proof); its block is accepted although it has no weight (DESIGN.md §13.5).
    let (name, secret) = leader();
    let mut committee = committee();
    committee.authorities.get_mut(&name).unwrap().stake = 0;
    let block = Block::new_from_key(qc(), name, 3, Vec::new(), &secret);
    assert!(matches!(block.verify(&committee), Err(ConsensusError::UnknownAuthority(_))));
    committee.handover = Some((3, name));
    assert!(block.verify(&committee).is_ok());
    let later = Block::new_from_key(qc(), name, 4, Vec::new(), &secret);
    assert!(later.verify(&committee).is_err());
}
