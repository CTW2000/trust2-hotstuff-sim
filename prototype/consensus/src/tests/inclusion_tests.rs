use super::*;
use crate::common::{committee, keys, EPOCH};

const GUARD: Duration = Duration::from_millis(100);

fn otx(account: u64, nonce: u64) -> Otx {
    Otx { account, nonce, data: [0; 32] }
}

fn block(round: Round, otxs: Vec<Otx>) -> Block {
    Block { round, epoch: EPOCH, otxs, ..Block::default() }
}

// Attestations of `round` by the first `n` fixture keys, each listing `list`.
fn attest_all(inclusion: &mut Inclusion, round: Round, n: usize, list: &[Digest]) -> Vec<OmitProof> {
    let mut proofs = Vec::new();
    for (name, secret) in keys().into_iter().take(n) {
        let attestation = Attestation::new_from_key(round, list.to_vec(), name, &secret);
        proofs.extend(inclusion.attest(attestation, &committee()));
    }
    proofs
}

#[test]
fn forwards_once_and_attests_after_the_guard() {
    let mut inclusion = Inclusion::new(GUARD, false);
    let t0 = Instant::now();
    let x = otx(1, 1);
    assert!(inclusion.receive(x.clone(), t0));
    assert!(!inclusion.receive(x.clone(), t0)); // forwarded already
    assert!(inclusion.to_attest(t0 + GUARD - Duration::from_millis(1)).is_empty());
    assert_eq!(inclusion.to_attest(t0 + GUARD), vec![x.id()]);
}

#[test]
fn leader_selects_oldest_first_without_conflicts() {
    let mut inclusion = Inclusion::new(GUARD, false);
    let t0 = Instant::now();
    let (a, b, c) = (otx(1, 1), Otx { data: [1; 32], ..otx(1, 1) }, otx(2, 1));
    for x in [&a, &b, &c] {
        inclusion.receive(x.clone(), t0);
    }
    assert_eq!(inclusion.select(), vec![a.clone(), c.clone()]); // b conflicts with the older a

    for n in 0..2 * MAX_OTXS as u64 {
        inclusion.receive(otx(3, n), t0);
    }
    assert_eq!(inclusion.select().len(), MAX_OTXS);

    // Once a is in a certified block it is no longer pending, and b can never be included.
    inclusion.certify(&block(4, vec![a.clone()]), &committee());
    let selected = inclusion.select();
    assert!(!selected.contains(&a) && !selected.contains(&b) && selected[0] == c);
    assert!(!inclusion.to_attest(t0 + GUARD).contains(&b.id()));
}

#[test]
fn certified_block_omitting_a_due_transaction_gives_a_proof() {
    let x = otx(1, 1);
    let check = |inclusion: &mut Inclusion, certified: Block| -> Vec<OmitProof> {
        let mut proofs = attest_all(inclusion, 5, 3, &[x.id()]);
        proofs.extend(inclusion.certify(&certified, &committee()));
        proofs
    };
    let fresh = || {
        let mut inclusion = Inclusion::new(GUARD, false);
        inclusion.receive(x.clone(), Instant::now());
        inclusion
    };

    // Left out by the certified block of round 5: one proof, valid, made once.
    let mut inclusion = fresh();
    let b5 = block(5, vec![otx(2, 1)]);
    let proofs = check(&mut inclusion, b5.clone());
    assert_eq!(proofs.len(), 1);
    assert_eq!((proofs[0].round, proofs[0].block.clone(), proofs[0].otx.clone()), (5, b5.digest(), x.clone()));
    assert!(proofs[0].verify(&committee()).is_ok());
    assert!(attest_all(&mut inclusion, 5, 4, &[x.id()]).is_empty());

    // Attestations arriving after the certification complete the proof too.
    let mut inclusion = fresh();
    assert!(inclusion.certify(&b5, &committee()).is_empty());
    assert_eq!(attest_all(&mut inclusion, 5, 3, &[x.id()]).len(), 1);

    // No proof: included, two thirds not exceeded, block full, conflicting transaction in it or before it.
    assert!(check(&mut fresh(), block(5, vec![x.clone()])).is_empty());
    let mut inclusion = fresh();
    assert!(attest_all(&mut inclusion, 5, 2, &[x.id()]).is_empty());
    assert!(inclusion.certify(&b5, &committee()).is_empty());
    let full: Vec<_> = (0..MAX_OTXS as u64).map(|n| otx(9, n)).collect();
    assert!(check(&mut fresh(), block(5, full)).is_empty());
    let rival = Otx { data: [7; 32], ..x.clone() };
    assert!(check(&mut fresh(), block(5, vec![rival.clone()])).is_empty());
    let mut inclusion = fresh();
    inclusion.certify(&block(4, vec![rival]), &committee());
    assert!(check(&mut inclusion, b5.clone()).is_empty());

    // Included in an earlier certified block: not an omission at round 5.
    let mut inclusion = fresh();
    inclusion.certify(&block(4, vec![x.clone()]), &committee());
    assert!(check(&mut inclusion, b5).is_empty());
}

#[test]
fn repeated_entries_do_not_inflate_the_quorum() {
    // 12.8: one attester listing x three times is still one author's weight, below the quorum of a 4-member
    // committee, so no proof is built. Counting per list entry (before the fix) reached the quorum and produced
    // a proof that every other node, counting per author, then rejected -- which could stall the chain.
    let x = otx(1, 1);
    let mut inclusion = Inclusion::new(GUARD, false);
    inclusion.receive(x.clone(), Instant::now());
    assert!(inclusion.certify(&block(5, vec![otx(2, 1)]), &committee()).is_empty());
    let (name, secret) = keys().remove(0);
    let repeated = Attestation::new_from_key(5, vec![x.id(), x.id(), x.id()], name, &secret);
    assert!(inclusion.attest(repeated, &committee()).is_empty());
}

#[test]
fn pending_table_is_bounded() {
    // 8.5 / 1.13: the pending buffer has a ceiling. Once it is full, a new distinct observed transaction is
    // refused (neither forwarded, attested nor included) rather than letting a flood of distinct transactions
    // -- which may never reach a certified block -- grow memory without bound. Transactions we already hold are
    // still deduplicated as before, so the cap never rejects a repeat.
    let mut inclusion = Inclusion::new(GUARD, false);
    inclusion.max_pending = 3;
    let t0 = Instant::now();
    assert!(inclusion.receive(otx(1, 1), t0));
    assert!(inclusion.receive(otx(1, 2), t0));
    assert!(inclusion.receive(otx(1, 3), t0));
    // Full: a fourth distinct transaction is refused and does not join the pending set.
    assert!(!inclusion.receive(otx(1, 4), t0));
    assert_eq!(inclusion.select().len(), 3);
    assert!(!inclusion.to_attest(t0 + GUARD).contains(&otx(1, 4).id()));
    // A transaction we already hold is still deduplicated (not an insert), so the cap does not reject it.
    assert!(!inclusion.receive(otx(1, 1), t0));
}

#[test]
fn censor_ignores_victim_transactions() {
    let mut inclusion = Inclusion::new(GUARD, true);
    let t0 = Instant::now();
    let (victim_tx, other) = (otx(4, 1), otx(5, 1));
    assert!(victim(&victim_tx) && !victim(&other));
    assert!(!inclusion.receive(victim_tx, t0));
    assert!(inclusion.receive(other.clone(), t0));
    assert_eq!(inclusion.select(), vec![other.clone()]);
    assert_eq!(inclusion.to_attest(t0 + GUARD), vec![other.id()]);
}
