use crate::config::{Committee, EpochNumber, Stake};
use crate::consensus::Round;
use crate::error::{ConsensusError, ConsensusResult};
use crate::messages::{Accusation, Timeout, Vote, QC, TC};
use crypto::Hash as _;
use crypto::{Digest, PublicKey, Signature};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};

#[cfg(test)]
#[path = "tests/aggregator_tests.rs"]
pub mod aggregator_tests;

/// Votes and timeouts are added after verification against the table of their epoch, which is passed in.
pub struct Aggregator {
    votes_aggregators: HashMap<Round, HashMap<Digest, Box<QCMaker>>>,
    timeouts_aggregators: HashMap<Round, Box<TCMaker>>,
}

impl Aggregator {
    pub fn new() -> Self {
        Self {
            votes_aggregators: HashMap::new(),
            timeouts_aggregators: HashMap::new(),
        }
    }

    pub fn add_vote(&mut self, vote: Vote, committee: &Committee) -> ConsensusResult<Option<QC>> {
        // TODO [issue #7]: A bad node may make us run out of memory by sending many votes
        // with different round numbers or different digests.

        // Add the new vote to our aggregator and see if we have a QC.
        self.votes_aggregators
            .entry(vote.round)
            .or_insert_with(HashMap::new)
            .entry(vote.digest())
            .or_insert_with(|| Box::new(QCMaker::new()))
            .append(vote, committee)
    }

    pub fn add_timeout(
        &mut self,
        timeout: Timeout,
        committee: &Committee,
    ) -> ConsensusResult<Option<TC>> {
        // TODO: A bad node may make us run out of memory by sending many timeouts
        // with different round numbers.

        // Add the new timeout to our aggregator and see if we have a TC.
        self.timeouts_aggregators
            .entry(timeout.round)
            .or_insert_with(|| Box::new(TCMaker::new()))
            .append(timeout, committee)
    }

    pub fn cleanup(&mut self, round: &Round) {
        self.votes_aggregators.retain(|k, _| k >= round);
        self.timeouts_aggregators.retain(|k, _| k >= round);
    }
}

/// G2: collects the NR = 1 timeouts of each round, also those that arrive after the round is over, into
/// AT accusations (one per round). Timeouts are verified by the caller.
pub struct Accuser {
    makers: BTreeMap<(EpochNumber, Round), (Stake, Vec<(PublicKey, Signature, Round)>)>,
    made: BTreeSet<(EpochNumber, Round)>,
}

impl Accuser {
    pub fn new() -> Self {
        Self {
            makers: BTreeMap::new(),
            made: BTreeSet::new(),
        }
    }

    pub fn add(&mut self, timeout: &Timeout, committee: &Committee) -> Option<Accusation> {
        let key = (timeout.epoch, timeout.round);
        if !timeout.nr || self.made.contains(&key) {
            return None;
        }
        let (weight, votes) = self.makers.entry(key).or_insert_with(|| (0, Vec::new()));
        if votes.iter().any(|(name, _, _)| *name == timeout.author) {
            return None;
        }
        votes.push((timeout.author, timeout.signature.clone(), timeout.high_qc.round));
        *weight += committee.stake(&timeout.author);
        if *weight < committee.quorum_threshold() {
            return None;
        }
        let (_, votes) = self.makers.remove(&key).unwrap();
        self.made.insert(key);
        Some(Accusation {
            round: timeout.round,
            epoch: timeout.epoch,
            votes,
        })
    }

    /// An accusation obtained otherwise (from a TC): returns whether its round had none yet.
    pub fn note(&mut self, accusation: &Accusation) -> bool {
        let key = (accusation.epoch, accusation.round);
        self.makers.remove(&key);
        self.made.insert(key)
    }

    /// Forget the rounds before `round`.
    pub fn cleanup(&mut self, round: Round) {
        self.makers.retain(|(_, r), _| *r >= round);
        self.made.retain(|(_, r)| *r >= round);
    }
}

struct QCMaker {
    weight: Stake,
    votes: Vec<(PublicKey, Signature)>,
    used: HashSet<PublicKey>,
}

impl QCMaker {
    pub fn new() -> Self {
        Self {
            weight: 0,
            votes: Vec::new(),
            used: HashSet::new(),
        }
    }

    /// Try to append a signature to a (partial) quorum.
    pub fn append(&mut self, vote: Vote, committee: &Committee) -> ConsensusResult<Option<QC>> {
        let author = vote.author;

        // Ensure it is the first time this authority votes.
        ensure!(
            self.used.insert(author),
            ConsensusError::AuthorityReuse(author)
        );

        self.votes.push((author, vote.signature));
        self.weight += committee.stake(&author);
        if self.weight >= committee.quorum_threshold() {
            self.weight = 0; // Ensures QC is only made once.
            return Ok(Some(QC {
                hash: vote.hash.clone(),
                round: vote.round,
                epoch: vote.epoch,
                votes: self.votes.clone(),
            }));
        }
        Ok(None)
    }
}

struct TCMaker {
    weight: Stake,
    votes: Vec<(PublicKey, Signature, Round, bool)>,
    used: HashSet<PublicKey>,
    high_qc: QC,
}

impl TCMaker {
    pub fn new() -> Self {
        Self {
            weight: 0,
            votes: Vec::new(),
            used: HashSet::new(),
            high_qc: QC::genesis(),
        }
    }

    /// Try to append a signature to a (partial) quorum.
    pub fn append(
        &mut self,
        timeout: Timeout,
        committee: &Committee,
    ) -> ConsensusResult<Option<TC>> {
        let author = timeout.author;

        // Ensure it is the first time this authority votes.
        ensure!(
            self.used.insert(author),
            ConsensusError::AuthorityReuse(author)
        );

        // Add the timeout to the accumulator; keep the highest QC (R2: the TC carries it).
        self.votes.push((
            author,
            timeout.signature,
            timeout.high_qc.round,
            timeout.nr,
        ));
        if timeout.high_qc.round > self.high_qc.round {
            self.high_qc = timeout.high_qc.clone();
        }
        self.weight += committee.stake(&author);
        if self.weight >= committee.quorum_threshold() {
            self.weight = 0; // Ensures TC is only created once.
            return Ok(Some(TC {
                round: timeout.round,
                epoch: timeout.epoch,
                votes: self.votes.clone(),
                high_qc: self.high_qc.clone(),
            }));
        }
        Ok(None)
    }
}
