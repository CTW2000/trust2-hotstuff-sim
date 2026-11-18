//! The evidence package of a fork and its stand-alone verifier (DESIGN.md §15.35; paper, third-party verification).
//!
//! After a safety violation the question of who is responsible goes to a third party that does not hold the chain:
//! a regulator, or a contract on another chain that holds the validators' collateral. `pack` puts what such a judge
//! needs into one self-contained message; `verify` checks it from the weight table of the first epoch and the epoch
//! length alone -- no ledger, no replay, no state of any node.
//!
//! A package for a fork located in epoch e* holds
//! * the table chain: for every epoch before e*, a certified block at or past the end of that epoch (its terminal
//!   block, or one after it) and the weight table of the next one. Such a block names the tables of its own and of
//!   the next epoch (`Block::table`, `Block::next_table`), so a QC under W_e certifies W_{e+1}; a block before the
//!   end of its epoch names no next table (DESIGN.md §15.43). The same for e* itself if the fork is at the end of
//!   it, where the commit proofs need W_{e*+1} too (H5);
//! * two commit proofs, each made of blocks of epoch e*: X, its child X+ at the next view, and the QCs of both;
//! * the headers of the ancestors of Y above the view of X, which show that X is not one of them;
//! * the evidence: for each culprit a piece of E1-E4, made of the culprit's own signatures.
//!
//! What the judge gets (S15): every culprit signed two messages that cannot both be signed, or voted for a block
//! that breaks the voting rule, whatever the Byzantine share; the culprits' share is taken in W_{e*}, which is the
//! table of the honest nodes if the Byzantine share of every earlier table is below 1/3; and any honest node that
//! holds one side of the fork and a commit proof of the other can build a package that is accepted.

use crate::config::{Committee, EpochNumber, Parameters, Stake};
use crate::consensus::Round;
use crate::epoch::{EpochConfig, Epochs};
use crate::forensics::{judge, read_records, replay_tables, witnesses, CommitProof, Finding, Records};
use crate::messages::{table_digest, Block, BlockHeader, Evidence, QC};
use crypto::{Digest, Hash as _, PublicKey};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::net::SocketAddr;

#[cfg(test)]
#[path = "tests/package_tests.rs"]
pub mod package_tests;

/// A weight table as a third party holds it: the epoch and every member's stake, in key order. This is all
/// `table_digest` covers.
#[derive(Clone, Serialize, Deserialize)]
pub struct Table {
    pub epoch: EpochNumber,
    pub stakes: Vec<(PublicKey, Stake)>,
}

impl Table {
    pub fn of(committee: &Committee) -> Self {
        let mut stakes: Vec<_> = committee.authorities.iter().map(|(name, a)| (*name, a.stake)).collect();
        stakes.sort_by_key(|(name, _)| *name);
        Self { epoch: committee.epoch, stakes }
    }

    /// The same table in the form the checks of `messages` read stakes from (the addresses are not used).
    pub fn committee(&self) -> Committee {
        let nowhere = SocketAddr::from(([0, 0, 0, 0], 0));
        Committee::new(self.stakes.iter().map(|(name, stake)| (*name, *stake, nowhere)).collect(), self.epoch)
    }
}

/// One link of the table chain: a certified block of an epoch and the weight table of the next epoch, whose digest
/// the block names.
#[derive(Clone, Serialize, Deserialize)]
pub struct Link {
    pub header: BlockHeader,
    pub qc: QC,
    pub next: Table,
}

/// A direct commit: X, its child X+ at the next view, and the QCs of both.
#[derive(Clone, Serialize, Deserialize)]
pub struct Commit {
    pub x: BlockHeader,
    pub qc_x: QC,
    pub x_plus: BlockHeader,
    pub qc_x_plus: QC,
}

