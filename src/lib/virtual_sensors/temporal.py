"""Lightweight, causal temporal priors for already detected froth boundaries.

All row coordinates follow camera convention: zero at top. No frames or
histograms are retained, only the last few *valid* interface coordinates.
"""
from collections import deque

import numpy as np


class TemporalBoundaryFilter:
    def __init__(self):
        self._history = deque(maxlen=9)

    def copy(self):
        result = TemporalBoundaryFilter()
        result._history.extend(self._history)
        return result

    def clear(self):
        self._history.clear()

    @property
    def prior(self):
        return tuple(self._history[-1]) if self._history else None

    def apply(self, upper, lower, config, profiles=None, height=None):
        """Return corrected rows plus the prior used, without changing invalid detections."""
        previous = self.prior
        mode = config.get("temporal_filter", "off")
        strength = float(config.get("temporal_strength", .35))
        radius = max(1., float(config.get("temporal_radius_px", 24.)))
        window = int(config.get("temporal_window", 3))
        if upper is None or lower is None or lower <= upper:
            return upper, lower, previous
        if previous is not None:
            if mode == "ema":
                upper = strength * previous[0] + (1 - strength) * upper
                lower = strength * previous[1] + (1 - strength) * lower
            elif mode == "median":
                past = list(self._history)[-(window - 1):]
                upper = float(np.median([v[0] for v in past] + [upper]))
                lower = float(np.median([v[1] for v in past] + [lower]))
            elif mode == "vote_prior" and profiles:
                def choose(score, current, preferred, start=0):
                    curve = np.asarray(score if score is not None else [], dtype=float)
                    if curve.ndim != 1 or curve.size < 2 or not np.isfinite(curve).any():
                        return strength * preferred + (1 - strength) * current
                    y = np.arange(curve.size)
                    curve = np.nan_to_num(curve, nan=0., posinf=0., neginf=0.)
                    curve -= curve.min()
                    maximum = float(curve.max())
                    if maximum <= 1e-10:
                        return current
                    prior = np.exp(-.5 * ((y - preferred) / radius)**2)
                    boosted = (1 - strength) * curve + strength * maximum * prior
                    start = min(max(0, int(start)), len(boosted) - 1)
                    return float(start + np.argmax(boosted[start:]))
                upper = choose(profiles.get("upper_vote") if hasattr(profiles, "get") else None,
                               upper, previous[0])
                lower = choose((profiles.get("lower_vote") if profiles.get("lower_vote") is not None
                                else profiles.get("lower_score")), lower, previous[1],
                               start=round(upper) + 1)
        if height is not None:
            upper = float(np.clip(upper, 0, height - 1))
            lower = float(np.clip(lower, 0, height - 1))
        if lower > upper:
            self._history.append((float(upper), float(lower)))
        return float(upper), float(lower), previous if mode != "off" else None
