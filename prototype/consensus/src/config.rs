use crate::consensus::Round;
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
    /// G1: at most this much base weight suspended at once, in ppm (L_max).
    #[serde(default = "default_l_max_ppm")]
    pub l_max_ppm: u64,
    /// G1 governance stand-in: an L4 without a fork counts as confirmed malicious (evicted).
    #[serde(default)]
    pub governance_malicious: bool,
    /// G2 inclusion attestations: observed transactions held at least this long (ms) are attested (Δ_g).
    #[serde(default = "default_attest_guard")]
    pub attest_guard: u64,
    /// Experiment switch, not part of the protocol: censor the observed transactions of victim accounts.
    #[serde(default)]
    pub censor: bool,
    /// Experiment switch: send a second vote for another digest with every vote (E1).
    #[serde(default)]
    pub equivocate: bool,
    /// Experiment switch: after every vote, also sign an NR = 1 timeout of the same round (NR contradiction).
    #[serde(default)]
    pub lie_nr: bool,
    /// Experiment switch: as leader, propose blocks that break the voting rule and vote for them (E2).
    #[serde(default)]
    pub invalid_block: bool,
    /// Experiment switch: after every vote, also sign a timeout of the same round with an older high QC (E3).
    #[serde(default)]
    pub regress: bool,
    /// Experiment switch: never vote, and report NR = 1 in every timeout (framing colluder).
    #[serde(default)]
    pub frame: bool,
}

fn default_attest_guard() -> u64 {
    500
}

fn default_l_max_ppm() -> u64 {
    100_000
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
            l_max_ppm: default_l_max_ppm(),
            governance_malicious: false,
            attest_guard: default_attest_guard(),
            censor: false,
            equivocate: false,
            lie_nr: false,
            invalid_block: false,
            regress: false,
            frame: false,
        }
    }
}

impl Parameters {
    pub fn log(&self) {
        // NOTE: These log entries are used to compute performance.
        info!("Timeout delay set to {} rounds", self.timeout_delay);
        info!("Sync retry delay set to {} ms", self.sync_retry_delay);
        info!("Epoch length set to {} rounds", self.epoch_length);
        info!("Suspension cap L_max set to {} ppm", self.l_max_ppm);
        info!("Attestation guard set to {} ms", self.attest_guard);
        if self.censor {
            info!("Censoring the observed transactions of victim accounts (experiment)");
        }
        if self.equivocate {
            info!("Voting twice in every round (experiment)");
        }
        if self.lie_nr {
            info!("Lying about NR after every vote (experiment)");
        }
        if self.invalid_block {
            info!("Proposing and voting for invalid blocks (experiment)");
        }
        if self.regress {
            info!("Regressing the high QC after every vote (experiment)");
        }
        if self.frame {
            info!("Framing: withholding votes and reporting NR = 1 (experiment)");
        }
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
    #[serde(default = "default_true")]
    pub certified: bool,
    /// G2: may lead in this epoch (false while excluded by the leader rule); set by the weight table, not by
    /// the configuration.
    #[serde(default = "default_true")]
    pub leader: bool,
}

fn default_true() -> bool {
    true
}

#[derive(Clone, Serialize, Deserialize)]
pub struct Committee {
    pub authorities: HashMap<PublicKey, Authority>,
    pub epoch: EpochNumber,
    /// The first round of the epoch and the leader the previous table gave it, which keeps it: the votes for
    /// the commit proof of the last epoch went there (DESIGN.md §12.2). Set by the weight table.
    #[serde(skip)]
    pub handover: Option<(Round, PublicKey)>,
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
                        leader: true,
                    };
                    (name, authority)
                })
                .collect(),
            epoch,
            handover: None,
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
