// Copyright(C) Facebook, Inc. and its affiliates.
use super::*;
use crate::common::{acking_listener, listener, stuck_listener};
use futures::future::try_join_all;
use tokio::net::TcpSocket;
use tokio::time::timeout;

/// More 64 KB messages than a connection's channel and the buffers of a socket hold together.
const MANY: usize = 1_300;
const SIZE: usize = 64 * 1024;

#[tokio::test]
async fn send() {
    // Run a TCP server.
    let address = "127.0.0.1:5000".parse::<SocketAddr>().unwrap();
    let message = "Hello, world!";
    let handle = listener(address, message.to_string());

    // Make the network sender and send the message.
    let mut sender = ReliableSender::new();
    let cancel_handler = sender.send(address, Bytes::from(message)).await;

    // Ensure we get back an acknowledgement.
    assert!(cancel_handler.await.is_ok());

    // Ensure the server received the expected message (ie. it did not panic).
    assert!(handle.await.is_ok());
}

#[tokio::test]
async fn broadcast() {
    // Run 3 TCP servers.
    let message = "Hello, world!";
    let (handles, addresses): (Vec<_>, Vec<_>) = (0..3)
        .map(|x| {
            let address = format!("127.0.0.1:{}", 5_200 + x)
                .parse::<SocketAddr>()
                .unwrap();
            (listener(address, message.to_string()), address)
        })
        .collect::<Vec<_>>()
        .into_iter()
        .unzip();

    // Make the network sender and send the message.
    let mut sender = ReliableSender::new();
    let cancel_handlers = sender.broadcast(addresses, Bytes::from(message)).await;

    // Ensure we get back an acknowledgement for each message.
    assert!(try_join_all(cancel_handlers).await.is_ok());

    // Ensure all servers received the broadcast.
    assert!(try_join_all(handles).await.is_ok());
}

#[tokio::test]
async fn retry() {
    // Make the network sender and send the message  (no listeners are running).
    let address = "127.0.0.1:5300".parse::<SocketAddr>().unwrap();
    let message = "Hello, world!";
    let mut sender = ReliableSender::new();
    let cancel_handler = sender.send(address, Bytes::from(message)).await;

    // Run a TCP server.
    sleep(Duration::from_millis(50)).await;
    let handle = listener(address, message.to_string());

    // Ensure we get back an acknowledgement.
    assert!(cancel_handler.await.is_ok());

    // Ensure the server received the message (ie. it did not panic).
    assert!(handle.await.is_ok());
}

#[tokio::test]
async fn a_peer_that_stops_reading_holds_back_no_one() {
    let stuck = "127.0.0.1:5400".parse::<SocketAddr>().unwrap();
    let live = "127.0.0.1:5401".parse::<SocketAddr>().unwrap();
    let _stuck = stuck_listener(stuck);
    let handle = acking_listener(live, MANY);
    sleep(Duration::from_millis(50)).await;

    // As the quorum waiters do: broadcast, wait for the ACK that makes the quorum, drop the other handler.
    let mut sender = ReliableSender::new();
    let data = Bytes::from(vec![0u8; SIZE]);
    let all = async {
        for _ in 0..MANY {
            let mut handlers = sender.broadcast(vec![stuck, live], data.clone()).await;
            assert!(handlers.pop().unwrap().await.is_ok());
        }
    };
    timeout(Duration::from_secs(10), all).await.expect("the stuck peer held back the broadcast");
    assert!(handle.await.is_ok());
}

#[tokio::test]
async fn a_peer_that_does_not_answer_the_connection_holds_back_no_one() {
    // The peer never accepts and its accept queue is full, so the next connection attempt hangs.
    let address = "127.0.0.1:5402".parse::<SocketAddr>().unwrap();
    let socket = TcpSocket::new_v4().unwrap();
    socket.bind(address).unwrap();
    let _listener = socket.listen(1).unwrap();
    let mut queued = Vec::new();
    for _ in 0..4 {
        if let Ok(Ok(stream)) = timeout(Duration::from_millis(100), TcpStream::connect(address)).await {
            queued.push(stream);
        }
    }
    assert_eq!(queued.len(), 2, "the accept queue should hold two connections");

    let (left, _tx) = cancel_many(address).await;
    assert!(left <= 1, "{} messages left", left);
}

#[tokio::test]
async fn cancelled_messages_do_not_pile_up_behind_a_stuck_peer() {
    let address = "127.0.0.1:5403".parse::<SocketAddr>().unwrap();
    let _stuck = stuck_listener(address);
    sleep(Duration::from_millis(50)).await;

    let (left, _tx) = cancel_many(address).await;
    assert!(left <= 1, "{} messages left", left);
}

/// Run a connection to `address` through many messages, each cancelled as the caller gets its quorum of ACKs, and
/// return how many are left in its buffer.
async fn cancel_many(address: SocketAddr) -> (usize, Sender<InnerMessage>) {
    let (tx, rx) = channel(1_000);
    let mut connection = Connection { address, receiver: rx, retry_delay: 200, buffer: VecDeque::new() };
    let data = Bytes::from(vec![0u8; SIZE]);
    let cancel = async {
        for _ in 0..MANY {
            let (cancel_handler, handler) = oneshot::channel();
            tx.send(InnerMessage { data: data.clone(), cancel_handler }).await.unwrap();
            sleep(Duration::from_micros(100)).await;
            drop(handler);
        }
        sleep(Duration::from_millis(100)).await;
    };
    tokio::select! {
        () = connection.run() => unreachable!(),
        result = timeout(Duration::from_secs(10), cancel) => result.expect("the peer held back the channel"),
    }
    (connection.buffer.len(), tx)
}

#[tokio::test]
async fn a_message_on_its_way_is_dropped_only_once_the_peer_is_stuck() {
    let (_tx, rx) = channel(1);
    let mut connection = Connection {
        address: "127.0.0.1:5404".parse::<SocketAddr>().unwrap(),
        receiver: rx,
        retry_delay: 200,
        buffer: VecDeque::new(),
    };
    let cancelled = |at, on_its_way| {
        let (handler, _) = oneshot::channel();
        (Bytes::new(), handler, at, on_its_way)
    };
    let now = Instant::now();
    connection.buffer.push_back(cancelled(now - 2 * STUCK_AFTER, true));
    connection.buffer.push_back(cancelled(now, false));
    connection.buffer.push_back(cancelled(now, true));
    connection.buffer.push_back(cancelled(now, false));

    // Long overdue, and cancelled and not on its way: gone. Due just now: it still stands for bytes on the wire.
    connection.skip_cancelled();
    assert_eq!(connection.buffer.len(), 2);
}
