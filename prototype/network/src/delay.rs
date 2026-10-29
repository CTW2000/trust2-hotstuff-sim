//! Synthetic link delays for experiments (prototype/DESIGN.md §14.1), as the simulator's network model
//! (sim2/net.py): a message from node i to node j waits base[i][j] + U(0, jitter) + bytes / bandwidth before it
//! is written to the socket, counted from the time it was queued; a message to one of the `late_to` addresses
//! (the consensus ports) is, with probability late_p, late by late_ms more (model P, which the simulator applies
//! to consensus messages only; it does not model data dissemination). Each message is delayed independently, as
//! in the simulator: the senders write the queued messages of a link in the order they are due, so a late message
//! does not hold back the ones behind it.
//!
//! Configured through the environment: TTRU_DELAYS names a JSON file {"addresses": {"<ip:port>": node, ...},
//! "base_ms": [[...]], "jitter_ms": x, "bandwidth_mbps": y, "late_p": p, "late_ms": z, "late_to": ["<ip:port>",
//! ...]} and TTRU_NODE is this node's index. Without them there is no delay at all.
use rand::Rng as _;
use serde::Deserialize;
use std::collections::{HashMap, HashSet};
use std::net::SocketAddr;
use std::sync::OnceLock;
use tokio::time::{Duration, Instant};

#[cfg(test)]
#[path = "tests/delay_tests.rs"]
pub mod delay_tests;

#[derive(Deserialize)]
pub struct Delays {
    addresses: HashMap<SocketAddr, usize>,
    base_ms: Vec<Vec<f64>>,
    jitter_ms: f64,
    bandwidth_mbps: f64,
    #[serde(default)]
    late_p: f64,
    #[serde(default)]
    late_ms: f64,
    #[serde(default)]
    late_to: HashSet<SocketAddr>,
    #[serde(skip)]
    me: usize,
}

impl Delays {
    pub fn from_json(json: &str, me: usize) -> Result<Self, serde_json::Error> {
        let mut delays: Self = serde_json::from_str(json)?;
        delays.me = me;
        Ok(delays)
    }

    /// The delay of a message of `bytes` bytes to `to`, if `to` is another node of the table.
    pub fn of(&self, to: &SocketAddr, bytes: usize) -> Option<Duration> {
        let j = *self.addresses.get(to)?;
        if j == self.me {
            return None;
        }
        let jitter = match self.jitter_ms > 0.0 {
            true => rand::thread_rng().gen_range(0.0, self.jitter_ms),
            false => 0.0,
        };
        let transmission = bytes as f64 * 8.0 / (self.bandwidth_mbps * 1e3);
        let late = match self.late_p > 0.0 && self.late_to.contains(to) && rand::thread_rng().gen_bool(self.late_p) {
            true => self.late_ms,
            false => 0.0,
        };
        Some(Duration::from_secs_f64((self.base_ms[self.me][j] + jitter + transmission + late) / 1e3))
    }
}

static DELAYS: OnceLock<Option<Delays>> = OnceLock::new();

fn load() -> Option<Delays> {
    let path = std::env::var("TTRU_DELAYS").ok()?;
    let me = std::env::var("TTRU_NODE").ok()?.parse().expect("TTRU_NODE must be a node index");
    let json = std::fs::read_to_string(&path).expect("cannot read TTRU_DELAYS");
    let delays = Delays::from_json(&json, me).expect("malformed TTRU_DELAYS");
    log::info!("Synthetic link delays from {} (node {})", path, me);
    Some(delays)
}

/// Whether synthetic delays are configured.
pub fn enabled() -> bool {
    DELAYS.get_or_init(load).is_some()
}

/// When a message of `bytes` bytes to `to`, queued now, is due.
pub fn due(to: &SocketAddr, bytes: usize) -> Instant {
    let now = Instant::now();
    match DELAYS.get_or_init(load) {
        Some(delays) => now + delays.of(to, bytes).unwrap_or_default(),
        None => now,
    }
}

/// Where a message due at `at` goes in a queue kept in due order (after the messages due at the same time, so
/// that without delays the queue stays first in, first out).
pub fn position<T>(queue: &std::collections::VecDeque<T>, at: Instant, due: impl Fn(&T) -> Instant) -> usize {
    queue.iter().rposition(|x| due(x) <= at).map_or(0, |i| i + 1)
}