#[derive(Clone, Serialize, Deserialize)]
pub struct Package {
    /// The table chain, from the first epoch to the epoch of the fork (and one more link if the fork is at its end).
    pub links: Vec<Link>,
    /// The two commit proofs, the one of the lower view first.
    pub x: Commit,
    pub y: Commit,
    /// The ancestors of Y of a view above that of X, the parent of Y first.
    pub branch: Vec<BlockHeader>,
    pub evidence: Vec<Evidence>,
}

/// What an accepted package establishes.
#[derive(Debug)]
pub struct Verdict {
    /// e*: the epoch of the two commit proofs, in whose table the culprits' share is taken.
    pub epoch: EpochNumber,
    pub x_round: Round,
    pub y_round: Round,
    pub culprits: BTreeSet<PublicKey>,
    /// The culprits' weight and the total weight in W_{e*}.
    pub weight: Stake,
    pub total: Stake,
}

impl Verdict {
    /// Whether the culprits hold more than 1/3 of W_{e*} (the theorem's bound).
    pub fn accountable(&self) -> bool {
        3 * self.weight as u128 > self.total as u128
    }
}

/// `qc` certifies the block of `header` under `table`, the table of its epoch that the block names; past the end of
/// the epoch (H5, by `BlockHeader::start` and the epoch length) also under `next`, the next table it names.
fn certified(
    header: &BlockHeader,
    qc: &QC,
    table: &Committee,
    next: Option<&Committee>,
    length: Round,
) -> Result<(), String> {
    if qc.hash != header.digest() || qc.round != header.round || qc.epoch != header.epoch {
        return Err(format!("the QC does not certify the block of round {}", header.round));
    }
    if header.table != table_digest(table) {
        return Err(format!("the block of round {} names another table of epoch {}", header.round, header.epoch));
    }
    qc.verify(table).map_err(|e| format!("the QC of round {}: {}", qc.round, e))?;
    if length > 0 && header.round >= header.start.saturating_add(length) {
        let next = next.ok_or_else(|| format!("the QC of round {} is past the end of its epoch: no next table", qc.round))?;
        if header.next_table != table_digest(next) {
            return Err(format!("the block of round {} names another table of epoch {}", header.round, next.epoch));
        }
        if !qc.has_quorum_in(next) {
            return Err(format!("the QC of round {} is past the end of its epoch and holds no quorum of the next table", qc.round));
        }
    }
    Ok(())
}

impl Commit {
    fn of(proof: &CommitProof) -> Self {
        Self {
            x: proof.x.header(),
            qc_x: proof.x_plus.qc.clone(),
            x_plus: proof.x_plus.header(),
            qc_x_plus: proof.qc_x_plus.clone(),
        }
    }

    fn check(&self, epoch: EpochNumber, table: &Committee, next: Option<&Committee>, length: Round) -> Result<(), String> {
        if self.x.epoch != epoch || self.x_plus.epoch != epoch {
            return Err(format!("the commit proof of round {} is not made of blocks of epoch {}", self.x.round, epoch));
        }
        let child = self.x_plus.qc_hash == self.x.digest() && self.x_plus.qc_round == self.x.round;
        if !child || self.x.round.checked_add(1) != Some(self.x_plus.round) {
            return Err(format!("no direct commit of round {}: X+ is not its child at the next view", self.x.round));
        }
        certified(&self.x, &self.qc_x, table, next, length)?;
        certified(&self.x_plus, &self.qc_x_plus, table, next, length)
    }
}

/// X and Y conflict: neither is an ancestor of the other. `branch` gives the ancestors of Y above the view of X.
fn conflicting(x: &BlockHeader, y: &BlockHeader, branch: &[BlockHeader]) -> Result<(), String> {
    if x.round > y.round {
        return Err("the commit proof of the lower view must come first".to_string());
    }
    let target = x.digest();
    if y.digest() == target {
        return Err("the two commit proofs are of the same block".to_string());
    }
    // Walk down the ancestors of Y while they are above the view of X. Views fall along the way; the chain either
    // reaches the view of X at another block or passes below it, and then X is not on it.
    let mut child = y;
    let mut rest = branch.iter();
    while child.round > x.round {
        if child.qc_round >= child.round {
            return Err(format!("the block of round {} does not extend an earlier round", child.round));
        }
        if child.qc_round < x.round {
            return Ok(());
        }
        if child.qc_round == x.round {
            return if child.qc_hash == target { Err("X is an ancestor of Y".to_string()) } else { Ok(()) };
        }
        let parent = rest.next().ok_or_else(|| format!("the branch of Y stops at round {}, above X", child.round))?;
        if parent.digest() != child.qc_hash || parent.round != child.qc_round {
            return Err(format!("the branch of Y is not a chain at round {}", child.round));
        }
        child = parent;
    }
    Ok(())
}

