#[macro_use]
mod error;
mod aggregator;
mod config;
mod consensus;
mod core;
mod epoch;
mod evidence;
pub mod forensics;
mod helper;
mod inclusion;
mod leader;
mod mempool;
mod messages;
mod proposer;
mod punish;
mod reputation;
mod synchronizer;
mod timer;
pub mod ttru;

#[cfg(test)]
#[path = "tests/common.rs"]
mod common;

#[cfg(test)]
#[path = "tests/overhead_tests.rs"]
mod overhead_tests;

pub use crate::config::{Committee, Parameters};

/// Whether CapNorm accepts `committee` as a roster under the caps of `parameters` (DESIGN.md §15.28); a node must
/// not start on a roster CapNorm rejects.
pub fn check_roster(committee: &Committee, parameters: &Parameters) -> Result<(), String> {
    crate::epoch::check_roster(committee, &crate::consensus::epoch_config(parameters))
        .map_err(|e| format!("CapNorm rejects the roster: {} (cap {} ppm, u_max {} ppm)", e,
                             parameters.entity_cap_ppm, parameters.class_cap_ppm))
}
pub use crate::consensus::{Consensus, ConsensusMessage};
pub use crate::messages::{Block, Otx, QC, TC};
