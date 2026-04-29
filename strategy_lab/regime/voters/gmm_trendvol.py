"""
Gaussian-mixture voter on joint (log_return, realized_vol, ema_slope) features.

Design:
  * Fit a 3-component GaussianMixture on an initial training window
    [warmup, warmup + gmm_train_window], then refit every gmm_refit_bars.
  * Between refits, the frozen model predicts posteriors on new bars.
  * Components are post-hoc canonically labeled by centroid mean-return:
        most_negative → "down"; middle → "range"; most_positive → "up"
  * Vol posterior contribution: the "range" component's posterior probability
    is split between low and normal vol based on the component's mean-vol
    tertile; the "up"/"down" components contribute to vol=normal by default,
    but vol=high if their realized_vol centroid is above the overall 66th pct.

This replaces the `hmmlearn.GaussianHMM` planned in the mission brief —
rationale in docs/research/02_REGIME_LAYER_RESEARCH.md § 1b.

No-lookahead:
  * `.fit(...)` is called on closed past windows only.
  * `.predict_proba(...)` on bar i uses only past-fit parameters.
  * Each refit uses bars [0 .. current-1], never future bars.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import VoterOutput


class GmmTrendVolVoter:
    name = "gmm_trendvol"

    def vote(self, df, features, config) -> VoterOutput:
        from sklearn.mixture import GaussianMixture

        feat = features[["log_return", "realized_vol", "ema_slope"]].copy()

        n = len(feat)
        warmup = int(config.warmup_bars)
        train_window = int(config.gmm_train_window)
        refit_bars = int(config.gmm_refit_bars)

        trend_vote = pd.Series(0.0, index=df.index)
        vol_probs = pd.DataFrame(0.0, index=df.index, columns=["low", "normal", "high"])
        vol_probs["normal"] = 1.0  # safe default during warmup / no-model

        first_fit_bar = warmup + train_window
        if n <= first_fit_bar:
            # Not enough data to fit once → contribute neutral vote
            return VoterOutput(trend_vote=trend_vote, vol_probs=vol_probs,
                               meta={"fitted": False, "reason": "insufficient_data"})

        # Precompute expanding vol quantiles for vol-category mapping
        # (uses same definition as vol_quantile voter for consistency)
        vol = feat["realized_vol"].ffill()
        q_low  = vol.expanding(min_periods=warmup).quantile(config.vol_low_quantile)
        q_high = vol.expanding(min_periods=warmup).quantile(config.vol_high_quantile)

        model = None
        fit_at = first_fit_bar  # next bar at which we refit
        comp_labels: dict[int, str] = {}
        comp_vol_category: dict[int, str] = {}

        # We walk bars [first_fit_bar .. n-1]; on each refit point we retrain
        # on bars [warmup .. i-1] to avoid look-ahead.
        i = first_fit_bar
        while i < n:
            # Refit window: look-back closed at i (strictly before)
            train = feat.iloc[max(warmup, i - train_window) : i].dropna()
            if len(train) >= train_window // 2:
                model = GaussianMixture(
                    n_components=config.gmm_n_components,
                    covariance_type=config.gmm_covariance_type,
                    random_state=config.gmm_random_state,
                    max_iter=200, reg_covar=1e-4,
                ).fit(train.values)
                # Canonical labeling: sort components by mean log-return
                means = model.means_[:, 0]  # log_return is column 0
                order = np.argsort(means)
                comp_labels = {}
                if config.gmm_n_components == 3:
                    comp_labels[int(order[0])] = "down"
                    comp_labels[int(order[1])] = "range"
                    comp_labels[int(order[2])] = "up"
                else:
                    # Generic: lowest-mean → down, highest-mean → up, rest → range
                    comp_labels[int(order[0])] = "down"
                    comp_labels[int(order[-1])] = "up"
                    for k in order[1:-1]:
                        comp_labels[int(k)] = "range"
                # Vol-category mapping for each component, using the component's
                # realized_vol (column 1 of features).
                vol_means = model.means_[:, 1]
                # Overall tertiles from the same training slice
                vol_lo = np.quantile(train["realized_vol"].values, config.vol_low_quantile)
                vol_hi = np.quantile(train["realized_vol"].values, config.vol_high_quantile)
                comp_vol_category = {}
                for k in range(config.gmm_n_components):
                    if vol_means[k] <= vol_lo:
                        comp_vol_category[int(k)] = "low"
                    elif vol_means[k] >= vol_hi:
                        comp_vol_category[int(k)] = "high"
                    else:
                        comp_vol_category[int(k)] = "normal"

            next_fit = min(i + refit_bars, n)
            if model is None:
                i = next_fit
                continue

            # Predict for bars [i .. next_fit-1]
            block = feat.iloc[i:next_fit]
            valid_mask = ~block.isna().any(axis=1)
            if valid_mask.any():
                X = block.loc[valid_mask].values
                probs = model.predict_proba(X)        # (m, k)
                # Trend vote: P(up) - P(down)
                up_idx  = [c for c, lbl in comp_labels.items() if lbl == "up"]
                dn_idx  = [c for c, lbl in comp_labels.items() if lbl == "down"]
                p_up = probs[:, up_idx].sum(axis=1)
                p_dn = probs[:, dn_idx].sum(axis=1)
                # Map the P(up)-P(down) in [-1, +1] directly → contributes to trend_score
                tv = p_up - p_dn
                trend_vote.loc[block.index[valid_mask]] = tv

                # Vol posterior: sum component probs by vol category
                vp = np.zeros((len(X), 3))  # columns: low, normal, high
                for c in range(config.gmm_n_components):
                    cat = comp_vol_category.get(c, "normal")
                    col = {"low": 0, "normal": 1, "high": 2}[cat]
                    vp[:, col] += probs[:, c]
                vp_df = pd.DataFrame(vp, index=block.index[valid_mask],
                                     columns=["low", "normal", "high"])
                vol_probs.loc[vp_df.index] = vp_df.values

            i = next_fit

        return VoterOutput(
            trend_vote=trend_vote, vol_probs=vol_probs,
            meta={"fitted": True, "first_fit_bar": int(first_fit_bar)},
        )
