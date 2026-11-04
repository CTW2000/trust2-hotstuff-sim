//! Epochs and the handover of the weight table (prototype/DESIGN.md §9; theory rules H1–H4).
//!
//! - H1: the terminal block G_e of epoch e is the first block of epoch e on the chain whose round is at
//!   least s_e + length, where s_e is the round of G_{e-1} (0 for the first epoch). The predicate only
//!   looks at the block, so it is a function of the chain prefix.
//! - H1': the table of epoch e+1 is a deterministic function of the ledger up to G_{e-1}, one epoch behind, so
//!   that a node knows it before its ledger reaches G_e (the first two epochs share the configured table). The
//!   AT accusations on the ledger drive the G2 leader rule and the reputations (reputation.rs, DESIGN.md §12.2),
//!   which give each member's stake (CapNorm of the base weights times r, within the budget) and whether it may
//!   lead; the G1 evidence on it drives the graded punishment (punish.rs, DESIGN.md §13): suspension (z = 0),
//!   bars from leading, eviction.
//! - H3: a node enters epoch e+1 when it first holds G_e and a commit proof of it: when its ledger reaches G_e
//!   (Core::commit), or earlier, with G_e, its child and the proof at hand but some block before G_e still
//!   missing (enter_early; DESIGN.md §15.10). From then on it signs no message of an older epoch. The tables
//!   of the last few epochs are kept to verify old blocks received through synchronization.

use crate::config::{Authority, Committee, EpochNumber, Stake};
use crate::consensus::Round;
use crate::leader::leader;
use crate::messages::{Block, OmitProof};
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

/// Tables kept: the next epoch's (H1'), the current epoch's and the previous ones, for verification.
const KEEP: usize = 17;

/// In a single-epoch run, committed blocks and accusation facts of rounds more than this far behind the latest
/// committed block are forgotten: there is no handover to process them (enter_next), so nothing else would. It
/// must outlast any honest omission proof, which is for a round at most about two detection windows old (core.rs
/// checks the bound at compile time).
pub const SINGLE_EPOCH_LEDGER_WINDOW: Round = 1_000;

/// The epoch length the G1 durations and the reputation recovery of the defaults are given for (scaled).
pub const REFERENCE_EPOCH_LENGTH: Round = 100;

#[derive(Clone, Copy, Debug)]
pub struct EpochConfig {
    /// Rounds per epoch, counted from the previous terminal block (0: a single epoch).
    pub length: Round,
    /// The epoch length the G1 durations (in epochs) and the reputation recovery (per epoch) of the defaults are
    /// given for: 100 rounds, as in the simulator. At another length they are converted to last as many rounds
    /// (scaled; DESIGN.md §15.11). 0 leaves them as they are.
    pub reference_length: Round,
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
    /// The entity of each member. CapNorm, G1 and G2 work on entities; a table splits each entity's weight among
    /// its members.
    entity_of: Vec<usize>,
    /// G2 state from the ledger, by entity; holds the CapNorm base weights.
    reputation: Reputation,
    /// G1 graded punishment from the ledger; its base shares change only when a fork culprit is evicted.
    punishment: Punishment,
    current: EpochNumber,
    /// s_e: round of the terminal block of the previous epoch.
    start: Round,
    /// The epoch the committed ledger is in, and the round of the terminal block before it. It is one behind
    /// `current` after an early entry, until the ledger reaches that terminal block.
    ledger: EpochNumber,
    ledger_start: Round,
    tables: BTreeMap<EpochNumber, Committee>,
    /// First round of each kept epoch (a round's leader comes from the table of its epoch).
    first_rounds: BTreeMap<EpochNumber, Round>,
    /// G2 inclusion attestations on the ledger (DESIGN.md §12.4): committed blocks of the rounds not yet
    /// processed, and for the rounds before them the highest nonce of each owner.
    committed: BTreeMap<Round, LedgerBlock>,
    watermark: HashMap<PublicKey, u64>,
}

/// What an omission proof is checked against: a committed block's digest and observed transactions.
struct LedgerBlock {
    digest: Digest,
    author: PublicKey,
    otxs: HashSet<Digest>,
    keys: HashSet<(PublicKey, u64)>,
}

/// The member that led `round`: by the table of the epoch its accusation was made in (`accused_in`), which is the
/// table the accusers went by, or else by the table of the epoch the round falls in.
fn leader_index(
    tables: &BTreeMap<EpochNumber, Committee>,
    first_rounds: &BTreeMap<EpochNumber, Round>,
    members: &[(PublicKey, Authority)],
    round: Round,
    accused_in: Option<EpochNumber>,
) -> Option<usize> {
    let epoch = accused_in.or_else(|| {
        first_rounds.iter().rev().find(|(_, first)| **first <= round).map(|(e, _)| *e)
    })?;
    let name = leader(tables.get(&epoch)?, round);
    members.binary_search_by_key(&name, |(n, _)| *n).ok()
}

