//! The transactions of the database workloads and the state machine that executes them (DESIGN.md §15.38).
//!
//! The client writes an operation into each transaction; a node that runs with `--execute` applies the transactions
//! of every committed block, in ledger order, to a key-value state and logs a digest of the state after each block.
//! Two nodes that executed the same ledger log the same digests.
//!
//! A transaction: byte 0 is the client's sample flag and bytes 1..9 its counter (as before); byte 9 is the operation;
//! the operands follow, big endian; the rest is padding, which an update takes its value from.
//!
//! * YCSB-like: read, update and read-modify-write of one record, the key drawn from a scrambled Zipfian
//!   distribution (the generator of YCSB). Workloads A, B and C are 50%, 95% and 100% reads.
//! * SmallBank-like: accounts with a checking and a savings balance and the six procedures of the benchmark in its
//!   usual mix (25% payments between two accounts, 15% each of the others).

use bytes::BufMut as _;
use bytes::BytesMut;
use rand::Rng;
use std::collections::HashMap;
use std::convert::TryInto as _;

/// Where the operation starts in a transaction.
pub const OP_AT: usize = 9;
/// The length of a record's value, taken from the transaction's padding.
pub const VALUE_LEN: usize = 100;
/// The balance of each of the two accounts of a SmallBank customer before its first transaction.
pub const INITIAL_BALANCE: i64 = 10_000;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Op {
    /// A transaction without an operation (the plain benchmark client).
    Nop,
    Read(u64),
    Update(u64),
    ReadModifyWrite(u64),
    Balance(u64),
    DepositChecking(u64, i64),
    TransactSavings(u64, i64),
    Amalgamate(u64, u64),
    WriteCheck(u64, i64),
    SendPayment(u64, u64, i64),
}

impl Op {
    /// Append the operation to a transaction that holds the sample flag and the counter.
    pub fn encode(&self, tx: &mut BytesMut) {
        debug_assert_eq!(tx.len(), OP_AT);
        match *self {
            Op::Nop => tx.put_u8(0),
            Op::Read(k) => {
                tx.put_u8(1);
                tx.put_u64(k);
            }
            Op::Update(k) => {
                tx.put_u8(2);
                tx.put_u64(k);
            }
            Op::ReadModifyWrite(k) => {
                tx.put_u8(3);
                tx.put_u64(k);
            }
            Op::Balance(a) => {
                tx.put_u8(10);
                tx.put_u64(a);
            }
            Op::DepositChecking(a, v) => {
                tx.put_u8(11);
                tx.put_u64(a);
                tx.put_i64(v);
            }
            Op::TransactSavings(a, v) => {
                tx.put_u8(12);
                tx.put_u64(a);
                tx.put_i64(v);
            }
            Op::Amalgamate(a, b) => {
                tx.put_u8(13);
                tx.put_u64(a);
                tx.put_u64(b);
            }
            Op::WriteCheck(a, v) => {
                tx.put_u8(14);
                tx.put_u64(a);
                tx.put_i64(v);
            }
            Op::SendPayment(a, b, v) => {
                tx.put_u8(15);
                tx.put_u64(a);
                tx.put_u64(b);
                tx.put_i64(v);
            }
        }
    }

    /// The operation of a transaction; anything malformed is a `Nop`.
    pub fn decode(tx: &[u8]) -> Op {
        let word = |i: usize| -> Option<u64> {
            let at = OP_AT + 1 + 8 * i;
            tx.get(at..at + 8).map(|b| u64::from_be_bytes(b.try_into().expect("eight bytes")))
        };
        let one = |f: fn(u64) -> Op| word(0).map(f);
        let amount = |f: fn(u64, i64) -> Op| Some(f(word(0)?, word(1)? as i64));
        let op = match tx.get(OP_AT) {
            Some(1) => one(Op::Read),
            Some(2) => one(Op::Update),
            Some(3) => one(Op::ReadModifyWrite),
            Some(10) => one(Op::Balance),
            Some(11) => amount(Op::DepositChecking),
            Some(12) => amount(Op::TransactSavings),
            Some(13) => word(0).and_then(|a| Some(Op::Amalgamate(a, word(1)?))),
            Some(14) => amount(Op::WriteCheck),
            Some(15) => word(0).and_then(|a| Some(Op::SendPayment(a, word(1)?, word(2)? as i64))),
            _ => None,
        };
        op.unwrap_or(Op::Nop)
    }

