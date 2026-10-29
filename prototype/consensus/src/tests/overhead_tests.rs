//! X1 (prototype/DESIGN.md §14.3): serialized message sizes, the cost of verifying G1/G2 evidence, and the cost of
//! an epoch change. Prints one JSON object per committee size.
//! Run:  cargo test --release -p consensus overhead -- --ignored --nocapture
use crate::config::Committee;
use crate::epoch::{EpochConfig, Epochs};
use crate::messages::{
    Accusation, Attestation, Block, Evidence, OmitProof, Otx, SignedTimeout, Timeout, Vote, QC, TC,
};
use crypto::Hash as _;
use crypto::{generate_keypair, Digest, PublicKey, SecretKey, Signature};
use rand::rngs::StdRng;
use rand::SeedableRng as _;
use std::time::Instant;

const EPOCH: u128 = 1;

fn keys(n: usize) -> Vec<(PublicKey, SecretKey)> {
    let mut rng = StdRng::from_seed([1; 32]);
    (0..n).map(|_| generate_keypair(&mut rng)).collect()
}

fn committee(keys: &[(PublicKey, SecretKey)]) -> Committee {
    let info = keys
        .iter()
        .enumerate()
        .map(|(i, (name, _))| (*name, 1, format!("127.0.0.1:{}", 10_000 + i).parse().unwrap()))
        .collect();
    Committee::new(info, EPOCH)
}

fn qc(keys: &[(PublicKey, SecretKey)], hash: Digest, round: u64) -> QC {
    let votes = keys
        .iter()
        .map(|(name, secret)| {
            let vote = Vote { hash: hash.clone(), round, epoch: EPOCH, author: *name, signature: Signature::default() };
            (*name, Signature::new(&vote.digest(), secret))
        })
        .collect();
    QC { hash, round, epoch: EPOCH, votes }
}

fn signed_vote(hash: Digest, round: u64, key: &(PublicKey, SecretKey)) -> Vote {
    let vote = Vote { hash, round, epoch: EPOCH, author: key.0, signature: Signature::default() };
    Vote { signature: Signature::new(&vote.digest(), &key.1), ..vote }
}

fn attestation(round: u64, otxs: Vec<Digest>, key: &(PublicKey, SecretKey)) -> Attestation {
    let attestation = Attestation { round, epoch: EPOCH, otxs, author: key.0, signature: Signature::default() };
    Attestation { signature: Signature::new(&attestation.digest(), &key.1), ..attestation }
}

fn timeout(high_qc: &QC, round: u64, nr: bool, key: &(PublicKey, SecretKey)) -> Timeout {
    let timeout = Timeout {
        high_qc: high_qc.clone(),
        round,
        epoch: EPOCH,
        nr,
        author: key.0,
        signature: Signature::default(),
    };
    Timeout { signature: Signature::new(&timeout.digest(), &key.1), ..timeout }
}

fn tc(keys: &[(PublicKey, SecretKey)], high_qc: &QC, round: u64, nr: bool) -> TC {
    let votes = keys
        .iter()
        .map(|key| {
            let t = timeout(high_qc, round, nr, key);
            (key.0, t.signature, high_qc.round, nr)
        })
        .collect();
    TC { round, epoch: EPOCH, votes, high_qc: high_qc.clone() }
}

fn size<T: serde::Serialize>(x: &T) -> usize {
    bincode::serialize(x).unwrap().len()
}

/// Mean microseconds of `f` over `times` runs.
fn time<F: FnMut()>(times: u32, mut f: F) -> f64 {
    let start = Instant::now();
    for _ in 0..times {
        f();
    }
    start.elapsed().as_secs_f64() * 1e6 / times as f64
}

