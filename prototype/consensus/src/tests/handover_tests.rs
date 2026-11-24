//! DESIGN.md §15.54 (mock review M1, R10 and R23): a fork across an epoch handover, on the consensus cores of the
//! prototype under a scripted schedule.
//!
//! Five members. AS, AH, R1 and R2 run the node's own `Core` and `Proposer`, each on a store of its own. What they
//! send goes to listeners at the members' addresses and reaches another member only when the script hands it over:
//! the script is the network before GST. Z is Byzantine, and the script signs its messages with its key. AS follows
//! the protocol except for one second vote in the first epoch, which the script signs with AS's key; the double vote
//! gets on the ledger and suspends AS, so the table of the third epoch gives it no weight. That table change comes
//! from the ledger, not from the test. The handover from the second epoch to the third is the one under test
//! (epochs of 10 rounds):
//!
//!   rounds 1-21   everyone takes part; B20 is the terminal block G of the second epoch and B21 its child C;
//!   round 22      Z leads the first round of the third epoch and gives N1, which carries the commit proof QC(C),
//!                 to R1 and R2 alone; they enter the third epoch; N2 follows, and QC(N2) commits N1 at both;
//!   rounds 21-23  AS and AH, left in the second epoch, time out, and Z times out with them: these are TCs of the
//!                 second epoch past its end;
//!   round 24      Z proposes N', a block of the third epoch on C that carries TC(23), to AH and R2;
//!   round 25      N'' on N'; QC(N'') commits N' at AH.
//!
//! R1 then holds N1 and AH holds N', both committed. With H5 the TCs of rounds 21-23 count only with a quorum of
//! the third table too. The stores of R1 and AH go through the forensics, the evidence package and its verifier.
//! The arms differ in the weights and in H5 (`run`).

use super::*;
use crate::config::{Parameters, Stake};
use crate::consensus::epoch_config;
use crate::proposer::Proposer;
use crypto::{generate_keypair, SecretKey, Signature};
use futures::sink::SinkExt as _;
use futures::stream::StreamExt as _;
use rand::rngs::StdRng;
use rand::SeedableRng as _;
use std::fs;
use std::net::SocketAddr;
use tokio::net::TcpListener;
use tokio::sync::mpsc::{channel, unbounded_channel, UnboundedReceiver, UnboundedSender};
use tokio::time::timeout;
use tokio_util::codec::{Framed, LengthDelimitedCodec};

const AS: usize = 0;
const AH: usize = 1;
const R1: usize = 2;
const R2: usize = 3;
const Z: usize = 4;
/// The members that run the node's code, by index (AS but for its one double vote).
const HONEST: [usize; 4] = [AS, AH, R1, R2];
const NAMES: [&str; 5] = ["AS", "AH", "R1", "R2", "Z"];
const LENGTH: Round = 10;

fn keypairs() -> Vec<(PublicKey, SecretKey)> {
    let mut rng = StdRng::from_seed([7; 32]);
    (0..5).map(|_| generate_keypair(&mut rng)).collect()
}

fn roster(weights: [Stake; 5], epoch: EpochNumber, port: u16) -> Committee {
    let info = keypairs()
        .into_iter()
        .zip(weights)
        .enumerate()
        .map(|(i, ((name, _), stake))| (name, stake, format!("127.0.0.1:{}", port + i as u16).parse().unwrap()))
        .collect();
    Committee::new(info, epoch)
}

/// Epochs of 10 rounds and no caps (five members cannot meet an entity cap of 10%); the rest as a node has it.
fn parameters(no_h5: bool) -> Parameters {
    Parameters {
        epoch_length: LENGTH,
        entity_cap_ppm: 1_000_000,
        class_cap_ppm: 1_000_000,
        no_h5,
        ..Parameters::default()
    }
}

