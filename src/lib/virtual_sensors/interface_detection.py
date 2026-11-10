"""Froth interface detection algorithms for calibrated planar ROI images.

This module assumes the unwrapped ROI image is already in memory.
Batch IO (loading/saving many files) should live in a separate script.

Current algorithm: entropy_foam_detection

It replicates the user's tested approach (entropy + row-mean profiles + crossings)
but avoids skimage dependencies by using SciPy's generic_filter for local entropy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d, generic_filter, sobel


import time



@dataclass(frozen=True)
class EntropyFoamResult:
    froth_row_px: Optional[float]
    pulp_row_px: Optional[float]
    froth_row_cm: Optional[float]
    pulp_row_cm: Optional[float]
    froth_height_norm: Optional[float]
    pulp_height_norm: Optional[float]
    plot_path: Optional[str]
    diagnostics: Optional[dict] = None


@dataclass
class EntropyFoamDetector:
    """Stateful detector.

    The module is image-in-memory only; batch scripts are responsible for IO.
    `px_per_cm` should come from the perspective calibration JSON and is used
    only to convert detected rows from px -> cm.
    """

    px_per_cm: Optional[float] = None
    origin_y_cm: Optional[float] = None

    def entropy_foam_detection(
        self,
        img_gray: np.ndarray,
        out_dir: str | Path = "results/depth_estimation",
        stem: str = "frame",
        *,
        entropy_radius: int = 20,
        entropy_bins: int = 32,
        sigma: float = 1.0,
        threshold_froth: float = 0.0,
        threshold_pulp: float = 1.0,
        method: str = "mean_derivative",
        simplification_alg: str = "turning_point",
        simplification_tol: float = 0.2,
        options: Optional[dict] = None,
        min_row: int = 10,
        save_plot: bool = True,
        show_plot: bool = True,
        ref_surface_px: Optional[float] = None,
        ref_interface_px: Optional[float] = None,
        return_diagnostics: bool = False,

    ) -> EntropyFoamResult:
        """Estimate froth/pulp interface heights using entropy profile crossings.

        Args:
            img_gray: image in memory (H,W) grayscale or (H,W,3) BGR/RGB.
            out_dir: output folder for the plot.
            stem: filename stem for plot.
            entropy_radius: neighborhood radius for entropy filter.
            entropy_bins: quantization bins for entropy.
            sigma: Gaussian smoothing sigma along rows.
            threshold_froth: crossing threshold on normalized derivative.
            threshold_pulp: crossing threshold on normalized derivative.
            method: detection method. "mean_derivative" (existing) or
                "cumulative_distribution" (CREM).
            simplification_alg : simplification algorithm. "turning_point", "reumann_witkam", "douglas_peucker" , "opheim", "lang"
            options: optional dict holding thresholds for both methods:
                threshold_froth, threshold_pulp, cdf_foam, cdf_pulp.
            min_row: ignore crossings above this row.Reumann-Witkam
            save_plot: if True, save plot to disk.
        """
        start = time.perf_counter()


        img_in = np.asarray(img_gray)
        img_for_plot_full = img_in
        if img_in.ndim == 3:
            img = img_in[..., 0] * 0.114 + img_in[..., 1] * 0.587 + img_in[..., 2] * 0.299
        else:
            img = img_in
        img = np.asarray(img, dtype=np.float64)

        if img.size == 0:
            raise ValueError("empty image")
        vmin = float(np.nanmin(img))
        vmax = float(np.nanmax(img))
        if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax <= vmin:
            img_u8 = np.zeros(img.shape[:2], dtype=np.uint8)
        else:
            img_u8 = np.clip((img - vmin) * (255.0 / (vmax - vmin)), 0, 255).astype(np.uint8)

        #ent_img = local_entropy_u8_fast(img_u8, radius=int(entropy_radius), bins=int(entropy_bins))
        ent_img = local_entropy_u8_compatible(img_u8, radius=int(entropy_radius), bins=int(entropy_bins))

        row_mean = ent_img.mean(axis=1)
        row_mean = gaussian_filter1d(row_mean, sigma=float(sigma))

        rs = row_mean
        rs_min = float(np.min(rs))
        rs_max = float(np.max(rs))
        if rs_max > rs_min:
            rs_norm = (rs - rs_min) / (rs_max - rs_min)
        else:
            rs_norm = np.zeros_like(rs)

        opts = options or {}
        if method not in {"mean_derivative", "cumulative_distribution","heuristic_entropy"}:
            raise ValueError(
                f"method must be 'mean_derivative' or 'cumulative_distribution', got {method!r}"
            )

        # Secondary plotted signal (and right-hand grayscale bar):
        # derivative for mean_derivative; CDF for CREM.
        signal2_norm: Optional[np.ndarray] = None

        if method == "mean_derivative":
            thr_froth = float(opts.get("threshold_froth", threshold_froth))
            thr_pulp = float(opts.get("threshold_pulp", threshold_pulp))

            
            row_diff = np.gradient(row_mean)
            row_diff = gaussian_filter1d(row_diff, sigma=float(sigma))
            

            dmin = float(np.min(row_diff))
            dmax = float(np.max(row_diff))
            if dmax <= dmin or not np.isfinite(dmin) or not np.isfinite(dmax):
                row_diff_norm = np.zeros_like(row_diff, dtype=np.float64)
            else:
                row_diff_norm = (row_diff - dmin) / (dmax - dmin)
            
            signal2_norm = row_diff_norm


            # Mean-derivative method:
            # - froth: threshold crossing on normalized derivative
            # - pulp:  threshold crossing on normalized entropy row mean
            cross_f = crossings_1d(row_diff_norm, thr_froth)
            cross_p = crossings_1d(rs_norm, thr_pulp)

            cross_f = cross_f[cross_f > float(min_row)]
            cross_p = cross_p[cross_p > float(min_row)]

            froth_row = float(np.min(cross_f)) if cross_f.size else None
            pulp_row = float(np.max(cross_p)) if cross_p.size else None
        elif method == "heuristic_entropy":
            def turning_points_series(s):
                """Turning points filter: remove intermediate monotonic points, keep extremes."""
                s2 = s.loc[s.ne(s.shift())]
                if len(s2) < 3:
                    return s2
                dy = s2.diff().to_numpy()[1:]
                sign = np.sign(dy)

                ids = np.r_[ 
                    0,
                    np.where(np.diff(sign) != 0)[0] + 1,
                    len(s2) - 1
                ]
                return s2.iloc[ids]

            selection_criteria = str(opts.get("selection_criteria", "hybrid"))

            # opções:
            # "strong_candidates": pega pulp e froth como os dois últimos saltos fortes
            # "next_tp_after_pulp": pega pulp como último salto forte e froth como o TP imediatamente acima
            row_mean = np.asarray(row_mean, dtype=float)

            points = np.column_stack((
                            np.arange(len(row_mean)),
                            row_mean,
                        ))
            if simplification_alg == "turning_point":
                row_mean = pd.Series(row_mean)
                row_mean_simpl = turning_points_series(row_mean)
            else: 
                import pySimpl as ps
                points = np.column_stack((
                                np.arange(len(row_mean)),
                                row_mean,
                            ))

            match simplification_alg:
                case "turning_point":
                    pass

                case "reumann_witkam":
                    simplified = ps.reumann_witkam(
                        points,
                        tol=simplification_tol,
                        dim=2,
                    )

                case "douglas_peucker":
                    simplified = ps.douglas_peucker(
                        points,
                        tol=simplification_tol,
                        dim=2,
                    )

                case "opheim":
                    simplified = ps.opheim(
                        points,
                        min_tol=simplification_tol,
                        max_tol=1,
                        dim=2,
                    )

                case "lang":
                    simplified = ps.lang(
                        points,
                        tol=simplification_tol,
                        look_ahead=10,
                        dim=2,
                    )
                case _:
                    raise NotImplementedError(f"{simplification_alg} not implemented")
                
            if simplification_alg != "turning_point":
                row_mean_simpl = pd.Series(
                    data=simplified[:, 1],
                    index=simplified[:, 0].astype(int),
                    name="row_mean",
                )
            row_mean_simpl = (
                row_mean_simpl - row_mean_simpl.min()
            ) / max(row_mean_simpl.max() - row_mean_simpl.min(), 1e-12)

            if len(row_mean_simpl) < 5:
                froth_row = None
                pulp_row = None

            else:
                y = row_mean_simpl.to_numpy(dtype=float)
                x = row_mean_simpl.index.to_numpy(dtype=float)

                y = (y - np.nanmin(y)) / max(np.nanmax(y) - np.nanmin(y), 1e-12)

                # from scipy.signal import savgol_filter

                # w = min(11, len(y) // 2 * 2 - 1)
                # w = max(5, w)

                # if w >= len(y):
                #     w = len(y) if len(y) % 2 == 1 else len(y) - 1

                # trend = savgol_filter(y, window_length=w, polyorder=2, mode="interp")

                # y_hp = y - trend

                # y_hp = (y_hp - np.nanmin(y_hp)) / max(np.nanmax(y_hp) - np.nanmin(y_hp), 1e-12)

                y_hp = y.copy()

                var = np.abs(np.diff(y_hp))

                vmax = np.nanmax(var)

                if np.isfinite(vmax) and vmax > 0:
                    candidate_pos = np.where(var > 0.5 * vmax)[0] + 1
                else:
                    candidate_pos = np.array([], dtype=int)

                if candidate_pos.size == 0:
                    raise RuntimeError("No candidate points found in heuristic_entropy")

                if selection_criteria == "strong_candidates":
                    cross_rows = x[candidate_pos]

                    if cross_rows.size >= 2:
                        pulp_row = float(cross_rows[-1])
                        froth_row = float(cross_rows[-2])
                    elif cross_rows.size == 1:
                        raise RuntimeError("Single Point Error in strong_candidates")
                    else:
                        raise RuntimeError("No points found in strong_candidates")

                elif selection_criteria == "next_tp_after_pulp":
                    pulp_pos = int(candidate_pos[-1])

                    if pulp_pos < 1:
                        raise RuntimeError("pulp_pos has no previous TP point")

                    froth_pos = pulp_pos - 1

                    # índice/linha real no row_mean original
                    pulp_row = float(row_mean_simpl.index[pulp_pos])
                    froth_row = float(row_mean_simpl.index[froth_pos])

                    # valores correspondentes no row_mean original, se quiser usar/debugar
                    pulp_value = float(row_mean.loc[row_mean_simpl.index[pulp_pos]])
                    froth_value = float(row_mean.loc[row_mean_simpl.index[froth_pos]])
                elif selection_criteria == "hybrid":
                    pulp_pos = int(candidate_pos[-1])
                    froth_pos = pulp_pos
                    if pulp_pos < 1:
                        raise RuntimeError("pulp_pos has no previous TP point")
                    # find closest fitting point for pulp and droth via thresholds

                    # froth_thr = 0.8
                    froth_thr = threshold_froth
                    while froth_pos > 0 and float(row_mean_simpl.iloc[froth_pos]) <= froth_thr:
                        froth_pos -= 1
                    if float(row_mean_simpl.iloc[froth_pos]) <= froth_thr:
                        froth_pos = pulp_pos -1

                    # pulp_thr = 0.4
                    pulp_thr = threshold_pulp

                    pulp_start_pos = int(candidate_pos[-1])
                    pulp_pos = pulp_start_pos
                    while (
                            pulp_pos < len(row_mean_simpl) - 1
                            and float(row_mean_simpl.iloc[pulp_pos]) >= pulp_thr):
                        pulp_pos += 1

                    if float(row_mean_simpl.iloc[pulp_pos]) >= pulp_thr:
                        pulp_pos = pulp_start_pos

                    pulp_row = float(row_mean_simpl.index[pulp_pos])
                    froth_row = float(row_mean_simpl.index[froth_pos])
                    if not np.isfinite(pulp_row):
                        raise RuntimeError("pulp_row is NaN or infinite")

                    if not np.isfinite(froth_row):
                        raise RuntimeError("froth_row is NaN or infinite")

                #
                # --------------------------------------------------------------------------------
                #  
                elif selection_criteria == "interpolate":
                    pulp_pos = int(candidate_pos[-1])
                    froth_pos = pulp_pos
                    if pulp_pos < 1:
                        raise RuntimeError("pulp_pos has no previous TP point")
                    # find closest fitting point for pulp and droth via thresholds

                    # froth_thr = 0.8
                    froth_thr = threshold_froth
                    while froth_pos > 0 and float(row_mean_simpl.iloc[froth_pos]) <= froth_thr:
                        froth_pos -= 1
                    if float(row_mean_simpl.iloc[froth_pos]) <= froth_thr:
                        froth_pos = pulp_pos -1

                    # pulp_thr = 0.4
                    pulp_thr = threshold_pulp

                    pulp_start_pos = int(candidate_pos[-1])
                    pulp_pos = pulp_start_pos
                    while (
                            pulp_pos < len(row_mean_simpl) - 1
                            and float(row_mean_simpl.iloc[pulp_pos]) >= pulp_thr):
                        pulp_pos += 1

                    if float(row_mean_simpl.iloc[pulp_pos]) >= pulp_thr:
                        pulp_pos = pulp_start_pos

                    pulp_row = float(row_mean_simpl.index[pulp_pos])
                    froth_row = float(row_mean_simpl.index[froth_pos])
                    if not np.isfinite(pulp_row):
                        raise RuntimeError("pulp_row is NaN or infinite")

                    if not np.isfinite(froth_row):
                        raise RuntimeError("froth_row is NaN or infinite")
                    
                    x0 = froth_row
                    x1 = pulp_row
                    
                    y0 = float(row_mean_simpl.iloc[froth_pos])
                    y1 = float(row_mean_simpl.iloc[pulp_pos])

                    if abs(y1 - y0) < 1e-12:
                        raise RuntimeError("Cannot interpolate pulp: y0 and y1 are equal")

                    target = 0
                    pulp_row = x0 + (target - y0) * (x1 - x0) / (y1 - y0)
                        

                    # froth_thr = threshold_froth
                    # while froth_pos > 0 and float(row_mean_simpl.iloc[froth_pos]) <= froth_thr:
                    #     froth_pos -= 1
                    # if float(row_mean_simpl.iloc[froth_pos]) <= froth_thr:
                    #     froth_pos = pulp_pos -1
                    # froth_row = float(row_mean_simpl.index[froth_pos])


                    if float(row_mean_simpl.iloc[froth_pos]) <= froth_thr:
                        # target = threshold_froth
                        target = 1
                        froth_row = x0 + (target - y0) * (x1 - x0) / (y1 - y0)
                    # froth NÃO é interpolado
                    # froth_row = float(row_mean_simpl.index[froth_pos])


 

        else:
            # CREM: cumulative distribution of phi(r)=row_mean.
            cdf_foam = float(opts.get("cdf_foam", 0.5))
            cdf_pulp = float(opts.get("cdf_pulp", 0.8))

            phi = np.asarray(row_mean, dtype=np.float64)
            if phi.size == 0:
                froth_row = None
                pulp_row = None
                cdf = np.zeros((0,), dtype=np.float64)
            else:
                cum = np.cumsum(phi)
                total = float(cum[-1])
                if not np.isfinite(total) or total <= 0:
                    cdf = np.zeros_like(cum, dtype=np.float64)
                else:
                    cdf = cum / total

                # Efficient monotonic threshold search.
                i_f = int(np.searchsorted(cdf, cdf_foam, side="left"))
                i_p = int(np.searchsorted(cdf, cdf_pulp, side="left"))

                froth_row = float(i_f) if 0 <= i_f < int(phi.size) else None
                pulp_row = float(i_p) if 0 <= i_p < int(phi.size) else None

            if froth_row is not None and froth_row <= float(min_row):
                froth_row = None
            if pulp_row is not None and pulp_row <= float(min_row):
                pulp_row = None



            signal2_norm = cdf

        h = int(ent_img.shape[0])
        froth_norm = (froth_row / (h - 1)) if (froth_row is not None and h > 1) else None
        pulp_norm = (pulp_row / (h - 1)) if (pulp_row is not None and h > 1) else None

        froth_cm = None
        pulp_cm = None
        if self.px_per_cm is None:
            raise ValueError("px_per_cm is required (cm-only outputs)")
        s = float(self.px_per_cm)
        if not np.isfinite(s) or s <= 0:
            raise ValueError(f"invalid px_per_cm: {self.px_per_cm}")
        oy = float(self.origin_y_cm) if self.origin_y_cm is not None else 0.0
        froth_cm = (oy + float(froth_row) / s) if froth_row is not None else None
        pulp_cm = (oy + float(pulp_row) / s) if pulp_row is not None else None

        # Batch runners may execute this in many processes; keep stdout quiet.
        # (Timing can be measured in the caller if needed.)

        process_time = time.perf_counter() - start


        plot_path: Optional[str] = None
        if save_plot or show_plot:
            out_dir = Path(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            plot_path = str(out_dir / f"{stem}_entropy_depth.png")

            import matplotlib

            # In batch/headless runs we typically only save figures.
            if not show_plot:
                matplotlib.use("Agg", force=True)
            import matplotlib.pyplot as plt

            img_h, img_w = int(ent_img.shape[0]), int(ent_img.shape[1])
            # Dynamic sizing: scale with image pixels/aspect. Keep a small fixed side panel
            # for legend + single metric line (no need to make the figure very wide).
            px_per_in = 200.0
            panel_w_in = max(3.2, min(8.5, img_w / px_per_in))
            panel_h_in = max(3.0, min(9.5, img_h / px_per_in))
            side_w_in = 2.2
            fig_w_in = min(18.0, 2.0 * panel_w_in + side_w_in)
            fig_h_in = min(11.0, panel_h_in + 0.4)

            fig, (ax0, ax1, ax_info) = plt.subplots(
                1,
                3,
                figsize=(fig_w_in, fig_h_in),
                gridspec_kw={"width_ratios": [1, 1, side_w_in / max(0.1, panel_w_in)]},
            )

            # Always show the full ROI image on the left.
            if np.asarray(img_for_plot_full).ndim == 3:
                ax0.imshow(np.asarray(img_for_plot_full)[..., ::-1])
            else:
                ax0.imshow(img_u8, cmap="gray")

            ax0.set_title("Original")
            ax0.set_axis_off()

            ax1.imshow(ent_img, cmap="gray")
            ax1.set_title("Detected")

            w = int(ent_img.shape[1])


            ax1.plot(
                rs_norm * (w - 1),
                np.arange(ent_img.shape[0]),
                color="red",
                lw=1,
                label=r"Normalized $\mu_{row}(entropy)$",
            )

            if signal2_norm is not None and signal2_norm.size:
                ax1.plot(
                    signal2_norm * (w - 1),
                    np.arange(ent_img.shape[0]),
                    color="green",
                    lw=1,
                    label=(
                        r"Normalized $\partial\mu/\partial r$"
                        if method == "mean_derivative"
                        else r"CDF($\phi(r)$)"
                    ),
                )
                ax1.plot(
                    rs_norm*signal2_norm * (w - 1),
                    np.arange(ent_img.shape[0]),
                    color="blue",
                    lw=1,
                    label=(
                        r"Normalized $r \cdot \partial\mu/\partial r$"
                        if method == "mean_derivative"
                        else r"CDF($\phi(r)$) \cdot r$"
                    ),
                )
            if method == "heuristic_entropy":
                row_mean_simpl = (row_mean_simpl - row_mean_simpl.min()) / max(row_mean_simpl.max() - row_mean_simpl.min(), 1e-12)
                ax1.plot(
                    row_mean_simpl.to_numpy(dtype=float)*ent_img.shape[1],
                    row_mean_simpl.index.to_numpy(),
                    "o-",
                    linewidth=1.5,
                    markersize=3,
                    label="row_mean_simpl",
                )
                ax1.scatter(
                    row_mean_simpl.iloc[candidate_pos].to_numpy(dtype=float) * ent_img.shape[1],
                    row_mean_simpl.index.to_numpy()[candidate_pos],
                    s=45,
                    c="yellow",
                    edgecolors="black",
                    zorder=10,
                    label="candidates",
                )



            # Two narrow grayscale bars to the right: they visualize the same
            # normalized 1D signals being plotted (rs_norm and row_diff_norm).
            bar_w = max(6, int(round(0.03 * w)))
            gap = max(2, int(round(0.01 * w)))
            bars_x0 = (w - 1) + gap
            bars_x1 = bars_x0 + bar_w
            bars_x2 = bars_x1 + gap
            bars_x3 = bars_x2 + bar_w

            bar_rs = np.repeat(rs_norm.reshape(-1, 1), bar_w, axis=1)
            bar_sig2 = (
                np.repeat(signal2_norm.reshape(-1, 1), bar_w, axis=1)
                if (signal2_norm is not None and signal2_norm.size)
                else np.zeros((ent_img.shape[0], bar_w), dtype=np.float64)
            )
            ax1.imshow(
                bar_rs,
                cmap="gray",
                vmin=0.0,
                vmax=1.0,
                aspect="auto",
                extent=[bars_x0, bars_x1, ent_img.shape[0] - 1, 0],
                interpolation="nearest",
            )
            ax1.imshow(
                bar_sig2,
                cmap="gray",
                vmin=0.0,
                vmax=1.0,
                aspect="auto",
                extent=[bars_x2, bars_x3, ent_img.shape[0] - 1, 0],
                interpolation="nearest",
            )
            ax1.axvline(bars_x0, color="white", lw=0.8, alpha=0.7)
            ax1.axvline(bars_x2, color="white", lw=0.8, alpha=0.7)
            ax1.set_xlim(0, bars_x3)

            if froth_row is not None:
                ax0.axhline(froth_row, color="magenta", ls="--", lw=1)
                ax1.axhline(froth_row, color="magenta", ls="--", lw=1, label="froth")
            if pulp_row is not None:
                ax0.axhline(pulp_row, color="cyan", ls="--", lw=1)
                ax1.axhline(pulp_row, color="cyan", ls="--", lw=1, label="pulp")
            # Reference lines from ground truth (if provided)
            if ref_surface_px is not None:
                ax0.axhline(ref_surface_px, color="gray", ls="--", lw=1, alpha=0.8)
                ax1.axhline(ref_surface_px, color="gray", ls="--", lw=1, alpha=0.8, label="gt surface")
            if ref_interface_px is not None:
                ax0.axhline(ref_interface_px, color="gray", ls="-.", lw=1, alpha=0.8)
                ax1.axhline(ref_interface_px, color="gray", ls="-.", lw=1, alpha=0.8, label="gt interface")

            ax1.set_xticks(np.linspace(0, w - 1, 6))
            ax1.set_xticklabels(np.linspace(0, 1, 6).round(2))
            ax1.tick_params(axis="both", which="both", labelsize=9)
            # cm-only y axis
            yt_px = np.linspace(0, ent_img.shape[0] - 1, 6)
            yt_cm = oy + yt_px / float(self.px_per_cm)
            ax1.set_yticks(yt_px)
            ax1.set_yticklabels(np.round(yt_cm, 2))
            ax1.set_ylabel("height (cm)")

            # Right-side info panel (outside the images).
            ax_info.set_axis_off()
            handles, labels = ax1.get_legend_handles_labels()
            if handles:
                ax_info.legend(handles, labels, loc="upper left", frameon=False, fontsize=8)

            time_txt = f"Process Time: {process_time:.4f} s"
            ax_info.text(0.0, 0.12, time_txt, va="bottom", ha="left", fontsize=10)

            # Resolution (px/mm) with 2 significant figures.
            if self.px_per_cm:
                res_px_per_mm = self.px_per_cm / 10.0
                res_txt = f"Resolution: {res_px_per_mm:.2g} px/mm"
                ax_info.text(0.0, 0.17, res_txt, va="bottom", ha="left", fontsize=10)

            depth_txt = "Froth Depth: N/A"
            if froth_cm is not None and pulp_cm is not None:
                depth_txt = f"Froth Depth: {abs(float(pulp_cm) - float(froth_cm)):.2f} cm"


            ax_info.text(0.0, 0.05, depth_txt, va="bottom", ha="left", fontsize=10)

            fig.tight_layout()
            if save_plot:
                fig.savefig(plot_path, transparent=True)
            if show_plot:
                plt.show()
            plt.close(fig)
                

        diagnostic = ({"entropy_map": ent_img, "profiles": {"row_entropy": rs_norm,
                       **({"row_derivative": signal2_norm} if method == "mean_derivative"
                          else {"cumulative_entropy": signal2_norm} if method == "cumulative_distribution" else {})}}
                      if return_diagnostics else None)
        return EntropyFoamResult(
            froth_row_px=froth_row,
            pulp_row_px=pulp_row,
            froth_row_cm=froth_cm,
            pulp_row_cm=pulp_cm,
            froth_height_norm=froth_norm,
            pulp_height_norm=pulp_norm,
            plot_path=plot_path,
            diagnostics=diagnostic,
        )


def disk_footprint(radius: int) -> np.ndarray:
    r = int(radius)
    if r < 1:
        return np.ones((1, 1), dtype=bool)
    y, x = np.ogrid[-r : r + 1, -r : r + 1]
    return (x * x + y * y) <= (r * r)
import numpy as np
from skimage.filters.rank import entropy
from skimage.morphology import disk


def local_entropy_u8_fast(
    img_u8: np.ndarray,
    radius: int = 20,
    bins: int = 32,
) -> np.ndarray:
    img_u8 = np.asarray(img_u8)

    if img_u8.dtype != np.uint8:
        img_u8 = np.clip(img_u8, 0, 255).astype(np.uint8)

    radius = int(radius)
    bins = int(np.clip(bins, 2, 256))

    q = (
        img_u8.astype(np.uint16) * bins // 256
    ).astype(np.uint8)

    out = entropy(
        q,
        footprint=disk(radius),
    )

    return out.astype(np.float32)

def local_entropy_u8(img_u8: np.ndarray, radius: int = 20, bins: int = 32) -> np.ndarray:
    """Approximate rank entropy filter.

    Args:
        img_u8: uint8 grayscale image.
        radius: disk radius.
        bins: quantization bins for speed.

    Returns:
        float32 image (same H,W) with entropy values.
    """
    img_u8 = np.asarray(img_u8)
    if img_u8.dtype != np.uint8:
        img_u8 = np.clip(img_u8, 0, 255).astype(np.uint8)

    b = int(bins)
    if b < 2:
        b = 2
    if b > 256:
        b = 256

    # Quantize to reduce histogram cost.
    q = (img_u8.astype(np.uint16) * b) // 256
    q = np.clip(q, 0, b - 1).astype(np.uint8)

    fp = disk_footprint(int(radius))

    def ent(values):
        # values contains only footprint-selected samples.
        counts = np.bincount(values.astype(np.int32), minlength=b).astype(np.float64)
        s = counts.sum()
        if s <= 0:
            return 0.0
        p = counts / s
        p = p[p > 0]
        return float(-(p * np.log2(p)).sum())

    out = generic_filter(q, ent, footprint=fp, mode="nearest")
    return out.astype(np.float32)

import numpy as np
from skimage.filters.rank import entropy


def local_entropy_u8_compatible(
    img_u8: np.ndarray,
    radius: int = 20,
    bins: int = 32,
) -> np.ndarray:
    img_u8 = np.asarray(img_u8)

    if img_u8.dtype != np.uint8:
        img_u8 = np.clip(img_u8, 0, 255).astype(np.uint8)

    radius = int(radius)
    bins = int(np.clip(bins, 2, 256))

    q = (img_u8.astype(np.uint16) * bins) // 256
    q = np.clip(q, 0, bins - 1).astype(np.uint8)

    footprint = disk_footprint(radius)

    q_pad = np.pad(q, radius, mode="edge")

    out = entropy(
        q_pad,
        footprint=footprint,
    )

    if radius > 0:
        out = out[radius:-radius, radius:-radius]

    # Preserve the original uint8 truncation used in the validated detector.
    return out.astype(np.uint8).astype(np.float32)
def crossings_1d(signal: np.ndarray, thr: float) -> np.ndarray:
    """Return subpixel indices where signal crosses threshold."""
    s = np.asarray(signal, dtype=np.float64) - float(thr)
    if s.size < 2:
        return np.array([], dtype=np.float64)
    idx = np.where(np.sign(s[:-1]) != np.sign(s[1:]))[0]
    if idx.size == 0:
        return np.array([], dtype=np.float64)

    # Linear interpolation for crossing location.
    denom = (s[idx + 1] - s[idx])
    denom[denom == 0] = np.nan
    frac = -s[idx] / denom
    x = idx.astype(np.float64) + frac
    return x[np.isfinite(x)]


def entropy_foam_detection(
    img_gray: np.ndarray,
    out_dir: str | Path = "results/depth_estimation",
    stem: str = "frame",
    *,
    px_per_cm: Optional[float] = None,
    origin_y_cm: Optional[float] = None,
    entropy_radius: int = 20,
    entropy_bins: int = 32,
    sigma: float = 1.0,
    threshold_froth: float = 0.0,
    threshold_pulp: float = 1.0,
    method: str = "mean_derivative",
    options: Optional[dict] = None,
    min_row: int = 10,
    save_plot: bool = True,
) -> EntropyFoamResult:
    """Convenience wrapper (stateless API)."""
    det = EntropyFoamDetector(px_per_cm=px_per_cm, origin_y_cm=origin_y_cm)
    return det.entropy_foam_detection(
        img_gray,
        out_dir=out_dir,
        stem=stem,
        entropy_radius=entropy_radius,
        entropy_bins=entropy_bins,
        sigma=sigma,
        threshold_froth=threshold_froth,
        threshold_pulp=threshold_pulp,
        method=method,
        options=options,
        min_row=min_row,
        save_plot=save_plot,
    )

# -----------------------------------------------------------------------------
# Dual entropy/profile foam boundary detector
# Dual entropy methods used by the virtual interface sensor.
# -----------------------------------------------------------------------------

import cv2
import numpy as np


def _dual_smooth1d(x: np.ndarray, sigma: float) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32).reshape(-1, 1)
    if sigma <= 0:
        return x[:, 0]
    k = int(max(3, round(6 * sigma + 1)))
    if k % 2 == 0:
        k += 1
    return cv2.GaussianBlur(
        x,
        (1, k),
        sigmaX=0,
        sigmaY=float(sigma),
        borderType=cv2.BORDER_REPLICATE,
    )[:, 0]


def _dual_robust_z(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    med = float(np.nanmedian(x))
    q1, q3 = np.nanpercentile(x, [25, 75])
    scale = max(float(q3 - q1) / 1.349, 1e-6)
    return (x - med) / scale


def _dual_local_std(img: np.ndarray, ksize: int = 21) -> np.ndarray:
    img = img.astype(np.float32)
    ksize = int(max(3, ksize))
    if ksize % 2 == 0:
        ksize += 1
    mean = cv2.blur(img, (ksize, ksize), borderType=cv2.BORDER_REPLICATE)
    mean2 = cv2.blur(img * img, (ksize, ksize), borderType=cv2.BORDER_REPLICATE)
    return np.sqrt(np.maximum(mean2 - mean * mean, 0.0))


def _dual_fast_local_entropy(gray: np.ndarray, radius: int = 11, bins: int = 16) -> np.ndarray:
    """Approximate local Shannon entropy using quantized bins and box filters."""
    gray = np.asarray(gray, dtype=np.uint8)
    bins = int(max(4, min(64, bins)))
    radius = int(max(1, radius))
    k = 2 * radius + 1

    q = (gray.astype(np.int32) * bins) // 256
    q = np.clip(q, 0, bins - 1)

    entropy = np.zeros(gray.shape, dtype=np.float32)
    eps = 1e-8
    for b in range(bins):
        mask = (q == b).astype(np.float32)
        p = cv2.blur(mask, (k, k), borderType=cv2.BORDER_REPLICATE)
        entropy -= np.where(p > eps, p * np.log2(p + eps), 0.0).astype(np.float32)

    entropy /= float(np.log2(bins))
    return entropy


def _dual_contrast_profile(prof: np.ndarray, win: int, mode: str) -> np.ndarray:
    """Difference of row averages above/below each row."""
    prof = np.asarray(prof, dtype=np.float32)
    h = len(prof)
    out = np.zeros(h, dtype=np.float32)
    win = max(2, int(win))
    for y in range(win, h - win):
        above = float(np.mean(prof[y - win:y]))
        below = float(np.mean(prof[y:y + win]))
        if mode == "above_minus_below":
            out[y] = above - below
        else:
            out[y] = below - above
    return out


def detect_dual_entropy_boundaries(
    img_bgr: np.ndarray,
    *,
    x0_frac: float = 0.12,
    x1_frac: float = 0.95,
    min_y_frac: float = 0.18,
    lower_search_start: float = 0.40,
    lower_search_end: float = 0.92,
    min_thickness_px: int = 25,
    sigma_rows: float = 7.0,
    entropy_radius: int = 11,
    entropy_bins: int = 16,
    texture_ksize: int = 21,
    upper_threshold_q: float = 62.0,
    lower_bias: float = 0.0,
    return_diagnostics: bool = False,
) -> dict:
    """Detect upper and lower foam boundaries without a trained classifier.

    Returns a dict with:
        upper_row_px: upper foam surface row
        lower_row_px: lower foam/pulp interface row
        foam_thickness_px: lower - upper
        x_range_used: [x0, x1]
        profiles: diagnostic 1D profiles
    """
    if img_bgr is None:
        raise ValueError("img_bgr is None")
    if img_bgr.ndim != 3 or img_bgr.shape[2] != 3:
        raise ValueError(f"expected BGR image with shape (H,W,3), got {img_bgr.shape}")

    h, w = img_bgr.shape[:2]
    x0 = int(round(w * float(x0_frac)))
    x1 = int(round(w * float(x1_frac)))
    x0 = max(0, min(w - 2, x0))
    x1 = max(x0 + 1, min(w, x1))

    crop = img_bgr[:, x0:x1]
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).astype(np.float32)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).astype(np.float32)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    L = lab[:, :, 0]
    S = hsv[:, :, 1]

    L_blur = cv2.GaussianBlur(L, (5, 5), 0, borderType=cv2.BORDER_REPLICATE)
    edge_y = np.abs(cv2.Sobel(L_blur, cv2.CV_32F, 0, 1, ksize=3))
    std_map = _dual_local_std(L, ksize=texture_ksize)
    entropy_map = _dual_fast_local_entropy(gray, radius=entropy_radius, bins=entropy_bins)

    L_prof = _dual_smooth1d(np.median(L, axis=1), sigma_rows)
    S_prof = _dual_smooth1d(np.percentile(S, 70, axis=1), sigma_rows)
    edge_prof = _dual_smooth1d(np.percentile(edge_y, 88, axis=1), sigma_rows)
    std_prof = _dual_smooth1d(np.percentile(std_map, 75, axis=1), sigma_rows)
    ent_prof = _dual_smooth1d(np.percentile(entropy_map, 75, axis=1), sigma_rows)

    dL = _dual_smooth1d(np.gradient(L_prof), max(1.0, sigma_rows / 2.0))
    dE = _dual_smooth1d(np.gradient(ent_prof), max(1.0, sigma_rows / 2.0))
    dT = _dual_smooth1d(np.gradient(std_prof), max(1.0, sigma_rows / 2.0))

    foamness = (
        1.20 * _dual_robust_z(ent_prof)
        + 0.85 * _dual_robust_z(std_prof)
        + 0.55 * _dual_robust_z(edge_prof)
        + 0.25 * _dual_robust_z(S_prof)
        - 0.20 * _dual_robust_z(L_prof)
    )
    foamness = _dual_smooth1d(foamness, sigma_rows)

    win = max(8, int(round(0.018 * h)))
    L_contrast = _dual_contrast_profile(L_prof, win, "above_minus_below")
    E_contrast = _dual_contrast_profile(ent_prof, win, "above_minus_below")

    lower_score = (
        1.45 * _dual_robust_z(-dL)
        + 0.75 * _dual_robust_z(edge_prof)
        + 0.75 * _dual_robust_z(-dE)
        + 0.45 * _dual_robust_z(-dT)
        + 0.75 * _dual_robust_z(L_contrast)
        + 0.30 * _dual_robust_z(E_contrast)
        + float(lower_bias) * np.linspace(0.0, 1.0, h, dtype=np.float32)
    )
    lower_score = _dual_smooth1d(lower_score, max(1.0, sigma_rows / 2.0))

    lo = int(round(h * float(lower_search_start)))
    hi = int(round(h * float(lower_search_end)))
    lo = max(0, min(h - 1, lo))
    hi = max(lo + 1, min(h, hi))
    y_lower = int(lo + np.argmax(lower_score[lo:hi]))

    top_lo = int(round(h * float(min_y_frac)))
    top_hi = max(top_lo + 1, y_lower - int(min_thickness_px))
    top_lo = max(0, min(h - 2, top_lo))
    top_hi = max(top_lo + 1, min(h, top_hi))

    search = foamness[top_lo:y_lower]
    if len(search) <= 4:
        y_upper = top_lo
    else:
        threshold = float(np.percentile(search, float(upper_threshold_q)))
        allowed_gap = max(3, int(round(0.008 * h)))

        y = max(top_lo, y_lower - 1)
        while y > top_lo and foamness[y] < threshold:
            y -= 1

        gap = 0
        y_start = y
        while y > top_lo:
            if foamness[y] >= threshold:
                gap = 0
                y_start = y
            else:
                gap += 1
                if gap > allowed_gap:
                    break
            y -= 1

        y_upper = int(y_start)

        if y_upper >= top_hi or (y_lower - y_upper) < min_thickness_px:
            upper_score = (
                1.05 * _dual_robust_z(np.maximum(dE, 0.0))
                + 0.80 * _dual_robust_z(np.maximum(dT, 0.0))
                + 0.35 * _dual_robust_z(edge_prof)
                + 0.30 * _dual_robust_z(foamness)
            )
            upper_score = _dual_smooth1d(upper_score, max(1.0, sigma_rows / 2.0))
            y_upper = int(top_lo + np.argmax(upper_score[top_lo:top_hi]))

    y_upper = int(np.clip(y_upper, 0, h - 1))
    y_lower = int(np.clip(y_lower, 0, h - 1))
    if y_upper >= y_lower:
        y_upper = max(0, y_lower - int(min_thickness_px))

    full_entropy = None
    if return_diagnostics:
        full_entropy = np.zeros((h, w), dtype=np.float32)
        full_entropy[:, x0:x1] = entropy_map

    return {
        **({"entropy_map": full_entropy} if return_diagnostics else {}),
        "upper_row_px": y_upper,
        "lower_row_px": y_lower,
        "foam_thickness_px": max(0, y_lower - y_upper),
        "x_range_used": [x0, x1],
        "profiles": {
            "L": L_prof,
            "S": S_prof,
            "edge": edge_prof,
            "std": std_prof,
            "entropy": ent_prof,
            "foamness": foamness,
            "lower_score": lower_score,
        },
    }


def draw_dual_entropy_detection(img_bgr: np.ndarray, det: dict, *, label: bool = True) -> np.ndarray:
    """Draw upper/lower foam boundaries on an image."""
    out = img_bgr.copy()
    h, w = out.shape[:2]
    yu = int(round(float(det["upper_row_px"])))
    yl = int(round(float(det["lower_row_px"])))
    x0, x1 = map(lambda v: int(round(float(v))), det.get("x_range_used", [0, w]))

    overlay = out.copy()
    cv2.rectangle(overlay, (x0, 0), (x1, h - 1), (255, 255, 255), -1)
    cv2.addWeighted(overlay, 0.06, out, 0.94, 0, out)

    cv2.line(out, (0, yu), (w - 1, yu), (0, 255, 255), 3, cv2.LINE_AA)
    cv2.line(out, (0, yl), (w - 1, yl), (0, 0, 255), 3, cv2.LINE_AA)
    cv2.line(out, (x0, 0), (x0, h - 1), (255, 255, 0), 1, cv2.LINE_AA)
    cv2.line(out, (x1, 0), (x1, h - 1), (255, 255, 0), 1, cv2.LINE_AA)

    if label:
        def txt(s, org, color):
            cv2.putText(out, s, org, cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(out, s, org, cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 1, cv2.LINE_AA)

        txt(f"upper={yu}px", (10, max(24, yu - 8)), (0, 255, 255))
        txt(f"lower={yl}px", (10, min(h - 10, yl + 24)), (0, 0, 255))
        txt(f"thickness={yl - yu}px", (10, 24), (255, 255, 255))

    return out

# -----------------------------------------------------------------------------
# Dual entropy striped foam boundary detector
# Append this block to: markers/Aruco/module/depth_estimation.py
# Requires the v2 dual entropy helpers/functions to already exist:
#   _dual_smooth1d, _dual_normalize01, detect_dual_entropy_boundaries
# -----------------------------------------------------------------------------

import cv2
import numpy as np


def _dual_striped_vote_curve(rows, weights, length, sigma_px=12.0):
    rows = np.asarray(rows, dtype=np.float32)
    weights = np.asarray(weights, dtype=np.float32)
    if rows.size == 0:
        return np.zeros(int(length), dtype=np.float32)
    y = np.arange(int(length), dtype=np.float32)[:, None]
    sigma = max(float(sigma_px), 1.0)
    g = np.exp(-0.5 * ((y - rows[None, :]) / sigma) ** 2)
    curve = (g * weights[None, :]).sum(axis=1)
    m = float(curve.max()) if curve.size else 0.0
    if m > 1e-8:
        curve = curve / m
    return curve.astype(np.float32)


def _dual_weighted_median(values, weights):
    values = np.asarray(values, dtype=np.float32)
    weights = np.asarray(weights, dtype=np.float32)
    if values.size == 0:
        return np.nan
    order = np.argsort(values)
    values = values[order]
    weights = weights[order]
    cs = np.cumsum(weights)
    cutoff = 0.5 * float(cs[-1])
    idx = int(np.searchsorted(cs, cutoff, side="left"))
    idx = max(0, min(len(values) - 1, idx))
    return float(values[idx])


def detect_dual_entropy_striped_boundaries(
    img_bgr: np.ndarray,
    *,
    x0_frac: float = 0.12,
    x1_frac: float = 0.95,
    min_y_frac: float = 0.18,
    lower_search_start: float = 0.40,
    lower_search_end: float = 0.92,
    min_thickness_px: int = 25,
    sigma_rows: float = 7.0,
    entropy_radius: int = 11,
    entropy_bins: int = 16,
    texture_ksize: int = 21,
    upper_threshold_q: float = 62.0,
    lower_bias: float = 0.0,
    n_stripes: int = 7,
    stripe_overlap: float = 0.40,
    min_valid_stripes: int = 3,
    vote_sigma_px: float = 12.0,
    outlier_mad: float = 2.5,
    return_diagnostics: bool = False,
) -> dict:
    """Run the dual-entropy detector over several overlapping vertical stripes,
    then combine upper/lower boundaries by robust voting.

    Why this helps:
    - dirt and scratches are often local in x, while the foam band is spatially persistent;
    - each stripe yields a local hypothesis with a confidence value;
    - final lines come from a consensus vote, not a single global profile.
    """
    if img_bgr is None:
        raise ValueError("img_bgr is None")
    if img_bgr.ndim != 3 or img_bgr.shape[2] != 3:
        raise ValueError(f"expected BGR image with shape (H,W,3), got {img_bgr.shape}")

    h, w = img_bgr.shape[:2]
    x0 = int(round(w * float(x0_frac)))
    x1 = int(round(w * float(x1_frac)))
    x0 = max(0, min(w - 2, x0))
    x1 = max(x0 + 1, min(w, x1))
    usable_w = x1 - x0

    n_stripes = int(max(3, n_stripes))
    stripe_overlap = float(np.clip(stripe_overlap, 0.0, 0.9))
    min_valid_stripes = int(max(1, min_valid_stripes))

    # Evenly spaced stripe centers. Stripe width grows with overlap.
    step = usable_w / float(n_stripes)
    stripe_w = max(12.0, step * (1.0 + 2.0 * stripe_overlap))
    half = 0.5 * stripe_w
    centers = np.linspace(x0 + 0.5 * step, x1 - 0.5 * step, n_stripes)

    stripes = []
    upper_rows = []
    lower_rows = []
    weights_upper = []
    weights_lower = []
    ent_total = np.zeros((h,w), np.float32) if return_diagnostics else None
    ent_weight = np.zeros((h,w), np.float32) if return_diagnostics else None

    for i, c in enumerate(centers):
        sx0 = int(round(max(x0, c - half)))
        sx1 = int(round(min(x1, c + half)))
        if sx1 - sx0 < 8:
            continue

        det = detect_dual_entropy_boundaries(
            img_bgr,
            x0_frac=float(sx0) / float(w),
            x1_frac=float(sx1) / float(w),
            min_y_frac=min_y_frac,
            lower_search_start=lower_search_start,
            lower_search_end=lower_search_end,
            min_thickness_px=min_thickness_px,
            sigma_rows=sigma_rows,
            entropy_radius=entropy_radius,
            entropy_bins=entropy_bins,
            texture_ksize=texture_ksize,
            upper_threshold_q=upper_threshold_q,
            lower_bias=lower_bias, return_diagnostics=return_diagnostics,
        )
        if return_diagnostics and det.get("entropy_map") is not None:
            ent_total[:,sx0:sx1] += det["entropy_map"][:,sx0:sx1]
            ent_weight[:,sx0:sx1] += 1.0

        yu = int(det["upper_row_px"])
        yl = int(det["lower_row_px"])
        thick = int(det["foam_thickness_px"])
        prof = det.get("profiles", {}) or {}
        continuity = np.asarray(prof.get("continuity", np.zeros(h, dtype=np.float32)), dtype=np.float32)
        lower_score = np.asarray(prof.get("lower_score", np.zeros(h, dtype=np.float32)), dtype=np.float32)
        persistence = np.asarray(prof.get("persistence", np.zeros(h, dtype=np.float32)), dtype=np.float32)

        cu = float(continuity[yu]) if 0 <= yu < len(continuity) else 0.0
        cl = float(lower_score[yl]) if 0 <= yl < len(lower_score) else 0.0
        cp = float(persistence[min(max(yu, 0), len(persistence)-1)]) if persistence.size else 0.0
        # Encourage stripes with a persistent foam band and a plausible thickness.
        cgeom = max(0.05, 0.55 * cu + 0.30 * cl + 0.15 * cp)
        valid = bool((yl > yu) and (thick >= int(min_thickness_px)))

        stripes.append({
            "index": int(i),
            "x0": int(sx0),
            "x1": int(sx1),
            "upper_row_px": int(yu),
            "lower_row_px": int(yl),
            "foam_thickness_px": int(thick),
            "upper_conf": float(cu),
            "lower_conf": float(cl),
            "persistence_conf": float(cp),
            "weight": float(cgeom),
            "valid": bool(valid),
        })

        if valid:
            upper_rows.append(float(yu))
            lower_rows.append(float(yl))
            weights_upper.append(max(0.05, float(cu) + 0.4 * float(cp)))
            weights_lower.append(max(0.05, float(cl) + 0.2 * float(cp)))

    if len(upper_rows) == 0 or len(lower_rows) == 0:
        # Fallback to the original global method.
        base = detect_dual_entropy_boundaries(
            img_bgr,
            x0_frac=x0_frac,
            x1_frac=x1_frac,
            min_y_frac=min_y_frac,
            lower_search_start=lower_search_start,
            lower_search_end=lower_search_end,
            min_thickness_px=min_thickness_px,
            sigma_rows=sigma_rows,
            entropy_radius=entropy_radius,
            entropy_bins=entropy_bins,
            texture_ksize=texture_ksize,
            upper_threshold_q=upper_threshold_q,
            lower_bias=lower_bias, return_diagnostics=return_diagnostics,
        )
        base["stripes"] = stripes
        base["valid_stripes"] = 0
        base["combine_method"] = "fallback_single"
        return base

    upper_rows = np.asarray(upper_rows, dtype=np.float32)
    lower_rows = np.asarray(lower_rows, dtype=np.float32)
    weights_upper = np.asarray(weights_upper, dtype=np.float32)
    weights_lower = np.asarray(weights_lower, dtype=np.float32)

    # Robust outlier rejection by MAD around weighted medians.
    med_u = _dual_weighted_median(upper_rows, weights_upper)
    med_l = _dual_weighted_median(lower_rows, weights_lower)

    mad_u = float(np.median(np.abs(upper_rows - med_u)))
    mad_l = float(np.median(np.abs(lower_rows - med_l)))
    thr_u = max(4.0, float(outlier_mad) * max(mad_u, 2.0))
    thr_l = max(4.0, float(outlier_mad) * max(mad_l, 2.0))
    keep = (np.abs(upper_rows - med_u) <= thr_u) & (np.abs(lower_rows - med_l) <= thr_l)

    if int(np.sum(keep)) >= min_valid_stripes:
        upper_rows_k = upper_rows[keep]
        lower_rows_k = lower_rows[keep]
        weights_upper_k = weights_upper[keep]
        weights_lower_k = weights_lower[keep]
    else:
        upper_rows_k = upper_rows
        lower_rows_k = lower_rows
        weights_upper_k = weights_upper
        weights_lower_k = weights_lower

    upper_vote = _dual_striped_vote_curve(upper_rows_k, weights_upper_k, h, sigma_px=vote_sigma_px)
    lower_vote = _dual_striped_vote_curve(lower_rows_k, weights_lower_k, h, sigma_px=vote_sigma_px)

    y_upper = int(np.argmax(upper_vote))
    lower_start = min(h - 1, y_upper + int(min_thickness_px))
    if lower_start < h - 1:
        y_lower = lower_start + int(np.argmax(lower_vote[lower_start:]))
    else:
        y_lower = min(h - 1, y_upper + int(min_thickness_px))

    if y_lower <= y_upper:
        y_lower = min(h - 1, y_upper + int(min_thickness_px))

    # Keep a compact summary and a visualization-friendly stripe list.
    return {
        **({"entropy_map": ent_total / np.maximum(1.0, ent_weight)} if return_diagnostics else {}),
        "upper_row_px": int(y_upper),
        "lower_row_px": int(y_lower),
        "foam_thickness_px": int(max(0, y_lower - y_upper)),
        "x_range_used": [int(x0), int(x1)],
        "profiles": {
            "upper_vote": upper_vote,
            "lower_vote": lower_vote,
        },
        "stripes": stripes,
        "valid_stripes": int(sum(1 for s in stripes if s.get("valid"))),
        "combine_method": "striped_vote",
    }


def draw_dual_entropy_striped_detection(img_bgr: np.ndarray, det: dict, *, label: bool = True) -> np.ndarray:
    """Draw the striped detector result.

    Thin pale lines: per-stripe local detections
    Bold yellow: final upper line
    Bold red: final lower line
    Cyan verticals: global x-range used
    """
    out = img_bgr.copy()
    h, w = out.shape[:2]
    yu = int(round(float(det["upper_row_px"])))
    yl = int(round(float(det["lower_row_px"])))
    x0, x1 = map(lambda v: int(round(float(v))), det.get("x_range_used", [0, w]))

    overlay = out.copy()
    cv2.rectangle(overlay, (x0, 0), (x1, h - 1), (255, 255, 255), -1)
    cv2.addWeighted(overlay, 0.05, out, 0.95, 0, out)

    for s in det.get("stripes", []) or []:
        sx0 = int(s.get("x0", 0))
        sx1 = int(s.get("x1", 0))
        syu = int(s.get("upper_row_px", 0))
        syl = int(s.get("lower_row_px", 0))
        valid = bool(s.get("valid", True))
        a = 0.18 if valid else 0.10
        tmp = out.copy()
        cv2.line(tmp, (sx0, syu), (sx1, syu), (80, 220, 255), 1, cv2.LINE_AA)
        cv2.line(tmp, (sx0, syl), (sx1, syl), (100, 100, 255), 1, cv2.LINE_AA)
        cv2.addWeighted(tmp, a, out, 1.0 - a, 0, out)

    cv2.line(out, (0, yu), (w - 1, yu), (0, 255, 255), 3, cv2.LINE_AA)
    cv2.line(out, (0, yl), (w - 1, yl), (0, 0, 255), 3, cv2.LINE_AA)
    cv2.line(out, (x0, 0), (x0, h - 1), (255, 255, 0), 1, cv2.LINE_AA)
    cv2.line(out, (x1, 0), (x1, h - 1), (255, 255, 0), 1, cv2.LINE_AA)

    if label:
        def txt(s, org, color):
            cv2.putText(out, s, org, cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(out, s, org, cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 1, cv2.LINE_AA)

        txt(f"upper={yu}px", (10, max(24, yu - 8)), (0, 255, 255))
        txt(f"lower={yl}px", (10, min(h - 10, yl + 24)), (0, 0, 255))
        txt(f"thickness={yl - yu}px", (10, 24), (255, 255, 255))
        txt(
            f"stripes={len(det.get('stripes', []) or [])}, valid={int(det.get('valid_stripes', 0))}",
            (10, 50),
            (220, 255, 220),
        )

    return out

# -----------------------------------------------------------------------------
# Hybrid foam boundary detector
# Append this block to: markers/Aruco/module/depth_estimation.py
# Requires:
#   detect_dual_entropy_boundaries
#   draw_dual_entropy_detection
#   detect_dual_entropy_striped_boundaries
# -----------------------------------------------------------------------------

import cv2
import numpy as np


def detect_dual_entropy_hybrid_boundaries(
    img_bgr: np.ndarray,
    *,
    x0_frac: float = 0.12,
    x1_frac: float = 0.95,
    min_y_frac: float = 0.18,
    lower_search_start: float = 0.40,
    lower_search_end: float = 0.92,
    min_thickness_px: int = 25,
    sigma_rows: float = 7.0,
    entropy_radius: int = 11,
    entropy_bins: int = 16,
    texture_ksize: int = 21,
    upper_threshold_q: float = 62.0,
    lower_bias: float = 0.0,
    n_stripes: int = 7,
    stripe_overlap: float = 0.40,
    min_valid_stripes: int = 3,
    vote_sigma_px: float = 12.0,
    outlier_mad: float = 2.5,
    return_diagnostics: bool = False,
) -> dict:
    """Hybrid detector:
    - upper boundary from the striped detector (more robust to localized dirt)
    - lower boundary from the global dual-entropy detector (often better for the soft lower foam boundary)
    """
    det_upper = detect_dual_entropy_striped_boundaries(
        img_bgr,
        x0_frac=x0_frac,
        x1_frac=x1_frac,
        min_y_frac=min_y_frac,
        lower_search_start=lower_search_start,
        lower_search_end=lower_search_end,
        min_thickness_px=min_thickness_px,
        sigma_rows=sigma_rows,
        entropy_radius=entropy_radius,
        entropy_bins=entropy_bins,
        texture_ksize=texture_ksize,
        upper_threshold_q=upper_threshold_q,
        lower_bias=lower_bias,
        n_stripes=n_stripes,
        stripe_overlap=stripe_overlap,
        min_valid_stripes=min_valid_stripes,
        vote_sigma_px=vote_sigma_px,
        outlier_mad=outlier_mad,
    )

    det_lower = detect_dual_entropy_boundaries(
        img_bgr,
        x0_frac=x0_frac,
        x1_frac=x1_frac,
        min_y_frac=min_y_frac,
        lower_search_start=lower_search_start,
        lower_search_end=lower_search_end,
        min_thickness_px=min_thickness_px,
        sigma_rows=sigma_rows,
        entropy_radius=entropy_radius,
        entropy_bins=entropy_bins,
        texture_ksize=texture_ksize,
        upper_threshold_q=upper_threshold_q,
        lower_bias=lower_bias, return_diagnostics=return_diagnostics,
    )

    yu = int(det_upper["upper_row_px"])
    yl = int(det_lower["lower_row_px"])
    if yl <= yu:
        yl = max(yu + int(min_thickness_px), int(det_lower.get("lower_row_px", yu + min_thickness_px)))
        h = img_bgr.shape[0]
        yl = min(h - 1, yl)

    profiles = {}
    # Keep vote curves from striped and lower score from global for debugging if available.
    try:
        profiles.update(det_upper.get("profiles", {}) or {})
    except Exception:
        pass
    try:
        for k, v in (det_lower.get("profiles", {}) or {}).items():
            if k not in profiles:
                profiles[k] = v
            else:
                profiles[f"global_{k}"] = v
    except Exception:
        pass

    return {
        **({"entropy_map": det_lower["entropy_map"]} if return_diagnostics else {}),
        "upper_row_px": int(yu),
        "lower_row_px": int(yl),
        "foam_thickness_px": int(max(0, yl - yu)),
        "x_range_used": det_upper.get("x_range_used", det_lower.get("x_range_used", [0, img_bgr.shape[1]])),
        "profiles": profiles,
        "stripes": det_upper.get("stripes", []),
        "valid_stripes": int(det_upper.get("valid_stripes", 0)),
        "combine_method": "hybrid_upper_striped_lower_global",
        "upper_source": "dual_entropy_striped",
        "lower_source": "dual_entropy_global",
    }


def draw_dual_entropy_hybrid_detection(img_bgr: np.ndarray, det: dict, *, label: bool = True) -> np.ndarray:
    out = img_bgr.copy()
    h, w = out.shape[:2]
    yu = int(round(float(det["upper_row_px"])))
    yl = int(round(float(det["lower_row_px"])))
    x0, x1 = map(lambda v: int(round(float(v))), det.get("x_range_used", [0, w]))

    overlay = out.copy()
    cv2.rectangle(overlay, (x0, 0), (x1, h - 1), (255, 255, 255), -1)
    cv2.addWeighted(overlay, 0.05, out, 0.95, 0, out)

    for s in det.get("stripes", []) or []:
        sx0 = int(s.get("x0", 0))
        sx1 = int(s.get("x1", 0))
        syu = int(s.get("upper_row_px", 0))
        valid = bool(s.get("valid", True))
        a = 0.15 if valid else 0.08
        tmp = out.copy()
        cv2.line(tmp, (sx0, syu), (sx1, syu), (80, 220, 255), 1, cv2.LINE_AA)
        cv2.addWeighted(tmp, a, out, 1.0 - a, 0, out)

    cv2.line(out, (0, yu), (w - 1, yu), (0, 255, 255), 3, cv2.LINE_AA)
    cv2.line(out, (0, yl), (w - 1, yl), (0, 0, 255), 3, cv2.LINE_AA)
    cv2.line(out, (x0, 0), (x0, h - 1), (255, 255, 0), 1, cv2.LINE_AA)
    cv2.line(out, (x1, 0), (x1, h - 1), (255, 255, 0), 1, cv2.LINE_AA)

    if label:
        def txt(s, org, color):
            cv2.putText(out, s, org, cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(out, s, org, cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 1, cv2.LINE_AA)

        txt(f"upper={yu}px striped", (10, max(24, yu - 8)), (0, 255, 255))
        txt(f"lower={yl}px global", (10, min(h - 10, yl + 24)), (0, 0, 255))
        txt(f"thickness={yl - yu}px", (10, 24), (255, 255, 255))

    return out