#[test]
#[ignore]
fn overhead() {
    for n in [4usize, 31, 100] {
        let keys = keys(n);
        let committee = committee(&keys);
        let q = 2 * n / 3 + 1;
        let quorum = &keys[..q];
        let hash = Digest([7; 32]);
        let qc5 = qc(quorum, hash.clone(), 5);
        let tc6 = tc(quorum, &qc5, 6, false);
        let block = |tc: Option<TC>, payload: usize| Block {
            qc: qc5.clone(),
            tc,
            author: keys[0].0,
            round: 7,
            epoch: EPOCH,
            payload: (0..payload).map(|i| Digest([i as u8; 32])).collect(),
            ..Block::default()
        };
        let vote = signed_vote(hash.clone(), 5, &keys[0]);
        let accusation = Accusation::from_tc(&tc(quorum, &qc5, 6, true), &committee).unwrap();
        let x = Otx { account: 1, nonce: 1, data: [0; 32] };
        let attestations: Vec<_> = quorum
            .iter()
            .map(|key| attestation(6, vec![x.id()], key))
            .collect();
        let omission = OmitProof {
            round: 6,
            epoch: EPOCH,
            block: block(None, 0).digest(),
            otx: x.clone(),
            attestations: attestations.iter().map(|a| (a.author, a.signature.clone(), a.otxs.clone())).collect(),
        };
        let other = signed_vote(Digest([8; 32]), 5, &keys[0]);
        let e1 = Evidence::DoubleVote(vote.clone(), other);
        let nr = Evidence::NrContradiction(vote.clone(), SignedTimeout::from(&timeout(&qc5, 5, true, &keys[0])));

        let reps = if n == 100 { 20 } else { 100 };
        let verify_qc = time(reps, || qc5.verify(&committee).unwrap());
        let verify_tc = time(reps, || tc6.verify(&committee).unwrap());
        let verify_accusation = time(reps, || accusation.verify(&committee).unwrap());
        let verify_omission = time(reps, || omission.verify(&committee).unwrap());
        let verify_e1 = time(reps, || e1.verify().unwrap());

        // Epoch changes with some accusations on the ledger each epoch.
        let config = EpochConfig {
            length: 100,
            entity_cap_ppm: 1_000_000,
            class_cap_ppm: 1_000_000,
            l_max_ppm: 100_000,
            governance_malicious: false,
        };
        let mut epochs = Epochs::new(&committee, config);
        let mut changes = Vec::new();
        for k in 1..=40u64 {
            let accused: Vec<Accusation> = (0..3)
                .map(|i| Accusation { round: 100 * k - 10 * i, ..accusation.clone() })
                .collect();
            epochs.record(&Block { epoch: EPOCH + k as u128 - 1, round: 100 * k - 1, accusations: accused, ..Block::default() });
            let terminal = Block { epoch: EPOCH + k as u128 - 1, round: 100 * k, ..Block::default() };
            let start = Instant::now();
            epochs.enter_next(&terminal);
            changes.push(start.elapsed().as_secs_f64() * 1e6);
        }
        changes.sort_by(|a, b| a.partial_cmp(b).unwrap());

        println!(
            "{{\"n\": {}, \"quorum\": {}, \"bytes\": {{\"vote\": {}, \"timeout\": {}, \"qc\": {}, \"tc\": {}, \
             \"block_empty\": {}, \"block_tc\": {}, \"block_100\": {}, \"accusation\": {}, \"attestation\": {}, \
             \"omission\": {}, \"e1\": {}, \"nr\": {}}}, \"us\": {{\"verify_qc\": {:.0}, \"verify_tc\": {:.0}, \
             \"verify_accusation\": {:.0}, \"verify_omission\": {:.0}, \"verify_e1\": {:.0}, \
             \"epoch_change_median\": {:.0}, \"epoch_change_max\": {:.0}}}}}",
            n,
            q,
            size(&vote),
            size(&timeout(&qc5, 6, false, &keys[0])),
            size(&qc5),
            size(&tc6),
            size(&block(None, 0)),
            size(&block(Some(tc6.clone()), 0)),
            size(&block(None, 100)),
            size(&accusation),
            size(&attestations[0]),
            size(&omission),
            size(&e1),
            size(&nr),
            verify_qc,
            verify_tc,
            verify_accusation,
            verify_omission,
            verify_e1,
            changes[changes.len() / 2],
            changes[changes.len() - 1],
        );
    }
}
