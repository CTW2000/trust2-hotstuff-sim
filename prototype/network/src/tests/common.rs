// Copyright(C) Facebook, Inc. and its affiliates.
use bytes::Bytes;
use futures::sink::SinkExt as _;
use futures::stream::StreamExt as _;
use std::net::SocketAddr;
use tokio::net::TcpListener;
use tokio::task::JoinHandle;
use tokio_util::codec::{Framed, LengthDelimitedCodec};

pub fn listener(address: SocketAddr, expected: String) -> JoinHandle<()> {
    tokio::spawn(async move {
        let listener = TcpListener::bind(&address).await.unwrap();
        let (socket, _) = listener.accept().await.unwrap();
        let transport = Framed::new(socket, LengthDelimitedCodec::new());
        let (mut writer, mut reader) = transport.split();
        match reader.next().await {
            Some(Ok(received)) => {
                assert_eq!(received, expected);
                writer.send(Bytes::from("Ack")).await.unwrap()
            }
            _ => panic!("Failed to receive network message"),
        }
    })
}

/// A peer that accepts the connection and then never reads from it.
pub fn stuck_listener(address: SocketAddr) -> JoinHandle<()> {
    tokio::spawn(async move {
        let listener = TcpListener::bind(&address).await.unwrap();
        let (_socket, _) = listener.accept().await.unwrap();
        std::future::pending::<()>().await
    })
}

/// A peer that receives and acknowledges `count` messages.
pub fn acking_listener(address: SocketAddr, count: usize) -> JoinHandle<()> {
    tokio::spawn(async move {
        let listener = TcpListener::bind(&address).await.unwrap();
        let (socket, _) = listener.accept().await.unwrap();
        let (mut writer, mut reader) = Framed::new(socket, LengthDelimitedCodec::new()).split();
        for _ in 0..count {
            reader.next().await.unwrap().unwrap();
            writer.send(Bytes::from("Ack")).await.unwrap();
        }
    })
}