/// The weight tables of the three epochs of a run. The first two are the roster's (H1'); the third is what the
/// ledger gives once a double vote of `culprit` is on it in the first epoch, computed by the same `Epochs` as the
/// nodes. The script needs them for the leaders and for Z's blocks, and the run checks them against the nodes' own.
fn tables(roster: &Committee, config: EpochConfig, culprit: PublicKey) -> Vec<Committee> {
    let first = roster.epoch;
    let vote = |tag: u8| Vote {
        hash: Digest([tag; 32]),
        round: 2,
        epoch: first,
        author: culprit,
        signature: Signature::default(),
    };
    let mut epochs = Epochs::new(roster, config);
    let evidence = vec![Evidence::DoubleVote(vote(1), vote(2))];
    epochs.record(&Block { round: 3, epoch: first, evidence, ..Block::default() });
    let terminal = Block { round: LENGTH, epoch: first, ..Block::default() };
    epochs.record(&terminal);
    epochs.enter_next(&terminal);
    (0..3)
        .map(|k| Committee { handover: None, ..epochs.get(first + k).expect("three tables").clone() })
        .collect()
}

/// The first epoch number that gives the schedule the script needs (the leader of a round is drawn from the epoch
/// number and the round): Z leads round 22 by the second table and rounds 23 to 25 by the third; neither AH nor
/// R2 leads round 26, so their votes of round 25 go over the network; AS and AH do not lead rounds 23 and 24 of
/// the second epoch, where they sit and time out; and one of AH, R1, R2 leads a round from 4 to 9, so the double
/// vote gets into a block of the first epoch.
fn first_epoch(weights: [Stake; 5], config: EpochConfig) -> EpochNumber {
    let names: Vec<PublicKey> = keypairs().into_iter().map(|(name, _)| name).collect();
    let base = tables(&roster(weights, 1, 0), config, names[AS]);
    (1..1_000_000u128)
        .find(|first| {
            let w: Vec<Committee> = (0..3).map(|k| Committee { epoch: first + k as u128, ..base[k].clone() }).collect();
            let leads = |table: usize, round: Round, who: usize| leader(&w[table], round) == names[who];
            leads(1, 22, Z)
                && (23..=25).all(|round| leads(2, round, Z))
                && !leads(2, 26, AH)
                && !leads(2, 26, R2)
                && (23..=24).all(|round| !leads(1, round, AS) && !leads(1, round, AH))
                && (4..=9).any(|round| [AH, R1, R2].iter().any(|who| leads(0, round, *who)))
        })
        .expect("no epoch number gives the schedule")
}

/// A listener at a member's address. It stands for the network: what the nodes send there is handed to the script,
/// and a proposal is acknowledged as a node's receiver acknowledges it (a proposer waits for a quorum of those).
async fn tap(address: SocketAddr, tx: UnboundedSender<ConsensusMessage>) {
    let listener = TcpListener::bind(&address).await.unwrap();
    tokio::spawn(async move {
        while let Ok((socket, _)) = listener.accept().await {
            let tx = tx.clone();
            tokio::spawn(async move {
                let (mut writer, mut reader) = Framed::new(socket, LengthDelimitedCodec::new()).split();
                while let Some(Ok(frame)) = reader.next().await {
                    if let Ok(message) = bincode::deserialize::<ConsensusMessage>(&frame) {
                        if matches!(message, ConsensusMessage::Propose(_)) {
                            let _ = writer.send(Bytes::from("Ack")).await;
                        }
                        let _ = tx.send(message);
                    }
                }
            });
        }
    });
}

struct Node {
    core: Core,
    /// What its proposer makes; in a running node this goes back to the core.
    blocks: Receiver<Block>,
    /// The blocks it puts on its ledger.
    commits: Receiver<Block>,
    store: Store,
    path: String,
    /// The other ends of the channels of the tasks around the core, kept open.
    _open: (Sender<ConsensusMessage>, Sender<Block>, Sender<Digest>),
}