/// The G1 and reputation parameters for the configured epoch length: the durations in epochs (L1 bar, L2 and L3
/// suspensions, chain window, look-back, governance delay) and the recovery per epoch of the defaults are for
/// epochs of `reference_length` rounds, and keep their length in rounds at any other epoch length. The leader
/// rule's windows (lag, exclusion, queue wait) are in rounds already.
pub fn scaled(config: &EpochConfig) -> (PunishConfig, G2Config) {
    let mut punish = PunishConfig {
        l_max: ttru::from_ppm(config.l_max_ppm),
        ..PunishConfig::default()
    };
    let mut g2 = G2Config::default();
    let (length, reference) = (config.length, config.reference_length);
    if length > 0 && reference > 0 && length != reference {
        let epochs = |n: u64| ((n * reference + length / 2) / length).max(1);
        punish.lead_bar = epochs(punish.lead_bar);
        punish.suspend_l2 = epochs(punish.suspend_l2);
        punish.suspend_l3 = epochs(punish.suspend_l3);
        punish.chain_window = epochs(punish.chain_window);
        punish.lookback = epochs(punish.lookback);
        punish.governance_delay = epochs(punish.governance_delay);
        g2.recover_ppm = g2.recover_ppm * length / reference;
    }
    (punish, g2)
}

/// The entity of each member, numbered in the order of their first members.
fn entities(members: &[(PublicKey, Authority)]) -> Vec<usize> {
    let mut known = HashMap::new();
    let mut count = 0;
    members
        .iter()
        .map(|(_, a)| {
            let mut new = || {
                count += 1;
                count - 1
            };
            match a.entity {
                Some(id) => *known.entry(id).or_insert_with(new),
                None => new(),
            }
        })
        .collect()
}

