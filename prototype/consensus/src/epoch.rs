//! Epochs and the handover of the weight table (prototype/DESIGN.md §9; theory rules H1–H4).
//!
//! - H1: the terminal block G_e of epoch e is the first block of epoch e on the chain whose round is at
//!   least s_e + length, where s_e is the round of G_{e-1} (0 for the first epoch). The predicate only
//!   looks at the block, so it is a function of the chain prefix.
//! - The table of epoch e+1 is a deterministic function of the ledger up to G_e: the AT accusations on it
//!   drive the G2 leader rule and the reputations (reputation.rs, DESIGN.md §12.2), which give each
//!   member's stake (CapNorm of the base weights times r, within the budget) and whether it may lead; the G1
//!   evidence on it drives the graded punishment (punish.rs, DESIGN.md §13): suspension (z = 0), bars from
//!   leading, eviction.
//! - H3: a node enters epoch e+1 when it first holds a commit proof of G_e (Core::commit); from then on it
//!   signs no message of an older epoch. The tables of the last few epochs are kept to verify old blocks
//!   received through synchronization.

use crate::config::{Authority, Committee, EpochNumber, Stake};
use crate::consensus::Round;
use crate::leader::leader;
use crate::messages::{Block, OmitProof, MAX_OTXS};
use crate::punish::{G1Event, Kind, PunishConfig, Punishment};
use crate::reputation::{Event, G2Config, Reputation};
use crate::ttru::{self, Class};
use crypto::Hash as _;
use crypto::{Digest, PublicKey};
use log::info;
use std::collections::{BTreeMap, HashMap, HashSet};

#[cfg(test)]
#[path = "tests/epoch_tests.rs"]
pub mod epoch_tests;

/// Tables kept for verification: the current epoch and the previous ones.
const KEEP: usize = 16;

/// In a single-epoch run, committed blocks and accusation facts of rounds more than this far behind the latest
/// committed block are forgotten: there is no handover to process them (enter_next), so nothing else would. It
/// must outlast any honest omission proof, which is for a round at most about two detection windows old (core.rs
/// checks the bound at compile time).
pub const SINGLE_EPOCH_LEDGER_WINDOW: Round = 1_000;

#[derive(Clone, Copy, Debug)]
pub struct EpochConfig {
    /// Rounds per epoch, counted from the previous terminal block (0: a single epoch).
    pub length: Round,
    pub entity_cap_ppm: u64,
    pub class_cap_ppm: u64,
    /// G1: at most this much base weight suspended at once (ppm).
    pub l_max_ppm: u64,
    /// G1 governance stand-in: an L4 without a fork counts as confirmed malicious (evicted) rather than as a
    /// client fault (downgraded).
    pub governance_malicious: bool,
}

pub struct Epochs {
    config: EpochConfig,
    /// Members in a fixed order with their addresses and classes (from the configuration).
    members: Vec<(PublicKey, Authority)>,
    /// G2 state from the ledger, by member index; holds the CapNorm base weights.
    reputation: Reputation,
    /// G1 graded punishment from the ledger; its base shares change only when a fork culprit is evicted.
    punishment: Punishment,
    current: EpochNumber,
    /// s_e: round of the terminal block of the previous epoch.
    start: Round,
    tables: BTreeMap<EpochNumber, Committee>,
    /// First round of each kept epoch (a round's leader comes from the table of its epoch).
    first_rounds: BTreeMap<EpochNumber, Round>,
    /// G2 inclusion attestations on the ledger (DESIGN.md §12.4): committed blocks of the rounds not yet
    /// processed, and the round where each observed transaction and conflict key was first included.
    committed: BTreeMap<Round, LedgerBlock>,
    included: HashMap<Digest, Round>,
    taken: HashMap<(u64, u64), Round>,
}

/// What an omission proof is checked against: a committed block's digest and observed transactions.
struct LedgerBlock {
    digest: Digest,
    author: PublicKey,
    otxs: HashSet<Digest>,
    keys: HashSet<(u64, u64)>,
}

