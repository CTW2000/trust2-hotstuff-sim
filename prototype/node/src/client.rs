use anyhow::{Context, Result};
use bytes::BufMut as _;
use bytes::BytesMut;
use clap::Parser;
use env_logger::Env;
use futures::future::join_all;
use futures::sink::SinkExt as _;
use log::{info, warn};
use rand::Rng;
use std::net::SocketAddr;
use workload::{Generator, Workload};
use tokio::net::TcpStream;
use tokio::time::{interval, sleep, Duration, Instant};
use tokio_util::codec::{Framed, LengthDelimitedCodec};

#[allow(dead_code)]
mod workload;

#[derive(Parser)]
#[clap(
    author,
    version,
    about,
    long_about = "Benchmark client for HotStuff nodes."
)]
struct Cli {
    /// The network address of the node where to send txs.
    #[clap(value_parser, value_name = "ADDR")]
    target: SocketAddr,
    /// The nodes timeout value.
    #[clap(short, long, value_parser, value_name = "INT")]
    timeout: u64,
    /// The size of each transaction in bytes.
    #[clap(short, long, value_parser, value_name = "INT")]
    size: usize,
    /// The rate (txs/s) at which to send the transactions.
    #[clap(short, long, value_parser, value_name = "INT")]
    rate: u64,
    /// Network addresses that must be reachable before starting the benchmark.
    #[clap(short, long, value_parser, value_name = "[Addr]", multiple = true)]
    nodes: Vec<SocketAddr>,
    /// The operations in the transactions: none, ycsb-a, ycsb-b, ycsb-c or smallbank (DESIGN.md §15.38).
    #[clap(long, value_parser, default_value = "none")]
    workload: Workload,
    /// The number of records (YCSB) or customers (SmallBank).
    #[clap(long, value_parser, default_value_t = 100_000)]
    records: u64,
    /// The skew of the YCSB keys (Zipfian constant).
    #[clap(long, value_parser, default_value_t = 0.99)]
    theta: f64,
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();

    env_logger::Builder::from_env(Env::default().default_filter_or("info"))
        .format_timestamp_millis()
        .init();

    info!("Node address: {}", cli.target);
    info!("Transactions size: {} B", cli.size);
    info!("Transactions rate: {} tx/s", cli.rate);
    info!("Workload: {:?} over {} records", cli.workload, cli.records);
    let client = Client {
        target: cli.target,
        size: cli.size,
        rate: cli.rate,
        timeout: cli.timeout,
        nodes: cli.nodes,
        generator: Generator::new(cli.workload, cli.records, cli.theta),
    };

    // Wait for all nodes to be online and synchronized.
    client.wait().await;

    // Start the benchmark.
    client.send().await.context("Failed to submit transactions")
}

struct Client {
    target: SocketAddr,
    size: usize,
    rate: u64,
    timeout: u64,
    nodes: Vec<SocketAddr>,
    generator: Generator,
}

impl Client {
    pub async fn send(&self) -> Result<()> {
        const PRECISION: u64 = 20; // Sample precision.
        const BURST_DURATION: u64 = 1000 / PRECISION;

        // The sample flag, the counter and the largest operation take 34 bytes.
        if self.size < 34 {
            return Err(anyhow::Error::msg("Transaction size must be at least 34 bytes"));
        }

        // Connect to the mempool.
        let stream = TcpStream::connect(self.target)
            .await
            .context(format!("failed to connect to {}", self.target))?;

        // Submit all transactions.
        let burst = self.rate / PRECISION;
        let mut tx = BytesMut::with_capacity(self.size);
        let mut counter = 0;
        let mut rng = rand::thread_rng();
        let mut r: u64 = rng.gen();
        let mut transport = Framed::new(stream, LengthDelimitedCodec::new());
        let interval = interval(Duration::from_millis(BURST_DURATION));
        tokio::pin!(interval);

        // NOTE: This log entry is used to compute performance.
        info!("Start sending transactions");

        'main: loop {
            interval.as_mut().tick().await;
            let now = Instant::now();

            for x in 0..burst {
                if x == counter % burst {
                    // NOTE: This log entry is used to compute performance.
                    info!("Sending sample transaction {}", counter);

                    tx.put_u8(0u8); // Sample txs start with 0.
                    tx.put_u64(counter); // This counter identifies the tx.
                } else {
                    r += 1;

                    tx.put_u8(1u8); // Standard txs start with 1.
                    tx.put_u64(r); // Ensures all clients send different txs.
                };
                // The workload's operation; the padding is the value an update writes.
                self.generator.next(&mut rng).encode(&mut tx);
                tx.resize(self.size, r as u8);
                let bytes = tx.split().freeze();

                if let Err(e) = transport.send(bytes).await {
                    warn!("Failed to send transaction: {}", e);
                    break 'main;
                }
            }
            if now.elapsed().as_millis() > BURST_DURATION as u128 {
                // NOTE: This log entry is used to compute performance.
                warn!("Transaction rate too high for this client");
            }
            counter += 1;
        }
        Ok(())
    }

    pub async fn wait(&self) {
        // First wait for all nodes to be online.
        info!("Waiting for all nodes to be online...");
        join_all(self.nodes.iter().cloned().map(|address| {
            tokio::spawn(async move {
                while TcpStream::connect(address).await.is_err() {
                    sleep(Duration::from_millis(10)).await;
                }
            })
        }))
        .await;

        // Then wait for the nodes to be synchronized.
        info!("Waiting for all nodes to be synchronized...");
        sleep(Duration::from_millis(2 * self.timeout)).await;
    }
}