/// Check a package against `first`, the weight table of the first epoch, and the epoch length (0: a single epoch).
/// Nothing else is used. An accepted package gives the culprits, each with verified evidence, and their weight in
/// the table of the fork's epoch; whether that is above 1/3 is `Verdict::accountable`.
pub fn verify(package: &Package, first: &Table, length: Round) -> Result<Verdict, String> {
    // The table chain: W_e certifies W_{e+1}.
    let mut tables = vec![first.committee()];
    for link in &package.links {
        let current = tables.last().expect("the first table");
        let next = link.next.committee();
        if link.header.epoch != current.epoch || next.epoch != current.epoch + 1 {
            return Err(format!("the table chain does not go from epoch {} to the next", current.epoch));
        }
        if length == 0 || link.header.round < link.header.start.saturating_add(length) {
            return Err(format!("table chain, epoch {}: the block is before the end of its epoch and names no next table", current.epoch));
        }
        if link.header.next_table != table_digest(&next) {
            return Err(format!("the table given for epoch {} is not the one the certified block names", next.epoch));
        }
        certified(&link.header, &link.qc, current, Some(&next), length)
            .map_err(|e| format!("table chain, epoch {}: {}", current.epoch, e))?;
        tables.push(next);
    }
    let digests: Vec<Digest> = tables.iter().map(table_digest).collect();

    // The two commit proofs, in the table of their epoch.
    let epoch = package.x.x.epoch;
    let table = tables
        .iter()
        .find(|t| t.epoch == epoch)
        .ok_or_else(|| format!("the table chain does not reach epoch {}", epoch))?;
    let next = tables.iter().find(|t| t.epoch == epoch + 1);
    package.x.check(epoch, table, next, length)?;
    package.y.check(epoch, table, next, length)?;
    conflicting(&package.x.x, &package.y.x, &package.branch)?;

    // The evidence: the culprits' own signatures; E2 by the tables its block names, if they are on the chain.
    let by_digest = |digest: &Digest| digests.iter().position(|d| d == digest).map(|i| &tables[i]);
    let mut culprits = BTreeSet::new();
    for evidence in &package.evidence {
        evidence
            .verify_with(by_digest, length)
            .map_err(|e| format!("the evidence against {} does not hold: {}", evidence.culprit(), e))?;
        culprits.insert(evidence.culprit());
    }
    Ok(Verdict {
        epoch,
        x_round: package.x.x.round,
        y_round: package.y.x.round,
        weight: culprits.iter().map(|name| table.stake(name)).sum(),
        total: table.authorities.values().map(|a| a.stake).sum(),
        culprits,
    })
}

