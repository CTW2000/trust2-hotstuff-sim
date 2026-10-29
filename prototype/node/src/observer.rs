//! Observer client (experiment tool, prototype/DESIGN.md §12.4): submits observed transactions at a fixed rate,
//! each to f+1 random nodes (at least one honest), and logs every submission so that inclusion delays can be
//! measured from the node logs ("Committed B<round> -> observed transaction <id>").
use anyhow::Result;
use bytes::Bytes;
use clap::Parser;
use consensus::{ConsensusMessage, Otx};
use env_logger::Env;
use futures::future::join_all;
use futures::sink::SinkExt as _;
use log::{info, warn};
use rand::seq::SliceRandom as _;
use rand::Rng as _;
use std::collections::HashMap;
use std::net::SocketAddr;
use tokio::net::TcpStream;
use tokio::time::{interval, sleep, Duration};
use tokio_util::codec::{Framed, LengthDelimitedCodec};

#[derive(Parser)]
#[clap(author, version, about, long_about = "Observer client: submits observed transactions.")]
struct Cli {
    /// Observed transactions per second.
    #[clap(short, long, value_parser, value_name = "INT")]
    rate: u64,
    /// Number of accounts (one in four is a victim of the censoring nodes).
    #[clap(short, long, value_parser, value_name = "INT", default_value = "100")]
    accounts: u64,
    /// Wait this long (ms) after the nodes are online before submitting.
    #[clap(short, long, value_parser, value_name = "INT", default_value = "2000")]
    delay: u64,
    /// Consensus addresses of the nodes.
    #[clap(value_parser, value_name = "ADDR", multiple = true)]
    nodes: Vec<SocketAddr>,
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();
    env_logger::Builder::from_env(Env::default().default_filter_or("info"))
        .format_timestamp_millis()
        .init();

    // Wait for the nodes to be online.
    join_all(cli.nodes.iter().cloned().map(|address| {
        tokio::spawn(async move {
            while TcpStream::connect(address).await.is_err() {
                sleep(Duration::from_millis(10)).await;
            }
        })
    }))
    .await;
    sleep(Duration::from_millis(cli.delay)).await;

    let fanout = cli.nodes.len() / 3 + 1;
    info!("Observed transactions: {} per second, each to {} of {} nodes", cli.rate, fanout, cli.nodes.len());
    let mut connections = HashMap::new();
    let mut rng = rand::thread_rng();
    let mut ticker = interval(Duration::from_micros(1_000_000 / cli.rate.max(1)));
    for nonce in 0.. {
        ticker.tick().await;
        let otx = Otx {
            account: rng.gen_range(0, cli.accounts),
            nonce,
            data: rng.gen(),
        };
        // NOTE: This log entry is used to measure the inclusion delay of observed transactions.
        info!("Observed transaction {} account {}", otx.id(), otx.account);
        let message = Bytes::from(bincode::serialize(&ConsensusMessage::Otx(otx))?);
        for address in cli.nodes.choose_multiple(&mut rng, fanout) {
            if !connections.contains_key(address) {
                match TcpStream::connect(address).await {
                    Ok(stream) => {
                        connections.insert(*address, Framed::new(stream, LengthDelimitedCodec::new()));
                    }
                    Err(e) => {
                        warn!("Failed to connect to {}: {}", address, e);
                        continue;
                    }
                }
            }
            let transport = connections.get_mut(address).unwrap();
            if let Err(e) = transport.send(message.clone()).await {
                warn!("Failed to send to {}: {}", address, e);
                connections.remove(address);
            }
        }
    }
    Ok(())
}
