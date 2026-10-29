//! G2 on the ledger (prototype/DESIGN.md §12): AT accusations feed a CUSUM per leader; a conviction excludes
//! the leader from leading (exclusion cap on base weight, strict FIFO queue, expiry) and lowers its reputation
//! r within the budget B_rep. The rules and parameters are those of the simulator (sim2/schedule.py
//! `CusumExclusion` with AT evidence and expiry by round, sim2/ttru.py `TtruWeights`); the test vectors in
//! tests/g2_vectors.json come from them (prototype/scripts/gen_g2_vectors.py).
//!
//! The state only changes at an epoch change, from the accusations committed up to the terminal block, so
//! every node derives the same reputations, exclusions and leader schedule. Integers only: the CUSUM counts
//! in millionths, r in ppm, weights in fixed point.

use crate::config::EpochNumber;
use crate::consensus::Round;
use crate::ttru::{self, ONE, PPM};
use std::collections::BTreeMap;

#[cfg(test)]
#[path = "tests/reputation_tests.rs"]
pub mod reputation_tests;

#[derive(Clone, Copy, Debug)]
pub struct G2Config {
    /// Facts of rounds <= (terminal round + 1 - lag) are processed at an epoch change.
    pub lag: Round,
    /// CUSUM increments in millionths: ln(q/ρ̄) on an accusation, ln((1-q)/(1-ρ̄)) otherwise; threshold ln γ.
    pub up: i64,
    pub down: i64,
    pub threshold: i64,
    /// An exclusion lasts this many rounds.
    pub exclusion: Round,
    /// At most this much base weight is excluded at once (fixed point); further convictions queue.
    pub cap: u128,
    /// A queued conviction is dropped after this many rounds.
    pub queue_wait: Round,
    pub r_min_ppm: u64,
    pub step_ppm: u64,
    pub recover_ppm: u64,
    /// Reputation budget: at most this much base weight is cut (fixed point).
    pub b_rep: u128,
}

impl Default for G2Config {
    /// The recommended protocol (信任2.0_协议级验证 §4.4): q = 0.5, ρ̄ = 0.1, γ = 10⁴, D = 500, cap 0.5,
    /// Wq = 500, r_min = 0.7, step 0.1, recovery 0.02, B_rep = 0.10, lag 10.
    fn default() -> Self {
        Self {
            lag: 10,
            up: 1_609_438,         // ln 5
            down: -587_787,        // ln(5/9)
            threshold: 9_210_340,  // ln 10⁴
            exclusion: 500,
            cap: ONE / 2,
            queue_wait: 500,
            r_min_ppm: 700_000,
            step_ppm: 100_000,
            recover_ppm: 20_000,
            b_rep: ONE / 10,
        }
    }
}

/// What the leader rule did, as in the simulator's rule log.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Event {
    Exclude(usize, Round),
    Release(usize, Round),
    Queue(usize, Round),
    Drop(usize, Round),
}

pub struct Reputation {
    config: G2Config,
    /// CapNorm of the base weights (fixed point), by member index.
    base: Vec<u128>,
    cusum: Vec<i64>,
    excluded: Vec<bool>,
    until: Vec<Round>,
    queue: Vec<(usize, Round)>,
    /// Rounds up to here have been processed.
    done: Round,
    r_ppm: Vec<u64>,
    /// Accusations found on the ledger and not processed yet: round -> epoch of the accusation.
    accused: BTreeMap<Round, EpochNumber>,
    log: Vec<Event>,
}

impl Reputation {
    pub fn new(base: Vec<u128>, config: G2Config) -> Self {
        let n = base.len();
        Self {
            config,
            base,
            cusum: vec![0; n],
            excluded: vec![false; n],
            until: vec![0; n],
            queue: Vec::new(),
            done: 0,
            r_ppm: vec![PPM as u64; n],
            accused: BTreeMap::new(),
            log: Vec::new(),
        }
    }

    pub fn config(&self) -> &G2Config {
        &self.config
    }

    /// Rounds up to here are processed; later accusations of them are ignored.
    pub fn done(&self) -> Round {
        self.done
    }

    pub fn r_ppm(&self) -> &[u64] {
        &self.r_ppm
    }

    /// Members barred from leading.
    pub fn excluded(&self) -> &[bool] {
        &self.excluded
    }

    /// Bad facts recorded and not processed yet: round -> epoch.
    pub fn facts(&self) -> &BTreeMap<Round, EpochNumber> {
        &self.accused
    }

