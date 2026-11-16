//! G1 evidence detection at one node (prototype/DESIGN.md §13.1). The node feeds it what it verified: votes it
//! receives, the votes inside QCs, timeouts, the reports inside TCs, and blocks. A contradiction between two
//! of a signer's own messages gives a piece of evidence for the ledger:
//!
//! - E1: two votes of one signer for the same (epoch, round) and different blocks;
//! - E2: a vote for a block that breaks the voting rule (its TC judged by the weight table the block names);
//! - E3: a vote for a block certifying round j and a timeout of a round at least as high reporting hq < j, of the
//!   epoch of the vote or a later one;
//! - E4: a vote and a vote or timeout of an earlier epoch at the same round or a higher one (DESIGN.md §15.34);
//! - NR: a vote and an NR = 1 timeout for the same (epoch, round).
//!
//! Honest nodes never produce these (rules R1-R6, H3). One piece is reported per culprit, class and epoch: the
//! graded punishment counts one window per (entity, class, sign epoch), so further evidence adds nothing.

use crate::config::{Committee, EpochNumber};
use crate::consensus::Round;
use crate::messages::{table_digest, Block, Earlier, Evidence, Judge, SignedTimeout, Vote, QC, TC};
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
    /// The weight tables we hold, by digest: E2 judges a block's TC by the tables the block names, if we hold them.
    tables: HashMap<Digest, Committee>,
    /// L, the rounds per epoch (E2: which TCs are past the end of their epoch).
    length: Round,
}

impl Detector {
    pub fn new() -> Self {
        Self {
            votes: BTreeMap::new(),
            timeouts: BTreeMap::new(),
            blocks: HashMap::new(),
            certificates: HashSet::new(),
            reported: HashSet::new(),
            tables: HashMap::new(),
            length: 0,
        }
    }

    /// The epoch length L (0: a single epoch).
    pub fn set_length(&mut self, length: Round) {
        self.length = length;
    }

    /// The weight tables we hold now (E2).
    pub fn set_tables<'a>(&mut self, tables: impl IntoIterator<Item = &'a Committee>) {
        self.tables = tables.into_iter().map(|t| (table_digest(t), t.clone())).collect();
    }

    fn report(&mut self, evidence: Evidence, found: &mut Vec<Evidence>) {
        if self.reported.insert(Self::window(&evidence)) {
            found.push(evidence);
        }
    }

    /// The block a vote is for breaks the voting rule (Evidence::InvalidBlock checks the same), its TC judged by
    /// the table the block names when we hold it.
    fn invalid(&self, vote: &Vote, block: &Block) -> bool {
        // The common case, a block right after its QC and without a TC, breaks no voting rule (it extends validly,
        // and only a block with a TC is judged by its table): skip cloning its header for every vote seen
        // (DESIGN.md §15.30). Exactly what `holds_under` would answer.
        if block.tc.is_none() && block.qc.round.checked_add(1) == Some(block.round) {
            return false;
        }
        let judge =
            Judge { table: self.tables.get(&block.table), next: self.tables.get(&block.next_table), length: self.length };
        Evidence::InvalidBlock(vote.clone(), block.header()).holds_under(judge)
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
        // E4, this vote being the later one: a message of an earlier epoch at this round or above.
        let earlier = self
            .votes
            .range(..(vote.epoch, 0))
            .filter(|((_, round), _)| *round >= vote.round)
            .find_map(|(_, m)| m.get(&vote.author))
            .map(|v| Earlier::Vote(v.clone()))
            .or_else(|| {
                self.timeouts
                    .range(..(vote.epoch, 0))
                    .filter(|((_, round), _)| *round >= vote.round)
                    .find_map(|(_, m)| m.get(&vote.author))
                    .map(|t| Earlier::Timeout(t.clone()))
            });
        if let Some(earlier) = earlier {
            self.report(Evidence::CrossEpoch(vote.clone(), earlier), found);
        }
        // E4, this vote being the earlier one.
        if let Some(later) = self.later_vote(&vote.author, vote.epoch, vote.round) {
            self.report(Evidence::CrossEpoch(later, Earlier::Vote(vote.clone())), found);
        }
        if let Some(block) = self.blocks.get(&vote.hash).cloned() {
            self.check_vote_on_block(vote, &block, found);
        }
    }

    /// A vote of `author` in an epoch after `epoch` at `round` or below (E4).
    fn later_vote(&self, author: &PublicKey, epoch: EpochNumber, round: Round) -> Option<Vote> {
        let next = epoch.checked_add(1)?;
        self.votes
            .range((next, 0)..)
            .filter(|((_, r), _)| *r <= round)
            .find_map(|(_, m)| m.get(author))
            .cloned()
    }

    /// E2 and E3 for a vote whose block we hold.
    fn check_vote_on_block(&mut self, vote: &Vote, block: &Block, found: &mut Vec<Evidence>) {
        if self.invalid(vote, block) {
            self.report(Evidence::InvalidBlock(vote.clone(), block.header()), found);
        }
        // E3: a timeout of the vote's epoch or a later one, at the vote's round or above.
        let later = self
            .timeouts
            .range((vote.epoch, vote.round)..)
            .filter(|((_, round), _)| *round >= vote.round)
            .filter_map(|(_, m)| m.get(&vote.author))
            .find(|t| t.high_qc_round < block.qc.round)
            .cloned();
        if let Some(timeout) = later {
            self.report(Evidence::Regression(vote.clone(), block.header(), timeout), found);
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
        // E4: a vote of a later epoch at this round or below.
        if let Some(later) = self.later_vote(&timeout.author, timeout.epoch, timeout.round) {
            self.report(Evidence::CrossEpoch(later, Earlier::Timeout(timeout.clone())), &mut found);
        }
        // E3: an earlier-or-same-round vote of this signer, in this epoch or an earlier one, for a block certifying
        // a round above its hq.
        let earlier: Vec<Vote> = self
            .votes
            .range(..=(timeout.epoch, Round::MAX))
            .filter(|((_, round), _)| *round <= timeout.round)
            .filter_map(|(_, m)| m.get(&timeout.author))
            .cloned()
            .collect();
        for vote in earlier {
            if let Some(block) = self.blocks.get(&vote.hash) {
                if timeout.high_qc_round < block.qc.round {
                    let evidence = Evidence::Regression(vote, block.header(), timeout.clone());
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

    /// Evidence of this window is on the ledger: nothing more to report for it.
    pub fn on_ledger(&mut self, evidence: &Evidence) {
        self.reported.insert(Self::window(evidence));
    }

    /// The punishment window of a piece of evidence: (culprit, safety class, sign epoch).
    pub fn window(evidence: &Evidence) -> (PublicKey, bool, EpochNumber) {
        (evidence.culprit(), evidence.is_safety(), evidence.epoch())
    }

    /// Forget the rounds before `round`.
    pub fn cleanup(&mut self, round: Round) {
        self.votes.retain(|(_, r), _| *r >= round);
        self.timeouts.retain(|(_, r), _| *r >= round);
        self.blocks.retain(|_, b| b.round >= round);
        self.certificates.retain(|(_, r, _)| *r >= round);
    }
}
