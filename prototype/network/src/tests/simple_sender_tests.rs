// Copyright(C) Facebook, Inc. and its affiliates.
use super::*;
use crate::common::{acking_listener, listener, stuck_listener};
use futures::future::try_join_all;
use tokio::time::{sleep, timeout};

/// More 64 KB messages than a connection's channel and the buffers of a socket hold together.
const MANY: usize = 1_300;
const SIZE: usize = 64 * 1024;

#[tokio::test]
async fn simple_send() {
    // Run a TCP server.
    let address = "127.0.0.1:6100".parse::<SocketAddr>().unwrap();
    let message = "Hello, world!";
    let handle = listener(address, message.to_string());

    // Make the network sender and send the message.
    let mut sender = SimpleSender::new();
    sender.send(address, Bytes::from(message)).await;

    // Ensure the server received the message (ie. it did not panic).
    assert!(handle.await.is_ok());
}

#[tokio::test]
async fn broadcast() {
    // Run 3 TCP servers.
    let message = "Hello, world!";
    let (handles, addresses): (Vec<_>, Vec<_>) = (0..3)
        .map(|x| {
            let address = format!("127.0.0.1:{}", 6_200 + x)
                .parse::<SocketAddr>()
                .unwrap();
            (listener(address, message.to_string()), address)
        })
        .collect::<Vec<_>>()
        .into_iter()
        .unzip();

    // Make the network sender and send the message.
    let mut sender = SimpleSender::new();
    sender.broadcast(addresses, Bytes::from(message)).await;

    // Ensure all servers received the broadcast.
    assert!(try_join_all(handles).await.is_ok());
}

#[tokio::test]
async fn a_peer_that_stops_reading_holds_back_no_one() {
    let stuck = "127.0.0.1:6300".parse::<SocketAddr>().unwrap();
    let live = "127.0.0.1:6301".parse::<SocketAddr>().unwrap();
    let _stuck = stuck_listener(stuck);
    let handle = acking_listener(live, MANY);
    sleep(Duration::from_millis(50)).await;

    let mut sender = SimpleSender::new();
    let data = Bytes::from(vec![0u8; SIZE]);
    let all = async {
        for _ in 0..MANY {
            sender.broadcast(vec![stuck, live], data.clone()).await;
            sleep(Duration::from_millis(1)).await;
        }
    };
    timeout(Duration::from_secs(20), all).await.expect("the stuck peer held back the broadcast");
    assert!(handle.await.is_ok());
}