/// The members of an entity.
fn members_of<'a>(
    members: &'a [(PublicKey, Authority)],
    entity_of: &'a [usize],
    entity: usize,
) -> impl Iterator<Item = &'a PublicKey> {
    members.iter().zip(entity_of).filter(move |(_, e)| **e == entity).map(|((name, _), _)| name)
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
        let entity_of = entities(&members);
        let count = entity_of.iter().max().map_or(0, |e| e + 1);
        let mut classes = vec![Class::Licensed; count];
        let mut weights = vec![0u64; count];
        for ((_, a), e) in members.iter().zip(&entity_of) {
            weights[*e] += a.stake as u64;
            if !a.certified {
                classes[*e] = Class::Uncertified;
            }
        }
        let (cap, u_max) = (ttru::from_ppm(config.entity_cap_ppm), ttru::from_ppm(config.class_cap_ppm));
        let base = ttru::base_weights(&classes, &weights, cap, u_max);
        for ((name, a), e) in members.iter().zip(&entity_of) {
            // NOTE: this log entry is used to weigh the reputation cuts by base weight (benchmark/p5.py).
            let b = base[*e] * a.stake as u128 / (weights[*e] as u128).max(1);
            info!("T_tru base weight of {} is {} ppm", name, b * ttru::PPM / ttru::ONE);
        }
        let largest = base.iter().copied().max().unwrap_or(0);
        if largest > cap {
            info!("Entity cap relaxed to {} ppm: the committee is too small for it", largest * ttru::PPM / ttru::ONE);
        }
        let (punish_config, g2_config) = scaled(&config);
        let punishment = Punishment::new(classes, weights, cap, u_max, punish_config);
        let mut epochs = Self {
            config,
            members,
            entity_of,
            reputation: Reputation::new(base, g2_config),
            punishment,
            current: roster.epoch,
            start: 0,
            ledger: roster.epoch,
            ledger_start: 0,
            tables: BTreeMap::new(),
            first_rounds: BTreeMap::new(),
            committed: BTreeMap::new(),
            watermark: HashMap::new(),
        };
        // H1': the second epoch has no ledger two terminal blocks back either, so it starts from the same state.
        for epoch in roster.epoch..=roster.epoch + 1 {
            let table = epochs.make_table(epoch);
            epochs.tables.insert(epoch, table);
        }
        epochs.first_rounds.insert(roster.epoch, 0);
        epochs
    }

    /// W_e = F(ledger up to G_{e-2}) (H1'): stakes from the base shares (G1), reputations within the budget (G2)
    /// and suspensions (z, G1); leadership barred by the G2 exclusions and by G1 (L1, suspended, queued, evicted).
    fn make_table(&self, epoch: EpochNumber) -> Committee {
        let z = self.punishment.z();
        let stakes = self.split(&self.reputation.stakes_on(self.punishment.base(), &z));
        let excluded = self.reputation.excluded();
        let bars = self.punishment.bars();
        Committee {
            authorities: self
                .members
                .iter()
                .enumerate()
                .zip(stakes)
                .map(|((i, (name, a)), stake)| {
                    let e = self.entity_of[i];
                    let authority = Authority {
                        stake: stake as Stake,
                        leader: !excluded[e] && !bars[e],
                        ..a.clone()
                    };
                    (*name, authority)
                })
                .collect(),
            epoch,
            handover: None,
        }
    }

    /// The stakes of the members: each entity's stake, in proportion to their base weights.
    fn split(&self, stakes: &[u64]) -> Vec<u64> {
        let mut totals = vec![0u64; stakes.len()];
        for ((_, a), e) in self.members.iter().zip(&self.entity_of) {
            totals[*e] += a.stake as u64;
        }
        let mut left = stakes.to_vec();
        let mut split: Vec<u64> = self
            .members
            .iter()
            .zip(&self.entity_of)
            .map(|((_, a), e)| {
                let stake = stakes[*e] * a.stake as u64 / totals[*e].max(1);
                left[*e] -= stake;
                stake
            })
            .collect();
        // What the rounding leaves goes to the first member of the entity.
        for (i, e) in self.entity_of.iter().enumerate() {
            split[i] += std::mem::take(&mut left[*e]);
        }
        split
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
                self.punishment.record(self.entity_of[i], kind, evidence.epoch(), block.epoch, malicious, false);
            }
        }
        let entry = LedgerBlock {
            digest: block.digest(),
            author: block.author,
            otxs: block.otxs.iter().map(|x| x.id()).collect(),
            keys: block.otxs.iter().map(|x| x.key()).collect(),
        };
        if block.round > self.reputation.done() {
            self.committed.insert(block.round, entry);
        } else {
            self.raise_watermark(&entry);
        }
        // A single-epoch run has no handover to process these facts and then forget them (enter_next), so keep
        // only the recent rounds. The horizon comes from the ledger (the block just recorded), so every node
        // keeps the same.
        if self.single_epoch() {
            let horizon = block.round.saturating_sub(SINGLE_EPOCH_LEDGER_WINDOW);
            self.forget_blocks_before(horizon);
            self.reputation.forget_before(horizon);
        }
    }

    fn raise_watermark(&mut self, block: &LedgerBlock) {
        for (owner, nonce) in &block.keys {
            let highest = self.watermark.entry(*owner).or_insert(0);
            *highest = (*highest).max(*nonce);
        }
    }

    /// Committed blocks before `round` are only kept as the watermark from here on.
    fn forget_blocks_before(&mut self, round: Round) {
        let kept = self.committed.split_off(&round);
        for (_, block) in std::mem::replace(&mut self.committed, kept) {
            self.raise_watermark(&block);
        }
    }

    /// An omission proof holds if the committed block of its round is the certified block it names and leaves the
    /// transaction out: not in it, no conflicting transaction in it, and still valid, its nonce above its owner's
    /// highest before that block. A higher nonce in the block itself does not excuse it: the leader could have
    /// included both.
    fn omission_holds(&self, omission: &OmitProof) -> bool {
        let block = match self.committed.get(&omission.round) {
            Some(block) => block,
            None => return false,
        };
        let (id, key) = (omission.otx.id(), omission.otx.key());
        let earlier = self.committed.range(..omission.round).flat_map(|(_, b)| b.keys.iter());
        let highest = earlier
            .filter(|(owner, _)| *owner == key.0)
            .map(|(_, nonce)| *nonce)
            .chain(self.watermark.get(&key.0).copied())
            .max()
            .unwrap_or(0);
        block.digest == omission.block
            && !block.otxs.contains(&id)
            && !block.keys.contains(&key)
            && key.1 > highest
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

    /// H1: whether `block`, the next block of the ledger in chain order, is the terminal block of the ledger's
    /// epoch.
    pub fn is_terminal(&self, block: &Block) -> bool {
        self.config.length > 0
            && block.epoch == self.ledger
            && block.round >= self.ledger_start + self.config.length
    }

    /// Whether `round` is past the end of the current epoch (a block there may be its terminal block or after it).
    pub fn past_end(&self, round: Round) -> bool {
        self.config.length > 0 && round >= self.start + self.config.length
    }

    /// Whether a QC of `round` may be the commit proof of the terminal block (its block's parent may be
    /// the terminal block), which can only be told once the certified block is at hand.
    pub fn may_end(&self, round: Round) -> bool {
        self.config.length > 0 && round > self.start + self.config.length
    }

    /// The ledger reaches the terminal block of its epoch. The leader rule processes the rounds up to (terminal
    /// round + 1 - lag), each led by the leader of its epoch's table (the epoch the accusation was made in, if
    /// any); then the table two epochs ahead is computed (H1'). The node enters the next epoch now (H3) unless
    /// it already did (enter_early). Returns whether it entered.
    pub fn enter_next(&mut self, terminal: &Block) -> bool {
        let horizon = (terminal.round + 1).saturating_sub(self.reputation.config().lag);
        let before = self.reputation.r_ppm().to_vec();
        let (tables, first_rounds, members) = (&self.tables, &self.first_rounds, &self.members);
        let entity_of = &self.entity_of;
        let events = self.reputation.advance(horizon, |round, accused_in| {
            leader_index(tables, first_rounds, members, round, accused_in).map(|i| entity_of[i])
        });
        for event in events {
            let (what, k, round) = match event {
                Event::Exclude(k, u) => ("excluded from leading", k, u),
                Event::Release(k, u) => ("may lead again", k, u),
                Event::Queue(k, u) => ("convicted, queued", k, u),
                Event::Drop(k, u) => ("dropped from the queue", k, u),
            };
            for name in members_of(members, entity_of, *k) {
                info!("G2: {} {} at round {}", name, what, round);
            }
        }
        self.forget_blocks_before(self.reputation.done() + 1);
        for (k, (old, new)) in before.iter().zip(self.reputation.r_ppm()).enumerate() {
            if old != new {
                for name in members_of(&self.members, &self.entity_of, k) {
                    info!("G2: reputation of {} is {} ppm", name, new);
                }
            }
        }

        // G1: the graded punishment for the table two epochs ahead.
        let target = self.ledger + 2;
        for event in self.punishment.update(target) {
            let (what, i, k) = match *event {
                G1Event::Level(l, i, k) => (format!("level L{}", l), i, k),
                G1Event::Queue(i, k) => ("queued for suspension".to_string(), i, k),
                G1Event::Suspend(i, k) => ("suspended".to_string(), i, k),
                G1Event::Release(i, k) => ("released".to_string(), i, k),
                G1Event::Evict(i, k) => ("evicted".to_string(), i, k),
                G1Event::Downgrade(i, k) => ("downgraded by governance".to_string(), i, k),
            };
            for name in members_of(&self.members, &self.entity_of, i) {
                info!("G1: {} {} at epoch {}", name, what, k);
            }
        }

        let table = self.make_table(target);
        self.tables.insert(target, table);
        let entering = self.current == self.ledger;
        if entering {
            self.enter(terminal);
        }
        self.ledger += 1;
        self.ledger_start = terminal.round;
        while self.tables.len() > KEEP {
            let oldest = *self.tables.keys().next().unwrap();
            self.tables.remove(&oldest);
            self.first_rounds.remove(&oldest);
        }
        entering
    }

    /// H3: switch to the next epoch, whose table is known a whole epoch ahead (H1'), at its terminal block.
    fn enter(&mut self, terminal: &Block) {
        // The child of the terminal block still belongs to this epoch (the commit proof certifies it, at the
        // adjacent round); the next epoch starts after it, and its first round keeps the old leader, which
        // holds that proof, even if the new table suspends it (it then proposes without voting).
        let next = self.current + 1;
        let first = terminal.round + 2;
        let handover = leader(self.current(), first);
        let table = self.tables.get_mut(&next).expect("the next table is known an epoch ahead");
        table.handover = Some((first, handover));
        self.first_rounds.insert(next, first);
        self.current = next;
        self.start = terminal.round;
    }

    /// H3 before the ledger gets there: a node that holds the terminal block of the current epoch and a commit
    /// proof of it (checked by the caller), but not yet every block before it, enters the next epoch, whose
    /// table it already knows (H1'). `terminal` must be the first block of the epoch past its end: its parent is
    /// not. The ledger's own processing of the epoch follows when it gets there (enter_next). Returns whether the
    /// node entered.
    pub fn enter_early(&mut self, terminal: &Block) -> bool {
        let first_past_end = self.past_end(terminal.round) && !self.past_end(terminal.qc.round);
        if terminal.epoch != self.current || !first_past_end || !self.tables.contains_key(&(self.current + 1)) {
            return false;
        }
        self.enter(terminal);
        true
    }
}
