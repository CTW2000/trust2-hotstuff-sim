//! With synthetic delays (src/delay.rs) a queued message stands for bytes already on the wire, so a cancellation does
//! not stop it: a leader that heard from 2f+1 nodes first would otherwise cancel its block to the slower ones, an
//! artifact of the injected delays (DESIGN.md §14.1). This is its own test binary because the delay table is read once
//! per process from the environment, and the unit tests run without one.
use bytes::Bytes;
use futures::sink::SinkExt as _;
use futures::stream::StreamExt as _;
use network::ReliableSender;
use std::net::SocketAddr;
use tokio::net::TcpListener;
use tokio::time::{timeout, Duration};
use tokio_util::codec::{Framed, LengthDelimitedCodec};

#[tokio::test]
async fn a_cancelled_message_in_the_delay_queue_is_still_sent() {
    let address: SocketAddr = "127.0.0.1:17401".parse().unwrap();
    let table = format!(
        r#"{{"addresses": {{"{}": 1}}, "base_ms": [[0, 50], [50, 0]], "jitter_ms": 0, "bandwidth_mbps": 1000}}"#,
        address
    );
    let path = std::env::temp_dir().join(format!("ttru_delays_{}.json", std::process::id()));
    std::fs::write(&path, table).unwrap();
    std::env::set_var("TTRU_DELAYS", &path);
    std::env::set_var("TTRU_NODE", "0");

    // Listen first: while it cannot connect, the sender purges cancelled messages.
    let listener = TcpListener::bind(address).await.unwrap();
    let mut sender = ReliableSender::new();

    // The caller cancels at once, while the message waits out the 50 ms of its link.
    drop(sender.send(address, Bytes::from("block")).await);

    let (socket, _) = timeout(Duration::from_secs(2), listener.accept()).await.expect("no connection").unwrap();
    let mut transport = Framed::new(socket, LengthDelimitedCodec::new());
    let frame = timeout(Duration::from_secs(2), transport.next()).await.expect("the cancelled message was dropped");
    assert_eq!(frame.unwrap().unwrap().freeze(), Bytes::from("block"));
    transport.send(Bytes::from("Ack")).await.unwrap();
    std::fs::remove_file(&path).unwrap();
}
