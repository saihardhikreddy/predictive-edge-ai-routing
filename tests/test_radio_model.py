import unittest

from simulation.mesh_engine import MeshSimulationEngine


class RadioModelTests(unittest.TestCase):

    def setUp(self):
        self.eng = MeshSimulationEngine(node_count=8, seed=7, auto_traffic=False)

    def test_success_prob_is_half_at_midpoint(self):
        self.assertAlmostEqual(self.eng.packet_success_prob(self.eng.PSR_MID_DBM), 0.5)

    def test_success_prob_is_monotonic_and_bounded(self):
        probs = [self.eng.packet_success_prob(r) for r in range(-110, -40, 2)]
        self.assertTrue(all(0.0 < p < 1.0 for p in probs))
        self.assertEqual(probs, sorted(probs))

    def test_strong_and_weak_links(self):
        self.assertGreater(self.eng.packet_success_prob(-60), 0.99)
        self.assertLess(self.eng.packet_success_prob(-100), 0.01)

    def test_adjacency_is_symmetric(self):
        self.eng.update_topology()
        for a, nbrs in self.eng.adj.items():
            for b, rssi in nbrs.items():
                self.assertEqual(self.eng.adj[b][a], rssi)

    def test_same_seed_gives_same_topology(self):
        other = MeshSimulationEngine(node_count=8, seed=7, auto_traffic=False)
        self.eng.update_topology()
        other.update_topology()
        self.assertEqual(self.eng.adj, other.adj)


if __name__ == "__main__":
    unittest.main()
