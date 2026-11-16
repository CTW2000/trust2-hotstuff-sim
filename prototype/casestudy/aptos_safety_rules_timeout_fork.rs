// Case study for Trust 2.0 (prototype/DESIGN.md §15.37): a fork that goes through a timeout certificate, driven
// through the safety-rules module of aptos-core. Put this file at
//     consensus/safety-rules/src/tests/twins_timeout_fork.rs
// add `mod twins_timeout_fork;` to consensus/safety-rules/src/tests/mod.rs, and run
//     cargo test -p aptos-safety-rules twins_timeout_fork -- --nocapture
//
// Every vote and every timeout below is signed by an unmodified `SafetyRules` instance through its public interface;
// nothing is signed outside its rules. Two of the four validators run a second instance with the same key and a
// fresh safety storage (a "twin"), which is beyond the fault assumption of one in four. The question is not whether
// the ledger can fork then, but what the records left behind allow one to prove afterwards. Nothing here touches a
// deployed network: the test builds blocks and certificates in memory.

use crate::{
    persistent_safety_storage::PersistentSafetyStorage,
    test_utils::{self, Proof},
    SafetyRules, TSafetyRules,
};
use aptos_consensus_types::{
    block::Block,
    common::{Author, Payload, Round},
    quorum_cert::QuorumCert,
    timeout_2chain::{TwoChainTimeout, TwoChainTimeoutCertificate, TwoChainTimeoutWithPartialSignatures},
    vote::Vote,
    vote_proposal::VoteProposal,
};
use aptos_crypto::HashValue;
use aptos_secure_storage::{InMemoryStorage, Storage};
use aptos_types::{
    aggregate_signature::{AggregateSignature, PartialSignatures},
    epoch_change::EpochChangeProof,
    ledger_info::{LedgerInfoWithSignatures, LedgerInfoWithVerifiedSignatures},
    validator_signer::ValidatorSigner,
    validator_verifier::{generate_validator_verifier, ValidatorVerifier},
};
use std::collections::{HashMap, HashSet};

/// A safety-rules instance of `signer` with a fresh safety storage, in the epoch of `proof`.
fn instance(signer: &ValidatorSigner, all: &[&ValidatorSigner], proof: &EpochChangeProof) -> SafetyRules {
    let storage = PersistentSafetyStorage::initialize(
        Storage::from(InMemoryStorage::new()),
        signer.author(),
        signer.private_key().clone(),
        test_utils::validator_signers_to_waypoint(all),
        true,
    );
    let mut safety_rules = SafetyRules::new(storage, false);
    safety_rules.initialize(proof).unwrap();
    safety_rules
}

/// The QC made of the votes the instances gave for one proposal.
fn certify(votes: &[Vote], verifier: &ValidatorVerifier) -> QuorumCert {
    let mut ledger_info =
        LedgerInfoWithVerifiedSignatures::new(votes[0].ledger_info().clone(), PartialSignatures::empty());
    for vote in votes {
        assert_eq!(vote.vote_data(), votes[0].vote_data());
        ledger_info.add_signature(
            vote.author(),
            vote.signature_with_status().decompressed_signature().unwrap(),
        );
    }
    QuorumCert::new(
        votes[0].vote_data().clone(),
        ledger_info.aggregate_signatures(verifier).unwrap(),
    )
}

/// The proposal of `round` by `proposer` that extends `parent` with its QC `qc`.
fn child(round: Round, parent: &VoteProposal, qc: QuorumCert, proposer: &ValidatorSigner) -> VoteProposal {
    let parent_output = parent
        .accumulator_extension_proof()
        .verify(parent.block().quorum_cert().certified_block().executed_state_id())
        .unwrap();
    let proof = Proof::new(
        parent_output.frozen_subtree_roots().clone(),
        parent_output.num_leaves(),
        vec![],
    );
    let block = Block::new_proposal(
        Payload::empty(false),
        round,
        parent.block().timestamp_usecs() + 1,
        qc,
        proposer,
        Vec::new(),
    )
    .unwrap();
    VoteProposal::new(proof, block, None, false)
}

/// The timeout certificate of `round` made of the timeouts the instances sign, each reporting `hqc`.
fn time_out(
    instances: &mut [(&ValidatorSigner, &mut SafetyRules)],
    round: Round,
    hqc: &QuorumCert,
    last_tc: Option<&TwoChainTimeoutCertificate>,
    verifier: &ValidatorVerifier,
) -> TwoChainTimeoutCertificate {
    let timeout = TwoChainTimeout::new(1, round, hqc.clone());
    let mut partial = TwoChainTimeoutWithPartialSignatures::new(timeout.clone());
    for (signer, safety_rules) in instances.iter_mut() {
        let signature = safety_rules.sign_timeout_with_qc(&timeout, last_tc).unwrap();
        partial.add(signer.author(), timeout.clone(), signature);
    }
    partial.aggregate_signatures(verifier).unwrap()
}

fn vote_all(
    instances: &mut [(&ValidatorSigner, &mut SafetyRules)],
    proposal: &VoteProposal,
    tc: Option<&TwoChainTimeoutCertificate>,
) -> Vec<Vote> {
    instances
        .iter_mut()
        .map(|(_, safety_rules)| safety_rules.construct_and_sign_vote_two_chain(proposal, tc).unwrap())
        .collect()
}

