"""
tests/test_pipeline.py — Automated Tests for Factor Pipeline & Decomposition

Run with: py -m pytest tests/test_pipeline.py -v
"""

import sys
import os
import pytest

# Add parent dir to path so we can import backend modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestFamaFrenchDownload:
    """Test that we can download and parse Fama-French factor data."""

    def test_download_ff_factors(self):
        from factor_pipeline import download_ff_factors
        df = download_ff_factors()

        assert not df.empty, "FF factor DataFrame should not be empty"
        assert "Mkt-RF" in df.columns
        assert "SMB" in df.columns
        assert "HML" in df.columns
        assert "RF" in df.columns
        assert len(df) > 100, "Should have at least 100 days of factor data"

    def test_ff_data_is_decimal(self):
        from factor_pipeline import download_ff_factors
        df = download_ff_factors()

        # Should be in decimal form (e.g. 0.01), not percent (e.g. 1.0)
        assert abs(df["Mkt-RF"].mean()) < 0.05, "Mkt-RF mean should be near 0 in decimal form"


class TestPriceFetching:
    """Test stock price fetching."""

    def test_fetch_single_us_stock(self):
        from factor_pipeline import fetch_prices
        prices = fetch_prices(["AAPL"])

        assert not prices.empty, "Should get price data for AAPL"
        assert "AAPL" in prices.columns
        assert len(prices) > 100, "Should have at least 100 days of prices"

    def test_tsx_ticker_detection(self):
        from factor_pipeline import _is_tsx_ticker
        assert _is_tsx_ticker("SHOP.TO") is True
        assert _is_tsx_ticker("RY.TO") is True
        assert _is_tsx_ticker("ABC.V") is True
        assert _is_tsx_ticker("AAPL") is False
        assert _is_tsx_ticker("MSFT") is False


class TestFactorRegression:
    """Test OLS regression outputs are sensible."""

    def test_aapl_beta_range(self):
        """AAPL market beta should be roughly 1.0-1.6 (known ballpark)."""
        from factor_pipeline import analyze_all
        results, ff_df, prices = analyze_all(["AAPL"])

        aapl = results["AAPL"]
        assert aapl["sufficient_data"] is True, "AAPL should have sufficient data"
        assert 0.7 <= aapl["beta_mkt"] <= 2.0, f"AAPL beta_mkt={aapl['beta_mkt']:.3f} outside expected range"
        assert aapl["r_squared"] > 0.2, f"AAPL R²={aapl['r_squared']:.3f} too low"
        assert aapl["n_observations"] >= 60, "Should have at least 60 observations"

    def test_insufficient_data_handling(self):
        """A very new or invalid ticker should return sufficient_data=False."""
        from factor_pipeline import _empty_result
        result = _empty_result("FAKE")
        assert result["sufficient_data"] is False


class TestVarianceDecomposition:
    """Test that variance decomposition math is correct."""

    def test_decomposition_sums_to_100(self):
        """Factor percentages should sum to approximately 100%."""
        from factor_pipeline import analyze_all
        from decomposition import compute_factor_covariance, decompose_portfolio_variance

        tickers = ["AAPL", "MSFT"]
        results, ff_df, prices = analyze_all(tickers)

        factor_cov = compute_factor_covariance(ff_df)
        weights = {"AAPL": 0.6, "MSFT": 0.4}
        residual_vars = {t: results[t]["residual_variance"] for t in tickers}

        decomp = decompose_portfolio_variance(weights, results, factor_cov, residual_vars)

        total = (
            decomp["market_pct"] +
            decomp["smb_pct"] +
            decomp["hml_pct"] +
            decomp["idiosyncratic_pct"]
        )
        assert abs(total - 100.0) < 1.0, f"Decomposition sums to {total:.1f}%, should be ~100%"

    def test_annual_vol_positive(self):
        from factor_pipeline import analyze_all
        from decomposition import compute_factor_covariance, decompose_portfolio_variance

        tickers = ["AAPL"]
        results, ff_df, prices = analyze_all(tickers)

        factor_cov = compute_factor_covariance(ff_df)
        weights = {"AAPL": 1.0}
        residual_vars = {"AAPL": results["AAPL"]["residual_variance"]}

        decomp = decompose_portfolio_variance(weights, results, factor_cov, residual_vars)
        assert decomp["total_annual_vol"] > 0, "Annual vol should be positive"
        assert decomp["total_annual_vol"] < 200, "Annual vol should be < 200%"

    def test_cross_factor_pct_returned(self):
        """Should return cross_factor_pct key."""
        from factor_pipeline import analyze_all
        from decomposition import compute_factor_covariance, decompose_portfolio_variance

        tickers = ["AAPL"]
        results, ff_df, prices = analyze_all(tickers)

        factor_cov = compute_factor_covariance(ff_df)
        weights = {"AAPL": 1.0}
        residual_vars = {"AAPL": results["AAPL"]["residual_variance"]}

        decomp = decompose_portfolio_variance(weights, results, factor_cov, residual_vars)
        assert "cross_factor_pct" in decomp, "Should return cross_factor_pct"


class TestInsight:
    """Test insight generation."""

    def test_market_concentration_insight(self):
        from insight import generate_insight
        decomp = {
            "market_pct": 80.0,
            "smb_pct": 5.0,
            "hml_pct": 5.0,
            "idiosyncratic_pct": 10.0,
            "total_annual_vol": 20.0,
            "stock_contributions": {},
        }
        insight = generate_insight(decomp, [])
        assert "market" in insight.lower(), "Should mention market exposure"
        assert len(insight) > 20, "Insight should be a full sentence"

    def test_smb_tilt_insight(self):
        from insight import generate_insight
        decomp = {
            "market_pct": 40.0,
            "smb_pct": 35.0,
            "hml_pct": 10.0,
            "idiosyncratic_pct": 15.0,
            "total_annual_vol": 25.0,
            "stock_contributions": {},
        }
        insight = generate_insight(decomp, [])
        assert "small" in insight.lower() or "smb" in insight.lower() or "size" in insight.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