fn node(name: PublicKey, secret: SecretKey, roster: &Committee, parameters: &Parameters, path: String) -> Node {
    let _ = fs::remove_dir_all(&path);
    let store = Store::new(&path).unwrap();
    let (tx_loopback, blocks) = channel(100);
    let (tx_unused, rx_unused) = channel(1);
    let (tx_message, rx_message) = channel(1);
    let (tx_payload, rx_payload) = channel(1);
    let (tx_mempool, mut rx_mempool) = channel(100);
    tokio::spawn(async move { while rx_mempool.recv().await.is_some() {} });
    let (tx_commit, commits) = channel(1_000);
    let (tx_proposer, rx_proposer) = channel(100);
    let signature_service = SignatureService::new(secret);
    Proposer::spawn(name, roster.clone(), signature_service.clone(), rx_payload, rx_proposer, tx_loopback.clone());
    let synchronizer = Synchronizer::new(name, roster.clone(), store.clone(), tx_loopback.clone(), 100_000);
    let core = Core::new(
        name,
        roster.clone(),
        epoch_config(parameters),
        Inclusion::new(Duration::from_millis(parameters.attest_guard), false),
        Faults { no_h5: parameters.no_h5, ..Faults::default() },
        signature_service,
        store.clone(),
        MempoolDriver::new(store.clone(), tx_mempool, tx_loopback),
        synchronizer,
        parameters.timeout_delay,
        rx_message,
        rx_unused,
        tx_proposer,
        tx_commit,
    );
    Node { core, blocks, commits, store, path, _open: (tx_message, tx_unused, tx_payload) }
}

fn certificate(block: &Block, votes: &[Vote]) -> QC {
    QC {
        hash: block.digest(),
        round: block.round,
        epoch: block.epoch,
        votes: votes.iter().map(|vote| (vote.author, vote.signature.clone())).collect(),
    }
}

fn timeout_certificate(timeouts: &[Timeout]) -> TC {
    let high_qc = timeouts.iter().map(|t| &t.high_qc).max_by_key(|qc| qc.round).unwrap().clone();
    TC {
        round: timeouts[0].round,
        epoch: timeouts[0].epoch,
        votes: timeouts.iter().map(|t| (t.author, t.signature.clone(), t.high_qc.round, t.nr)).collect(),
        high_qc,
    }
}

/// The share of `members` in `table`.
fn share(table: &Committee, members: &[PublicKey]) -> f64 {
    let total: Stake = table.authorities.values().map(|a| a.stake).sum();
    members.iter().map(|name| table.stake(name)).sum::<Stake>() as f64 / total as f64
}

struct World {
    first: EpochNumber,
    parameters: Parameters,
    roster: Committee,
    names: Vec<PublicKey>,
    secrets: Vec<SecretKey>,
    /// The tables of the three epochs, without the handover leader.
    tables: Vec<Committee>,
    /// AS, AH, R1, R2.
    nodes: Vec<Node>,
    wire: UnboundedReceiver<ConsensusMessage>,
    /// Everything the nodes sent so far.
    seen: Vec<ConsensusMessage>,
    /// The QC the next block of the common chain goes on.
    qc: QC,
    steps: Vec<String>,
}

impl World {
    async fn new(arm: &str, weights: [Stake; 5], no_h5: bool, port: u16) -> Self {
        let parameters = parameters(no_h5);
        let config = epoch_config(&parameters);
        let first = first_epoch(weights, config);
        let roster = roster(weights, first, port);
        let (names, secrets): (Vec<_>, Vec<_>) = keypairs().into_iter().unzip();
        let (tx, wire) = unbounded_channel();
        for name in &names {
            tap(roster.address(name).unwrap(), tx.clone()).await;
        }
        let tables = tables(&roster, config, names[AS]);
        let nodes = keypairs()
            .into_iter()
            .take(HONEST.len())
            .enumerate()
            .map(|(i, (name, secret))| {
                node(name, secret, &roster, &parameters, format!(".db_test_handover_{}_{}", arm, NAMES[i]))
            })
            .collect();
        Self {
            first,
            parameters,
            roster,
            names,
            secrets,
            tables,
            nodes,
            wire,
            seen: Vec::new(),
            qc: QC::genesis(),
            steps: Vec::new(),
        }
    }

    fn step(&mut self, what: String) {
        println!("  {}", what);
        self.steps.push(what);
    }

    fn honest(&self, name: &PublicKey) -> Option<usize> {
        HONEST.iter().copied().find(|i| self.names[*i] == *name)
    }

    /// The epoch of a round of the schedule, as an index into the tables, and its start: no round fails before 22.
    fn epoch_at(round: Round) -> (usize, Round) {
        match round {
            0..=11 => (0, 0),
            12..=21 => (1, 10),
            _ => (2, 20),
        }
    }

