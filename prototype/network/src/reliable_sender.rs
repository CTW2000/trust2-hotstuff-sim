// Copyright(C) Facebook, Inc. and its affiliates.
use crate::delay;
use crate::error::NetworkError;
use bytes::Bytes;
use futures::sink::SinkExt as _;
use futures::stream::StreamExt as _;
use log::{info, warn};
use rand::prelude::SliceRandom as _;
use rand::rngs::SmallRng;
use rand::SeedableRng as _;
use std::cmp::min;
use std::collections::{HashMap, VecDeque};
use std::fmt::Debug;
use std::net::SocketAddr;
use tokio::net::TcpStream;
use tokio::sync::mpsc::{channel, Receiver, Sender};
use tokio::sync::oneshot;
use tokio::time::{sleep, sleep_until, Duration, Instant};
use tokio_util::codec::{Framed, LengthDelimitedCodec};

#[cfg(test)]
#[path = "tests/reliable_sender_tests.rs"]
pub mod reliable_sender_tests;

/// A message on its way that is still in the buffer this long after it was due has not left because the peer
/// stopped reading: it no longer stands for bytes on the wire.
const STUCK_AFTER: Duration = Duration::from_secs(1);

/// Convenient alias for cancel handlers returned to the caller task.
pub type CancelHandler = oneshot::Receiver<Bytes>;

/// We keep alive one TCP connection per peer, each connection is handled by a separate task (called `Connection`).
/// We communicate with our 'connections' through a dedicated channel kept by the HashMap called `connections`.
/// This sender is 'reliable' in the sense that it keeps trying to re-transmit messages for which it didn't
/// receive an ACK back (until they succeed or are canceled).
pub struct ReliableSender {
    /// A map holding the channels to our connections.
    connections: HashMap<SocketAddr, Sender<InnerMessage>>,
    /// Small RNG just used to shuffle nodes and randomize connections (not crypto related).
    rng: SmallRng,
}

impl std::default::Default for ReliableSender {
    fn default() -> Self {
        Self::new()
    }
}

impl ReliableSender {
    pub fn new() -> Self {
        Self {
            connections: HashMap::new(),
            rng: SmallRng::from_entropy(),
        }
    }

    /// Helper function to spawn a new connection.
    fn spawn_connection(address: SocketAddr) -> Sender<InnerMessage> {
        let (tx, rx) = channel(1_000);
        Connection::spawn(address, rx);
        tx
    }

    /// Reliably send a message to a specific address.
    pub async fn send(&mut self, address: SocketAddr, data: Bytes) -> CancelHandler {
        let (sender, receiver) = oneshot::channel();
        self.connections
            .entry(address)
            .or_insert_with(|| Self::spawn_connection(address))
            .send(InnerMessage {
                data,
                cancel_handler: sender,
            })
            .await
            .expect("Failed to send internal message");
        receiver
    }

    /// Broadcast the message to all specified addresses in a reliable manner. It returns a vector of
    /// cancel handlers ordered as the input `addresses` vector.
    pub async fn broadcast(
        &mut self,
        addresses: Vec<SocketAddr>,
        data: Bytes,
    ) -> Vec<CancelHandler> {
        let mut handlers = Vec::new();
        for address in addresses {
            let handler = self.send(address, data.clone()).await;
            handlers.push(handler);
        }
        handlers
    }

    /// Pick a few addresses at random (specified by `nodes`) and send the message only to them.
    /// It returns a vector of cancel handlers with no specific order.
    pub async fn lucky_broadcast(
        &mut self,
        mut addresses: Vec<SocketAddr>,
        data: Bytes,
        nodes: usize,
    ) -> Vec<CancelHandler> {
        addresses.shuffle(&mut self.rng);
        addresses.truncate(nodes);
        self.broadcast(addresses, data).await
    }
}

/// Simple message used by `ReliableSender` to communicate with its connections.
#[derive(Debug)]
struct InnerMessage {
    /// The data to transmit.
    data: Bytes,
    /// The cancel handler allowing the caller task to cancel the transmission of this message
    /// and to be notified of its successfully transmission.
    cancel_handler: oneshot::Sender<Bytes>,
}

/// A connection is responsible to reliably establish (and keep alive) a connection with a single peer.
struct Connection {
    /// The destination address.
    address: SocketAddr,
    /// Channel from which the connection receives its commands.
    receiver: Receiver<InnerMessage>,
    /// The initial delay to wait before re-attempting a connection (in ms).
    retry_delay: u64,
    /// Buffer keeping all messages that need to be re-transmitted, in the order they are due (synthetic link
    /// delay, see delay.rs), and whether each is already on its way: a message waiting for its synthetic delay
    /// stands for bytes already on the wire, so a cancellation (the caller got its quorum of ACKs) does not stop it.
    buffer: VecDeque<(Bytes, oneshot::Sender<Bytes>, Instant, bool)>,
}

impl Connection {
    fn spawn(address: SocketAddr, receiver: Receiver<InnerMessage>) {
        tokio::spawn(async move {
            Self {
                address,
                receiver,
                retry_delay: 200,
                buffer: VecDeque::new(),
            }
            .run()
            .await;
        });
    }

