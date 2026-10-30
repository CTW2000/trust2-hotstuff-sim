//! Graded G1 punishment on the ledger (方案说明 v0.12 §3.3; prototype/DESIGN.md §13): levels L1-L4 from the
//! evidence class, the correlated share c and repeats k; L1 bars from leading, L2/L3 suspend (z = 0) within the
//! suspension cap L_max through a strict FIFO queue, L4 goes to governance (stand-in: a fork or confirmed
//! malice evicts, otherwise downgraded to L2, or to L3 for a repeat). The rules are those of the simulator
//! (sim2/punish.py `GradedPunishment`, adopted defaults); the test vectors in tests/g1_vectors.json come from
//! it (prototype/scripts/gen_g1_vectors.py).
//!
//! Evidence enters with its sign epoch (es) and the epoch of the block that carried it (ec); it takes effect at
//! the table of the first epoch after ec. Everything is counted on base shares (CapNorm output), never on table
//! shares. Integers only.

use crate::config::EpochNumber;
use crate::ttru::{self, Class, ONE};
use std::collections::HashMap;

#[cfg(test)]
#[path = "tests/punish_tests.rs"]
pub mod punish_tests;

#[derive(Clone, Copy, Debug)]
pub struct PunishConfig {
    /// At most this much base weight suspended at once (fixed point).
    pub l_max: u128,
    /// Suspension of L2 and L3, in epochs.
    pub suspend_l2: u64,
    pub suspend_l3: u64,
    /// L1 bars from leading for this many epochs.
    pub lead_bar: u64,
    /// Chain window of the correlated share and look-back of repeats, in epochs.
    pub chain_window: u64,
    pub lookback: u64,
    /// Governance decides an L4 this many epochs later.
    pub governance_delay: u64,
}

