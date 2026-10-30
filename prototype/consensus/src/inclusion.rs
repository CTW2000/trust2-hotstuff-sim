//! G2 inclusion attestations at one node (prototype/DESIGN.md §12.4; the simulator's model is sim2/txlayer.py).
//!
//! - Observed transactions are forwarded to every node on first receipt and stay pending until we see them in
//!   a certified block.
//! - On entering a round we attest the pending ones held for at least the guard Δ_g.
//! - As leader we include the pending ones we hold, oldest first, at most MAX_OTXS, never two conflicting.
//! - When a block we hold is certified, a transaction listed by attestations of its round from more than 2/3
//!   of the weight that the block leaves out, without an exemption (full block, or a conflicting transaction
//!   already included), gives an omission proof for the ledger.
//! - A certified block can still be abandoned (a TC extended an older QC). Once the chain has passed its round,
//!   what it held counts as never included and is pending again.
//!
//! `censor` is an experiment switch (not part of the protocol): the node ignores the transactions of victim
//! accounts, so it neither forwards, attests nor includes them, as the simulator's TxAdversary.censor.

use crate::config::{Committee, EpochNumber, Stake};
use crate::consensus::Round;
use crate::messages::{Attestation, Block, OmitProof, Otx, MAX_ATTESTATION_OTXS, MAX_OTXS};
use crypto::Hash as _;
use crypto::{Digest, PublicKey, Signature};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::time::{Duration, Instant};

#[cfg(test)]
#[path = "tests/inclusion_tests.rs"]
pub mod inclusion_tests;

/// The censor's victims: one account in four (the simulator's victim_frac = 0.25).
pub fn victim(otx: &Otx) -> bool {
    otx.account % 4 == 0
}

/// A ceiling on the pending observed transactions one node buffers: once reached, new distinct transactions
/// are refused rather than letting a flood of them -- which may never reach a certified block -- grow memory
/// without bound. Generous, so honest load never reaches it. A per-node buffer bound, not part of the protocol.
const MAX_PENDING_OTXS: usize = 100_000;

pub struct Inclusion {
    guard: Duration,
    censor: bool,
    /// Ceiling on `pending`: new transactions are refused once it is reached.
    max_pending: usize,
    /// Pending observed transactions we hold: id -> (transaction, held since, arrival number).
    pending: HashMap<Digest, (Otx, Instant, u64)>,
    arrivals: u64,
    /// Every observed transaction we hold, pending or not (an omission proof carries the transaction).
    known: HashMap<Digest, Otx>,
    /// Seen in a certified block: ids and conflict keys, with the round of that block.
    included: HashMap<Digest, Round>,
    taken: HashMap<(u64, u64), Round>,
    /// Attestations of recent rounds: (epoch, round) -> author -> (signature, list).
    attestations: BTreeMap<(EpochNumber, Round), HashMap<PublicKey, (Signature, Vec<Digest>)>>,
    /// Certified blocks of recent rounds (late attestations are checked against them).
    certified: BTreeMap<Round, Block>,
    made: HashSet<(EpochNumber, Round, Digest)>,
    /// The highest committed round: up to here the chain is settled.
    settled: Round,
}

impl Inclusion {
    pub fn new(guard: Duration, censor: bool) -> Self {
        Self {
            guard,
            censor,
            max_pending: MAX_PENDING_OTXS,
            pending: HashMap::new(),
            arrivals: 0,
            known: HashMap::new(),
            included: HashMap::new(),
            taken: HashMap::new(),
            attestations: BTreeMap::new(),
            certified: BTreeMap::new(),
            made: HashSet::new(),
            settled: 0,
        }
    }