    /// The leader of a round by the table of its epoch; the first round of an epoch keeps the leader the table
    /// before gives it.
    fn leader_of(&self, round: Round) -> PublicKey {
        let (k, start) = Self::epoch_at(round);
        let table = if k > 0 && round == start + 2 { &self.tables[k - 1] } else { &self.tables[k] };
        leader(table, round)
    }

    /// Hand a message to a node as its receiver does, and then the messages it kept for the epoch it may have
    /// entered (the loop of `Core::run`).
    async fn deliver(&mut self, to: usize, message: ConsensusMessage) -> ConsensusResult<()> {
        let core = &mut self.nodes[to].core;
        let result = core.handle_message(message).await;
        while let Some(message) = core.replay.pop_front() {
            let _ = core.handle_message(message).await;
        }
        result
    }

    /// The timer of a node fires.
    async fn fire(&mut self, node: usize) {
        let core = &mut self.nodes[node].core;
        core.local_timeout_round().await.unwrap();
        while let Some(message) = core.replay.pop_front() {
            let _ = core.handle_message(message).await;
        }
    }

    /// The first message the nodes sent that `pick` takes; waits for it to come.
    async fn sent<T>(&mut self, what: String, pick: impl Fn(&ConsensusMessage) -> Option<T>) -> T {
        if let Some(found) = self.seen.iter().find_map(&pick) {
            return found;
        }
        loop {
            match timeout(Duration::from_secs(3), self.wire.recv()).await {
                Ok(Some(message)) => {
                    let found = pick(&message);
                    self.seen.push(message);
                    if let Some(found) = found {
                        return found;
                    }
                }
                _ => panic!("{} was not sent", what),
            }
        }
    }

    /// The vote a node sent for `block`.
    async fn vote_of(&mut self, voter: usize, block: &Block) -> Vote {
        let (name, hash) = (self.names[voter], block.digest());
        let what = format!("the vote of {} for B{}", NAMES[voter], block.round);
        self.sent(what, move |message| match message {
            ConsensusMessage::Vote(vote) if vote.author == name && vote.hash == hash => Some(vote.clone()),
            _ => None,
        })
        .await
    }

    /// The timeout a node sent for `round` in `epoch`.
    async fn timeout_of(&mut self, node: usize, epoch: EpochNumber, round: Round) -> Timeout {
        let name = self.names[node];
        let what = format!("the timeout of {} for round {}", NAMES[node], round);
        self.sent(what, move |message| match message {
            ConsensusMessage::Timeout(t) if t.author == name && t.round == round && t.epoch == epoch => Some(t.clone()),
            _ => None,
        })
        .await
    }

    /// The TC of `round` in `epoch` that a node assembled and sent.
    async fn tc_of(&mut self, epoch: EpochNumber, round: Round) -> TC {
        self.sent(format!("a TC of round {}", round), move |message| match message {
            ConsensusMessage::TC(tc) if tc.round == round && tc.epoch == epoch => Some(tc.clone()),
            _ => None,
        })
        .await
    }

    /// A vote signed with the key of `who`: Z's, or the second vote of AS.
    fn vote_by(&self, who: usize, hash: Digest, round: Round, epoch: EpochNumber) -> Vote {
        let mut vote = Vote { hash, round, epoch, author: self.names[who], signature: Signature::default() };
        vote.signature = Signature::new(&vote.digest(), &self.secrets[who]);
        vote
    }

    /// A timeout of Z.
    fn timeout_by(&self, who: usize, epoch: EpochNumber, round: Round, high_qc: &QC, nr: bool) -> Timeout {
        let mut timeout = Timeout {
            high_qc: high_qc.clone(),
            round,
            epoch,
            nr,
            author: self.names[who],
            signature: Signature::default(),
        };
        timeout.signature = Signature::new(&timeout.digest(), &self.secrets[who]);
        timeout
    }

    /// A block of Z for a round it leads, on `qc` and `tc`, naming the tables of the schedule.
    fn block_by(&self, who: usize, round: Round, qc: QC, tc: Option<TC>) -> Block {
        assert!(self.leader_of(round) == self.names[who], "{} does not lead round {}", NAMES[who], round);
        let (k, start) = Self::epoch_at(round);
        let next_table = match round >= start + LENGTH {
            true => table_digest(&self.tables[k + 1]),
            false => Digest::default(),
        };
        let mut block = Block {
            qc,
            tc,
            author: self.names[who],
            round,
            epoch: self.first + k as EpochNumber,
            table: table_digest(&self.tables[k]),
            next_table,
            start,
            ..Block::default()
        };
        block.signature = Signature::new(&block.digest(), &self.secrets[who]);
        block
    }

