//! Epochs and the handover of the weight table (prototype/DESIGN.md §9; theory rules H1–H4).
//!
//! - H1: the terminal block G_e of epoch e is the first block of epoch e on the chain whose round is at
//!   least s_e + length, where s_e is the round of G_{e-1} (0 for the first epoch). The predicate only
//!   looks at the block, so it is a function of the chain prefix.
//! - The table of epoch e+1 is a deterministic function of the ledger up to G_e: the AT accusations on it
//!   drive the G2 leader rule and the reputations (reputation.rs, DESIGN.md §12.2), which give each
//!   member's stake (CapNorm of the base weights times r, within the budget) and whether it may lead.
//!   Suspensions (z, G1) come with P4.
//! - H3: a node enters epoch e+1 when it first holds a commit proof of G_e (Core::commit); from then on it
//!   signs no message of an older epoch. The tables of the last few epochs are kept to verify old blocks
//!   received through synchronization.

use crate::config::{Authority, Committee, EpochNumber, Stake};
use crate::consensus::Round;
use crate::leader::leader;
use crate::messages::Block;
use crate::reputation::{Event, G2Config, Reputation};
use crate::ttru::{self, Class};
use crypto::PublicKey;
use log::info;
use std::collections::BTreeMap;

#[cfg(test)]
#[path = "tests/epoch_tests.rs"]
pub mod epoch_tests;

/// Tables kept for verification: the current epoch and the previous ones.
const KEEP: usize = 16;

#[derive(Clone, Copy, Debug)]
pub struct EpochConfig {
    /// Rounds per epoch, counted from the previous terminal block (0: a single epoch).
    pub length: Round,
    pub entity_cap_ppm: u64,
    pub class_cap_ppm: u64,
}

pub struct Epochs {
    config: EpochConfig,
    /// Members in a fixed order with their addresses and classes (from the configuration).
    members: Vec<(PublicKey, Authority)>,
    /// G2 state from the ledger, by member index; holds the CapNorm base weights.
    reputation: Reputation,
    current: EpochNumber,
    /// s_e: round of the terminal block of the previous epoch.
    start: Round,
    tables: BTreeMap<EpochNumber, Committee>,
    /// First round of each kept epoch (a round's leader comes from the table of its epoch).
    first_rounds: BTreeMap<EpochNumber, Round>,
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
        let base = ttru::base_weights(
            &classes,
            &weights,
            ttru::from_ppm(config.entity_cap_ppm),
            ttru::from_ppm(config.class_cap_ppm),
        );
        let mut epochs = Self {
            config,
            members,
            reputation: Reputation::new(base, G2Config::default()),
            current: roster.epoch,
            start: 0,
            tables: BTreeMap::new(),
            first_rounds: BTreeMap::new(),
        };
        let first = epochs.make_table(roster.epoch);
        epochs.tables.insert(roster.epoch, first);
        epochs.first_rounds.insert(roster.epoch, 0);
        epochs
    }

    /// W_e = F(ledger up to G_{e-1}): stakes from the reputations within the budget, leadership from the G2
    /// exclusions. P3: no suspensions yet (z = 1).
    fn make_table(&self, epoch: EpochNumber) -> Committee {
        let n = self.members.len();
        let stakes = self.reputation.stakes(&vec![true; n]);
        let excluded = self.reputation.excluded();
        Committee {
            authorities: self
                .members
                .iter()
                .zip(stakes)
                .zip(excluded)
                .map(|(((name, a), stake), excluded)| {
                    let authority = Authority {
                        stake: stake as Stake,
                        leader: !excluded,
                        ..a.clone()
                    };
                    (*name, authority)
                })
                .collect(),
            epoch,
        }
    }

    /// A committed block, in chain order: the AT accusations it carries go on the ledger state.
    pub fn record(&mut self, block: &Block) {
        for accusation in &block.accusations {
            self.reputation.record(accusation.round, accusation.epoch);
        }
    }

    /// Rounds up to here have been processed by the leader rule; accusations of them come too late.
    pub fn done(&self) -> Round {
        self.reputation.done()
    }

    pub fn epoch(&self) -> EpochNumber {
        self.current
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

        let next = self.current + 1;
        let table = self.make_table(next);
        self.tables.insert(next, table);
        // The child of the terminal block still belongs to this epoch; the next one starts after it.
        self.first_rounds.insert(next, terminal.round + 2);
        self.current = next;
        self.start = terminal.round;
        while self.tables.len() > KEEP {
            let oldest = *self.tables.keys().next().unwrap();
            self.tables.remove(&oldest);
            self.first_rounds.remove(&oldest);
        }
    }
}