#[test]
fn twins_timeout_fork() {
    // Four validators of equal voting power; three are a quorum.
    let signers: Vec<ValidatorSigner> = (0..4).map(ValidatorSigner::from_int).collect();
    let all: Vec<&ValidatorSigner> = signers.iter().collect();
    let verifier = generate_validator_verifier(&signers);
    let addresses = verifier.get_ordered_account_addresses();

    let genesis_li = test_utils::validator_signers_to_ledger_info(&all);
    let genesis = Block::make_genesis_block_from_ledger_info(&genesis_li);
    let genesis_qc = QuorumCert::certificate_for_genesis_from_ledger_info(&genesis_li, genesis.id());
    let proof = EpochChangeProof::new(
        vec![LedgerInfoWithSignatures::new(genesis_li, AggregateSignature::empty())],
        false,
    );

    // Side one: validators 0, 1 and 2. Side two: validator 3 and the twins of validators 0 and 1.
    let (mut v0, mut v1, mut v2) = (
        instance(&signers[0], &all, &proof),
        instance(&signers[1], &all, &proof),
        instance(&signers[2], &all, &proof),
    );
    let (mut twin0, mut twin1, mut v3) = (
        instance(&signers[0], &all, &proof),
        instance(&signers[1], &all, &proof),
        instance(&signers[3], &all, &proof),
    );

    // Side one certifies the blocks of rounds 1 and 2; the QC of round 2 commits the block of round 1.
    let b1 = test_utils::make_proposal_with_qc(1, genesis_qc.clone(), &signers[2]);
    let (qc1, b2, qc2) = {
        let mut side_one = [(&signers[0], &mut v0), (&signers[1], &mut v1), (&signers[2], &mut v2)];
        let qc1 = certify(&vote_all(&mut side_one, &b1, None), &verifier);
        let b2 = child(2, &b1, qc1.clone(), &signers[2]);
        let qc2 = certify(&vote_all(&mut side_one, &b2, None), &verifier);
        (qc1, b2, qc2)
    };
    assert_eq!(qc2.commit_info().id(), b1.block().id());

    // Side two hears no proposal in rounds 1 and 2: its instances time out, reporting the genesis QC as their
    // highest. In round 3 a block extends the genesis under the timeout certificate of round 2; its QC is as high
    // as every QC the certificate reports, so the instances vote for it, and the QC of round 4 commits it.
    let (tc2, b3, qc3, qc4) = {
        let mut side_two = [(&signers[0], &mut twin0), (&signers[1], &mut twin1), (&signers[3], &mut v3)];
        let tc1 = time_out(&mut side_two, 1, &genesis_qc, None, &verifier);
        let tc2 = time_out(&mut side_two, 2, &genesis_qc, Some(&tc1), &verifier);
        let b3 = test_utils::make_proposal_with_qc(3, genesis_qc.clone(), &signers[3]);
        let qc3 = certify(&vote_all(&mut side_two, &b3, Some(&tc2)), &verifier);
        let b4 = child(4, &b3, qc3.clone(), &signers[3]);
        let qc4 = certify(&vote_all(&mut side_two, &b4, None), &verifier);
        (tc2, b3, qc3, qc4)
    };
    assert_eq!(qc4.commit_info().id(), b3.block().id());

    // 1. The two committed blocks conflict: the one of side two extends the genesis, not the block of round 1.
    assert_ne!(b1.block().id(), b3.block().id());
    assert_eq!(b3.block().quorum_cert().certified_block().round(), 0);
    assert_eq!(b2.block().quorum_cert().certified_block().id(), b1.block().id());

    // 2. What the two ledgers hold is blocks and QCs. In those QCs no validator voted for two blocks of one round.
    let mut voted: HashMap<(Author, Round), HashSet<HashValue>> = HashMap::new();
    for qc in [&qc1, &qc2, &qc3, &qc4] {
        for voter in qc.ledger_info().get_voters(&addresses) {
            voted
                .entry((voter, qc.certified_block().round()))
                .or_default()
                .insert(qc.certified_block().id());
        }
    }
    let double_votes = voted.values().filter(|blocks| blocks.len() > 1).count();
    assert_eq!(double_votes, 0);

    // 3. The timeout certificate under which side two voted in round 3 is in no block. With it: the validators
    // that voted for the block of round 2 on side one, which certifies round 1, and reported a highest QC of round
    // 0 in a timeout of round 2.
    let x_plus_voters: HashSet<Author> = qc2.ledger_info().get_voters(&addresses).into_iter().collect();
    let reports = tc2.signatures_with_rounds().get_voters_and_rounds(&addresses);
    let culprits: HashSet<Author> = reports
        .iter()
        .filter(|(author, hqc_round)| {
            *hqc_round < qc2.parent_block().round() && tc2.round() >= qc2.certified_block().round() && x_plus_voters.contains(author)
        })
        .map(|(author, _)| *author)
        .collect();
    let twins: HashSet<Author> = [signers[0].author(), signers[1].author()].into_iter().collect();
    assert_eq!(culprits, twins);

    println!(
        "[TimeoutFork] side one committed round {} (QCs of rounds 1, 2 by {} validators); side two committed round {} on a parent of round {}",
        qc2.commit_info().round(),
        x_plus_voters.len(),
        qc4.commit_info().round(),
        b3.block().quorum_cert().certified_block().round()
    );
    println!(
        "[TimeoutFork] from the QCs of both sides: {} validators with two votes in one round",
        double_votes
    );
    println!(
        "[TimeoutFork] with the timeout certificate of round {} (highest QC round {}, {} signers): {} of {} validators contradict themselves",
        tc2.round(),
        tc2.highest_hqc_round(),
        reports.len(),
        culprits.len(),
        addresses.len()
    );
}