    /// The block the proposer of an honest leader made for `round`, handed back to its core as in a running node.
    async fn own_block(&mut self, leader: usize, round: Round) -> Block {
        let node = &mut self.nodes[leader];
        let block = match timeout(Duration::from_secs(3), node.blocks.recv()).await {
            Ok(Some(block)) => block,
            _ => panic!("{} proposed nothing for round {}", NAMES[leader], round),
        };
        assert_eq!(block.round, round, "{} proposed for another round", NAMES[leader]);
        node.core.process_block(&block).await.unwrap();
        block
    }

    /// The QC of `block` from the votes of the nodes in `voters`, which hold the block, and of Z. If one of them
    /// leads the next round it gathers the votes itself (and its proposer makes the next block); otherwise the
    /// votes are the ones the nodes sent to that leader.
    async fn certify(&mut self, block: &Block, voters: &[usize]) -> QC {
        let next = self.honest(&self.leader_of(block.round + 1)).filter(|i| voters.contains(i));
        let mut votes = vec![self.vote_by(Z, block.digest(), block.round, block.epoch)];
        for voter in voters {
            if Some(*voter) != next {
                votes.push(self.vote_of(*voter, block).await);
            }
        }
        match next {
            Some(next) => {
                for vote in votes {
                    let _ = self.deliver(next, ConsensusMessage::Vote(vote)).await;
                }
                let qc = self.nodes[next].core.high_qc.clone();
                assert!(qc.hash == block.digest(), "{} did not gather the QC of B{}", NAMES[next], block.round);
                qc
            }
            None => certificate(block, &votes),
        }
    }

    /// A round in which everyone takes part: the leader's block goes to every node and each votes for it.
    async fn round(&mut self, round: Round) -> Block {
        let leader = self.leader_of(round);
        let block = match self.honest(&leader) {
            Some(leader) => self.own_block(leader, round).await,
            None => self.block_by(Z, round, self.qc.clone(), None),
        };
        for node in HONEST {
            if self.names[node] != block.author {
                self.deliver(node, ConsensusMessage::Propose(block.clone())).await.unwrap();
            }
            let voted = self.nodes[node].core.last_voted_round;
            assert_eq!(voted, round, "{} did not vote for B{}", NAMES[node], round);
        }
        block
    }

    /// `block` goes to `nodes`; returns those that voted for it, and notes what each made of it.
    async fn propose_to(&mut self, block: &Block, label: &str, nodes: &[usize]) -> Vec<usize> {
        let mut voters = Vec::new();
        for node in nodes {
            let result = self.deliver(*node, ConsensusMessage::Propose(block.clone())).await;
            let voted = self.nodes[*node].core.last_voted_round == block.round;
            let outcome = match (&result, voted) {
                (Ok(()), true) => "votes for it".to_string(),
                (Ok(()), false) => "does not vote for it".to_string(),
                (Err(e), _) => format!("refuses it: {}", e),
            };
            self.step(format!("{} is given {} (round {}): {}", NAMES[*node], label, block.round, outcome));
            if voted {
                voters.push(*node);
            }
        }
        voters
    }

    /// The rounds of the blocks a node has put on its ledger so far.
    fn ledger(&mut self, node: usize) -> Vec<Round> {
        let mut rounds = Vec::new();
        while let Ok(block) = self.nodes[node].commits.try_recv() {
            rounds.push(block.round);
        }
        rounds
    }
}

