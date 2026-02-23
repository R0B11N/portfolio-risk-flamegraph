"""Generate plain-English insight sentences from variance decomposition output."""

from typing import Dict, Any, List


def generate_insight(
    decomposition: Dict[str, Any],
    positions: List[Dict[str, Any]],
) -> str:
    """
    Generate one plain-English insight sentence from the variance decomposition.

    Priority order:
    1. If market_pct > 65% → warn about market concentration
    2. If any single stock contributes > 20% of idiosyncratic risk → name it
    3. If smb_pct > 20% → flag the small-cap bet
    4. Otherwise → top two risk drivers
    """
    market_pct = decomposition["market_pct"]
    smb_pct = decomposition["smb_pct"]
    hml_pct = decomposition["hml_pct"]
    idio_pct = decomposition["idiosyncratic_pct"]
    vol = decomposition["total_annual_vol"]
    stock_contribs = decomposition.get("stock_contributions", {})

    # --- Priority 1: Market concentration ---
    if market_pct > 65:
        return (
            f"{market_pct:.0f}% of your portfolio risk comes from market exposure alone. "
            f"You are less diversified than you think — adding bonds or uncorrelated "
            f"assets would meaningfully reduce your risk."
        )

    # --- Priority 2: Single-stock idiosyncratic concentration ---
    if idio_pct > 10 and stock_contribs:
        total_idio = sum(s.get("idio_contribution", 0) for s in stock_contribs.values())
        if total_idio > 0:
            for ticker, contrib in stock_contribs.items():
                stock_share = (contrib.get("idio_contribution", 0) / total_idio) * 100
                if stock_share > 20:
                    return (
                        f"{ticker} alone accounts for {stock_share:.0f}% of your "
                        f"stock-specific risk — that's a concentrated bet on one company "
                        f"that your factor model can't explain."
                    )

    # --- Priority 3: Small-cap tilt ---
    if smb_pct > 20:
        return (
            f"Your portfolio has a significant small-cap tilt — {smb_pct:.0f}% of your "
            f"risk comes from the size factor. You are effectively betting on "
            f"small-cap stocks outperforming large-caps."
        )

    # --- Priority 4: Value tilt ---
    if hml_pct > 20:
        return (
            f"{hml_pct:.0f}% of your risk is driven by value factor exposure. "
            f"Your portfolio is significantly tilted toward value stocks over growth."
        )

    # --- Priority 5: Top two risk drivers ---
    components = [
        ("market exposure", market_pct),
        ("size factor (SMB)", smb_pct),
        ("value factor (HML)", hml_pct),
        ("stock-specific risk", idio_pct),
    ]
    components.sort(key=lambda x: x[1], reverse=True)

    top1_name, top1_pct = components[0]
    top2_name, top2_pct = components[1]

    return (
        f"Your top risk drivers are {top1_name} ({top1_pct:.0f}%) and "
        f"{top2_name} ({top2_pct:.0f}%), with a total annualized volatility "
        f"of {vol:.1f}%."
    )