    /// Queued convictions (member, round of the conviction), head first.
    pub fn queue(&self) -> &[(usize, Round)] {
        &self.queue
    }

    /// An accusation of `round` (made with the table of `epoch`) found on the ledger. The first one counts;
    /// accusations of rounds already processed come too late and are ignored.
    pub fn record(&mut self, round: Round, epoch: EpochNumber) {
        if round > self.done {
            self.accused.entry(round).or_insert(epoch);
        }
    }

    /// Epoch change: process the rounds up to `horizon` in order, then update the reputations. `leader_of`
    /// gives the member that led a round (given the epoch of its accusation, if any), or None if unknown.
    /// Returns the events of this epoch change.
    pub fn advance<F>(&mut self, horizon: Round, leader_of: F) -> &[Event]
    where
        F: Fn(Round, Option<EpochNumber>) -> Option<usize>,
    {
        self.log.clear();
        let mut convicted = vec![false; self.base.len()];
        for u in self.done + 1..=horizon {
            if u < 1 {
                continue;
            }
            self.step(u, &leader_of);
        }
        self.done = self.done.max(horizon);
        self.accused = self.accused.split_off(&(self.done + 1));
        for event in &self.log {
            if let Event::Exclude(k, _) = event {
                convicted[*k] = true;
            }
        }

        // TtruWeights: a conviction lowers r; r stays put during the exclusion and recovers otherwise.
        let c = &self.config;
        for (k, r) in self.r_ppm.iter_mut().enumerate() {
            *r = if convicted[k] {
                r.saturating_sub(c.step_ppm).max(c.r_min_ppm)
            } else if self.excluded[k] {
                *r
            } else {
                (*r + c.recover_ppm).min(PPM as u64)
            };
        }
        &self.log
    }

    /// One round of CusumExclusion._advance (expiry by round).
    fn step<F>(&mut self, u: Round, leader_of: &F)
    where
        F: Fn(Round, Option<EpochNumber>) -> Option<usize>,
    {
        for k in 0..self.base.len() {
            if self.excluded[k] && self.until[k] <= u {
                self.excluded[k] = false;
                self.log.push(Event::Release(k, u));
            }
        }

        let mut keep = Vec::new();
        let mut blocked = false;
        for (k, t) in std::mem::take(&mut self.queue) {
            if u - t > self.config.queue_wait {
                // A dropped conviction starts over.
                self.cusum[k] = 0;
                self.log.push(Event::Drop(k, u));
            } else if !blocked && !self.excluded[k] && self.room(k) {
                self.exclude(k, u);
            } else {
                if !self.excluded[k] {
                    blocked = true; // strict FIFO: later entries wait behind the head
                }
                keep.push((k, t));
            }
        }
        self.queue = keep;

        let accusation = self.accused.get(&u).copied();
        let leader = match leader_of(u, accusation) {
            Some(k) if !self.excluded[k] => k,
            _ => return,
        };
        let increment = match accusation {
            Some(_) => self.config.up,
            None => self.config.down,
        };
        self.cusum[leader] = (self.cusum[leader] + increment).max(0);
        if self.cusum[leader] >= self.config.threshold {
            self.convict(leader, u);
        }
    }

    fn room(&self, k: usize) -> bool {
        let excluded: u128 = (0..self.base.len())
            .filter(|i| self.excluded[*i])
            .map(|i| self.base[i])
            .sum();
        excluded + self.base[k] <= self.config.cap
    }

    fn convict(&mut self, k: usize, u: Round) {
        match self.queue.iter().position(|(x, _)| *x == k) {
            None if self.queue.is_empty() && self.room(k) => self.exclude(k, u),
            None => {
                self.queue.push((k, u));
                self.cusum[k] = 0;
                self.log.push(Event::Queue(k, u));
            }
            Some(_) => self.cusum[k] = self.config.threshold, // already queued: no pile-up
        }
    }

    fn exclude(&mut self, k: usize, u: Round) {
        self.excluded[k] = true;
        self.until[k] = u + self.config.exclusion;
        self.cusum[k] = 0;
        self.log.push(Event::Exclude(k, u));
    }

    /// Integer stakes of the next table: T = base · r · z within the budget (`ttru::table`).
    pub fn stakes(&self, z: &[bool]) -> Vec<u64> {
        ttru::table(&self.base, &self.r_ppm, z, self.config.b_rep)
    }
}
