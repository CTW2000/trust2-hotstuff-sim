use std::collections::{HashMap, VecDeque};
use tokio::sync::mpsc::{channel, Sender};
use tokio::sync::oneshot;

#[cfg(test)]
#[path = "tests/store_tests.rs"]
pub mod store_tests;

pub type StoreError = rocksdb::Error;
type StoreResult<T> = Result<T, StoreError>;

type Key = Vec<u8>;
type Value = Vec<u8>;

pub enum StoreCommand {
    Write(Key, Value),
    /// A write that is on disk (WAL synced) before the reply.
    WriteSync(Key, Value, oneshot::Sender<()>),
    Read(Key, oneshot::Sender<StoreResult<Option<Value>>>),
    NotifyRead(Key, oneshot::Sender<StoreResult<Value>>),
}

#[derive(Clone)]
pub struct Store {
    channel: Sender<StoreCommand>,
}

impl Store {
    pub fn new(path: &str) -> StoreResult<Self> {
        Self::open(path, false)
    }

    /// Experiment switch (DESIGN.md §15.33): a store that loses what was not synced when the process is killed, as a
    /// machine does when it loses power. Plain writes skip the write-ahead log and stay in memory until RocksDB
    /// flushes them; `write_sync` goes through the log and is synced as usual.
    pub fn new_lossy(path: &str) -> StoreResult<Self> {
        Self::open(path, true)
    }

    fn open(path: &str, lossy: bool) -> StoreResult<Self> {
        let db = rocksdb::DB::open_default(path)?;
        let mut plain = rocksdb::WriteOptions::default();
        plain.disable_wal(lossy);
        let mut synced = rocksdb::WriteOptions::default();
        synced.set_sync(true);
        let mut obligations = HashMap::<_, VecDeque<oneshot::Sender<_>>>::new();
        let (tx, mut rx) = channel(100);
        tokio::spawn(async move {
            while let Some(command) = rx.recv().await {
                match command {
                    StoreCommand::Write(key, value) => {
                        let _ = db.put_opt(&key, &value, &plain);
                        if let Some(mut senders) = obligations.remove(&key) {
                            while let Some(s) = senders.pop_front() {
                                let _ = s.send(Ok(value.clone()));
                            }
                        }
                    }
                    StoreCommand::WriteSync(key, value, done) => {
                        // The log is synced up to this record: every earlier write that went through it (all of
                        // them unless the store is lossy) reaches the disk with the same sync.
                        db.put_opt(&key, &value, &synced).expect("Failed to sync a write to the store");
                        if let Some(mut senders) = obligations.remove(&key) {
                            while let Some(s) = senders.pop_front() {
                                let _ = s.send(Ok(value.clone()));
                            }
                        }
                        let _ = done.send(());
                    }
                    StoreCommand::Read(key, sender) => {
                        let response = db.get(&key);
                        let _ = sender.send(response);
                    }
                    StoreCommand::NotifyRead(key, sender) => {
                        let response = db.get(&key);
                        match response {
                            Ok(None) => obligations
                                .entry(key)
                                .or_insert_with(VecDeque::new)
                                .push_back(sender),
                            _ => {
                                let _ = sender.send(response.map(|x| x.unwrap()));
                            }
                        }
                    }
                }
            }
        });
        Ok(Self { channel: tx })
    }

    pub async fn write(&mut self, key: Key, value: Value) {
        if let Err(e) = self.channel.send(StoreCommand::Write(key, value)).await {
            panic!("Failed to send Write command to store: {}", e);
        }
    }

    /// Write and wait until the record is on disk.
    pub async fn write_sync(&mut self, key: Key, value: Value) {
        let (sender, receiver) = oneshot::channel();
        if let Err(e) = self.channel.send(StoreCommand::WriteSync(key, value, sender)).await {
            panic!("Failed to send WriteSync command to store: {}", e);
        }
        receiver.await.expect("Failed to receive reply to WriteSync command from store");
    }

    pub async fn read(&mut self, key: Key) -> StoreResult<Option<Value>> {
        let (sender, receiver) = oneshot::channel();
        if let Err(e) = self.channel.send(StoreCommand::Read(key, sender)).await {
            panic!("Failed to send Read command to store: {}", e);
        }
        receiver
            .await
            .expect("Failed to receive reply to Read command from store")
    }

    pub async fn notify_read(&mut self, key: Key) -> StoreResult<Value> {
        let (sender, receiver) = oneshot::channel();
        if let Err(e) = self
            .channel
            .send(StoreCommand::NotifyRead(key, sender))
            .await
        {
            panic!("Failed to send NotifyRead command to store: {}", e);
        }
        receiver
            .await
            .expect("Failed to receive reply to NotifyRead command from store")
    }
}

/// Test support: what a store would find at `path` after the machine lost power now -- a copy of its files as they
/// are, taken while it is open (the lock file left out). Records still in memory are not in the files; with a lossy
/// store those are the plain writes RocksDB has not flushed yet.
pub fn crash_image(path: &str, image: &str) -> std::io::Result<()> {
    let _ = std::fs::remove_dir_all(image);
    std::fs::create_dir_all(image)?;
    for entry in std::fs::read_dir(path)? {
        let entry = entry?;
        if entry.file_type()?.is_file() && entry.file_name() != "LOCK" {
            std::fs::copy(entry.path(), std::path::Path::new(image).join(entry.file_name()))?;
        }
    }
    Ok(())
}