/// Build the package of the fork between the records of two nodes, one of each side. The tables come from the
/// ledger of the side that holds Y, replayed as the node does; the evidence from the theorem's case analysis.
pub fn pack(
    a: &Records,
    b: &Records,
    roster: &Committee,
    config: EpochConfig,
    tc_in_block: bool,
) -> Result<(Package, Finding), String> {
    let (epoch, cx, cy) =
        witnesses(a, b).ok_or("no two conflicting direct commits made of blocks of one epoch")?;
    let y_side = if a.digests().contains(&cx.x.digest()) { b } else { a };
    let finding = judge(&cx, &cy, y_side, tc_in_block);

    let length = config.length;
    let tables = replay_tables(y_side, roster, config);
    // W_{e+1} is named by the blocks of epoch e at or past its end: the terminal block and the ones after it.
    let past_end = |block: &Block| length > 0 && block.round >= block.start.saturating_add(length);
    let mut links = Vec::new();
    for e in roster.epoch..=epoch {
        // The first certified block of the epoch on the chain that is past its end: the terminal block, as a rule.
        let mut link = y_side
            .chain
            .iter()
            .enumerate()
            .filter(|(_, block)| block.epoch == e && past_end(block))
            .find_map(|(i, block)| y_side.qc_of(i).map(|qc| (block.header(), qc.clone())));
        if link.is_none() && e == epoch {
            // In the epoch of the fork, a block of one of the commit proofs may be the only one past the end.
            link = [(&cx.x, &cx.x_plus.qc), (&cx.x_plus, &cx.qc_x_plus), (&cy.x, &cy.x_plus.qc), (&cy.x_plus, &cy.qc_x_plus)]
                .iter()
                .find(|(block, _)| past_end(block))
                .map(|(block, qc)| (block.header(), (*qc).clone()));
        }
        match link {
            Some((header, qc)) => {
                let next =
                    tables.get(&(e + 1)).ok_or_else(|| format!("the ledger does not give the table of epoch {}", e + 1))?;
                links.push(Link { header, qc, next: Table::of(next) });
            }
            // The fork is before the end of its epoch: nothing in the package needs the table after it.
            None if e == epoch => {}
            None => return Err(format!("no certified block at or past the end of epoch {} in the records", e)),
        }
    }

    let y = cy.x.digest();
    let at = y_side.chain.iter().position(|block| block.digest() == y).ok_or("Y is not in the records")?;
    let branch =
        y_side.chain[..at].iter().rev().take_while(|block| block.round > cx.x.round).map(|block| block.header()).collect();
    let package =
        Package { links, x: Commit::of(&cx), y: Commit::of(&cy), branch, evidence: finding.evidence.clone() };
    Ok((package, finding))
}

/// The weight table of the first epoch, which the configuration fixes: what a verifier starts from.
pub fn first_table(roster: &Committee, config: EpochConfig) -> Table {
    Table::of(Epochs::new(roster, config).current())
}

/// `node package`: the stores of two stopped nodes, one of each side; writes the package to `out`.
pub async fn write(committee: &Committee, parameters: &Parameters, a: &str, b: &str, out: &str) -> Result<String, String> {
    let config = crate::consensus::epoch_config(parameters);
    let (ra, rb) = (read_records(a).await?, read_records(b).await?);
    let (package, finding) = pack(&ra, &rb, committee, config, !parameters.tc_outside_block)?;
    let bytes = bincode::serialize(&package).map_err(|e| e.to_string())?;
    std::fs::write(out, &bytes).map_err(|e| format!("{}: {}", out, e))?;
    Ok(serde_json::json!({
        "bytes": bytes.len(),
        "links": package.links.len(),
        "branch": package.branch.len(),
        "evidence": package.evidence.len(),
        "case": format!("{:?}", finding.case),
        "missing": finding.missing,
    })
    .to_string())
}

/// `node verify`: a package file, checked from the configuration alone (the first table and the epoch length).
pub fn check(committee: &Committee, parameters: &Parameters, path: &str) -> Result<String, String> {
    let config = crate::consensus::epoch_config(parameters);
    let bytes = std::fs::read(path).map_err(|e| format!("{}: {}", path, e))?;
    let package: Package = bincode::deserialize(&bytes).map_err(|e| e.to_string())?;
    let verdict = verify(&package, &first_table(committee, config), config.length)?;
    Ok(serde_json::json!({
        "epoch": verdict.epoch,
        "x_round": verdict.x_round,
        "y_round": verdict.y_round,
        "culprits": verdict.culprits.iter().map(|k| k.encode_base64()).collect::<Vec<_>>(),
        "weight": verdict.weight,
        "total": verdict.total,
        "accountable": verdict.accountable(),
    })
    .to_string())
}
