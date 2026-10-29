//! G1 evidence detection at one node (prototype/DESIGN.md §13.1). The node feeds it what it verified: votes it
//! receives, the votes inside QCs, timeouts, the reports inside TCs, and blocks. A contradiction between two
//! of a signer's own messages gives a piece of evidence for the ledger:
//!
//! - E1: two votes of one signer for the same (epoch, round) and different blocks;
//! - E2: a vote for a block that breaks the voting rule;
//! - E3: a vote for a block certifying round j and a timeout of a round at least as high reporting hq < j;
//! - NR: a vote and an NR = 1 timeout for the same (epoch, round).
//!
//! Honest nodes never produce these (rules R1-R6). One piece is reported per culprit, class and epoch: the
//! graded punishment counts one window per (entity, class, sign epoch), so further evidence adds nothing.

use crate::config::EpochNumber;
use crate::consensus::Round;
use crate::messages::{Block, Evidence, SignedTimeout, Vote, QC, TC};
use crypto::Hash as _;
use crypto::{Digest, PublicKey};
use std::collections::{BTreeMap, HashMap, HashSet};

#[cfg(test)]
#[path = "tests/evidence_tests.rs"]
pub mod evidence_tests;

pub struct Detector {
    /// The first vote of each signer in recent rounds.
    votes: BTreeMap<(EpochNumber, Round), HashMap<PublicKey, Vote>>,
    /// The first timeout of each signer in recent rounds.
    timeouts: BTreeMap<(EpochNumber, Round), HashMap<PublicKey, SignedTimeout>>,
    /// Blocks of recent rounds, by digest.
    blocks: HashMap<Digest, Block>,
    /// Certificates already taken in.
    certificates: HashSet<(EpochNumber, Round, Digest)>,
    /// (culprit, safety class, epoch) already reported.
    reported: HashSet<(PublicKey, bool, EpochNumber)>,
}

impl Detector {
    pub fn new() -> Self {
        Self {
            votes: BTreeMap::new(),
            timeouts: BTreeMap::new(),
            blocks: HashMap::new(),
            certificates: HashSet::new(),
            reported: HashSet::new(),
        }
    }

    fn report(&mut self, evidence: Evidence, found: &mut Vec<Evidence>) {
        if self.reported.insert((evidence.culprit(), evidence.is_safety(), evidence.epoch())) {
            found.push(evidence);
        }
    }

    /// The block a vote is for breaks the voting rule (Evidence::InvalidBlock checks the same).
    fn invalid(vote: &Vote, block: &Block) -> bool {
        Evidence::InvalidBlock(vote.clone(), block.clone()).holds()
    }

    /// Contradictions of a vote with what we hold.
    fn check_vote(&mut self, vote: &Vote, found: &mut Vec<Evidence>) {
        let key = (vote.epoch, vote.round);
        if let Some(first) = self.votes.get(&key).and_then(|m| m.get(&vote.author)) {
            if first.hash != vote.hash {
                let evidence = Evidence::DoubleVote(first.clone(), vote.clone());
                self.report(evidence, found);
            }
        }
        if let Some(timeout) = self.timeouts.get(&key).and_then(|m| m.get(&vote.author)) {
            if timeout.nr {
                let evidence = Evidence::NrContradiction(vote.clone(), timeout.clone());
                self.report(evidence, found);
            }
        }
        if let Some(block) = self.blocks.get(&vote.hash).cloned() {
            self.check_vote_on_block(vote, &block, found);
        }
    }

    /// E2 and E3 for a vote whose block we hold.
    fn check_vote_on_block(&mut self, vote: &Vote, block: &Block, found: &mut Vec<Evidence>) {
        if Self::invalid(vote, block) {
            self.report(Evidence::InvalidBlock(vote.clone(), block.clone()), found);
        }
        let later: Vec<SignedTimeout> = self
            .timeouts
            .range((vote.epoch, vote.round)..=(vote.epoch, Round::MAX))
            .filter_map(|(_, m)| m.get(&vote.author))
            .filter(|t| t.high_qc_round < block.qc.round)
            .cloned()
            .collect();
        if let Some(timeout) = later.into_iter().next() {
            self.report(Evidence::Regression(vote.clone(), block.clone(), timeout), found);
        }
    }