impl Default for PunishConfig {
    /// The adopted defaults (方案说明 §3.3): L_max 10%, L2 4 and L3 32 epochs, L1 one epoch, windows 32 and 64,
    /// governance after 2 epochs.
    fn default() -> Self {
        Self {
            l_max: ONE / 10,
            suspend_l2: 4,
            suspend_l3: 32,
            lead_bar: 1,
            chain_window: 32,
            lookback: 64,
            governance_delay: 2,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Kind {
    /// NR self-contradiction.
    Liveness,
    /// E1, E2, E3.
    Safety,
}

/// What the punishment did, as in the simulator's log: (entity, epoch of the table).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum G1Event {
    Level(u8, usize, EpochNumber),
    Queue(usize, EpochNumber),
    Suspend(usize, EpochNumber),
    Release(usize, EpochNumber),
    Evict(usize, EpochNumber),
    Downgrade(usize, EpochNumber),
}

#[derive(Clone, Debug)]
struct Item {
    entity: usize,
    kind: Kind,
    sign_epoch: EpochNumber,
    chain_epoch: EpochNumber,
    malicious: bool,
    fork: bool,
    level: u8,
    repeats: u8,
}

pub struct Punishment {
    config: PunishConfig,
    classes: Vec<Class>,
    weights: Vec<u64>,
    cap: u128,
    u_max: u128,
    /// Above this share an offence is correlated: the cap, as CapNorm applied it.
    correlated: u128,
    /// Base shares when the run started (c is counted on them) and now (fork evictions recompute them).
    base0: Vec<u128>,
    base: Vec<u128>,
    /// Evidence on the ledger not yet taken in, in chain order.
    pending: Vec<Item>,
    items: Vec<Item>,
    windows: HashMap<(usize, Kind, EpochNumber), usize>,
    bar_until: Vec<EpochNumber>,
    /// Suspended in epochs < sus_until (None: not suspended), and the suspension's length.
    sus_until: Vec<Option<EpochNumber>>,
    sus_length: Vec<u64>,
    queue: Vec<(usize, u64, EpochNumber)>,
    governance: Vec<(usize, EpochNumber, usize)>,
    evicted: Vec<bool>,
    log: Vec<G1Event>,
    epoch: Option<EpochNumber>,
}

impl Punishment {
    /// `classes` and `weights` are the members' classes and base weights w_i; `cap` and `u_max` the CapNorm caps.
    pub fn new(classes: Vec<Class>, weights: Vec<u64>, cap: u128, u_max: u128, mut config: PunishConfig) -> Self {
        let base = ttru::base_weights(&classes, &weights, cap, u_max);
        // CapNorm relaxes the cap for a committee too small to respect it (no member can hold less than 1/n of an
        // equal split). L_max rises with it, or the strict FIFO queue would stall for good at a member above it;
        // and one member alone is still not a correlated fault.
        let largest = base.iter().copied().max().unwrap_or(0);
        config.l_max = config.l_max.max(largest);
        let n = classes.len();
        Self {
            config,
            classes,
            weights,
            cap,
            u_max,
            correlated: cap.max(largest),
            base0: base.clone(),
            base,
            pending: Vec::new(),
            items: Vec::new(),
            windows: HashMap::new(),
            bar_until: vec![0; n],
            sus_until: vec![None; n],
            sus_length: vec![0; n],
            queue: Vec::new(),
            governance: Vec::new(),
            evicted: vec![false; n],
            log: Vec::new(),
            epoch: None,
        }
    }

    /// The current base shares (CapNorm output; fork evictions recompute them).
    pub fn base(&self) -> &[u128] {
        &self.base
    }

    /// Evidence against `entity` signed in epoch `sign_epoch`, carried by a block of epoch `chain_epoch`.
    pub fn record(
        &mut self,
        entity: usize,
        kind: Kind,
        sign_epoch: EpochNumber,
        chain_epoch: EpochNumber,
        malicious: bool,
        fork: bool,
    ) {
        self.pending.push(Item {
            entity,
            kind,
            sign_epoch,
            chain_epoch,
            malicious,
            fork,
            level: 0,
            repeats: 0,
        });
    }

    /// One punished window per (entity, class, sign epoch): further evidence only feeds upgrades.
    fn add(&mut self, item: Item) {
        let key = (item.entity, item.kind, item.sign_epoch);
        match self.windows.get(&key) {
            Some(&index) => {
                self.items[index].fork |= item.fork;
                self.items[index].malicious |= item.malicious;
            }
            None => {
                self.windows.insert(key, self.items.len());
                self.items.push(item);
            }
        }
    }

    fn repeats(&self, entity: usize, kind: Kind, chain_epoch: EpochNumber) -> u8 {
        let since = chain_epoch.saturating_sub(self.config.lookback as EpochNumber);
        self.items
            .iter()
            .filter(|x| x.entity == entity && x.kind == kind && x.level > 0 && x.chain_epoch >= since)
            .count() as u8
    }

    /// The correlated share of a safety item: the larger of the sign window and the chain window.
    fn correlated(&self, item: &Item, k: EpochNumber) -> u128 {
        let share = |pick: &dyn Fn(&Item) -> bool| -> u128 {
            let mut entities: Vec<usize> = self
                .items
                .iter()
                .filter(|x| x.kind == Kind::Safety && pick(x))
                .map(|x| x.entity)
                .collect();
            entities.sort_unstable();
            entities.dedup();
            entities.iter().map(|i| self.base0[*i]).sum()
        };
        let mut c = share(&|x: &Item| x.sign_epoch == item.sign_epoch);
        let window = self.config.chain_window as EpochNumber;
        if item.chain_epoch + window > k {
            c = c.max(share(&|x: &Item| x.chain_epoch + window > k && x.chain_epoch <= k));
        }
        c
    }

    fn level(&self, item: &Item, k: EpochNumber) -> u8 {
        match item.kind {
            Kind::Liveness => (1 + item.repeats).min(3),
            Kind::Safety => {
                let c = self.correlated(item, k);
                let base = if item.fork || 3 * c > ONE {
                    4
                } else if c > self.correlated {
                    3
                } else {
                    2
                };
                (base + item.repeats).min(4)
            }
        }
    }

    fn suspend_request(&mut self, i: usize, length: u64, k: EpochNumber) {
        if self.evicted[i] {
            return;
        }
        if let Some(until) = self.sus_until[i] {
            if until > k {
                // Already suspended: an upgrade extends the suspension from its start.
                let start = until - self.sus_length[i] as EpochNumber;
                if start + length as EpochNumber > until {
                    self.sus_until[i] = Some(start + length as EpochNumber);
                    self.sus_length[i] = length;
                }
                return;
            }
        }
        if let Some(entry) = self.queue.iter_mut().find(|q| q.0 == i) {
            entry.1 = entry.1.max(length);
            return;
        }
        self.queue.push((i, length, k));
        self.log.push(G1Event::Queue(i, k));
    }

    fn apply(&mut self, index: usize, level: u8, k: EpochNumber) {
        let i = self.items[index].entity;
        self.log.push(G1Event::Level(level, i, k));
        match level {
            1 => self.bar_until[i] = self.bar_until[i].max(k + self.config.lead_bar as EpochNumber),
            2 => self.suspend_request(i, self.config.suspend_l2, k),
            3 => self.suspend_request(i, self.config.suspend_l3, k),
            _ => {
                if !self.governance.iter().any(|g| g.0 == i) {
                    let decide = k + self.config.governance_delay as EpochNumber;
                    self.governance.push((i, decide, index));
                }
            }
        }
    }

    fn evict(&mut self, i: usize, k: EpochNumber, fork: bool) {
        self.evicted[i] = true;
        self.sus_until[i] = None;
        self.queue.retain(|q| q.0 != i);
        self.log.push(G1Event::Evict(i, k));
        if !fork {
            // Other evictions just zero the entity, like a permanent suspension.
            self.base[i] = 0;
            return;
        }
        // A fork culprit: CapNorm over the rest. If the licensed class cannot fill its share under the cap,
        // the cap is relaxed to the smallest feasible value (the governance default), for both classes.
        let keep: Vec<usize> = (0..self.classes.len()).filter(|i| !self.evicted[*i]).collect();
        let licensed = keep.iter().filter(|i| self.classes[**i] == Class::Licensed).count() as u128;
        if licensed == 0 {
            self.base[i] = 0;
            return;
        }
        let total: u128 = keep.iter().map(|i| self.weights[*i] as u128).sum();
        let uncertified: u128 = keep
            .iter()
            .filter(|i| self.classes[**i] == Class::Uncertified)
            .map(|i| self.weights[*i] as u128)
            .sum();
        let licensed_total = ONE - (uncertified * ONE / total).min(self.u_max);
        let mut cap = self.cap;
        if licensed * cap < licensed_total {
            cap = licensed_total / licensed;
        }
        let classes: Vec<Class> = keep.iter().map(|i| self.classes[*i]).collect();
        let weights: Vec<u64> = keep.iter().map(|i| self.weights[*i]).collect();
        let shares = ttru::base_weights(&classes, &weights, cap, self.u_max);
        self.base = vec![0; self.classes.len()];
        for (i, share) in keep.into_iter().zip(shares) {
            self.base[i] = share;
        }
    }

    /// The state for the table of epoch `k` (called once per epoch, in order): takes in the evidence of chain
    /// epochs < k, applies new levels and upgrades, governance decisions, releases and the queue. Returns the
    /// events of this epoch change.
    pub fn update(&mut self, k: EpochNumber) -> &[G1Event] {
        if let Some(previous) = self.epoch {
            assert_eq!(k, previous + 1, "tables must be built in order");
        }
        self.epoch = Some(k);
        self.log.clear();

        let (now, later): (Vec<Item>, Vec<Item>) = std::mem::take(&mut self.pending)
            .into_iter()
            .partition(|x| x.chain_epoch < k);
        self.pending = later;
        let mut now = now;
        now.sort_by_key(|x| x.chain_epoch); // stable: chain order within an epoch
        for item in now {
            self.add(item);
        }

        for index in 0..self.items.len() {
            let item = self.items[index].clone();
            if self.evicted[item.entity] {
                continue;
            }
            if item.level == 0 {
                self.items[index].repeats = self.repeats(item.entity, item.kind, item.chain_epoch);
            }
            let level = self.level(&self.items[index].clone(), k);
            if level > self.items[index].level {
                self.items[index].level = level;
                self.apply(index, level, k);
            }
        }

        let due: Vec<_> = self.governance.iter().filter(|g| g.1 <= k).cloned().collect();
        self.governance.retain(|g| g.1 > k);
        for (i, _, index) in due {
            let item = self.items[index].clone();
            if item.fork || item.malicious {
                self.evict(i, k, item.fork);
            } else {
                // Without malice or a fork: a repeat is a long suspension, a client fault a short one.
                self.log.push(G1Event::Downgrade(i, k));
                let length = match item.repeats {
                    0 => self.config.suspend_l2,
                    _ => self.config.suspend_l3,
                };
                self.suspend_request(i, length, k);
            }
        }

        for i in 0..self.classes.len() {
            if matches!(self.sus_until[i], Some(until) if until <= k) {
                self.sus_until[i] = None;
                self.log.push(G1Event::Release(i, k));
            }
        }

        let mut keep = Vec::new();
        let mut blocked = false;
        for (i, length, t) in std::mem::take(&mut self.queue) {
            if !blocked && self.suspended_share(k) + self.base[i] <= self.config.l_max {
                self.sus_until[i] = Some(k + length as EpochNumber);
                self.sus_length[i] = length;
                self.log.push(G1Event::Suspend(i, k));
            } else {
                blocked = true; // strict FIFO
                keep.push((i, length, t));
            }
        }
        self.queue = keep;
        &self.log
    }

    fn suspended_share(&self, k: EpochNumber) -> u128 {
        (0..self.classes.len())
            .filter(|i| matches!(self.sus_until[*i], Some(until) if until > k))
            .map(|i| self.base[i])
            .sum()
    }

    fn suspended(&self, i: usize) -> bool {
        let k = self.epoch.unwrap_or(0);
        self.evicted[i] || matches!(self.sus_until[i], Some(until) if until > k)
    }

    /// z of the current table: false while suspended or evicted.
    pub fn z(&self) -> Vec<bool> {
        (0..self.classes.len()).map(|i| !self.suspended(i)).collect()
    }

    /// Barred from leading in the current epoch: L1, suspended, evicted, or queued for a suspension.
    pub fn bars(&self) -> Vec<bool> {
        let k = self.epoch.unwrap_or(0);
        (0..self.classes.len())
            .map(|i| self.bar_until[i] > k || self.suspended(i) || self.queue.iter().any(|q| q.0 == i))
            .collect()
    }

    /// Entities queued for a suspension, head first.
    pub fn queue(&self) -> Vec<usize> {
        self.queue.iter().map(|q| q.0).collect()
    }
}