/// One run of the schedule with the base weights of AS, AH, R1, R2, Z. Returns what happened, as JSON.
async fn run(arm: &str, weights: [Stake; 5], no_h5: bool, port: u16) -> serde_json::Value {
    println!("arm {}: weights {:?}, H5 {}", arm, weights, if no_h5 { "off" } else { "on" });
    let mut w = World::new(arm, weights, no_h5, port).await;
    let (old, new) = (w.first + 1, w.first + 2);

    // Rounds 1 to 21: everyone takes part. At round 2 AS signs a second vote, for a block that does not exist.
    if let Some(leader) = w.honest(&w.leader_of(1)) {
        w.nodes[leader].core.generate_proposal(None).await;
    }
    let mut child = None;
    for round in 1..=21 {
        let block = w.round(round).await;
        if round == 2 {
            let second = w.vote_by(AS, Digest([0xee; 32]), 2, w.first);
            for node in [AH, R1, R2] {
                let _ = w.deliver(node, ConsensusMessage::Vote(second.clone())).await;
            }
        }
        w.qc = w.certify(&block, &HONEST).await;
        child = Some(block);
    }
    let c = child.unwrap();
    let (qc_c, qc_g) = (w.qc.clone(), c.qc.clone());
    for node in HONEST {
        let core = &w.nodes[node].core;
        assert_eq!((core.epochs.epoch(), core.round), (old, 21), "{} is not at the end of the second epoch", NAMES[node]);
        let table = core.epochs.get(new).expect("the table of the third epoch");
        assert!(table_digest(table) == table_digest(&w.tables[2]), "the third table is not the one expected");
        assert_eq!(table.stake(&w.names[AS]), 0, "the double vote did not suspend AS");
    }
    w.step(format!(
        "rounds 1-21: the double vote of AS at round 2 is on the ledger; the third table gives AS no weight and Z {:.1}%",
        100.0 * share(&w.tables[2], &[w.names[Z]])
    ));

    // Round 22: Z leads the first round of the third epoch and gives its block, with the commit proof of G, to R1
    // and R2 alone. They enter the third epoch and commit N1 there.
    let n1 = w.block_by(Z, 22, qc_c.clone(), None);
    assert_eq!(w.propose_to(&n1, "N1", &[R1, R2]).await, vec![R1, R2]);
    let qc_n1 = w.certify(&n1, &[R1, R2]).await;
    let n2 = w.block_by(Z, 23, qc_n1, None);
    assert_eq!(w.propose_to(&n2, "N2", &[R1, R2]).await, vec![R1, R2]);
    let qc_n2 = w.certify(&n2, &[R1, R2]).await;
    let carrier = w.timeout_by(Z, new, 24, &qc_n2, true);
    for node in [R1, R2] {
        w.deliver(node, ConsensusMessage::Timeout(carrier.clone())).await.unwrap();
        let core = &w.nodes[node].core;
        assert_eq!((core.epochs.epoch(), core.last_committed_round), (new, 22), "{} did not commit N1", NAMES[node]);
    }
    w.step("R1 and R2 are given QC(N2) in a timeout of Z: both commit N1 (round 22) in the third epoch".to_string());

    // Rounds 21 to 23 of the second epoch: AS and AH never got the commit proof. Their timers fire, and Z times out
    // with them, reporting the QC of G as they do.
    let signers = [w.names[AS], w.names[AH], w.names[Z]];
    let mut tc = None;
    let mut refused = serde_json::Value::Null;
    for round in 21..=23 {
        for node in [AS, AH] {
            let core = &w.nodes[node].core;
            assert_eq!((core.epochs.epoch(), core.round), (old, round), "{} is elsewhere", NAMES[node]);
            w.fire(node).await;
        }
        let from_as = w.timeout_of(AS, old, round).await;
        let from_ah = w.timeout_of(AH, old, round).await;
        let from_z = w.timeout_by(Z, old, round, &qc_g, false);
        for (node, other) in [(AH, &from_as), (AS, &from_ah)] {
            w.deliver(node, ConsensusMessage::Timeout(other.clone())).await.unwrap();
            w.deliver(node, ConsensusMessage::Timeout(from_z.clone())).await.unwrap();
        }
        if w.nodes[AH].core.round == round {
            // No TC of this round at AH. The three timeouts are valid, so Z can put them together itself.
            let made = timeout_certificate(&[from_as, from_ah, from_z]);
            let result = w.deliver(AH, ConsensusMessage::TC(made)).await;
            let error = result.as_ref().err().map(|e| e.to_string());
            w.step(format!(
                "round {}: AS, AH and Z time out; they hold {:.1}% of the second table and {:.1}% of the third: AH \
                 assembles no TC, and refuses the one Z assembles: {}",
                round,
                100.0 * share(&w.tables[1], &signers),
                100.0 * share(&w.tables[2], &signers),
                error.clone().unwrap_or_else(|| "(accepted)".to_string())
            ));
            refused = serde_json::json!({
                "round": round,
                "error": error,
                "requires_quorum": matches!(result, Err(ConsensusError::TCRequiresQuorum)),
                "round_of_AH": w.nodes[AH].core.round,
            });
            break;
        }
        w.step(format!("round {}: AS, AH and Z time out; AS and AH assemble TC({}) and move on", round, round));
        tc = Some(w.tc_of(old, round).await);
    }

    // Round 24: N', a block of the third epoch on C that carries the TC of round 23 of the second epoch, and N'' on
    // it. With QC(N'') AH commits N'.
    let mut second_branch = false;
    if let Some(tc) = tc {
        let n_prime = w.block_by(Z, 24, qc_c.clone(), Some(tc));
        let voters = w.propose_to(&n_prime, "N'", &[AH, R2]).await;
        if voters == vec![AH, R2] {
            let qc_n_prime = w.certify(&n_prime, &voters).await;
            let n_second = w.block_by(Z, 25, qc_n_prime, None);
            assert_eq!(w.propose_to(&n_second, "N''", &[AH, R2]).await, vec![AH, R2]);
            let qc_n_second = w.certify(&n_second, &[AH, R2]).await;
            let carrier = w.timeout_by(Z, new, 26, &qc_n_second, true);
            w.deliver(AH, ConsensusMessage::Timeout(carrier)).await.unwrap();
            assert_eq!(w.nodes[AH].core.last_committed_round, 24, "AH did not commit N'");
            w.step("AH is given QC(N'') in a timeout of Z: it commits N' (round 24) in the third epoch".to_string());
            second_branch = true;
        }
    }

    // The run ends: the timers of R1 and AH fire once more, which puts their high QCs into their safety records.
    w.fire(R1).await;
    w.fire(AH).await;
    let (ledger_r1, ledger_ah) = (w.ledger(R1), w.ledger(AH));

    // The stores as they are on disk go to the forensics, the evidence package and its verifier.
    let mut images = Vec::new();
    for node in [R1, AH] {
        let node = &mut w.nodes[node];
        let _ = node.store.read(vec![0]).await; // every write before this read is in the database
        let image = format!("{}_image", node.path);
        store::crash_image(&node.path, &image).unwrap();
        images.push(image);
    }
    let report = crate::forensics::report(&w.roster, &w.parameters, &images[0], &images[1]).await.unwrap();
    let report: serde_json::Value = serde_json::from_str(&report).unwrap();
    let package = format!(".handover_{}.package", arm);
    let packed = crate::package::write(&w.roster, &w.parameters, &images[0], &images[1], &package).await;
    let verdict = match &packed {
        Ok(_) => Some(crate::package::check(&w.roster, &w.parameters, &package)),
        Err(_) => None,
    };
    let json = |result: &Result<String, String>| match result {
        Ok(text) => serde_json::from_str(text).unwrap(),
        Err(e) => serde_json::json!({ "error": e }),
    };
    let role = |key: &serde_json::Value| {
        let i = w.names.iter().position(|name| Some(name.encode_base64().as_str()) == key.as_str());
        i.map_or("?", |i| NAMES[i])
    };
    let culprits: Vec<&str> = report["culprits"].as_array().map_or(Vec::new(), |keys| keys.iter().map(role).collect());
    let table = |k: usize| {
        let stakes: serde_json::Map<String, serde_json::Value> =
            (0..5).map(|i| (NAMES[i].to_string(), w.tables[k].stake(&w.names[i]).into())).collect();
        serde_json::Value::Object(stakes)
    };
    let shares = |members: &[usize]| {
        let members: Vec<PublicKey> = members.iter().map(|i| w.names[*i]).collect();
        serde_json::json!({ "second": share(&w.tables[1], &members), "third": share(&w.tables[2], &members) })
    };
    let out = serde_json::json!({
        "arm": arm,
        "h5": !no_h5,
        "weights": weights.to_vec(),
        "first_epoch": w.first.to_string(),
        "tables": { "second": table(1), "third": table(2) },
        "shares": {
            "Z": shares(&[Z]),
            "tc_signers_AS_AH_Z": shares(&[AS, AH, Z]),
            "voters_of_N1_R1_R2_Z": shares(&[R1, R2, Z]),
            "voters_of_N_prime_AH_R2_Z": shares(&[AH, R2, Z]),
        },
        "steps": w.steps,
        "tc_refused": refused,
        "second_branch_committed": second_branch,
        "ledger": { "R1": ledger_r1, "AH": ledger_ah },
        "forensics": report,
        "culprits": culprits,
        "package": json(&packed),
        "verify": verdict.as_ref().map(json),
    });
    println!("{}", serde_json::to_string_pretty(&out).unwrap());
    if let Ok(directory) = std::env::var("HANDOVER_OUT") {
        fs::create_dir_all(&directory).unwrap();
        fs::write(format!("{}/{}.json", directory, arm), serde_json::to_string_pretty(&out).unwrap()).unwrap();
    }
    out
}

