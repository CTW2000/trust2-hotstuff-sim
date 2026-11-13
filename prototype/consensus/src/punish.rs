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
    /// Sign window, chain window of the correlated share and look-back of repeats, in epochs. Evidence signed in the
    /// same sign window counts as one fault of its entity and class.
    pub sign_window: u64,
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
            sign_window: 1,
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
        let base = ttru::base_weights(&classes, &weights, cap, u_max)
            .unwrap_or_else(|e| panic!("CapNorm rejects the roster: {}", e));
        // CapNorm never relaxes the cap (DESIGN.md §15.28), so no entity is above it; L_max is kept at least the
        // largest base share all the same, or the strict FIFO queue would stall for good at a member above it.
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
        // Evidence is valid for the look-back: older, it no longer punishes, as it no longer counts as a repeat.
        if chain_epoch.saturating_sub(sign_epoch) > self.config.lookback as EpochNumber {
            return;
        }
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

    /// One punished window per (entity, class, sign window): further evidence only feeds upgrades.
    fn add(&mut self, item: Item) {
        let key = (item.entity, item.kind, item.sign_epoch / self.config.sign_window.max(1) as EpochNumber);
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
        let w = self.config.sign_window.max(1) as EpochNumber;
        let mut c = share(&|x: &Item| x.sign_epoch / w == item.sign_epoch / w);
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
        // A fork culprit: CapNorm over the rest. If the rest is a roster CapNorm rejects (the caps cannot hold, or
        // no licensed entity is left), the base shares are not recomputed: the culprit is zeroed like any other
        // evicted entity, and governance has to add members (DESIGN.md §15.28). The cap is never relaxed.
        let keep: Vec<usize> = (0..self.classes.len()).filter(|i| !self.evicted[*i]).collect();
        let classes: Vec<Class> = keep.iter().map(|i| self.classes[*i]).collect();
        let weights: Vec<u64> = keep.iter().map(|i| self.weights[*i]).collect();
        match ttru::base_weights(&classes, &weights, self.cap, self.u_max) {
            Ok(shares) => {
                self.base = vec![0; self.classes.len()];
                for (i, share) in keep.into_iter().zip(shares) {
                    self.base[i] = share;
                }
            }
            Err(_) => self.base[i] = 0,
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

    /// Barred from leading in the current epoch: L1, suspended or evicted. An entity queued for a suspension keeps
    /// leading until the suspension starts (DESIGN.md §15.31): G1 evidence cannot be forged, so a late suspension
    /// frames nobody, while barring the whole queue, which L_max does not cap, would hand every lead to the rest
    /// after a client bug.
    pub fn bars(&self) -> Vec<bool> {
        let k = self.epoch.unwrap_or(0);
        (0..self.classes.len()).map(|i| self.bar_until[i] > k || self.suspended(i)).collect()
    }

    /// The events of the latest table (`update`).
    pub fn events(&self) -> &[G1Event] {
        &self.log
    }

    /// Entities queued for a suspension, head first.
    pub fn queue(&self) -> Vec<usize> {
        self.queue.iter().map(|q| q.0).collect()
    }
}
