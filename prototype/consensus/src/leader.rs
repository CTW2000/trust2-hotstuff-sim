use crate::config::{Committee, EpochNumber};
use crate::consensus::Round;
use crypto::PublicKey;
use ed25519_dalek::{Digest as _, Sha512};
use std::convert::TryInto as _;

/// Drawn in proportion to the weights in the given table, among the members that may lead (members suspended or
/// evicted in an epoch have no weight in its table; members excluded by the G2 leader rule still vote but do not
/// lead), as in the simulator (sim2/schedule.py `_draw`).
pub fn leader(committee: &Committee, round: Round) -> PublicKey {
    if let Some((first, leader)) = committee.handover {
        if round == first {
            return leader;
        }
    }
    let mut members: Vec<_> = committee
        .authorities
        .iter()
        .filter(|(_, a)| a.stake > 0 && a.leader)
        .map(|(name, a)| (*name, a.stake as u128))
        .collect();
    // If the leader rule has barred everyone (G1 suspensions plus G2 exclusions covering all of the weight),
    // fall back to the full membership so the round still gets a deterministic leader, rather than dividing by
    // zero and halting every node at once (and again on every replay of the same ledger).
    if members.is_empty() {
        members = committee.authorities.keys().map(|name| (*name, 1)).collect();
    }
    members.sort();
    let total: u128 = members.iter().map(|(_, stake)| stake).sum();
    // The draw as a fraction of the total: the same shares give the same leader, whatever their scale.
    let mut point = (draw(committee.epoch, round) as u128 * total) >> 64;
    for (name, stake) in &members {
        if point < *stake {
            return *name;
        }
        point -= stake;
    }
    unreachable!("the draw is below the total weight")
}

/// A uniform number fixed by the epoch and the round alone, not by the ledger: the schedule is public, as with
/// round robin, but no proposer can steer it through the contents of a block.
fn draw(epoch: EpochNumber, round: Round) -> u64 {
    let mut hasher = Sha512::new();
    hasher.update(epoch.to_le_bytes());
    hasher.update(round.to_le_bytes());
    u64::from_le_bytes(hasher.finalize()[..8].try_into().expect("a SHA-512 digest has 64 bytes"))
}

pub struct LeaderElector {
    committee: Committee,
}

impl LeaderElector {
    pub fn new(committee: Committee) -> Self {
        Self { committee }
    }

    pub fn get_leader(&self, round: Round) -> PublicKey {
        leader(&self.committee, round)
    }
}

#[cfg(test)]
mod leader_tests {
    use super::*;
    use crate::common::committee;
    use std::collections::HashSet;

    #[test]
    fn falls_back_when_all_members_are_barred() {
        // 6.1: if the leader rule bars every member (all weight suspended or excluded), leader() still returns
        // a deterministic member instead of dividing by zero and halting every node at once.
        let mut committee = committee();
        for authority in committee.authorities.values_mut() {
            authority.stake = 0;
        }
        let members: HashSet<_> = committee.authorities.keys().copied().collect();
        for round in [0u64, 1, 7, 42] {
            let chosen = leader(&committee, round);
            assert!(members.contains(&chosen));
            assert_eq!(chosen, leader(&committee, round)); // deterministic across nodes
        }
    }

    /// A committee with the given weights, in the order of their public keys.
    fn weighted(stakes: &[u32]) -> (Committee, Vec<PublicKey>) {
        let mut committee = committee();
        let mut names: Vec<_> = committee.authorities.keys().copied().collect();
        names.sort();
        for (name, stake) in names.iter().zip(stakes) {
            committee.authorities.get_mut(name).unwrap().stake = *stake;
        }
        (committee, names)
    }

    fn share(committee: &Committee, name: &PublicKey) -> f64 {
        let rounds = 20_000;
        (0..rounds).filter(|round| leader(committee, *round) == *name).count() as f64 / rounds as f64
    }

    #[test]
    fn members_lead_in_proportion_to_their_weight() {
        let (committee, names) = weighted(&[1, 2, 3, 4]);
        for (name, expected) in names.iter().zip([0.1, 0.2, 0.3, 0.4]) {
            let got = share(&committee, name);
            assert!((got - expected).abs() < 0.015, "{} instead of {}", got, expected);
        }
    }

    #[test]
    fn the_scale_of_the_weights_does_not_matter() {
        // A table holds T_tru shares in ppm, a configuration its own base weights.
        let (small, _) = weighted(&[1, 1, 1, 1]);
        let (large, _) = weighted(&[250_000, 250_000, 250_000, 250_000]);
        for round in 0..1_000 {
            assert_eq!(leader(&small, round), leader(&large, round));
        }
    }

    #[test]
    fn only_members_that_may_lead_are_drawn() {
        let (mut committee, names) = weighted(&[0, 1, 1, 1]);
        committee.authorities.get_mut(&names[1]).unwrap().leader = false;
        let (no_weight, barred) = (names[0], names[1]);
        for round in 0..2_000 {
            let chosen = leader(&committee, round);
            assert!(chosen != no_weight && chosen != barred);
        }
        assert!((share(&committee, &names[2]) - 0.5).abs() < 0.02);
    }

    #[test]
    fn each_epoch_has_its_own_schedule() {
        let (mut next, _) = weighted(&[1, 1, 1, 1]);
        let (this, _) = weighted(&[1, 1, 1, 1]);
        next.epoch += 1;
        let same = (0..1_000).filter(|round| leader(&this, *round) == leader(&next, *round)).count();
        assert!(same < 400, "{} of 1000 rounds have the same leader", same);
    }
}