    /// Where the operands end: an update's value starts here.
    fn operands_end(&self) -> usize {
        OP_AT
            + 1
            + match self {
                Op::Nop => 0,
                Op::Read(_) | Op::Update(_) | Op::ReadModifyWrite(_) | Op::Balance(_) => 8,
                Op::DepositChecking(..) | Op::TransactSavings(..) | Op::Amalgamate(..) | Op::WriteCheck(..) => 16,
                Op::SendPayment(..) => 24,
            }
    }
}

fn fnv(bytes: &[u8]) -> u64 {
    bytes.iter().fold(0xcbf2_9ce4_8422_2325, |h, b| (h ^ *b as u64).wrapping_mul(0x0000_0100_0000_01b3))
}

/// The state the transactions act on, and a running digest of every result so far.
#[derive(Default)]
pub struct State {
    records: HashMap<u64, Vec<u8>>,
    accounts: HashMap<u64, (i64, i64)>,
    results: u64,
    /// Transactions applied, with an operation or without.
    pub executed: u64,
}

impl State {
    fn note(&mut self, result: u64) {
        self.results = (self.results ^ result).wrapping_mul(0x0000_0100_0000_01b3);
    }

    fn account(&mut self, a: u64) -> &mut (i64, i64) {
        self.accounts.entry(a).or_insert((INITIAL_BALANCE, INITIAL_BALANCE))
    }

    /// Apply one transaction of the ledger.
    pub fn apply(&mut self, tx: &[u8]) {
        self.executed += 1;
        let op = Op::decode(tx);
        let from = op.operands_end().min(tx.len());
        let value = || -> Vec<u8> { tx[from..tx.len().min(from + VALUE_LEN)].to_vec() };
        match op {
            Op::Nop => (),
            Op::Read(k) => {
                let read = self.records.get(&k).map_or(0, |v| fnv(v));
                self.note(read);
            }
            Op::Update(k) => {
                self.records.insert(k, value());
                self.note(k);
            }
            Op::ReadModifyWrite(k) => {
                let read = self.records.get(&k).map_or(0, |v| fnv(v));
                let mut written = value();
                for (i, b) in read.to_be_bytes().iter().enumerate() {
                    if let Some(x) = written.get_mut(i) {
                        *x ^= *b;
                    }
                }
                self.records.insert(k, written);
                self.note(read);
            }
            Op::Balance(a) => {
                let (checking, savings) = *self.account(a);
                self.note((checking + savings) as u64);
            }
            Op::DepositChecking(a, v) => {
                let ok = v >= 0;
                if ok {
                    self.account(a).0 += v;
                }
                self.note(ok as u64);
            }
            Op::TransactSavings(a, v) => {
                let ok = self.account(a).1 + v >= 0;
                if ok {
                    self.account(a).1 += v;
                }
                self.note(ok as u64);
            }
            Op::Amalgamate(a, b) => {
                if a != b {
                    let (checking, savings) = std::mem::replace(self.account(a), (0, 0));
                    self.account(b).0 += checking + savings;
                }
                self.note(a ^ b);
            }
            Op::WriteCheck(a, v) => {
                let (checking, savings) = *self.account(a);
                // An overdraft costs one more.
                self.account(a).0 -= if checking + savings < v { v + 1 } else { v };
                self.note((checking + savings < v) as u64);
            }
            Op::SendPayment(a, b, v) => {
                let ok = v >= 0 && a != b && self.account(a).0 >= v;
                if ok {
                    self.account(a).0 -= v;
                    self.account(b).0 += v;
                }
                self.note(ok as u64);
            }
        }
    }

    /// A digest of the results of every transaction so far, in order.
    pub fn digest(&self) -> u64 {
        self.results ^ self.executed
    }

    /// The money in all accounts that were touched (tests).
    #[cfg(test)]
    fn money(&self) -> i64 {
        self.accounts.values().map(|(checking, savings)| checking + savings).sum()
    }
}

/// Which operations a client sends.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Workload {
    /// Transactions without an operation.
    None,
    /// Reads among `read_percent`% of the operations, updates otherwise.
    Ycsb { read_percent: u32 },
    SmallBank,
}

