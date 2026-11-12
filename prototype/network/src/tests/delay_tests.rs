use super::*;

const JSON: &str = r#"{
    "addresses": {"127.0.0.1:9000": 0, "127.0.0.1:9001": 1, "127.0.0.1:9004": 1},
    "base_ms": [[0.0, 50.0], [50.0, 0.0]],
    "jitter_ms": 10.0,
    "bandwidth_mbps": 1000.0
}"#;

#[test]
fn delay_follows_the_table() {
    let delays = Delays::from_json(JSON, 0).unwrap();
    let to_1: SocketAddr = "127.0.0.1:9001".parse().unwrap();
    for _ in 0..100 {
        // 50 ms base, up to 10 ms jitter, 1,000,000 bytes at 1 Gbps = 8 ms.
        let d = delays.of(&to_1, 1_000_000).unwrap().as_secs_f64() * 1e3;
        assert!((58.0..68.0).contains(&d), "{}", d);
    }
    // Another port of the same node (its mempool, say) has the same delay; unknown addresses and ourselves none.
    assert!(delays.of(&"127.0.0.1:9004".parse().unwrap(), 0).is_some());
    assert!(delays.of(&"127.0.0.1:9000".parse().unwrap(), 0).is_none());
    assert!(delays.of(&"127.0.0.1:9999".parse().unwrap(), 0).is_none());
}

#[test]
fn late_messages_get_the_extra_delay() {
    // Only messages to the listed (consensus) addresses can be late.
    let json = JSON.replace(
        "\"bandwidth_mbps\": 1000.0",
        "\"bandwidth_mbps\": 1000.0, \"late_p\": 1.0, \"late_ms\": 5000.0, \"late_to\": [\"127.0.0.1:9001\"]",
    );
    let delays = Delays::from_json(&json, 0).unwrap();
    let d = delays.of(&"127.0.0.1:9001".parse().unwrap(), 0).unwrap().as_secs_f64() * 1e3;
    assert!((5050.0..5060.0).contains(&d), "{}", d);
    let d = delays.of(&"127.0.0.1:9004".parse().unwrap(), 0).unwrap().as_secs_f64() * 1e3;
    assert!(d < 60.0, "{}", d);
}

#[test]
fn queue_stays_in_due_order() {
    // Without a table (no environment) a message is due now; the queue keeps due order, first in first out on ties.
    let to: SocketAddr = "127.0.0.1:9001".parse().unwrap();
    assert!(due(&to, 10) <= Instant::now());
    let t = Instant::now();
    let mut queue: std::collections::VecDeque<(Instant, u8)> = std::collections::VecDeque::new();
    for (offset, tag) in [(30, 1), (10, 2), (30, 3), (20, 4)] {
        let at = t + Duration::from_millis(offset);
        let index = position(&queue, at, |(due, _)| *due);
        queue.insert(index, (at, tag));
    }
    assert_eq!(queue.iter().map(|(_, tag)| *tag).collect::<Vec<_>>(), vec![2, 4, 1, 3]);
}

#[test]
fn a_region_outage_holds_messages_across_the_cut_until_it_ends() {
    // Node 0 is in the region; between t = 1000 and 4000 ms a message to node 1 waits for the end of the outage.
    let json = JSON.replace(
        "\"bandwidth_mbps\": 1000.0",
        "\"bandwidth_mbps\": 1000.0, \"outage\": [0], \"outage_from_ms\": 1000, \"outage_until_ms\": 4000",
    );
    let inside = Delays::from_json(&json, 0).unwrap();
    assert_eq!(inside.held_ms(1, 999), 0.0);
    assert_eq!(inside.held_ms(1, 1000), 3000.0);
    assert_eq!(inside.held_ms(1, 3500), 500.0);
    assert_eq!(inside.held_ms(1, 4000), 0.0);
    // The other way round as well; within the region nothing is held.
    let outside = Delays::from_json(&json, 1).unwrap();
    assert_eq!(outside.held_ms(0, 2000), 2000.0);
    assert_eq!(inside.held_ms(0, 2000), 0.0);
    // Without an outage nothing is held.
    assert_eq!(Delays::from_json(JSON, 0).unwrap().held_ms(1, 2000), 0.0);
}

#[test]
fn a_recurring_outage_holds_messages_in_every_window() {
    // From t = 1000, an outage of 3000 ms every 10000 ms.
    let json = JSON.replace(
        "\"bandwidth_mbps\": 1000.0",
        "\"bandwidth_mbps\": 1000.0, \"outage\": [0], \"outage_from_ms\": 1000, \"outage_until_ms\": 4000, \"outage_period_ms\": 10000",
    );
    let inside = Delays::from_json(&json, 0).unwrap();
    assert_eq!(inside.held_ms(1, 999), 0.0);
    assert_eq!(inside.held_ms(1, 1500), 2500.0);
    assert_eq!(inside.held_ms(1, 5000), 0.0);
    assert_eq!(inside.held_ms(1, 11000), 3000.0);
    assert_eq!(inside.held_ms(1, 13999), 1.0);
    assert_eq!(inside.held_ms(1, 14000), 0.0);
    assert_eq!(inside.held_ms(0, 11000), 0.0);
}

#[test]
fn bursts_raise_the_late_probability_for_a_while() {
    // From t = 0, the first 2000 ms of every 10000 ms are a burst with late_p 0.5; otherwise 0.05.
    let json = JSON.replace(
        "\"bandwidth_mbps\": 1000.0",
        "\"bandwidth_mbps\": 1000.0, \"late_p\": 0.05, \"burst_period_ms\": 10000, \"burst_ms\": 2000, \"burst_late_p\": 0.5",
    );
    let delays = Delays::from_json(&json, 0).unwrap();
    assert_eq!(delays.late_p_at(500), 0.5);
    assert_eq!(delays.late_p_at(2500), 0.05);
    assert_eq!(delays.late_p_at(11999), 0.5);
    assert_eq!(delays.late_p_at(12000), 0.05);
    assert_eq!(Delays::from_json(JSON, 0).unwrap().late_p_at(500), 0.0);
}

#[test]
fn a_targeted_node_is_slow_only_towards_the_chosen_nodes_and_only_on_consensus_ports() {
    // Node 0 is a target, node 1 a victim: node 0's consensus messages to node 1 are 3 s late, its other messages
    // (to node 1's mempool port) are not, and node 1's messages to node 0 are not either.
    let json = JSON.replace(
        "\"bandwidth_mbps\": 1000.0",
        "\"bandwidth_mbps\": 1000.0, \"late_to\": [\"127.0.0.1:9000\", \"127.0.0.1:9001\"], \
         \"slow_from\": [0], \"slow_to\": [1], \"slow_ms\": 3000.0",
    );
    let target = Delays::from_json(&json, 0).unwrap();
    let d = target.of(&"127.0.0.1:9001".parse().unwrap(), 0).unwrap().as_secs_f64() * 1e3;
    assert!((3050.0..3060.0).contains(&d), "{}", d);
    let d = target.of(&"127.0.0.1:9004".parse().unwrap(), 0).unwrap().as_secs_f64() * 1e3;
    assert!(d < 60.0, "{}", d);
    let victim = Delays::from_json(&json, 1).unwrap();
    let d = victim.of(&"127.0.0.1:9000".parse().unwrap(), 0).unwrap().as_secs_f64() * 1e3;
    assert!(d < 60.0, "{}", d);
}
