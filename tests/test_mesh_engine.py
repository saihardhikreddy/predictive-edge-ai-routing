import math
import unittest

from simulation import triage
from simulation.mesh_engine import MeshSimulationEngine


def run(engine, seconds, dt=0.1):
    for _ in range(int(seconds / dt)):
        engine.tick(dt)


class TestTopologyAndSnapshot(unittest.TestCase):
    def setUp(self):
        self.engine = MeshSimulationEngine(node_count=14, seed=3, warmup_s=5)

    def test_initialization_and_topology(self):
        self.assertEqual(len(self.engine.nodes), 14)
        self.assertGreater(len(self.engine.edges), 0)
        # adjacency is symmetric
        for u, nbrs in self.engine.adj.items():
            for v in nbrs:
                self.assertIn(u, self.engine.adj[v])

    def test_state_snapshot_serialization(self):
        import json

        snap = self.engine.get_state_snapshot()
        for key in ("nodes", "edges", "packets", "metrics", "logs", "flood_branches"):
            self.assertIn(key, snap)
        self.assertEqual(len(snap["nodes"]), 14)
        json.dumps(snap)  # must be JSON-serialisable

    def test_same_seed_same_world(self):
        a = MeshSimulationEngine(node_count=10, seed=42, warmup_s=5)
        b = MeshSimulationEngine(node_count=10, seed=42, warmup_s=5)
        run(a, 20)
        run(b, 20)
        self.assertEqual(a.summary()["marl"]["delivered"], b.summary()["marl"]["delivered"])


class TestRouting(unittest.TestCase):
    def test_marl_delivers_and_learns_locally(self):
        e = MeshSimulationEngine(node_count=16, seed=1)
        w0 = list(e.nodes["Node_01"].w)
        run(e, 120)
        s = e.summary()["marl"]
        self.assertGreater(s["generated"], 20)
        self.assertGreater(s["pdr"], 0.8)
        self.assertTrue(any(n.n_samples > 0 for n in e.nodes.values()))
        self.assertNotEqual(w0, e.nodes["Node_01"].w)  # weights moved (TD and/or FedAvg)

    def test_route_only_uses_existing_links(self):
        e = MeshSimulationEngine(node_count=16, seed=2, auto_traffic=False)
        e.trigger_message("Node_01", "Node_16")
        for _ in range(400):
            e.tick(0.1)
            for p in e.active_packets:
                if p.next_hop and p.progress == 0.0:
                    # a hop chosen this tick must be a current radio neighbour (local decision)
                    self.assertIn(p.next_hop, e.adj[p.holder])

    def test_flooding_counts_one_tx_per_broadcaster(self):
        e = MeshSimulationEngine(node_count=16, seed=4, auto_traffic=False)
        e.protocol_mode = "FLOODING"
        e.trigger_message("Node_01", "Node_16")
        f = e.summary()["flood"]
        self.assertEqual(f["generated"], 1)
        self.assertLessEqual(f["data_tx"], len(e.nodes))  # duplicate suppression
        self.assertEqual(f["control_tx"], 0)

    def test_federated_gossip_averages_weights(self):
        e = MeshSimulationEngine(node_count=2, seed=5, warmup_s=0, auto_traffic=False)
        a, b = e.nodes["Node_01"], e.nodes["Node_02"]
        a.w, b.w = [1.0] * 7, [3.0] * 7
        a.n_samples = b.n_samples = 9
        e.sim_time = 100.0
        e._gossip_fedavg(a, b)
        self.assertEqual(a.w, b.w)
        self.assertAlmostEqual(a.w[0], 2.0)

    def test_no_learning_ablation_keeps_prior(self):
        e = MeshSimulationEngine(node_count=12, seed=6, learning_enabled=False, federated_enabled=False)
        run(e, 60)
        for n in e.nodes.values():
            self.assertEqual(n.n_samples, 0)


class TestSecurity(unittest.TestCase):
    def test_sinkhole_detected_without_false_positives(self):
        e = MeshSimulationEngine(node_count=16, seed=0)
        run(e, 30)
        e.run_scenario(4)
        sink = next(n for n in e.nodes.values() if n.is_sinkhole)
        run(e, 90)
        self.assertTrue(sink.is_quarantined)
        ids = e.summary()["ids"]
        self.assertFalse(math.isnan(ids["detection_s"]))
        self.assertEqual(ids["false_positives"], 0)

    def test_no_attack_no_quarantine(self):
        e = MeshSimulationEngine(node_count=16, seed=7)
        run(e, 150)
        self.assertFalse(any(n.is_quarantined for n in e.nodes.values()))


class TestTriage(unittest.TestCase):
    def test_emergency_classified_and_compressed(self):
        for text in triage.EMERGENCY_CORPUS:
            r = triage.encode(text)
            self.assertEqual(r.intent, triage.INTENT_SOS, text)
            self.assertLess(r.payload_bytes, r.raw_payload_bytes / 2)
            self.assertTrue(triage.decode(r.encoded).startswith("EMERGENCY_SOS"))

    def test_routine_is_lossless(self):
        for text in triage.ROUTINE_CORPUS:
            r = triage.encode(text)
            self.assertNotEqual(r.intent, triage.INTENT_SOS, text)
            self.assertEqual(triage.decode(r.encoded), text)
            self.assertLessEqual(r.payload_bytes, r.raw_payload_bytes + 1)

    def test_slm_off_sends_raw(self):
        r = triage.encode(triage.EMERGENCY_CORPUS[0], slm_enabled=False)
        self.assertEqual(r.intent, triage.INTENT_ROUTINE)
        self.assertEqual(triage.decode(r.encoded), triage.EMERGENCY_CORPUS[0])


if __name__ == "__main__":
    unittest.main()