    /// A verified vote (received by us, or inside a QC).
    pub fn vote(&mut self, vote: Vote) -> Vec<Evidence> {
        let mut found = Vec::new();
        self.check_vote(&vote, &mut found);
        self.votes
            .entry((vote.epoch, vote.round))
            .or_insert_with(HashMap::new)
            .entry(vote.author)
            .or_insert(vote);
        found
    }

    /// A verified QC: the votes of its signers.
    pub fn qc(&mut self, qc: &QC) -> Vec<Evidence> {
        if *qc == QC::genesis() || !self.certificates.insert((qc.epoch, qc.round, qc.hash.clone())) {
            return Vec::new();
        }
        let mut found = Vec::new();
        for (author, signature) in &qc.votes {
            let vote = Vote {
                hash: qc.hash.clone(),
                round: qc.round,
                epoch: qc.epoch,
                author: *author,
                signature: signature.clone(),
            };
            found.extend(self.vote(vote));
        }
        found
    }

    /// A verified timeout (received, or a report inside a TC).
    pub fn timeout(&mut self, timeout: SignedTimeout) -> Vec<Evidence> {
        let mut found = Vec::new();
        let key = (timeout.epoch, timeout.round);
        if timeout.nr {
            if let Some(vote) = self.votes.get(&key).and_then(|m| m.get(&timeout.author)).cloned() {
                self.report(Evidence::NrContradiction(vote, timeout.clone()), &mut found);
            }
        }
        // E3: an earlier-or-same-round vote of this signer for a block certifying a round above its hq.
        let earlier: Vec<Vote> = self
            .votes
            .range((timeout.epoch, 0)..=key)
            .filter_map(|(_, m)| m.get(&timeout.author))
            .cloned()
            .collect();
        for vote in earlier {
            if let Some(block) = self.blocks.get(&vote.hash) {
                if timeout.high_qc_round < block.qc.round {
                    let evidence = Evidence::Regression(vote, block.clone(), timeout.clone());
                    self.report(evidence, &mut found);
                    break;
                }
            }
        }
        self.timeouts
            .entry(key)
            .or_insert_with(HashMap::new)
            .entry(timeout.author)
            .or_insert(timeout);
        found
    }

    /// A verified TC: the reports of its signers.
    pub fn tc(&mut self, tc: &TC) -> Vec<Evidence> {
        if !self.certificates.insert((tc.epoch, tc.round, Digest::default())) {
            return Vec::new();
        }
        let mut found = Vec::new();
        for (author, signature, high_qc_round, nr) in &tc.votes {
            found.extend(self.timeout(SignedTimeout {
                author: *author,
                signature: signature.clone(),
                epoch: tc.epoch,
                round: tc.round,
                high_qc_round: *high_qc_round,
                nr: *nr,
            }));
        }
        found
    }

    /// A block signed by its author: votes for it may now be E2 or E3.
    pub fn block(&mut self, block: &Block) -> Vec<Evidence> {
        let digest = block.digest();
        if self.blocks.contains_key(&digest) {
            return Vec::new();
        }
        self.blocks.insert(digest.clone(), block.clone());
        let voters: Vec<Vote> = self
            .votes
            .get(&(block.epoch, block.round))
            .map(|m| m.values().filter(|v| v.hash == digest).cloned().collect())
            .unwrap_or_default();
        let mut found = Vec::new();
        for vote in voters {
            self.check_vote_on_block(&vote, block, &mut found);
        }
        found
    }

    /// Forget the rounds before `round`.
    pub fn cleanup(&mut self, round: Round) {
        self.votes.retain(|(_, r), _| *r >= round);
        self.timeouts.retain(|(_, r), _| *r >= round);
        self.blocks.retain(|_, b| b.round >= round);
        self.certificates.retain(|(_, r, _)| *r >= round);
    }
}