/// The weights of the first two arms: AS 10, AH 29, R1 29, R2 3, Z 29. In the second table AS, AH and Z hold 68%, a
/// quorum; in the third, where AS is suspended, AH and Z hold 64.4%, R1, R2 and Z 67.8%, AH, R2 and Z 67.8%, and Z
/// alone 32.2%.
const BELOW_A_THIRD: [Stake; 5] = [10, 29, 29, 3, 29];

#[tokio::test]
async fn handover_fork_without_h5() {
    // H5 off: certificates past the end of an epoch count under the table of that epoch alone. The TC of round 23
    // of the second epoch lets N' leave N1 and N2 aside, and R2, which voted for those, votes for N' by the voting
    // rule. Two blocks of the third epoch are committed. The only member that signed what it could not sign is Z:
    // E4, a vote in the third epoch and a timeout of the second at the same round. Z holds less than a third.
    let out = run("off", BELOW_A_THIRD, true, 19_300).await;
    let report = &out["forensics"];
    assert_eq!(report["fork"], true, "{}", report);
    assert_eq!((report["x_round"].as_u64(), report["y_round"].as_u64()), (Some(22), Some(24)));
    assert_eq!(report["case"], "C3");
    assert_eq!((report["e1"].as_u64(), report["e2"].as_u64(), report["e3"].as_u64(), report["e4"].as_u64()), (Some(0), Some(0), Some(0), Some(1)));
    assert_eq!(out["culprits"], serde_json::json!(["Z"]));
    assert!(report["share"].as_f64().unwrap() < 1.0 / 3.0);
    assert_eq!(out["verify"]["accountable"], false, "{}", out["verify"]);
}

