use crate::config::Export as _;
use crate::config::{Committee, ConfigError, Parameters, Secret};
use crate::workload::State;
use consensus::{Block, Consensus};
use crypto::SignatureService;
use log::{info, warn};
use mempool::{Mempool, MempoolMessage};
use std::time::Instant;
use store::Store;
use tokio::sync::mpsc::{channel, Receiver};

/// The default channel capacity for this module.
pub const CHANNEL_CAPACITY: usize = 1_000;

pub struct Node {
    pub commit: Receiver<Block>,
    /// The store, where the mempool keeps the batches the blocks name.
    store: Store,
    /// Whether to execute the transactions of committed blocks (DESIGN.md §15.38).
    execute: bool,
}

/// Experiment switches, not part of the protocol (prototype/DESIGN.md §12.4, §13.3).
#[derive(Clone, Copy, Default)]
pub struct Experiment {
    pub censor: bool,
    pub equivocate: bool,
    pub lie_nr: bool,
    pub invalid_block: bool,
    pub regress: bool,
    pub frame: bool,
    pub silent: bool,
    pub fill_suffix: bool,
    pub withhold_proof: bool,
    /// Not a fault: execute the transactions of the ledger (DESIGN.md §15.38).
    pub execute: bool,
}

impl Node {
    pub async fn new(
        committee_file: &str,
        key_file: &str,
        store_path: &str,
        parameters: Option<String>,
        experiment: Experiment,
    ) -> Result<Self, ConfigError> {
        let (tx_commit, rx_commit) = channel(CHANNEL_CAPACITY);
        let (tx_consensus_to_mempool, rx_consensus_to_mempool) = channel(CHANNEL_CAPACITY);
        let (tx_mempool_to_consensus, rx_mempool_to_consensus) = channel(CHANNEL_CAPACITY);

        // Read the committee and secret key from file.
        let committee = Committee::read(committee_file)?;
        let secret = Secret::read(key_file)?;
        let name = secret.name;
        let secret_key = secret.secret;

        // Load default parameters if none are specified.
        let mut parameters = match parameters {
            Some(filename) => Parameters::read(&filename)?,
            None => Parameters::default(),
        };
        parameters.consensus.check().map_err(ConfigError::InvalidParameters)?;
        consensus::check_roster(&committee.consensus, &parameters.consensus).map_err(ConfigError::InvalidParameters)?;
        parameters.consensus.censor |= experiment.censor;
        parameters.consensus.equivocate |= experiment.equivocate;
        parameters.consensus.lie_nr |= experiment.lie_nr;
        parameters.consensus.invalid_block |= experiment.invalid_block;
        parameters.consensus.regress |= experiment.regress;
        parameters.consensus.frame |= experiment.frame;
        parameters.consensus.silent |= experiment.silent;
        parameters.consensus.fill_suffix |= experiment.fill_suffix;
        parameters.consensus.withhold_proof |= experiment.withhold_proof;

        // Make the data store.
        let store = match parameters.consensus.lossy_store {
            true => Store::new_lossy(store_path),
            false => Store::new(store_path),
        }
        .expect("Failed to create store");

        // Run the signature service.
        let signature_service = SignatureService::new(secret_key);

        let ledger_store = store.clone();

        // Make a new mempool.
        Mempool::spawn(
            name,
            committee.mempool,
            parameters.mempool,
            store.clone(),
            rx_consensus_to_mempool,
            tx_mempool_to_consensus,
        );

        // Run the consensus core.
        Consensus::spawn(
            name,
            committee.consensus,
            parameters.consensus,
            signature_service,
            store,
            rx_mempool_to_consensus,
            tx_consensus_to_mempool,
            tx_commit,
        );

        info!("Node {} successfully booted", name);
        Ok(Self { commit: rx_commit, store: ledger_store, execute: experiment.execute })
    }

    pub fn print_key_file(filename: &str) -> Result<(), ConfigError> {
        Secret::new().write(filename)
    }

    /// The application: with `execute`, apply the transactions of every block of the ledger, in order, to the
    /// workload's state (DESIGN.md §15.38). Blocks after a terminal block never get here (H4).
    pub async fn analyze_block(&mut self) {
        let mut state = State::default();
        while let Some(block) = self.commit.recv().await {
            if !self.execute || block.payload.is_empty() {
                continue;
            }
            let started = Instant::now();
            let before = state.executed;
            for digest in &block.payload {
                // The node voted for the block or synchronized it, so the batch is in the store or on its way.
                let batch = match self.store.notify_read(digest.to_vec()).await {
                    Ok(bytes) => bytes,
                    Err(e) => {
                        warn!("Failed to read batch {}: {}", digest, e);
                        continue;
                    }
                };
                match bincode::deserialize(&batch) {
                    Ok(MempoolMessage::Batch(transactions)) => transactions.iter().for_each(|tx| state.apply(tx)),
                    _ => warn!("Batch {} is not a batch of transactions", digest),
                }
            }
            // NOTE: this log entry is used to compare the states of the nodes (benchmark/execstat.py).
            info!(
                "Executed {} -> {} txs in {} us, state {:016x}",
                block,
                state.executed - before,
                started.elapsed().as_micros(),
                state.digest()
            );
        }
    }
}
