//! Offline forensics of a fork (DESIGN.md §15.15): theorem 3 of the paper on real chain records. Given the commit
//! proof of a block X on one side and the records of ONE honest node of the other side, which committed a
//! conflicting block Y, build the G1 evidence the theorem promises and check every piece of it with
//! `Evidence::verify`. The case analysis is the one of `formal/mc_jolteon.py` (`Model::judge`):
//!   A   view(Y) = view(X):        QC(X) and QC(Y) are two QCs of one view          -> E1;
//!   B   view(Y) = view(X) + 1:    QC(X+) and QC(Y)                                 -> E1;
//!   otherwise let Z be the ancestor of Y (or Y) of smallest view above view(X) + 1, P its parent, j = view(P):
//!   C1  j = view(X) + 1:          QC(X+) and QC(P)                                 -> E1;
//!   C2  j = view(X):              QC(X) and QC(P)                                  -> E1;
//!   C3  j < view(X):              Z embeds TC(view(Z) - 1) whose signers reported high QCs <= j < view(X),
//!                                 though those in QC(X+) had voted for X+, which certifies view(X)       -> E3.
//! Before the cases, the blocks of Y's branch above view(X) + 1 are checked against the voting rule: the signers of
//! the QC of the first block that breaks it have E2 (the theorem's first step; honest code never certifies one).
//! Only the TC embedded in Z ties C3 to the records: a node keeps no other TC (DESIGN.md §15.15, S3). Where the TC
//! is not part of the block (`tc_outside_block`), stored blocks lack it and look invalid, so the E2 step is skipped.
//!
//! Across epochs (theorem 5 of the paper, DESIGN.md §15.24): the two ledgers are replayed through the same `Epochs` as
//! the nodes (H4 included) to get each side's weight tables; the fork is judged in the first epoch e* in which both
//! sides committed off the other's chain, by the table W_{e*}, which both sides share (H1': it depends on the ledger
//! up to G_{e*-2} only). An E2 sweep also judges the other side's blocks after the fork by the judge's own tables (as a
//! judge that ignored H2/E2's table rule would) and by the table each block names (the protocol).

use crate::config::{Committee, EpochNumber, Parameters, Stake};
use crate::epoch::EpochConfig;
use crate::epoch::Epochs;
use crate::consensus::Round;
use crate::messages::{extends_validly, table_digest, Block, Evidence, SignedTimeout, Timeout, Vote, QC, TC};
use crypto::{Digest, Hash as _, PublicKey};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use store::Store;

#[cfg(test)]
#[path = "tests/forensics_tests.rs"]
pub mod forensics_tests;

/// What one node holds: its chain from the genesis (excluded) up to the block its highest QC certifies, and that QC.
/// Consecutive blocks are parent and child.
pub struct Records {
    pub chain: Vec<Block>,
    pub high_qc: QC,
}

/// A direct commit: X, its child X+ of the next view, and QC(X+). QC(X) is the QC inside X+.
#[derive(Clone)]
pub struct CommitProof {
    pub x: Block,
    pub x_plus: Block,
    pub qc_x_plus: QC,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Case {
    /// A block of Y's branch breaks the voting rule (E2).
    Invalid,
    A,
    B,
    C1,
    C2,
    C3,
}

pub struct Finding {
    pub case: Case,
    pub x_round: Round,
    pub y_round: Round,
    /// C1-C3: the view of Z.
    pub z_round: Option<Round>,
    /// Verified evidence only.
    pub evidence: Vec<Evidence>,
    pub culprits: BTreeSet<PublicKey>,
    /// Why the records do not give the evidence the case needs (S3: the TC is not in Z).
    pub missing: Option<String>,
}

impl Records {
    /// The QC certifying chain[i]: the next block's QC, or the highest QC for the last block.
    fn qc_of(&self, i: usize) -> Option<&QC> {
        let digest = self.chain[i].digest();
        let qc = self.chain.get(i + 1).map_or(&self.high_qc, |child| &child.qc);
        (qc.hash == digest).then_some(qc)
    }

