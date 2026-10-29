import unittest

from simulation.link_predictor import LinkPredictor, calibration, metrics


class LinkPredictorTest(unittest.TestCase):
    def test_metrics_auc_extremes(self):
        self.assertEqual(metrics([(0.9, 1), (0.8, 1), (0.2, 0), (0.3, 0)])["auc"], 1.0)
        self.assertEqual(metrics([(0.1, 1), (0.2, 1), (0.9, 0), (0.8, 0)])["auc"], 0.0)

    def test_learns_that_fading_links_break(self):
        lp = LinkPredictor()
        t = 0.0
        # many episodes: a stable peer at -60 dBm, and a peer that fades from -70 by 4 dB/s then vanishes
        for ep in range(60):
            for k in range(8):
                heard = {"stable": -60.0}
                if k < 6:
                    heard["fade"] = -70.0 - 4.0 * k
                lp.observe(t, heard)
                t += 1.0
        lp.observe(t, {"stable": -60.0, "fade": -70.0}); t += 1
        lp.observe(t, {"stable": -60.0, "fade": -74.0}); t += 1
        lp.observe(t, {"stable": -60.0, "fade": -78.0})
        self.assertLess(lp.predict("fade", t), lp.predict("stable", t))
        d = metrics(lp.scored["trend"])
        self.assertGreater(d["auc"], 0.8)

    def test_no_prediction_sees_its_own_future(self):
        lp = LinkPredictor()
        lp.observe(0.0, {"a": -60.0})
        lp.observe(1.0, {"a": -60.0})
        self.assertTrue(lp.pending)  # waiting for its label
        self.assertEqual(len(lp.scored["trend"]), 0)

    def test_calibration_bins(self):
        bins = calibration([(0.1, 0), (0.15, 0), (0.9, 1), (0.95, 1)], bins=5)
        self.assertEqual(len(bins), 2)


if __name__ == "__main__":
    unittest.main()