impl Epochs {
    /// `roster` is the committee of the configuration: `stake` is the base weight w_i.
    pub fn new(roster: &Committee, config: EpochConfig) -> Self {
        let mut members: Vec<_> = roster
            .authorities
            .iter()
            .map(|(name, a)| (*name, a.clone()))
            .collect();
        members.sort_by_key(|(name, _)| *name);
        let classes: Vec<_> = members
            .iter()
            .map(|(_, a)| match a.certified {
                true => Class::Licensed,
                false => Class::Uncertified,
            })
            .collect();
        let weights: Vec<u64> = members.iter().map(|(_, a)| a.stake as u64).collect();
        let (cap, u_max) = (ttru::from_ppm(config.entity_cap_ppm), ttru::from_ppm(config.class_cap_ppm));
        let base = ttru::base_weights(&classes, &weights, cap, u_max);
        for ((name, _), b) in members.iter().zip(&base) {
            // NOTE: this log entry is used to weigh the reputation cuts by base weight (benchmark/p5.py).
            info!("T_tru base weight of {} is {} ppm", name, b * ttru::PPM / ttru::ONE);
        }
        let punish_config = PunishConfig {
            l_max: ttru::from_ppm(config.l_max_ppm),
            ..PunishConfig::default()
        };
        let punishment = Punishment::new(classes, weights, cap, u_max, punish_config);
        let mut epochs = Self {
            config,
            members,
            reputation: Reputation::new(base, G2Config::default()),
            punishment,
            current: roster.epoch,
            start: 0,
            tables: BTreeMap::new(),
            first_rounds: BTreeMap::new(),
            committed: BTreeMap::new(),
            included: HashMap::new(),
            taken: HashMap::new(),
        };
        let first = epochs.make_table(roster.epoch);
        epochs.tables.insert(roster.epoch, first);
        epochs.first_rounds.insert(roster.epoch, 0);
        epochs
    }

    /// W_e = F(ledger up to G_{e-1}): stakes from the base shares (G1), reputations within the budget (G2) and
    /// suspensions (z, G1); leadership barred by the G2 exclusions and by G1 (L1, suspended, queued, evicted).
    fn make_table(&self, epoch: EpochNumber) -> Committee {
        let z = self.punishment.z();
        let stakes = self.reputation.stakes_on(self.punishment.base(), &z);
        let excluded = self.reputation.excluded();
        let bars = self.punishment.bars();
        Committee {
            authorities: self
                .members
                .iter()
                .enumerate()
                .zip(stakes)
                .map(|((i, (name, a)), stake)| {
                    let authority = Authority {
                        stake: stake as Stake,
                        leader: !excluded[i] && !bars[i],
                        ..a.clone()
                    };
                    (*name, authority)
                })
                .collect(),
            epoch,
            handover: None,
        }
    }

    /// A committed block, in chain order: the AT accusations it carries, and the omission proofs that hold on
    /// the ledger, are bad facts of their rounds; its observed transactions are included.
    pub fn record(&mut self, block: &Block) {
        for accusation in &block.accusations {
            // NOTE: this log entry is used to count the accusation facts per leader (benchmark/p5.py): the first
            // fact of a round counts, against the leader of that round in the table of the accusation's epoch.
            let counts = accusation.round > self.reputation.done()
                && !self.reputation.facts().contains_key(&accusation.round);
            if let Some(table) = self.tables.get(&accusation.epoch).filter(|_| counts) {
                info!("G2: accusation of round {} led by {}", accusation.round, leader(table, accusation.round));
            }
            self.reputation.record(accusation.round, accusation.epoch);
        }
        for omission in &block.omissions {
            if self.omission_holds(omission) {
                let author = self.committed[&omission.round].author;
                info!("G2: omission of {} at round {} by {}", omission.otx.id(), omission.round, author);
                self.reputation.record(omission.round, omission.epoch);
            }
        }
        for evidence in &block.evidence {
            if let Ok(i) = self.members.binary_search_by_key(&evidence.culprit(), |(n, _)| *n) {
                info!("G1: {:?} on the ledger", evidence);
                let kind = if evidence.is_safety() { Kind::Safety } else { Kind::Liveness };
                let malicious = self.config.governance_malicious;
                self.punishment.record(i, kind, evidence.epoch(), block.epoch, malicious, false);
            }
        }
        for x in &block.otxs {
            self.included.entry(x.id()).or_insert(block.round);
            self.taken.entry(x.key()).or_insert(block.round);
        }
        if block.round > self.reputation.done() {
            let entry = LedgerBlock {
                digest: block.digest(),
                author: block.author,
                otxs: block.otxs.iter().map(|x| x.id()).collect(),
                keys: block.otxs.iter().map(|x| x.key()).collect(),
            };
            self.committed.insert(block.round, entry);
        }
        // A single-epoch run has no handover to process these facts and then forget them (enter_next), so keep
        // only the recent rounds. The horizon comes from the ledger (the block just recorded), so every node
        // keeps the same.
        if self.single_epoch() {
            let horizon = block.round.saturating_sub(SINGLE_EPOCH_LEDGER_WINDOW);
            self.committed = self.committed.split_off(&horizon);
            self.reputation.forget_before(horizon);
        }
    }