    /// Every direct commit in the records, by ascending view.
    pub fn commit_proofs(&self) -> Vec<CommitProof> {
        (0..self.chain.len().saturating_sub(1))
            .filter(|&i| self.chain[i].round + 1 == self.chain[i + 1].round)
            .filter_map(|i| {
                self.qc_of(i + 1).map(|qc| CommitProof {
                    x: self.chain[i].clone(),
                    x_plus: self.chain[i + 1].clone(),
                    qc_x_plus: qc.clone(),
                })
            })
            .collect()
    }

    fn digests(&self) -> HashSet<Digest> {
        self.chain.iter().map(|b| b.digest()).collect()
    }
}

/// The first direct commits of `a` and of `b` off the other's chain, the one of the smaller view first; None if no
/// commit of either conflicts with the other chain.
pub fn first_conflict(a: &Records, b: &Records) -> Option<(CommitProof, CommitProof)> {
    let (da, db) = (a.digests(), b.digests());
    let x = a.commit_proofs().into_iter().find(|p| !db.contains(&p.x.digest()))?;
    let y = b.commit_proofs().into_iter().find(|p| !da.contains(&p.x.digest()))?;
    Some(if x.x.round <= y.x.round { (x, y) } else { (y, x) })
}

/// Theorem 5: the first epoch in which each side committed a block off the other's chain, with those first direct
/// commits (the one of the smaller view first). Within it both sides judge by the same table.
pub fn conflict_by_epoch(a: &Records, b: &Records) -> Option<(EpochNumber, CommitProof, CommitProof)> {
    let (da, db) = (a.digests(), b.digests());
    let off = |records: &Records, other: &HashSet<Digest>| {
        let mut first = BTreeMap::new();
        for proof in records.commit_proofs() {
            if !other.contains(&proof.x.digest()) {
                first.entry(proof.x.epoch).or_insert(proof);
            }
        }
        first
    };
    let (oa, ob) = (off(a, &db), off(b, &da));
    let epoch = *oa.keys().find(|e| ob.contains_key(e))?;
    let (x, y) = (oa[&epoch].clone(), ob[&epoch].clone());
    let (x, y) = if x.x.round <= y.x.round { (x, y) } else { (y, x) };
    Some((epoch, x, y))
}

/// The weight tables of every epoch a node's ledger reached, replayed from its records: the blocks up to its last
/// direct commit, in chain order, through the same `Epochs` as the node (H4: blocks after a terminal block skipped).
pub fn replay_tables(records: &Records, roster: &Committee, config: EpochConfig) -> BTreeMap<EpochNumber, Committee> {
    fn keep(epochs: &Epochs, tables: &mut BTreeMap<EpochNumber, Committee>) {
        for table in epochs.tables() {
            tables.entry(table.epoch).or_insert_with(|| table.clone());
        }
    }
    let mut epochs = Epochs::new(roster, config);
    let mut tables = BTreeMap::new();
    keep(&epochs, &mut tables);
    let last = match records.commit_proofs().last() {
        Some(proof) => proof.x.round,
        None => return tables,
    };
    for block in records.chain.iter().take_while(|b| b.round <= last) {
        if epochs.after_terminal(block) {
            continue;
        }
        epochs.record(block);
        if epochs.is_terminal(block) {
            epochs.enter_next(block);
            keep(&epochs, &mut tables);
        }
    }
    tables
}

/// The terminal blocks of a node's records as its ledger saw them: (epoch, round).
pub fn terminals(records: &Records, roster: &Committee, config: EpochConfig) -> Vec<(EpochNumber, Round)> {
    let mut epochs = Epochs::new(roster, config);
    let mut found = Vec::new();
    let last = records.commit_proofs().last().map_or(0, |proof| proof.x.round);
    for block in records.chain.iter().take_while(|b| b.round <= last) {
        if epochs.after_terminal(block) {
            continue;
        }
        if epochs.is_terminal(block) {
            found.push((block.epoch, block.round));
            epochs.enter_next(block);
        }
    }
    found
}

/// What an E2 judge holding `judge`'s records and tables makes of the blocks of `other`'s records off its own chain
/// that carry a TC of their own epoch and are certified in those records.
#[derive(Default)]
pub struct Sweep {
    pub blocks: usize,
    /// Blocks naming a table other than the judge's own for their epoch (the tables diverged).
    pub other_table: usize,
    /// Judged by the judge's own table of the block's epoch: blocks found invalid and the voters blamed.
    pub own_blocks: usize,
    pub own_voters: BTreeSet<PublicKey>,
    /// Judged by the table the block names (the protocol): found invalid, voters blamed, and blocks left unjudged
    /// because the judge does not hold that table.
    pub named_blocks: usize,
    pub named_voters: BTreeSet<PublicKey>,
    pub unjudged: usize,
}

pub fn e2_sweep(judge: &Records, tables: &BTreeMap<EpochNumber, Committee>, other: &Records) -> Sweep {
    let own_chain = judge.digests();
    let by_digest: HashMap<Digest, &Committee> = tables.values().map(|t| (table_digest(t), t)).collect();
    let mut sweep = Sweep::default();
    for (i, block) in other.chain.iter().enumerate() {
        if own_chain.contains(&block.digest()) {
            continue;
        }
        let tc_of_epoch = block.tc.as_ref().map_or(false, |tc| tc.epoch == block.epoch);
        let qc = match other.qc_of(i) {
            Some(qc) if tc_of_epoch => qc,
            _ => continue,
        };
        let tc = block.tc.as_ref().unwrap();
        let signers = qc.votes.iter().map(|(name, _)| *name);
        sweep.blocks += 1;
        let own = tables.get(&block.epoch);
        if own.map_or(false, |t| table_digest(t) != block.table) {
            sweep.other_table += 1;
        }
        if own.map_or(false, |t| tc.verify(t).is_err()) {
            sweep.own_blocks += 1;
            sweep.own_voters.extend(signers.clone());
        }
        match by_digest.get(&block.table) {
            None => sweep.unjudged += 1,
            Some(_) if qc.votes.is_empty() => (),
            Some(table) => {
                let (name, signature) = &qc.votes[0];
                let first = vote(&qc.hash, qc.round, qc.epoch, *name, signature);
                if Evidence::InvalidBlock(first, block.header()).holds_under(Some(table)) {
                    sweep.named_blocks += 1;
                    sweep.named_voters.extend(signers);
                }
            }
        }
    }
    sweep
}

/// What H2 does with the other side's blocks (DESIGN.md §15.26): the blocks of `other`'s records off the judge's chain
/// in an epoch the judge entered (its ledger has the terminal block of the epoch before). The table check stops those
/// that name a table other than the judge's for their epoch; of the rest, those without the judge's terminal block as
/// an ancestor -- they extend the other side's -- are kept out by H2 alone.
#[derive(Default)]
pub struct H2Sweep {
    pub blocks: usize,
    pub same_table: usize,
    pub off_terminal: usize,
    /// The lowest and highest epoch of the blocks only H2 keeps out.
    pub epochs: Option<(EpochNumber, EpochNumber)>,
}

pub fn h2_sweep(
    judge: &Records,
    roster: &Committee,
    config: EpochConfig,
    tables: &BTreeMap<EpochNumber, Committee>,
    other: &Records,
) -> H2Sweep {
    let own_chain = judge.digests();
    let at_round: HashMap<Round, Digest> = judge.chain.iter().map(|b| (b.round, b.digest())).collect();
    let terminal: HashMap<EpochNumber, Digest> = terminals(judge, roster, config)
        .into_iter()
        .filter_map(|(epoch, round)| at_round.get(&round).map(|digest| (epoch, digest.clone())))
        .collect();
    let mut sweep = H2Sweep::default();
    // The records are one chain from the genesis: the blocks before a block are its ancestors.
    let mut ancestors = HashSet::new();
    for block in &other.chain {
        let digest = block.digest();
        let entered = block.epoch.checked_sub(1).and_then(|before| terminal.get(&before));
        if let (Some(g), false) = (entered, own_chain.contains(&digest)) {
            sweep.blocks += 1;
            if tables.get(&block.epoch).map_or(false, |t| table_digest(t) == block.table) {
                sweep.same_table += 1;
                if !ancestors.contains(g) {
                    sweep.off_terminal += 1;
                    sweep.epochs = Some(match sweep.epochs {
                        None => (block.epoch, block.epoch),
                        Some((lo, hi)) => (lo.min(block.epoch), hi.max(block.epoch)),
                    });
                }
            }
        }
        ancestors.insert(digest);
    }
    sweep
}

/// The accountability theorem for the commit proofs `cx` and `cy` (view(X) <= view(Y)); `y_records` are the records
/// of one honest node that holds Y (Y and its ancestors). `tc_in_block`: blocks carry their TC (the protocol).
pub fn judge(cx: &CommitProof, cy: &CommitProof, y_records: &Records, tc_in_block: bool) -> Finding {
    let u = cx.x.round;
    let y = &cy.x;
    let qc_x = &cx.x_plus.qc;
    let qc_x_plus = &cx.qc_x_plus;
    let qc_y = &cy.x_plus.qc;
    let mut finding = Finding {
        case: Case::A,
        x_round: u,
        y_round: y.round,
        z_round: None,
        evidence: Vec::new(),
        culprits: BTreeSet::new(),
        missing: None,
    };
    let y_index = y_records.chain.iter().position(|b| b.digest() == y.digest());
    if let (true, Some(end)) = (tc_in_block, y_index) {
        let invalid = (0..=end).find(|&i| {
            let b = &y_records.chain[i];
            b.round > u + 1 && !extends_validly(b.round, b.qc.round, b.tc.as_ref())
        });
        if let Some(i) = invalid {
            finding.case = Case::Invalid;
            finding.z_round = Some(y_records.chain[i].round);
            finding.evidence = match y_records.qc_of(i) {
                Some(qc) => invalid_votes(&y_records.chain[i], qc),
                None => Vec::new(),
            };
            finding.culprits = finding.evidence.iter().map(culprit).collect();
            return finding;
        }
    }
    if y.round == u {
        finding.evidence = double_votes(qc_x, qc_y);
    } else if y.round == u + 1 {
        finding.case = Case::B;
        finding.evidence = double_votes(qc_x_plus, qc_y);
    } else {
        let digest = y.digest();
        let mut z = match y_records.chain.iter().position(|b| b.digest() == digest) {
            Some(i) => i,
            None => {
                finding.case = Case::C3;
                finding.missing = Some("Y is not in the records".to_string());
                return finding;
            }
        };
        while y_records.chain[z].qc.round > u + 1 {
            z -= 1;
        }
        let block = &y_records.chain[z];
        finding.z_round = Some(block.round);
        let j = block.qc.round;
        if j == u + 1 {
            finding.case = Case::C1;
            finding.evidence = double_votes(qc_x_plus, &block.qc);
        } else if j == u {
            finding.case = Case::C2;
            finding.evidence = double_votes(qc_x, &block.qc);
        } else {
            finding.case = Case::C3;
            match &block.tc {
                Some(tc) if tc.round + 1 == block.round => finding.evidence = regressions(cx, tc),
                _ => {
                    finding.missing = Some(format!(
                        "B{} extends B{} without TC({}) in the records",
                        block.round,
                        j,
                        block.round - 1
                    ))
                }
            }
        }
    }
    finding.culprits = finding.evidence.iter().map(|e| culprit(e)).collect();
    finding
}

fn culprit(evidence: &Evidence) -> PublicKey {
    match evidence {
        Evidence::DoubleVote(vote, _)
        | Evidence::InvalidBlock(vote, _)
        | Evidence::Regression(vote, _, _)
        | Evidence::NrContradiction(vote, _) => vote.author,
    }
}

fn vote(hash: &Digest, round: Round, epoch: EpochNumber, author: PublicKey, signature: &crypto::Signature) -> Vote {
    Vote { hash: hash.clone(), round, epoch, author, signature: signature.clone() }
}

/// E1 for every signer of both QCs, which certify different blocks of one view (verified).
fn double_votes(a: &QC, b: &QC) -> Vec<Evidence> {
    if a.round != b.round || a.epoch != b.epoch || a.hash == b.hash {
        return Vec::new();
    }
    a.votes
        .iter()
        .filter_map(|(name, sa)| {
            let (_, sb) = b.votes.iter().find(|(other, _)| other == name)?;
            let evidence = Evidence::DoubleVote(
                vote(&a.hash, a.round, a.epoch, *name, sa),
                vote(&b.hash, b.round, b.epoch, *name, sb),
            );
            evidence.verify().ok().map(|_| evidence)
        })
        .collect()
}

/// E2 for every signer of `qc`, which certifies `block`, a block that breaks the voting rule (verified).
fn invalid_votes(block: &Block, qc: &QC) -> Vec<Evidence> {
    qc.votes
        .iter()
        .filter_map(|(name, signature)| {
            let evidence = Evidence::InvalidBlock(vote(&qc.hash, qc.round, qc.epoch, *name, signature), block.header());
            evidence.verify().ok().map(|_| evidence)
        })
        .collect()
}

/// E3 for every signer of QC(X+) that also signed `tc` (verified): its vote for X+, which certifies view(X), and its
/// timeout of a later view reporting a lower high QC.
fn regressions(cx: &CommitProof, tc: &TC) -> Vec<Evidence> {
    let block = &cx.x_plus;
    let hash = block.digest();
    cx.qc_x_plus
        .votes
        .iter()
        .filter_map(|(name, signature)| {
            let (_, ts, high_qc_round, nr) = tc.votes.iter().find(|(other, ..)| other == name)?;
            let timeout = SignedTimeout {
                author: *name,
                signature: ts.clone(),
                epoch: tc.epoch,
                round: tc.round,
                high_qc_round: *high_qc_round,
                nr: *nr,
            };
            let evidence = Evidence::Regression(
                vote(&hash, block.round, block.epoch, *name, signature),
                block.header(),
                timeout,
            );
            evidence.verify().ok().map(|_| evidence)
        })
        .collect()
}

/// The voting-power share of `culprits` in `table` (the weight table of the epoch: stakes are weights).
pub fn share(culprits: &BTreeSet<PublicKey>, table: &Committee) -> f64 {
    let total: Stake = table.authorities.values().map(|a| a.stake).sum();
    let held: Stake = culprits.iter().map(|name| table.stake(name)).sum();
    held as f64 / total.max(1) as f64
}

/// The records of the node whose store is at `path` (the node must have stopped): its chain from the highest QC it
/// remembered (R8) back to the genesis.
pub async fn read_records(path: &str) -> Result<Records, String> {
    let mut store = Store::new(path).map_err(|e| format!("{}: {}", path, e))?;
    let bytes = store
        .read(crate::core::SAFETY_STATE.to_vec())
        .await
        .map_err(|e| e.to_string())?
        .ok_or_else(|| format!("{}: no safety state", path))?;
    let (_, high_qc, _): (Round, QC, Option<Timeout>) = bincode::deserialize(&bytes).map_err(|e| e.to_string())?;
    let mut chain = Vec::new();
    let mut digest = high_qc.hash.clone();
    let genesis = QC::genesis().hash;
    while digest != genesis {
        let bytes = store
            .read(digest.to_vec())
            .await
            .map_err(|e| e.to_string())?
            .ok_or_else(|| format!("{}: missing block {}", path, digest))?;
        let block: Block = bincode::deserialize(&bytes).map_err(|e| e.to_string())?;
        digest = block.qc.hash.clone();
        chain.push(block);
    }
    chain.reverse();
    Ok(Records { chain, high_qc })
}

/// `node forensics` (DESIGN.md §15.15, §15.24): the stores of two stopped nodes, one of each side. The fork is judged
/// in the first epoch e* in which both sides committed off the other's chain, and the culprits' share taken in W_{e*}.
pub async fn report(committee: &Committee, parameters: &Parameters, a: &str, b: &str) -> Result<String, String> {
    let config = crate::consensus::epoch_config(parameters);
    let (ra, rb) = (read_records(a).await?, read_records(b).await?);
    let (tables_a, tables_b) = (replay_tables(&ra, committee, config), replay_tables(&rb, committee, config));
    let sweep_json = |s: Sweep| {
        serde_json::json!({
            "blocks": s.blocks, "other_table": s.other_table,
            "own_blocks": s.own_blocks,
            "own_voters": s.own_voters.iter().map(|k| k.encode_base64()).collect::<Vec<_>>(),
            "named_blocks": s.named_blocks,
            "named_voters": s.named_voters.iter().map(|k| k.encode_base64()).collect::<Vec<_>>(),
            "unjudged": s.unjudged,
        })
    };
    let h2_json = |s: H2Sweep| {
        serde_json::json!({
            "blocks": s.blocks, "same_table": s.same_table, "off_terminal": s.off_terminal, "epochs": s.epochs,
        })
    };
    let epochs_json = serde_json::json!({
        "terminals_a": terminals(&ra, committee, config),
        "terminals_b": terminals(&rb, committee, config),
        "e2_a_judges_b": sweep_json(e2_sweep(&ra, &tables_a, &rb)),
        "e2_b_judges_a": sweep_json(e2_sweep(&rb, &tables_b, &ra)),
        "h2_a_judges_b": h2_json(h2_sweep(&ra, committee, config, &tables_a, &rb)),
        "h2_b_judges_a": h2_json(h2_sweep(&rb, committee, config, &tables_b, &ra)),
    });
    let top = |r: &Records| r.chain.last().map_or(0, |b| b.round);
    let mut out = serde_json::json!({
        "a_top": top(&ra), "b_top": top(&rb),
        "a_commits": ra.commit_proofs().len(), "b_commits": rb.commit_proofs().len(),
        "fork": false,
    });
    let conflict = conflict_by_epoch(&ra, &rb).or_else(|| first_conflict(&ra, &rb).map(|(x, y)| (x.x.epoch, x, y)));
    if let Some((e_star, cx, cy)) = conflict {
        let x_from_a = ra.digests().contains(&cx.x.digest());
        let first = Epochs::new(committee, config).current().clone();
        let table = tables_a.get(&e_star).cloned().unwrap_or(first);
        let tables_agree = match (tables_a.get(&e_star), tables_b.get(&e_star)) {
            (Some(ta), Some(tb)) => Some(table_digest(ta) == table_digest(tb)),
            _ => None,
        };
        let finding = judge(&cx, &cy, if x_from_a { &rb } else { &ra }, !parameters.tc_outside_block);
        let count = |e1: bool| {
            finding.evidence.iter().filter(|e| matches!(e, Evidence::DoubleVote(..)) == e1).count()
        };
        let licensed = finding
            .culprits
            .iter()
            .filter(|name| committee.authorities.get(name).map_or(false, |a| a.certified))
            .count();
        out = serde_json::json!({
            "a_top": top(&ra), "b_top": top(&rb),
            "a_commits": ra.commit_proofs().len(), "b_commits": rb.commit_proofs().len(),
            "fork": true,
            "x_side": if x_from_a { "a" } else { "b" },
            "x_round": finding.x_round, "y_round": finding.y_round, "z_round": finding.z_round,
            "x_epoch": cx.x.epoch, "y_epoch": cy.x.epoch, "e_star": e_star, "tables_agree": tables_agree,
            "case": format!("{:?}", finding.case),
            "e1": count(true),
            "e2": finding.evidence.iter().filter(|e| matches!(e, Evidence::InvalidBlock(..))).count(),
            "e3": finding.evidence.iter().filter(|e| matches!(e, Evidence::Regression(..))).count(),
            "culprits": finding.culprits.iter().map(|k| k.encode_base64()).collect::<Vec<_>>(),
            "share": share(&finding.culprits, &table),
            "licensed": licensed,
            "missing": finding.missing,
        });
    }
    out["epochs"] = epochs_json;
    Ok(out.to_string())
}
