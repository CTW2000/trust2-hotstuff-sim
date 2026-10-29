use crypto::PublicKey;
use log::info;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::net::SocketAddr;

pub type Stake = u32;
pub type EpochNumber = u128;

#[derive(Serialize, Deserialize)]
pub struct Parameters {
    pub timeout_delay: u64,
    pub sync_retry_delay: u64,
    /// Rounds per epoch, counted from the previous terminal block (0: a single epoch, no handover).
    #[serde(default = "default_epoch_length")]
    pub epoch_length: u64,
    /// Entity cap of CapNorm, in ppm of the total weight (1_000_000: no cap).
    #[serde(default = "default_ppm")]
    pub entity_cap_ppm: u64,
    /// Cap on the uncertified class, in ppm (1_000_000: no cap).
    #[serde(default = "default_ppm")]
    pub class_cap_ppm: u64,
}

fn default_epoch_length() -> u64 {
    100
}

fn default_ppm() -> u64 {
    1_000_000
}

impl Default for Parameters {
    fn default() -> Self {
        Self {
            timeout_delay: 5_000,
            sync_retry_delay: 10_000,
            epoch_length: default_epoch_length(),
            entity_cap_ppm: default_ppm(),
            class_cap_ppm: default_ppm(),
        }
    }
}

impl Parameters {
    pub fn log(&self) {
        // NOTE: These log entries are used to compute performance.
        info!("Timeout delay set to {} rounds", self.timeout_delay);
        info!("Sync retry delay set to {} ms", self.sync_retry_delay);
        info!("Epoch length set to {} rounds", self.epoch_length);
        info!(
            "Entity cap set to {} ppm, uncertified class cap to {} ppm",
            self.entity_cap_ppm, self.class_cap_ppm
        );
    }
}

/// In the configuration `stake` is the chain's base weight w_i; in an epoch's weight table it is the
/// integer T_tru weight (crate::epoch).
#[derive(Clone, Serialize, Deserialize)]
pub struct Authority {
    pub stake: Stake,
    pub address: SocketAddr,
    /// Certified (licensed) entity; uncertified ones share at most the class cap.
    #[serde(default = "default_certified")]
    pub certified: bool,
}

fn default_certified() -> bool {
    true
}

#[derive(Clone, Serialize, Deserialize)]
pub struct Committee {
    pub authorities: HashMap<PublicKey, Authority>,
    pub epoch: EpochNumber,
}

impl std::fmt::Debug for Committee {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "Committee(epoch {}, {} members)", self.epoch, self.size())
    }
}

impl Committee {
    pub fn new(info: Vec<(PublicKey, Stake, SocketAddr)>, epoch: EpochNumber) -> Self {
        Self {
            authorities: info
                .into_iter()
                .map(|(name, stake, address)| {
                    let authority = Authority {
                        stake,
                        address,
                        certified: true,
                    };
                    (name, authority)
                })
                .collect(),
            epoch,
        }
    }

    pub fn size(&self) -> usize {
        self.authorities.len()
    }

    pub fn stake(&self, name: &PublicKey) -> Stake {
        self.authorities.get(name).map_or_else(|| 0, |x| x.stake)
    }

    pub fn quorum_threshold(&self) -> Stake {
        // If N = 3f + 1 + k (0 <= k < 3)
        // then (2 N + 3) / 3 = 2f + 1 + (2k + 2)/3 = 2f + 1 + k = N - f
        let total_votes: Stake = self.authorities.values().map(|x| x.stake).sum();
        2 * total_votes / 3 + 1
    }

    pub fn address(&self, name: &PublicKey) -> Option<SocketAddr> {
        self.authorities.get(name).map(|x| x.address)
    }

    pub fn broadcast_addresses(&self, myself: &PublicKey) -> Vec<(PublicKey, SocketAddr)> {
        self.authorities
            .iter()
            .filter(|(name, _)| name != &myself)
            .map(|(name, x)| (*name, x.address))
            .collect()
    }
}
