"""Questrade OAuth integration: one-time portfolio fetch, token discarded."""

import os
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/auth", tags=["questrade"])

# Read from environment — user must provide these in .env
QUESTRADE_CLIENT_ID = os.getenv("QUESTRADE_CLIENT_ID", "")
QUESTRADE_REDIRECT_URI = os.getenv("QUESTRADE_REDIRECT_URI", "http://localhost:8000/auth/callback")

# Questrade OAuth URLs
QUESTRADE_AUTH_URL = "https://login.questrade.com/oauth2/authorize"
QUESTRADE_TOKEN_URL = "https://login.questrade.com/oauth2/token"


@router.get("/questrade")
async def questrade_auth():
    """
    Redirect user to Questrade's OAuth authorization page.
    """
    if not QUESTRADE_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="Questrade OAuth is not configured. Set QUESTRADE_CLIENT_ID in .env"
        )

    params = {
        "client_id": QUESTRADE_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": QUESTRADE_REDIRECT_URI,
    }
    auth_url = f"{QUESTRADE_AUTH_URL}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def questrade_callback(code: str = Query(...)):
    """
    Exchange the authorization code for an access token,
    fetch account positions, then DISCARD the token immediately.
    """
    if not QUESTRADE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Questrade OAuth not configured")

    access_token = None
    api_server = None

    try:
        # 1. Exchange code for access token
        token_resp = requests.post(
            QUESTRADE_TOKEN_URL,
            data={
                "client_id": QUESTRADE_CLIENT_ID,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": QUESTRADE_REDIRECT_URI,
            },
            timeout=15,
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()

        access_token = token_data["access_token"]
        api_server = token_data["api_server"]  # e.g. "https://api01.iq.questrade.com/"

        headers = {"Authorization": f"Bearer {access_token}"}

        # 2. Fetch accounts
        accounts_resp = requests.get(
            f"{api_server}v1/accounts",
            headers=headers,
            timeout=15,
        )
        accounts_resp.raise_for_status()
        accounts = accounts_resp.json().get("accounts", [])

        if not accounts:
            raise HTTPException(status_code=404, detail="No accounts found")

        # 3. Fetch positions from each account
        all_positions = []
        for account in accounts:
            account_id = account["number"]
            pos_resp = requests.get(
                f"{api_server}v1/accounts/{account_id}/positions",
                headers=headers,
                timeout=15,
            )
            pos_resp.raise_for_status()
            positions = pos_resp.json().get("positions", [])

            for pos in positions:
                symbol = pos.get("symbol", "")
                market_value = pos.get("currentMarketValue", 0)

                if symbol and market_value and market_value > 0:
                    # Questrade uses .TO suffix for TSX stocks — keep as-is for yfinance
                    all_positions.append({
                        "symbol": symbol,
                        "market_value": round(float(market_value), 2),
                    })

        if not all_positions:
            raise HTTPException(status_code=404, detail="No positions with market value found")

        return {
            "positions": all_positions,
            "token_discarded": True,
            "message": "Positions fetched successfully. Access token has been discarded.",
        }

    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Questrade API error: {str(e)}")

    finally:
        # CRITICAL: Discard token — never store it
        access_token = None
        api_server = None
