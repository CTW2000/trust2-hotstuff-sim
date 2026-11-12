use crate::consensus::Round;
use crypto::PublicKey;
use log::info;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::net::SocketAddr;

pub type Stake = u32;
pub type EpochNumber = u128;

/// Experiment switch, not part of the protocol: the leader rule, for comparisons on the same code (DESIGN.md §15.12).
/// Every rule keeps the T_tru base weights and G1; they differ in what decides who may lead.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum LeaderRule {
    /// Trust 2.0: AT accusations (and omissions) feed the G2 CUSUM, which excludes from leading and lowers r.
    Trust2,
    /// No reputation: leaders drawn by the base weights, nothing on the ledger changes who leads.
    None,
    /// Aptos LeaderReputation (ProposerAndVoterV2 with the aptos-core defaults; epoch.rs `aptos_weights`):
    /// voting weights unchanged, leaders drawn by a reputation weight times the voting weight.
    Aptos,
    /// Trust 2.0 with a framable fact: a failed proposer (a round skipped on the chain) instead of an AT accusation.
    Failed,
}

impl Default for LeaderRule {
    fn default() -> Self {
        Self::Trust2
    }
}

#[derive(Serialize, Deserialize)]
pub struct Parameters {
    pub timeout_delay: u64,
    pub sync_retry_delay: u64,
    /// Rounds per epoch, counted from the previous terminal block (0: a single epoch, no handover).
    #[serde(default = "default_epoch_length")]
    pub epoch_length: u64,
    /// Entity cap of CapNorm, in ppm of the total weight; at most L_max (`check`).
    #[serde(default = "default_entity_cap_ppm")]
    pub entity_cap_ppm: u64,
    /// Cap on the uncertified class u_max, in ppm (default 25%; 1_000_000: no cap; `check`).
    #[serde(default = "default_class_cap_ppm")]
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
    /// With `frame` (DESIGN.md §15.27, targeted framing): frame only in the rounds these members lead, and vote as
    /// usual otherwise (empty: every round).
    #[serde(default)]
    pub frame_targets: Vec<PublicKey>,
    /// Experiment switch: as leader, never propose; otherwise run as usual (a Byzantine silent leader).
    #[serde(default)]
    pub silent: bool,
    /// Experiment switch (DESIGN.md §15.25): as leader, put transactions and ledger facts into blocks after the
    /// terminal block, against H4's empty proposals.
    #[serde(default)]
    pub fill_suffix: bool,
    /// Experiment switch (DESIGN.md §15.25): as leader of the first block of a new epoch, which carries the commit
    /// proof of the terminal block, send it to only half of the other nodes.
    #[serde(default)]
    pub withhold_proof: bool,
    /// Experiment switch: the leader rule (all nodes alike).
    #[serde(default)]
    pub leader_rule: LeaderRule,
    /// Experiment switch: the G2 CUSUM threshold ln γ in millionths (0: the protocol's, `G2Config::default`).
    #[serde(default)]
    pub g2_threshold: i64,
    /// Experiment switch (DESIGN.md §15.18, ablation): G2 convictions only exclude from leading; reputation stays 1
    /// (B_rep = 0), as a leader-only reputation would.
    #[serde(default)]
    pub g2_no_reputation: bool,
    /// Experiment switch (DESIGN.md §15.20): the failure threshold of LeaderRule::Aptos in percent (0: aptos-core's 10).
    #[serde(default)]
    pub aptos_failure_percent: u64,
    /// Experiment switch (DESIGN.md §15.15): vote only in rounds fork_vote_from..=fork_vote_until (0: unbounded) --
    /// the two halves of a split-brain member keep their votes in disjoint rounds, so a fork leaves no E1.
    #[serde(default)]
    pub fork_vote_from: u64,
    #[serde(default)]
    pub fork_vote_until: u64,
    /// Experiment switch (DESIGN.md §15.15, all nodes alike): the TC travels with the proposal but is not part of
    /// the block -- not in its digest, not in the store -- as the TC of DiemBFT / Aptos travels in the sync info.
    #[serde(default)]
    pub tc_outside_block: bool,
    /// Experiment switch (DESIGN.md §15.26, ablation): store and vote for a block of a new epoch even if it does not
    /// extend the terminal block we entered that epoch on (H2 off).
    #[serde(default)]
    pub no_h2: bool,
}

fn default_attest_guard() -> u64 {
    500
}

fn default_entity_cap_ppm() -> u64 {
    50_000
}

fn default_l_max_ppm() -> u64 {
    100_000
}

