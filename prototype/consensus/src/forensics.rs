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

use crate::config::{Committee, EpochNumber, Parameters, Stake};
use crate::epoch::Epochs;
use crate::consensus::Round;
use crate::messages::{extends_validly, Block, Evidence, SignedTimeout, Timeout, Vote, QC, TC};
use crypto::{Digest, Hash as _, PublicKey};
use std::collections::{BTreeSet, HashSet};
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

/// `node forensics` (DESIGN.md §15.15): the stores of two stopped nodes, one of each side. The culprits' share is
/// taken in the weight table of the first epoch (the experiment runs a single epoch).
pub async fn report(committee: &Committee, parameters: &Parameters, a: &str, b: &str) -> Result<String, String> {
    let table = Epochs::new(committee, crate::consensus::epoch_config(parameters)).current().clone();
    let (ra, rb) = (read_records(a).await?, read_records(b).await?);
    let top = |r: &Records| r.chain.last().map_or(0, |b| b.round);
    let mut out = serde_json::json!({
        "a_top": top(&ra), "b_top": top(&rb),
        "a_commits": ra.commit_proofs().len(), "b_commits": rb.commit_proofs().len(),
        "fork": false,
    });
    if let Some((cx, cy)) = first_conflict(&ra, &rb) {
        let x_from_a = ra.digests().contains(&cx.x.digest());
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
    Ok(out.to_string())
}