    /// An observed transaction from a client or a node: whether it is new to us (then we forward it).
    pub fn receive(&mut self, otx: Otx, now: Instant) -> bool {
        let id = otx.id();
        if (self.censor && victim(&otx)) || self.known.contains_key(&id) {
            return false;
        }
        if self.included.contains_key(&id) {
            self.known.insert(id, otx); // already in a certified block: nothing to attest or include, but forward
            return true;
        }
        // Bound the pending buffer: once full, refuse new transactions rather than let a flood of distinct ones
        // grow memory without limit.
        if self.pending.len() >= self.max_pending {
            return false;
        }
        self.known.insert(id.clone(), otx.clone());
        self.arrivals += 1;
        self.pending.insert(id, (otx, now, self.arrivals));
        true
    }

    fn oldest_first(&self) -> Vec<&(Otx, Instant, u64)> {
        let mut pending: Vec<_> = self.pending.values().collect();
        pending.sort_by_key(|(_, _, arrival)| *arrival);
        pending
    }

    /// What we attest on entering a round: the pending transactions held for at least the guard, oldest first,
    /// at most MAX_ATTESTATION_OTXS (so our own attestation stays within the bound Attestation::verify enforces).
    pub fn to_attest(&self, now: Instant) -> Vec<Digest> {
        self.oldest_first()
            .into_iter()
            .filter(|(_, since, _)| *since + self.guard <= now)
            .take(MAX_ATTESTATION_OTXS)
            .map(|(otx, _, _)| otx.id())
            .collect()
    }

    /// What we include as leader: pending transactions, oldest first, at most MAX_OTXS, none conflicting with
    /// an included transaction or another selected one.
    pub fn select(&self) -> Vec<Otx> {
        let mut keys = HashSet::new();
        self.oldest_first()
            .into_iter()
            .filter(|(otx, _, _)| !self.taken.contains_key(&otx.key()) && keys.insert(otx.key()))
            .take(MAX_OTXS)
            .map(|(otx, _, _)| otx.clone())
            .collect()
    }

    /// A block we hold is certified: check the attestations of its round, then mark its transactions included.
    pub fn certify(&mut self, block: &Block, committee: &Committee) -> Vec<OmitProof> {
        if self.certified.get(&block.round).map_or(false, |b| b.digest() == block.digest()) {
            return Vec::new();
        }
        // A late certificate of a block the chain has already passed over: it stays abandoned.
        if block.round <= self.settled {
            return Vec::new();
        }
        self.mark(block);
        self.omissions(block.epoch, block.round, committee)
    }

    fn mark(&mut self, block: &Block) {
        self.certified.insert(block.round, block.clone());
        for x in &block.otxs {
            self.included.entry(x.id()).or_insert(block.round);
            self.taken.entry(x.key()).or_insert(block.round);
            self.pending.remove(&x.id());
        }
        // A transaction that conflicts with an included one can never be included: stop proposing it. It
        // stays known (unpending) so that omissions of it before the conflict can still be proved.
        let taken = &self.taken;
        self.pending.retain(|_, (otx, _, _)| !taken.contains_key(&otx.key()));
    }

    /// A block is committed, in chain order. That settles its round and those since the last commit: any other
    /// certified block among them has been abandoned, and what it held was not included after all.
    pub fn commit(&mut self, block: &Block, now: Instant) {
        if block.round <= self.settled {
            return;
        }
        let digest = block.digest();
        let abandoned: Vec<Round> = self
            .certified
            .range(self.settled + 1..=block.round)
            .filter(|(_, b)| b.digest() != digest)
            .map(|(round, _)| *round)
            .collect();
        self.settled = block.round;
        let abandoned: Vec<Block> = abandoned.iter().filter_map(|round| self.certified.remove(round)).collect();
        if !abandoned.is_empty() {
            self.give_back(&abandoned, now);
        }
        if !self.certified.contains_key(&block.round) {
            self.mark(block);
        }
    }