#[tokio::test]
async fn handover_no_fork_with_h5() {
    // The same schedule with H5: AS, AH and Z hold a quorum of the second table and 64.4% of the third, so their
    // timeouts past the end of the second epoch make no TC, and AH stays at round 21. No second branch.
    let out = run("on", BELOW_A_THIRD, false, 19_310).await;
    assert_eq!(out["tc_refused"]["round"], 21, "{}", out["tc_refused"]);
    assert_eq!(out["tc_refused"]["requires_quorum"], true);
    assert_eq!(out["tc_refused"]["round_of_AH"], 21);
    assert_eq!(out["second_branch_committed"], false);
    assert_eq!(out["forensics"]["fork"], false, "{}", out["forensics"]);
}

#[tokio::test]
async fn handover_fork_with_h5_is_accountable() {
    // H5 on and Z at 45% of the base weight: AS 10, AH 20, R1 20, R2 5, Z 45. AH and Z hold 72.2% of the third
    // table, so the TCs of the second epoch count under H5, and the fork goes through. E4 holds against Z, which
    // has half of the third table: the package passes the verifier and the culprits are above a third.
    let out = run("half", [10, 20, 20, 5, 45], false, 19_320).await;
    let report = &out["forensics"];
    assert_eq!(report["fork"], true, "{}", report);
    assert_eq!(report["case"], "C3");
    assert_eq!(report["e4"].as_u64(), Some(1));
    assert_eq!(out["culprits"], serde_json::json!(["Z"]));
    assert!(report["share"].as_f64().unwrap() > 1.0 / 3.0);
    assert_eq!(out["verify"]["accountable"], true, "{}", out["verify"]);
}
