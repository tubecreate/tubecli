"""
PayPal Payment Routes — TubeCLI Market (Proxy Mode)
All PayPal operations are handled by the PHP server.
This module proxies requests from the local dashboard to the PHP API.

Endpoints:
  GET  /api/v1/market/paypal/config            — Proxy to PHP /api/paypal/config.php
  GET  /api/v1/market/paypal/balance           — Proxy to PHP /api/stripe/balance.php (shared balance)
  POST /api/v1/market/paypal/topup-session     — Proxy to PHP /api/paypal/create-session.php
  POST /api/v1/market/paypal/quickpay-session  — Proxy to PHP /api/paypal/create-session.php

Note: IPN is handled directly by PHP at /api/paypal/ipn.php
      (PayPal calls PHP server directly, not through TubeCLI)
"""
import os
from typing import Optional
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

paypal_router = APIRouter(prefix="/paypal", tags=["paypal"])


def _get_php_api_base() -> str:
    """Get the PHP API base URL."""
    try:
        from tubecli.extensions.market.market_service import API_BASE
        # API_BASE = https://api.tubecreate.com/api/market-cli
        # We need https://api.tubecreate.com/api/paypal
        return API_BASE.replace("/api/market-cli", "/api/paypal").replace("/market-cli", "/paypal")
    except Exception:
        return "https://api.tubecreate.com/api/paypal"


def _get_php_stripe_base() -> str:
    """Get the PHP Stripe/Balance API base URL (balance is shared)."""
    try:
        from tubecli.extensions.market.market_service import API_BASE
        return API_BASE.replace("/api/market-cli", "/api/stripe").replace("/market-cli", "/stripe")
    except Exception:
        return "https://api.tubecreate.com/api/stripe"


# ── GET /config ──────────────────────────────────────────────────────────────
@paypal_router.get("/config")
async def paypal_config():
    """Proxy to PHP /api/paypal/config.php — returns credentials + packages."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{_get_php_api_base()}/config.php")
            return r.json()
    except Exception as e:
        return {"client_id": "", "packages": [], "error": str(e)}


# ── GET /balance ─────────────────────────────────────────────────────────────
@paypal_router.get("/balance")
async def get_balance(authorization: Optional[str] = Header(None)):
    """Proxy to PHP /api/stripe/balance.php — returns user credit balance (shared)."""
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
    item_title: str = ""     # ignored by PHP, kept for compatibility
    item_price_credits: float = 0  # ignored by PHP
    success_url: Optional[str] = None
    cancel_url:  Optional[str] = None


class CaptureRequest(BaseModel):
    order_id: str


# ── POST /topup-session ──────────────────────────────────────────────────────
@paypal_router.post("/topup-session")
async def create_topup_session(req: TopUpRequest, authorization: Optional[str] = Header(None)):
    """Proxy to PHP /api/paypal/create-session.php — creates PayPal Checkout Session for TopUp."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Đăng nhập để nạp credits")

    import httpx
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{_get_php_api_base()}/create-session.php",
                json={
                    "type": "topup",
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
        raise HTTPException(500, f"PayPal proxy error: {str(e)}")


# ── POST /quickpay-session ───────────────────────────────────────────────────
@paypal_router.post("/quickpay-session")
async def create_quickpay_session(req: QuickPayRequest, authorization: Optional[str] = Header(None)):
    """Proxy to PHP /api/paypal/create-session.php — creates PayPal Checkout Session for direct purchase."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Đăng nhập để mua sản phẩm")

    import httpx
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{_get_php_api_base()}/create-session.php",
                json={
                    "type": "quickpay",
                    "item_public_id": req.item_public_id,
                    "success_url":    req.success_url or "",
                    "cancel_url":     req.cancel_url or "",
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
        raise HTTPException(500, f"PayPal proxy error: {str(e)}")


# ── POST /capture ────────────────────────────────────────────────────────────
@paypal_router.post("/capture")
async def capture_paypal_order(req: CaptureRequest, authorization: Optional[str] = Header(None)):
    """Proxy to PHP /api/paypal/capture.php — captures payment and updates credits/purchase."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Đăng nhập để hoàn thành giao dịch")

    import httpx
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{_get_php_api_base()}/capture.php",
                json={
                    "order_id": req.order_id,
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
        raise HTTPException(500, f"PayPal capture proxy error: {str(e)}")