    /// Undo what abandoned blocks marked, then put back what is free again: first in line, as it has waited longest,
    /// and with the guard restarted. That includes the transactions pushed out as conflicting with them.
    fn give_back(&mut self, abandoned: &[Block], now: Instant) {
        let rounds: HashSet<Round> = abandoned.iter().map(|b| b.round).collect();
        self.included.retain(|_, round| !rounds.contains(round));
        self.taken.retain(|_, round| !rounds.contains(round));
        // A live certified block may hold the same transaction, or a conflicting one.
        for (round, block) in &self.certified {
            for x in &block.otxs {
                self.included.entry(x.id()).or_insert(*round);
                self.taken.entry(x.key()).or_insert(*round);
            }
        }
        let keys: HashSet<_> = abandoned.iter().flat_map(|b| b.otxs.iter().map(|x| x.key())).collect();
        for (id, otx) in &self.known {
            if keys.contains(&otx.key()) && !self.taken.contains_key(&otx.key()) {
                self.pending.entry(id.clone()).or_insert((otx.clone(), now, 0));
            }
        }
    }

    /// A verified attestation (of the table `committee`); it may complete an omission proof for a round whose
    /// certified block we hold.
    pub fn attest(&mut self, attestation: Attestation, committee: &Committee) -> Vec<OmitProof> {
        let key = (attestation.epoch, attestation.round);
        self.attestations
            .entry(key)
            .or_insert_with(HashMap::new)
            .entry(attestation.author)
            .or_insert((attestation.signature, attestation.otxs));
        self.omissions(key.0, key.1, committee)
    }

    /// Omission proofs for round `round` (attestations made in `epoch`), if its certified block is here.
    fn omissions(&mut self, epoch: EpochNumber, round: Round, committee: &Committee) -> Vec<OmitProof> {
        let block = match self.certified.get(&round) {
            Some(block) => block,
            None => return Vec::new(),
        };
        let before = |r: Option<&Round>| r.map_or(false, |r| *r < round);
        let attestations = match self.attestations.get(&(epoch, round)) {
            Some(attestations) => attestations,
            None => return Vec::new(),
        };
        if block.otxs.len() >= MAX_OTXS {
            return Vec::new(); // a full block is exempt
        }
        let in_block: HashSet<_> = block.otxs.iter().map(|x| x.id()).collect();
        let keys_in_block: HashSet<_> = block.otxs.iter().map(|x| x.key()).collect();

        let mut weights: HashMap<&Digest, Stake> = HashMap::new();
        for (author, (_, list)) in attestations {
            let stake = committee.stake(author);
            // Count each author's weight once per transaction, as OmitProof::verify does (per author, not per
            // list entry), so a repeated entry in one list cannot push the weight past the quorum and make us
            // assemble a proof that every other node then rejects.
            let mut counted = HashSet::new();
            for x in list {
                if counted.insert(x) {
                    *weights.entry(x).or_insert(0) += stake;
                }
            }
        }
        let mut proofs = Vec::new();
        for (x, weight) in weights {
            if weight < committee.quorum_threshold()
                || in_block.contains(x)
                || before(self.included.get(x))
                || self.made.contains(&(epoch, round, x.clone()))
            {
                continue;
            }
            // We can only prove what we hold; a conflicting included transaction exempts the block.
            let otx = match self.known.get(x) {
                Some(otx) => otx.clone(),
                None => continue,
            };
            if before(self.taken.get(&otx.key())) || keys_in_block.contains(&otx.key()) {
                continue;
            }
            self.made.insert((epoch, round, x.clone()));
            proofs.push(OmitProof {
                round,
                epoch,
                block: block.digest(),
                otx,
                attestations: attestations
                    .iter()
                    .filter(|(_, (_, list))| list.contains(x))
                    .map(|(author, (signature, list))| (*author, signature.clone(), list.clone()))
                    .collect(),
            });
        }
        proofs.sort_by_key(|p| p.otx.id());
        proofs
    }

    /// Forget the attestations and certified blocks of rounds before `round`, but no certified block of a round the
    /// chain has not settled yet: it may still be abandoned.
    pub fn cleanup(&mut self, round: Round) {
        self.attestations.retain(|(_, r), _| *r >= round);
        let settled = round.min(self.settled + 1);
        self.certified.retain(|r, _| *r >= settled);
        self.made.retain(|(_, r, _)| *r >= round);
    }
}
