"""
Stripe Payment Routes — TubeCLI Market (Proxy Mode)
All Stripe operations are handled by the PHP server.
This module proxies requests from the local dashboard to the PHP API.

Endpoints:
  GET  /api/v1/market/stripe/config            — Proxy to PHP /api/stripe/config.php
  GET  /api/v1/market/stripe/balance           — Proxy to PHP /api/stripe/balance.php
  POST /api/v1/market/stripe/topup-session     — Proxy to PHP /api/stripe/topup-session.php
  POST /api/v1/market/stripe/quickpay-session  — Proxy to PHP /api/stripe/quickpay-session.php

Note: Webhook is handled directly by PHP at /api/stripe/webhook.php
      (Stripe calls PHP server directly, not through TubeCLI)
"""
import os
from typing import Optional
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

stripe_router = APIRouter(prefix="/stripe", tags=["stripe"])


def _get_php_stripe_base() -> str:
    """Get the PHP Stripe API base URL."""
    try:
        from tubecli.extensions.market.market_service import API_BASE
        # API_BASE = https://api.tubecreate.com/api/market-cli
        # Stripe base = https://api.tubecreate.com/api/stripe
        return API_BASE.replace("/api/market-cli", "/api/stripe").replace("/market-cli", "/stripe")
    except Exception:
        return "https://api.tubecreate.com/api/stripe"


# ── GET /config ──────────────────────────────────────────────────────────────
@stripe_router.get("/config")
async def stripe_config():
    """Proxy to PHP /api/stripe/config.php — returns publishable key + packages."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{_get_php_stripe_base()}/config.php")
            return r.json()
    except Exception as e:
        return {"publishable_key": "", "packages": [], "error": str(e)}


# ── GET /balance ─────────────────────────────────────────────────────────────
@stripe_router.get("/balance")
async def get_balance(authorization: Optional[str] = Header(None)):
    """Proxy to PHP /api/stripe/balance.php — returns user credit balance."""
    if not authorization:
        return {"balance": 0, "error": "Not authenticated"}
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{_get_php_stripe_base()}/balance.php",
                headers={"Authorization": authorization},
            )
            return r.json()
    except Exception as e:
        return {"balance": 0, "error": str(e)}


# ── Pydantic models ─────────────────────────────────────────────────────────
class TopUpRequest(BaseModel):
    package_id: str          # starter | pro | power | ultimate
    success_url: Optional[str] = None
    cancel_url:  Optional[str] = None


class QuickPayRequest(BaseModel):
    item_public_id: str      # market item to purchase
    item_title: str = ""     # ignored by PHP (looked up from DB), kept for compatibility
    item_price_credits: float = 0  # ignored by PHP (looked up from DB)
    success_url: Optional[str] = None
    cancel_url:  Optional[str] = None


# ── POST /topup-session ──────────────────────────────────────────────────────
@stripe_router.post("/topup-session")
async def create_topup_session(req: TopUpRequest, authorization: Optional[str] = Header(None)):
    """Proxy to PHP /api/stripe/topup-session.php — creates Stripe Checkout Session for TopUp."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Đăng nhập để nạp credits")

    import httpx
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{_get_php_stripe_base()}/topup-session.php",
                json={
                    "package_id":  req.package_id,
                    "success_url": req.success_url or "",
                    "cancel_url":  req.cancel_url or "",
                },
                headers={"Authorization": authorization},
            )
            data = r.json()
            if r.status_code >= 400:
                raise HTTPException(r.status_code, data.get("error", "PHP server error"))
            return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Stripe proxy error: {str(e)}")


# ── POST /quickpay-session ───────────────────────────────────────────────────
@stripe_router.post("/quickpay-session")
async def create_quickpay_session(req: QuickPayRequest, authorization: Optional[str] = Header(None)):
    """Proxy to PHP /api/stripe/quickpay-session.php — creates Stripe Checkout Session for direct purchase."""
    import httpx
    headers = {}
    if authorization:
        headers["Authorization"] = authorization

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{_get_php_stripe_base()}/quickpay-session.php",
                json={
                    "item_public_id": req.item_public_id,
                    "success_url":    req.success_url or "",
                    "cancel_url":     req.cancel_url or "",
                },
                headers=headers,
            )
            data = r.json()
            if r.status_code >= 400:
                raise HTTPException(r.status_code, data.get("error", "PHP server error"))
            return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Stripe proxy error: {str(e)}")