    /// Main loop trying to connect to the peer and transmit messages.
    async fn run(&mut self) {
        let mut delay = self.retry_delay;
        let mut retry = 0;
        loop {
            match self.connect().await {
                Ok(stream) => {
                    info!("Outgoing connection established with {}", self.address);

                    // Reset the delay.
                    delay = self.retry_delay;
                    retry = 0;

                    // Try to transmit all messages in the buffer and keep transmitting incoming messages.
                    // The following function only returns if there is an error.
                    let error = self.keep_alive(stream).await;
                    warn!("{}", error);
                }
                Err(e) => {
                    warn!("{}", NetworkError::FailedToConnect(self.address, retry, e));
                    let timer = sleep(Duration::from_millis(delay));
                    tokio::pin!(timer);

                    'waiter: loop {
                        tokio::select! {
                            // Wait an increasing delay before attempting to reconnect.
                            () = &mut timer => {
                                delay = min(2*delay, 60_000);
                                retry +=1;
                                break 'waiter;
                            },

                            Some(InnerMessage{data, cancel_handler}) = self.receiver.recv() => {
                                self.stash(data, cancel_handler);
                            }
                        }
                    }
                }
            }
        }
    }

    /// Connect to the peer. That can take long if the peer does not answer: keep draining the channel meanwhile.
    async fn connect(&mut self) -> std::io::Result<TcpStream> {
        let connecting = TcpStream::connect(self.address);
        tokio::pin!(connecting);
        loop {
            tokio::select! {
                result = &mut connecting => return result,
                Some(InnerMessage{data, cancel_handler}) = self.receiver.recv() => {
                    self.stash(data, cancel_handler);
                }
            }
        }
    }

    /// Drain the channel into the buffer to not saturate the channel and block the caller task.
    /// The caller is responsible to cleanup the buffer through the cancel handlers.
    fn stash(&mut self, data: Bytes, handler: oneshot::Sender<Bytes>) {
        self.enqueue(data, handler);
        self.buffer.retain(|(_, handler, at, on_its_way)| !Self::cancelled(handler, *at, *on_its_way));
    }

    fn enqueue(&mut self, data: Bytes, handler: oneshot::Sender<Bytes>) {
        let at = delay::due(&self.address, data.len());
        let index = delay::position(&self.buffer, at, |(_, _, due, _)| *due);
        self.buffer.insert(index, (data, handler, at, delay::enabled()));
    }

    /// Whether a message has been cancelled, and is not already on its way.
    fn cancelled(handler: &oneshot::Sender<Bytes>, at: Instant, on_its_way: bool) -> bool {
        handler.is_closed() && !(on_its_way && Instant::now() < at + STUCK_AFTER)
    }

    /// Skip the cancelled messages at the front of the buffer.
    fn skip_cancelled(&mut self) {
        while let Some((_, handler, at, on_its_way)) = self.buffer.front() {
            if !Self::cancelled(handler, *at, *on_its_way) {
                break;
            }
            self.buffer.pop_front();
        }
    }

    /// Transmit messages once we have established a connection.
    async fn keep_alive(&mut self, stream: TcpStream) -> NetworkError {
        // This buffer keeps all messages and handlers that we have successfully transmitted but for
        // which we are still waiting to receive an ACK.
        let mut pending_replies = VecDeque::new();

        let (mut writer, mut reader) = Framed::new(stream, LengthDelimitedCodec::new()).split();

        // Writes run beside the loop below, one at a time. A peer that stops reading blocks them, and the loop must
        // keep draining the channel all the same, or the caller's broadcast blocks and no other peer gets anything.
        let (tx_write, mut rx_write) = channel::<Bytes>(1);
        let writes = async move {
            loop {
                let data = rx_write.recv().await.expect("Failed to receive message to write");
                if let Err(e) = writer.send(data).await {
                    return e;
                }
            }
        };
        tokio::pin!(writes);

        let error = 'connection: loop {
            self.skip_cancelled();
            let next = self.buffer.front().map(|(_, _, at, _)| *at);
            let due = next.map_or(false, |at| at <= Instant::now());

            // Check if there are any new messages to send, if the next one is due, or if we get an ACK for messages we
            // already sent.
            tokio::select! {
                e = &mut writes => {
                    // We failed to send a message: it is still in `pending_replies`, we will try to send it again.
                    break 'connection NetworkError::FailedToSendMessage(self.address, e);
                },
                permit = tx_write.reserve(), if due => {
                    // The message is on its way, we remove it from the buffer and add it to `pending_replies` while we
                    // wait for an ACK.
                    let (data, handler, _, _) = self.buffer.pop_front().unwrap();
                    permit.expect("Failed to reserve a write").send(data.clone());
                    pending_replies.push_back((data, handler));
                },
                Some(InnerMessage{data, cancel_handler}) = self.receiver.recv() => {
                    // Add the message to the buffer of messages to send.
                    self.enqueue(data, cancel_handler);
                },
                () = sleep_until(next.unwrap_or_else(Instant::now)), if next.is_some() && !due => {},
                response = reader.next() => {
                    let (data, handler) = match pending_replies.pop_front() {
                        Some(message) => message,
                        None => break 'connection NetworkError::UnexpectedAck(self.address)
                    };
                    match response {
                        Some(Ok(bytes)) => {
                            // Notify the handler that the message has been successfully sent.
                            let _ = handler.send(bytes.freeze());
                        },
                        _ => {
                            // Something has gone wrong (either the channel dropped or we failed to read from it).
                            // Put the message back in the buffer, we will try to send it again.
                            pending_replies.push_front((data, handler));
                            break 'connection NetworkError::FailedToReceiveAck(self.address);
                        }
                    }
                },
            }
        };

        // If we reach this code, it means something went wrong. Put the messages for which we didn't receive an ACK
        // back into the sending buffer, we will try to send them again once we manage to establish a new connection.
        while let Some((data, handler)) = pending_replies.pop_back() {
            self.buffer.push_front((data, handler, Instant::now(), false));
        }
        error
    }
}
