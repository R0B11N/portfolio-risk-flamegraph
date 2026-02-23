"""
Variance decomposition: Σ = B·F·Bᵀ + D → market / size / value / idiosyncratic.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Any, Tuple


def compute_factor_covariance(ff_df: pd.DataFrame, window: int = 252) -> np.ndarray:
    """
    Compute 3×3 factor covariance matrix from the most recent `window` days
    of Fama-French factor returns.
    Returns numpy array of shape (3, 3) for [Mkt-RF, SMB, HML].
    """
    factor_cols = ["Mkt-RF", "SMB", "HML"]
    recent = ff_df[factor_cols].dropna().tail(window)

    if len(recent) < 60:
        raise ValueError(f"Insufficient factor data: only {len(recent)} days available")

    return recent.cov().values  # 3x3 covariance matrix


def decompose_portfolio_variance(
    weights: Dict[str, float],
    betas: Dict[str, Dict[str, Any]],
    factor_cov: np.ndarray,
    residual_vars: Dict[str, float],
) -> Dict[str, Any]:
    """
    Decompose total portfolio variance into factor and idiosyncratic components.

    Parameters:
        weights: {ticker: portfolio_weight} — weights should sum to 1.0
        betas: {ticker: {beta_mkt, beta_smb, beta_hml, ...}}
        factor_cov: 3×3 factor covariance matrix
        residual_vars: {ticker: residual_variance} from OLS regressions

    Returns dict with:
        market_pct, smb_pct, hml_pct, idiosyncratic_pct (summing to 100)
        total_annual_vol — annualized portfolio volatility in percent
        stock_contributions — per-stock detail for flamegraph drill-down
    """
    tickers = list(weights.keys())
    n = len(tickers)

    # Weight vector
    w = np.array([weights[t] for t in tickers])

    # B matrix: n_stocks × 3 factor loadings
    B = np.array([
        [betas[t]["beta_mkt"], betas[t]["beta_smb"], betas[t]["beta_hml"]]
        for t in tickers
    ])

    # D matrix: diagonal of idiosyncratic variances
    D = np.diag([residual_vars.get(t, 0.0) for t in tickers])

    # Factor covariance: F is 3×3
    F = factor_cov

    # Systematic covariance: B·F·Bᵀ (n×n matrix)
    systematic_cov = B @ F @ B.T

    # Total covariance: Σ = B·F·Bᵀ + D
    sigma = systematic_cov + D

    # Total portfolio variance: w^T · Σ · w
    total_var = float(w @ sigma @ w)

    if total_var <= 0:
        return _zero_result(tickers, weights)

    # --- Decompose variance by factor ---
    # For each factor k, its marginal contribution: w^T · (b_k · var_k · b_k^T) · w
    # where b_k is the column of B for factor k
    factor_names = ["market", "smb", "hml"]
    raw_contributions = {}

    for k, name in enumerate(factor_names):
        b_k = B[:, k]  # n-vector of factor-k loadings
        # Pure factor-k variance contribution
        var_k = F[k, k]
        contrib = float((w * b_k) @ (w * b_k)) * var_k
        raw_contributions[name] = max(contrib, 0.0)

    # Cross-factor terms (total systematic - sum of pure factor terms)
    total_systematic = float(w @ systematic_cov @ w)
    pure_factor_sum = sum(raw_contributions.values())
    cross_terms = total_systematic - pure_factor_sum

    # Idiosyncratic contribution: w^T · D · w
    idio_var = float(w @ D @ w)

    # Apportion cross-factor terms proportionally to pure factor contributions
    if pure_factor_sum > 0 and cross_terms != 0:
        for name in factor_names:
            share = raw_contributions[name] / pure_factor_sum
            raw_contributions[name] += cross_terms * share

    # Compute percentages
    market_pct = (raw_contributions["market"] / total_var) * 100
    smb_pct = (raw_contributions["smb"] / total_var) * 100
    hml_pct = (raw_contributions["hml"] / total_var) * 100
    idio_pct = (idio_var / total_var) * 100

    # Clamp negatives to 0 and renormalize to 100%
    raw_pcts = {
        "market_pct": max(market_pct, 0),
        "smb_pct": max(smb_pct, 0),
        "hml_pct": max(hml_pct, 0),
        "idiosyncratic_pct": max(idio_pct, 0),
    }
    total_raw = sum(raw_pcts.values())
    if total_raw > 0:
        scale = 100.0 / total_raw
        for key in raw_pcts:
            raw_pcts[key] *= scale

    # Annualized volatility: sqrt(daily_var × 252) × 100
    annual_vol = float(np.sqrt(total_var * 252) * 100)

    # --- Per-stock contributions for flamegraph drill-down ---
    stock_contributions = _compute_stock_contributions(
        tickers, w, B, F, D, total_var
    )

    return {
        "market_pct": round(raw_pcts["market_pct"], 2),
        "smb_pct": round(raw_pcts["smb_pct"], 2),
        "hml_pct": round(raw_pcts["hml_pct"], 2),
        "idiosyncratic_pct": round(raw_pcts["idiosyncratic_pct"], 2),
        "cross_factor_pct": round((cross_terms / total_var) * 100, 2) if total_var > 0 else 0.0,
        "total_annual_vol": round(annual_vol, 2),
        "total_daily_var": total_var,
        "stock_contributions": stock_contributions,
    }


def _compute_stock_contributions(
    tickers: List[str],
    w: np.ndarray,
    B: np.ndarray,
    F: np.ndarray,
    D: np.ndarray,
    total_var: float,
) -> Dict[str, Dict[str, float]]:
    """
    Compute each stock's contribution to each factor bucket.
    For factor k, stock i's contribution ≈ w_i * beta_ik * (sum_j w_j * beta_jk) * F[k,k].
    For idiosyncratic, stock i's contribution = w_i² * D[i,i].
    """
    n = len(tickers)
    contributions = {}

    for i, ticker in enumerate(tickers):
        # Market beta contribution
        mkt_contrib = w[i] * B[i, 0] * float(w @ B[:, 0]) * F[0, 0]
        smb_contrib = w[i] * B[i, 1] * float(w @ B[:, 1]) * F[1, 1]
        hml_contrib = w[i] * B[i, 2] * float(w @ B[:, 2]) * F[2, 2]
        idio_contrib = (w[i] ** 2) * D[i, i]

        contributions[ticker] = {
            "market_contribution": max(float(mkt_contrib / total_var * 100), 0) if total_var > 0 else 0,
            "smb_contribution": max(float(smb_contrib / total_var * 100), 0) if total_var > 0 else 0,
            "hml_contribution": max(float(hml_contrib / total_var * 100), 0) if total_var > 0 else 0,
            "idio_contribution": max(float(idio_contrib / total_var * 100), 0) if total_var > 0 else 0,
            "weight": float(w[i]),
        }

    return contributions


def _zero_result(tickers, weights):
    return {
        "market_pct": 25.0,
        "smb_pct": 25.0,
        "hml_pct": 25.0,
        "idiosyncratic_pct": 25.0,
        "total_annual_vol": 0.0,
        "total_daily_var": 0.0,
        "stock_contributions": {
            t: {
                "market_contribution": 0, "smb_contribution": 0,
                "hml_contribution": 0, "idio_contribution": 0,
                "weight": weights.get(t, 0),
            }
            for t in tickers
        },
    }


def build_flamegraph_json(
    decomposition: Dict[str, Any],
    betas: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build the hierarchical JSON structure expected by the D3.js flamegraph.
    """
    sc = decomposition["stock_contributions"]
    vol = decomposition["total_annual_vol"]

    def make_factor_children(factor_key: str):
        children = []
        for ticker, contrib in sc.items():
            val = contrib[factor_key]
            if val > 0.5:  # Only show stocks with meaningful contribution
                children.append({
                    "name": ticker,
                    "value": round(val, 2),
                    "meta": {
                        "beta_mkt": betas[ticker]["beta_mkt"],
                        "beta_smb": betas[ticker]["beta_smb"],
                        "beta_hml": betas[ticker]["beta_hml"],
                        "r_squared": betas[ticker]["r_squared"],
                        "weight": contrib["weight"],
                    },
                })
        return sorted(children, key=lambda x: x["value"], reverse=True)

    flamegraph = {
        "name": f"Your Portfolio — {vol:.1f}% Annual Vol",
        "value": 100.0,
        "children": [
            {
                "name": "Market Beta",
                "value": decomposition["market_pct"],
                "factor": "market",
                "children": make_factor_children("market_contribution"),
            },
            {
                "name": "SMB (Size)",
                "value": decomposition["smb_pct"],
                "factor": "smb",
                "children": make_factor_children("smb_contribution"),
            },
            {
                "name": "HML (Value)",
                "value": decomposition["hml_pct"],
                "factor": "hml",
                "children": make_factor_children("hml_contribution"),
            },
            {
                "name": "Idiosyncratic",
                "value": decomposition["idiosyncratic_pct"],
                "factor": "idiosyncratic",
                "children": make_factor_children("idio_contribution"),
            },
        ],
    }

    return flamegraph