impl std::str::FromStr for Workload {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "none" => Ok(Workload::None),
            "ycsb-a" => Ok(Workload::Ycsb { read_percent: 50 }),
            "ycsb-b" => Ok(Workload::Ycsb { read_percent: 95 }),
            "ycsb-c" => Ok(Workload::Ycsb { read_percent: 100 }),
            "smallbank" => Ok(Workload::SmallBank),
            other => Err(format!("unknown workload {} (none, ycsb-a, ycsb-b, ycsb-c, smallbank)", other)),
        }
    }
}

/// The Zipfian generator of YCSB (Gray et al.) over 0..n, scrambled so that the popular keys are spread out.
pub struct Zipfian {
    n: u64,
    theta: f64,
    zetan: f64,
    alpha: f64,
    eta: f64,
}

impl Zipfian {
    pub fn new(n: u64, theta: f64) -> Self {
        assert!(n >= 2 && theta > 0.0 && theta < 1.0);
        let zetan: f64 = (1..=n).map(|i| 1.0 / (i as f64).powf(theta)).sum();
        let zeta2 = 1.0 + 0.5f64.powf(theta);
        let eta = (1.0 - (2.0 / n as f64).powf(1.0 - theta)) / (1.0 - zeta2 / zetan);
        Self { n, theta, zetan, alpha: 1.0 / (1.0 - theta), eta }
    }

    /// The rank drawn (0 is the most popular).
    fn rank(&self, u: f64) -> u64 {
        let uz = u * self.zetan;
        if uz < 1.0 {
            return 0;
        }
        if uz < 1.0 + 0.5f64.powf(self.theta) {
            return 1;
        }
        ((self.n as f64 * (self.eta * u - self.eta + 1.0).powf(self.alpha)) as u64).min(self.n - 1)
    }

    pub fn next<R: Rng>(&self, rng: &mut R) -> u64 {
        fnv(&self.rank(rng.gen::<f64>()).to_be_bytes()) % self.n
    }
}

/// The operations of one client.
pub struct Generator {
    workload: Workload,
    records: u64,
    zipfian: Option<Zipfian>,
}

impl Generator {
    pub fn new(workload: Workload, records: u64, theta: f64) -> Self {
        let zipfian = match workload {
            Workload::Ycsb { .. } => Some(Zipfian::new(records, theta)),
            _ => None,
        };
        Self { workload, records, zipfian }
    }