/// DESIGN.md §15.11: the next table is known an epoch ahead (H1'), and short epochs keep the delay of punishment
/// short.
fn default_epoch_length() -> u64 {
    25
}

/// The scheme's default class cap u_max = 25% (方案 §3.3, the paper's default; it must stay below (1 - B_rep)/3).
fn default_class_cap_ppm() -> u64 {
    250_000
}

impl Default for Parameters {
    fn default() -> Self {
        Self {
            timeout_delay: 5_000,
            sync_retry_delay: 10_000,
            epoch_length: default_epoch_length(),
            entity_cap_ppm: default_entity_cap_ppm(),
            class_cap_ppm: default_class_cap_ppm(),
            l_max_ppm: default_l_max_ppm(),
            governance_malicious: false,
            attest_guard: default_attest_guard(),
            censor: false,
            equivocate: false,
            lie_nr: false,
            invalid_block: false,
            regress: false,
            frame: false,
            frame_targets: Vec::new(),
            silent: false,
            fill_suffix: false,
            withhold_proof: false,
            leader_rule: LeaderRule::default(),
            g2_threshold: 0,
            g2_no_reputation: false,
            aptos_failure_percent: 0,
            fork_vote_from: 0,
            fork_vote_until: 0,
            tc_outside_block: false,
            no_h2: false,
        }
    }
}

impl Parameters {
    /// The scheme requires cap <= L_max (方案 §3.3): a member above L_max could never be suspended, and at the head
    /// of the strict FIFO suspension queue it would hold up everyone behind it.
    /// The class cap must stay below (1 - B_rep - L_max)/3, or the uncertified class alone could hold a third of the
    /// votes once reputation cuts and suspensions of honest members have shrunk the rest (the paper's corollary on
    /// licensed culprits in the worst case; (1 - B_rep)/3 is enough only while nobody is suspended).
    pub fn check(&self) -> Result<(), String> {
        if self.entity_cap_ppm > self.l_max_ppm {
            return Err(format!(
                "entity cap of {} ppm is above L_max of {} ppm",
                self.entity_cap_ppm, self.l_max_ppm
            ));
        }
        let b_rep_ppm = (crate::reputation::G2Config::default().b_rep * 1_000_000 / crate::ttru::ONE) as u64;
        let room = 1_000_000u64.saturating_sub(b_rep_ppm + self.l_max_ppm);
        if self.class_cap_ppm < 1_000_000 && 3 * self.class_cap_ppm >= room {
            return Err(format!(
                "class cap of {} ppm is not below (1 - B_rep - L_max)/3 = {} ppm",
                self.class_cap_ppm,
                room / 3
            ));
        }
        Ok(())
    }

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
            if !self.frame_targets.is_empty() {
                info!("Framing only in the rounds {} targets lead (experiment)", self.frame_targets.len());
            }
        }
        if self.silent {
            info!("Silent leader: never proposing (experiment)");
        }
        if self.fill_suffix {
            info!("Filling suffix blocks: transactions after the terminal block (experiment)");
        }
        if self.withhold_proof {
            info!("Withholding the commit proof: the first block of an epoch to half the nodes (experiment)");
        }
        if self.leader_rule != LeaderRule::Trust2 {
            info!("Leader rule set to {:?} (experiment)", self.leader_rule);
        }
        if self.fork_vote_from != 0 || self.fork_vote_until != 0 {
            info!(
                "Split brain: voting only in rounds {}..{} (experiment)",
                self.fork_vote_from, self.fork_vote_until
            );
        }
        if self.tc_outside_block {
            info!("TC outside the block (experiment)");
        }
        if self.no_h2 {
            info!("H2 off: blocks of a new epoch off the terminal block are stored and voted for (experiment)");
        }
        if self.g2_no_reputation {
            info!("G2 convictions exclude from leading only, reputation stays 1 (experiment)");
        }
        if self.g2_threshold != 0 {
            info!("G2 threshold set to {} millionths (experiment)", self.g2_threshold);
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
    /// The entity of this member: members of one beneficial owner share its cap and its punishments (None: an
    /// entity of its own).
    #[serde(default)]
    pub entity: Option<u32>,
    /// G2: may lead in this epoch (false while excluded by the leader rule); set by the weight table, not by
    /// the configuration.
    #[serde(default = "default_true")]
    pub leader: bool,
    /// Weight in the leader draw when positive (LeaderRule::Aptos: reputation weight times stake); otherwise the
    /// stake. Set by the weight table.
    #[serde(skip)]
    pub lead: u64,
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
                        entity: None,
                        leader: true,
                        lead: 0,
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
