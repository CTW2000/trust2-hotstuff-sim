//! Synthetic link delays for experiments (prototype/DESIGN.md §14.1), as the simulator's network model
//! (sim2/net.py): a message from node i to node j waits base[i][j] + U(0, jitter) + bytes / bandwidth before it
//! is written to the socket. Messages of one link keep their order: a message is due no earlier than the one
//! queued before it, and the delay is counted from the time it was queued.
//!
//! Configured through the environment: TTRU_DELAYS names a JSON file {"addresses": {"<ip:port>": node, ...},
//! "base_ms": [[...]], "jitter_ms": x, "bandwidth_mbps": y} and TTRU_NODE is this node's index. Without them
//! there is no delay at all.
use rand::Rng as _;
use serde::Deserialize;
use std::collections::HashMap;
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
        Some(Duration::from_secs_f64((self.base_ms[self.me][j] + jitter + transmission) / 1e3))
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

/// When a message of `bytes` bytes to `to`, queued now behind a message due at `last`, is due.
pub fn due(to: &SocketAddr, bytes: usize, last: Option<Instant>) -> Instant {
    let now = Instant::now();
    let at = match DELAYS.get_or_init(load) {
        Some(delays) => now + delays.of(to, bytes).unwrap_or_default(),
        None => now,
    };
    last.map_or(at, |last| at.max(last))
}