    pub fn next<R: Rng>(&self, rng: &mut R) -> Op {
        match self.workload {
            Workload::None => Op::Nop,
            Workload::Ycsb { read_percent } => {
                let key = self.zipfian.as_ref().expect("a YCSB workload").next(rng);
                if rng.gen_range(0, 100) < read_percent {
                    Op::Read(key)
                } else {
                    Op::Update(key)
                }
            }
            Workload::SmallBank => {
                let a = rng.gen_range(0, self.records);
                let b = (a + 1 + rng.gen_range(0, self.records - 1)) % self.records;
                let amount = rng.gen_range(1, 100);
                match rng.gen_range(0, 100) {
                    0..=14 => Op::Balance(a),
                    15..=29 => Op::DepositChecking(a, amount),
                    30..=44 => Op::TransactSavings(a, amount - 50),
                    45..=59 => Op::Amalgamate(a, b),
                    60..=74 => Op::WriteCheck(a, amount),
                    _ => Op::SendPayment(a, b, amount),
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rand::rngs::StdRng;
    use rand::SeedableRng as _;

    fn tx(op: &Op, fill: u8) -> Vec<u8> {
        let mut tx = BytesMut::new();
        tx.put_u8(1);
        tx.put_u64(7);
        op.encode(&mut tx);
        tx.resize(200, fill);
        tx.to_vec()
    }

    #[test]
    fn operations_survive_the_wire() {
        let ops = [
            Op::Nop,
            Op::Read(3),
            Op::Update(4),
            Op::ReadModifyWrite(5),
            Op::Balance(6),
            Op::DepositChecking(7, 10),
            Op::TransactSavings(8, -10),
            Op::Amalgamate(9, 10),
            Op::WriteCheck(11, 12),
            Op::SendPayment(13, 14, 15),
        ];
        for op in &ops {
            assert_eq!(Op::decode(&tx(op, 0)), *op);
        }
        // The plain client's transactions, and anything cut short, carry no operation.
        assert_eq!(Op::decode(&[1u8; 9]), Op::Nop);
        assert_eq!(Op::decode(&tx(&Op::SendPayment(1, 2, 3), 0)[..20]), Op::Nop);
    }

    #[test]
    fn the_same_ledger_gives_the_same_digest() {
        let mut rng = StdRng::seed_from_u64(1);
        for workload in [Workload::Ycsb { read_percent: 50 }, Workload::SmallBank] {
            let generator = Generator::new(workload, 1_000, 0.99);
            let ledger: Vec<Vec<u8>> = (0..5_000).map(|i| tx(&generator.next(&mut rng), i as u8)).collect();
            let run = |ledger: &[Vec<u8>]| {
                let mut state = State::default();
                ledger.iter().for_each(|tx| state.apply(tx));
                state.digest()
            };
            assert_eq!(run(&ledger), run(&ledger));
            // Another order of the same transactions is another ledger.
            let mut swapped = ledger.clone();
            swapped.swap(10, 4_000);
            assert_ne!(run(&ledger), run(&swapped));
        }
    }

    #[test]
    fn an_update_is_read_back() {
        let mut state = State::default();
        state.apply(&tx(&Op::Read(1), 0));
        let empty = state.results;
        state.apply(&tx(&Op::Update(1), 9));
        let mut other = State::default();
        other.apply(&tx(&Op::Read(1), 0));
        other.apply(&tx(&Op::Update(1), 8));
        assert_eq!(state.results, other.results, "a write notes its key, not its value");
        state.apply(&tx(&Op::Read(1), 0));
        other.apply(&tx(&Op::Read(1), 0));
        assert_ne!(state.results, other.results, "the read returns what was written");
        assert_ne!(state.results, empty);
        assert_eq!(state.records[&1].len(), VALUE_LEN);
    }

    #[test]
    fn payments_and_amalgamations_keep_the_money() {
        let mut state = State::default();
        for a in 0..4 {
            state.apply(&tx(&Op::Balance(a), 0));
        }
        let before = state.money();
        state.apply(&tx(&Op::SendPayment(0, 1, 500), 0));
        state.apply(&tx(&Op::SendPayment(2, 3, INITIAL_BALANCE + 1), 0)); // refused: not enough in checking
        state.apply(&tx(&Op::Amalgamate(1, 2), 0));
        state.apply(&tx(&Op::SendPayment(3, 3, 5), 0)); // refused: to itself
        assert_eq!(state.money(), before);
        assert_eq!(state.accounts[&0], (INITIAL_BALANCE - 500, INITIAL_BALANCE));
        assert_eq!(state.accounts[&1], (0, 0));
        assert_eq!(state.accounts[&2].0, 3 * INITIAL_BALANCE + 500);

        // A check above the total balance is an overdraft with a penalty of one; savings never go below zero.
        state.apply(&tx(&Op::WriteCheck(3, 2 * INITIAL_BALANCE + 5), 0));
        assert_eq!(state.accounts[&3].0, INITIAL_BALANCE - (2 * INITIAL_BALANCE + 6));
        state.apply(&tx(&Op::TransactSavings(0, -INITIAL_BALANCE - 1), 0));
        assert_eq!(state.accounts[&0].1, INITIAL_BALANCE);
    }

    #[test]
    fn the_zipfian_keys_are_skewed_and_in_range() {
        let zipfian = Zipfian::new(10_000, 0.99);
        let mut rng = StdRng::seed_from_u64(2);
        let mut counts: HashMap<u64, u32> = HashMap::new();
        for _ in 0..100_000 {
            let key = zipfian.next(&mut rng);
            assert!(key < 10_000);
            *counts.entry(key).or_default() += 1;
        }
        let mut sorted: Vec<u32> = counts.values().cloned().collect();
        sorted.sort_unstable_by(|a, b| b.cmp(a));
        let top: u32 = sorted.iter().take(10).sum();
        assert!(top > 20_000, "the ten most popular keys draw {} of 100000", top);
        assert!(counts.len() > 2_000, "the tail is drawn too: {} keys", counts.len());
    }
}
