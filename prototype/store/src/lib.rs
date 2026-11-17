use std::collections::{HashMap, VecDeque};
use std::convert::TryInto;
use std::fs::{File, OpenOptions};
use std::os::unix::fs::FileExt;
use std::path::Path;
use std::sync::{Arc, Mutex};
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

/// Name of the file of the safe record, inside the directory of the database (RocksDB leaves files it does not know
/// alone; it is copied and removed with the directory).
const SAFE_FILE: &str = "SAFE";
/// Size of one slot of that file: far more than the largest record (a few kilobytes per hundred members).
const SAFE_SLOT: u64 = 1 << 20;
/// Sequence number (8 bytes), length (4) and checksum (8) in front of the record.
const SAFE_HEADER: usize = 20;

/// The one record a node must never lose (the safety state of consensus, R8), kept apart from the database so that
/// syncing it flushes nothing else: the database also holds the transaction batches, and a synced write to it writes
/// out every batch stored before. The file has two slots, written in turn; a slot holds a sequence number, the
/// length and a checksum of the record, and the record. Each write is synced before it returns (data only: the file
/// has its full length from the start). A reader takes the valid slot with the higher sequence number, so a write
/// torn by a loss of power leaves the record before it.
struct SafeFile {
    file: File,
    sequence: u64,
}

impl SafeFile {
    fn open(directory: &str) -> std::io::Result<Self> {
        let path = Path::new(directory).join(SAFE_FILE);
        let created = !path.exists();
        let file = OpenOptions::new().read(true).write(true).create(true).open(&path)?;
        if created {
            file.set_len(2 * SAFE_SLOT)?;
            file.sync_all()?;
            File::open(directory)?.sync_all()?; // the entry of the new file in its directory
        }
        let sequence = (0..2).filter_map(|slot| Self::slot(&file, slot)).map(|(sequence, _)| sequence).max();
        Ok(Self { file, sequence: sequence.unwrap_or(0) })
    }

    fn checksum(sequence: u64, record: &[u8]) -> u64 {
        // FNV-1a over the sequence number, the length and the record: enough to tell a torn write.
        let mut hash = 0xcbf2_9ce4_8422_2325u64;
        let length = (record.len() as u32).to_le_bytes();
        for byte in sequence.to_le_bytes().iter().chain(length.iter()).chain(record.iter()) {
            hash = (hash ^ u64::from(*byte)).wrapping_mul(0x0000_0100_0000_01b3);
        }
        hash
    }

    fn slot(file: &File, slot: u64) -> Option<(u64, Value)> {
        let mut header = [0u8; SAFE_HEADER];
        file.read_exact_at(&mut header, slot * SAFE_SLOT).ok()?;
        let sequence = u64::from_le_bytes(header[..8].try_into().ok()?);
        let length = u32::from_le_bytes(header[8..12].try_into().ok()?) as usize;
        let checksum = u64::from_le_bytes(header[12..].try_into().ok()?);
        if sequence == 0 || length as u64 > SAFE_SLOT - SAFE_HEADER as u64 {
            return None;
        }
        let mut record = vec![0u8; length];
        file.read_exact_at(&mut record, slot * SAFE_SLOT + SAFE_HEADER as u64).ok()?;
        (Self::checksum(sequence, &record) == checksum).then(|| (sequence, record))
    }

    fn read(&self) -> Option<Value> {
        (0..2).filter_map(|slot| Self::slot(&self.file, slot)).max_by_key(|(sequence, _)| *sequence).map(|(_, record)| record)
    }

    fn write(&mut self, record: &[u8]) -> std::io::Result<()> {
        assert!(record.len() as u64 <= SAFE_SLOT - SAFE_HEADER as u64, "The safe record does not fit its slot");
        let sequence = self.sequence + 1;
        let mut bytes = Vec::with_capacity(SAFE_HEADER + record.len());
        bytes.extend_from_slice(&sequence.to_le_bytes());
        bytes.extend_from_slice(&(record.len() as u32).to_le_bytes());
        bytes.extend_from_slice(&Self::checksum(sequence, record).to_le_bytes());
        bytes.extend_from_slice(record);
        self.file.write_all_at(&bytes, (sequence % 2) * SAFE_SLOT)?;
        self.file.sync_data()?;
        self.sequence = sequence;
        Ok(())
    }
}

#[derive(Clone)]
pub struct Store {
    channel: Sender<StoreCommand>,
    safe: Arc<Mutex<SafeFile>>,
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
        let safe = SafeFile::open(path).expect("Failed to open the file of the safe record");
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
        Ok(Self { channel: tx, safe: Arc::new(Mutex::new(safe)) })
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

    /// Replace the safe record and wait until it is on disk. Nothing else is written out with it.
    pub async fn write_safe(&mut self, record: Value) {
        let safe = self.safe.clone();
        tokio::task::spawn_blocking(move || safe.lock().expect("The safe record is poisoned").write(&record))
            .await
            .expect("Failed to write the safe record")
            .expect("Failed to sync the safe record");
    }

    /// The safe record, if one was ever written.
    pub async fn read_safe(&mut self) -> Option<Value> {
        let safe = self.safe.clone();
        tokio::task::spawn_blocking(move || safe.lock().expect("The safe record is poisoned").read())
            .await
            .expect("Failed to read the safe record")
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