    /// An omission proof holds if the committed block of its round is the certified block it names, which
    /// leaves the transaction out without an exemption (not full, no conflicting transaction in it), and the
    /// transaction and its conflict key were not included earlier.
    fn omission_holds(&self, omission: &OmitProof) -> bool {
        let block = match self.committed.get(&omission.round) {
            Some(block) => block,
            None => return false,
        };
        let earlier = |r: Option<&Round>| r.map_or(false, |r| *r < omission.round);
        let (id, key) = (omission.otx.id(), omission.otx.key());
        block.digest == omission.block
            && block.otxs.len() < MAX_OTXS
            && !block.otxs.contains(&id)
            && !block.keys.contains(&key)
            && !earlier(self.included.get(&id))
            && !earlier(self.taken.get(&key))
    }

    /// Rounds up to here have been processed by the leader rule; accusations of them come too late.
    pub fn done(&self) -> Round {
        self.reputation.done()
    }

    pub fn epoch(&self) -> EpochNumber {
        self.current
    }

    /// Whether this is a single-epoch run (no handover, `length == 0`). Then no table computation ever consumes
    /// the accusations or inclusion attestations, so their per-round state may be bounded by the detection
    /// window instead of being kept until a handover that never comes.
    pub fn single_epoch(&self) -> bool {
        self.config.length == 0
    }

    /// The weight table of the current epoch.
    pub fn current(&self) -> &Committee {
        &self.tables[&self.current]
    }

    /// The weight table of a recent epoch, if kept.
    pub fn get(&self, epoch: EpochNumber) -> Option<&Committee> {
        self.tables.get(&epoch)
    }

    /// H1: whether `block` is the terminal block of the current epoch.
    pub fn is_terminal(&self, block: &Block) -> bool {
        self.config.length > 0
            && block.epoch == self.current
            && block.round >= self.start + self.config.length
    }

    /// Whether a QC of `round` may be the commit proof of the terminal block (its block's parent may be
    /// the terminal block), which can only be told once the certified block is at hand.
    pub fn may_end(&self, round: Round) -> bool {
        self.config.length > 0 && round > self.start + self.config.length
    }

    /// H3: enter the next epoch once its terminal block is committed. The leader rule processes the rounds up
    /// to (terminal round + 1 - lag), each led by the leader of its epoch's table (the epoch the accusation
    /// was made in, if any); then the next table is computed.
    pub fn enter_next(&mut self, terminal: &Block) {
        let horizon = (terminal.round + 1).saturating_sub(self.reputation.config().lag);
        let before = self.reputation.r_ppm().to_vec();
        let (tables, first_rounds, members) = (&self.tables, &self.first_rounds, &self.members);
        let events = self.reputation.advance(horizon, |round, accused_in| {
            let epoch = accused_in.or_else(|| {
                first_rounds.iter().rev().find(|(_, first)| **first <= round).map(|(e, _)| *e)
            })?;
            let name = leader(tables.get(&epoch)?, round);
            members.binary_search_by_key(&name, |(n, _)| *n).ok()
        });
        for event in events {
            let (what, k, round) = match event {
                Event::Exclude(k, u) => ("excluded from leading", k, u),
                Event::Release(k, u) => ("may lead again", k, u),
                Event::Queue(k, u) => ("convicted, queued", k, u),
                Event::Drop(k, u) => ("dropped from the queue", k, u),
            };
            info!("G2: {} {} at round {}", self.members[*k].0, what, round);
        }
        let done = self.reputation.done();
        self.committed = self.committed.split_off(&(done + 1));
        for (k, (old, new)) in before.iter().zip(self.reputation.r_ppm()).enumerate() {
            if old != new {
                info!("G2: reputation of {} is {} ppm", self.members[k].0, new);
            }
        }

        // G1: the graded punishment for the next table.
        let next = self.current + 1;
        for event in self.punishment.update(next) {
            let (what, i, k) = match *event {
                G1Event::Level(l, i, k) => (format!("level L{}", l), i, k),
                G1Event::Queue(i, k) => ("queued for suspension".to_string(), i, k),
                G1Event::Suspend(i, k) => ("suspended".to_string(), i, k),
                G1Event::Release(i, k) => ("released".to_string(), i, k),
                G1Event::Evict(i, k) => ("evicted".to_string(), i, k),
                G1Event::Downgrade(i, k) => ("downgraded by governance".to_string(), i, k),
            };
            info!("G1: {} {} at epoch {}", self.members[i].0, what, k);
        }

        // The child of the terminal block still belongs to this epoch (the commit proof certifies it, at the
        // adjacent round); the next epoch starts after it, and its first round keeps the old leader, which
        // holds that proof, even if the new table suspends it (it then proposes without voting).
        let first = terminal.round + 2;
        let mut table = self.make_table(next);
        table.handover = Some((first, leader(self.current(), first)));
        self.tables.insert(next, table);
        self.first_rounds.insert(next, first);
        self.current = next;
        self.start = terminal.round;
        while self.tables.len() > KEEP {
            let oldest = *self.tables.keys().next().unwrap();
            self.tables.remove(&oldest);
            self.first_rounds.remove(&oldest);
        }
    }
}
