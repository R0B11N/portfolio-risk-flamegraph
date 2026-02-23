"""Portfolio analysis endpoints: /api/analyze and /api/upload-csv."""

import io
import csv
import traceback
from typing import List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from factor_pipeline import analyze_all, download_ff_factors
from decomposition import (
    compute_factor_covariance,
    decompose_portfolio_variance,
    build_flamegraph_json,
)
from insight import generate_insight

router = APIRouter(prefix="/api", tags=["analysis"])




class Position(BaseModel):
    symbol: str
    market_value: float


class AnalyzeRequest(BaseModel):
    positions: List[Position]


class AnalyzeResponse(BaseModel):
    flamegraph: dict
    decomposition: dict
    insight: str
    stock_details: dict




@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_portfolio(request: AnalyzeRequest):
    """
    Main analysis endpoint. Takes positions (symbol + market_value),
    runs the full Fama-French pipeline, and returns flamegraph JSON + insight.
    """
    if not request.positions:
        raise HTTPException(status_code=400, detail="No positions provided")

    # Compute portfolio weights
    total_value = sum(p.market_value for p in request.positions)
    if total_value <= 0:
        raise HTTPException(status_code=400, detail="Total portfolio value must be positive")

    tickers = [p.symbol.upper() for p in request.positions]
    weights = {
        p.symbol.upper(): p.market_value / total_value
        for p in request.positions
    }

    try:
        # 1. Run factor regressions
        betas, ff_df, prices = analyze_all(tickers)

        # 2. Compute factor covariance matrix
        factor_cov = compute_factor_covariance(ff_df)

        # 3. Extract residual variances
        residual_vars = {t: betas[t]["residual_variance"] for t in tickers}

        # 4. Decompose portfolio variance
        decomposition = decompose_portfolio_variance(
            weights, betas, factor_cov, residual_vars
        )

        # 5. Build flamegraph JSON
        flamegraph = build_flamegraph_json(decomposition, betas)

        # 6. Generate insight
        positions_list = [{"symbol": t, "weight": weights[t]} for t in tickers]
        insight = generate_insight(decomposition, positions_list)

        # 7. Compute historical realized vol for sanity check
        realized_vol = None
        try:
            port_returns = sum(
                prices[t].pct_change().dropna() * weights[t]
                for t in tickers if t in prices.columns
            )
            realized_vol = round(float(port_returns.std() * (252 ** 0.5) * 100), 2)
        except Exception:
            pass

        return AnalyzeResponse(
            flamegraph=flamegraph,
            decomposition={
                "market_pct": decomposition["market_pct"],
                "smb_pct": decomposition["smb_pct"],
                "hml_pct": decomposition["hml_pct"],
                "idiosyncratic_pct": decomposition["idiosyncratic_pct"],
                "cross_factor_pct": decomposition.get("cross_factor_pct", 0.0),
                "total_annual_vol": decomposition["total_annual_vol"],
                "realized_vol": realized_vol,
            },
            insight=insight,
            stock_details=betas,
        )

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")




@router.post("/upload-csv")
async def upload_csv(file: UploadFile = File(...)):
    """
    Parse a Wealthsimple CSV export and return normalized positions.
    Expected columns: Symbol, Quantity, Current Price, Market Value
    Also handles simpler formats with just Symbol and Market Value.
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    content = await file.read()
    text = content.decode("utf-8-sig")  # Handle BOM

    try:
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {str(e)}")

    if not rows:
        raise HTTPException(status_code=400, detail="CSV is empty")

    # Normalize column names (case-insensitive, strip whitespace)
    fieldnames = {k.strip().lower(): k for k in rows[0].keys()}

    positions = []
    for row in rows:
        # Try to find symbol column
        symbol = None
        for key_candidate in ["symbol", "ticker", "stock", "security"]:
            if key_candidate in fieldnames:
                symbol = row[fieldnames[key_candidate]].strip()
                break

        if not symbol:
            continue

        # Try to find market value column
        market_value = None
        for key_candidate in ["market value", "marketvalue", "market_value", "value", "total"]:
            if key_candidate in fieldnames:
                raw = row[fieldnames[key_candidate]].strip().replace("$", "").replace(",", "")
                try:
                    market_value = float(raw)
                except ValueError:
                    continue
                break

        # Fallback: compute from quantity × price
        if market_value is None:
            qty_col = None
            price_col = None
            for key_candidate in ["quantity", "qty", "shares", "openquantity"]:
                if key_candidate in fieldnames:
                    qty_col = fieldnames[key_candidate]
                    break
            for key_candidate in ["current price", "price", "currentprice", "last price"]:
                if key_candidate in fieldnames:
                    price_col = fieldnames[key_candidate]
                    break

            if qty_col and price_col:
                try:
                    qty = float(row[qty_col].strip().replace(",", ""))
                    price = float(row[price_col].strip().replace("$", "").replace(",", ""))
                    market_value = qty * price
                except (ValueError, KeyError):
                    continue

        if market_value and market_value > 0:
            # Clean up symbol — remove exchange suffixes if needed
            symbol = symbol.replace(" ", "").upper()
            positions.append({"symbol": symbol, "market_value": round(market_value, 2)})

    if not positions:
        raise HTTPException(
            status_code=400,
            detail="Could not extract any valid positions from CSV. "
                   "Expected columns: Symbol and Market Value (or Quantity + Price)."
        )

    return {"positions": positions}
