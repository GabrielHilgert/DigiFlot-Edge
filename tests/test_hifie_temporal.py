"""Cheap causal smoothing and vote-prior regression tests, without camera hardware."""
import unittest
import numpy as np
from lib.virtual_sensors.temporal import TemporalBoundaryFilter
from lib.virtual_sensors.interface import normalized_config


class TemporalBoundaryTests(unittest.TestCase):
    def config(self, mode, **extra):
        return normalized_config({"temporal_filter": mode, **extra})

    def test_off_has_no_prior_overlay_and_never_moves_boundaries(self):
        filt = TemporalBoundaryFilter()
        conf = self.config("off")
        self.assertEqual(filt.apply(10, 35, conf, height=100), (10., 35., None))
        self.assertEqual(filt.apply(20, 50, conf, height=100), (20., 50., None))
        self.assertEqual(filt.prior, (20., 50.))

    def test_ema_is_causal_and_rejects_invalid_pairs(self):
        filt = TemporalBoundaryFilter()
        conf = self.config("ema", temporal_strength=.75)
        filt.apply(20, 60, conf, height=100)
        result = filt.apply(40, 80, conf, height=100)
        self.assertEqual(result, (25., 65., (20., 60.)))
        self.assertEqual(filt.apply(70, 30, conf)[:2], (70, 30))
        self.assertEqual(filt.prior, (25., 65.))
        filt.clear()
        self.assertIsNone(filt.prior)

    def test_median3_rejects_single_jump_and_independent_clone(self):
        filt = TemporalBoundaryFilter()
        conf = self.config("median", temporal_window=3)
        filt.apply(15, 60, conf)
        filt.apply(16, 61, conf)
        clone = filt.copy()
        filtered = filt.apply(70, 90, conf)
        self.assertEqual(filtered[:2], (16., 61.))
        self.assertEqual(clone.prior, (16., 61.))
        self.assertEqual(filt.prior, (16., 61.))

    def test_vote_prior_prefers_consistent_peak_without_forcing_it(self):
        filt = TemporalBoundaryFilter()
        conf = self.config("vote_prior", temporal_strength=.80, temporal_radius_px=8.)
        filt.apply(20, 60, conf)
        upper = np.zeros(100);upper[20]=.7;upper[47]=1.
        lower = np.zeros(100);lower[60]=.7;lower[83]=1.
        value = filt.apply(47, 83, conf, {"upper_vote":upper, "lower_vote":lower}, 100)
        self.assertEqual(value[:2], (20., 60.))
        self.assertEqual(value[2], (20., 60.))

    def test_preserves_order_with_hard_temporal_prior(self):
        filt=TemporalBoundaryFilter()
        conf=self.config("vote_prior",temporal_strength=.9,temporal_radius_px=3.)
        filt.apply(20,30,conf)
        upper=np.zeros(50);upper[40]=1.
        lower=np.zeros(50);lower[20]=1.
        result=filt.apply(40,42,conf,{"upper_vote":upper,"lower_vote":lower},50)
        self.assertGreater(result[1],result[0])


if __name__ == "__main__":
    unittest.main()
