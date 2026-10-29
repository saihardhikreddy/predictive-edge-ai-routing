import unittest

from benchmark import one_run


def run(variant, **kw):
    job = dict(experiment="t", variant=variant, nodes=16, seed=1, duration=90, traffic_interval=3.5)
    job.update(kw)
    return one_run(job)


class DtnBaselineTest(unittest.TestCase):
    def test_every_baseline_delivers(self):
        for v in ("Epidemic", "Spray-and-Wait (L=8)", "PRoPHET (GRTR)", "Direct delivery"):
            r = run(v)
            self.assertGreater(r["generated"], 10, v)
            self.assertGreater(r["pdr"], 0.3, v)

    def test_direct_delivery_is_one_hop(self):
        self.assertEqual(run("Direct delivery")["hops"], 1.0)

    def test_epidemic_costs_more_than_spray(self):
        self.assertGreater(run("Epidemic")["tx_per_delivery"], run("Spray-and-Wait (L=8)")["tx_per_delivery"])

    def test_instant_purge_is_cheaper(self):
        self.assertLess(run("Epidemic", vaccine=True)["tx_per_delivery"], run("Epidemic")["tx_per_delivery"])


if __name__ == "__main__":
    unittest.main()
