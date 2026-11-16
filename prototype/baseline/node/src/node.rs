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
    /// Whether to execute the transactions of committed blocks (as the Trust 2.0 node does with --execute).
    execute: bool,
}

impl Node {
    pub async fn new(
        committee_file: &str,
        key_file: &str,
        store_path: &str,
        parameters: Option<String>,
        execute: bool,
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
        let parameters = match parameters {
            Some(filename) => Parameters::read(&filename)?,
            None => Parameters::default(),
        };

        // Make the data store.
        let store = Store::new(store_path).expect("Failed to create store");
        let ledger_store = store.clone();

        // Run the signature service.
        let signature_service = SignatureService::new(secret_key);

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
        Ok(Self { commit: rx_commit, store: ledger_store, execute })
    }

    pub fn print_key_file(filename: &str) -> Result<(), ConfigError> {
        Secret::new().write(filename)
    }

    /// The application: with `execute`, apply the transactions of every committed block, in order, to the
    /// workload's state (the same code as the Trust 2.0 node, prototype/node/src/node.rs).
    pub async fn analyze_block(&mut self) {
        let mut state = State::default();
        while let Some(block) = self.commit.recv().await {
            if !self.execute || block.payload.is_empty() {
                continue;
            }
            let started = Instant::now();
            let before = state.executed;
            for digest in &block.payload {
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
