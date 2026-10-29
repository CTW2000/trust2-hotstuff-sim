//! X1 for the baseline (prototype/DESIGN.md §14.3): serialized message sizes and certificate verification, to compare
//! with prototype/consensus/src/tests/overhead_tests.rs. Prints one JSON object per committee size.
//! Run:  cargo test --release -p consensus overhead -- --ignored --nocapture
use crate::config::Committee;
use crate::messages::{Block, Timeout, Vote, QC, TC};
use crypto::Hash as _;
use crypto::{generate_keypair, Digest, PublicKey, SecretKey, Signature};
use rand::rngs::StdRng;
use rand::SeedableRng as _;
use std::time::Instant;

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
    Committee::new(info, 1)
}

fn qc(keys: &[(PublicKey, SecretKey)], hash: Digest, round: u64) -> QC {
    let votes = keys
        .iter()
        .map(|(name, secret)| {
            let vote = Vote { hash: hash.clone(), round, author: *name, signature: Signature::default() };
            (*name, Signature::new(&vote.digest(), secret))
        })
        .collect();
    QC { hash, round, votes }
}

fn timeout(high_qc: &QC, round: u64, key: &(PublicKey, SecretKey)) -> Timeout {
    let timeout = Timeout { high_qc: high_qc.clone(), round, author: key.0, signature: Signature::default() };
    Timeout { signature: Signature::new(&timeout.digest(), &key.1), ..timeout }
}

fn size<T: serde::Serialize>(x: &T) -> usize {
    bincode::serialize(x).unwrap().len()
}

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
        let tc6 = TC {
            round: 6,
            votes: quorum.iter().map(|k| (k.0, timeout(&qc5, 6, k).signature, qc5.round)).collect(),
        };
        let block = |tc: Option<TC>, payload: usize| Block {
            qc: qc5.clone(),
            tc,
            author: keys[0].0,
            round: 7,
            payload: (0..payload).map(|i| Digest([i as u8; 32])).collect(),
            signature: Signature::default(),
        };
        let vote = Vote { hash: hash.clone(), round: 5, author: keys[0].0, signature: Signature::default() };
        let reps = if n == 100 { 20 } else { 100 };
        let verify_qc = time(reps, || qc5.verify(&committee).unwrap());
        let verify_tc = time(reps, || tc6.verify(&committee).unwrap());
        println!(
            "{{\"n\": {}, \"quorum\": {}, \"bytes\": {{\"vote\": {}, \"timeout\": {}, \"qc\": {}, \"tc\": {}, \
             \"block_empty\": {}, \"block_tc\": {}, \"block_100\": {}}}, \"us\": {{\"verify_qc\": {:.0}, \
             \"verify_tc\": {:.0}}}}}",
            n,
            q,
            size(&vote),
            size(&timeout(&qc5, 6, &keys[0])),
            size(&qc5),
            size(&tc6),
            size(&block(None, 0)),
            size(&block(Some(tc6.clone()), 0)),
            size(&block(None, 100)),
            verify_qc,
            verify_tc,
        );
    }
}
