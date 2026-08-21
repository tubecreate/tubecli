"""
PayPal Payment Routes — TubeCLI Market (Proxy Mode)
All PayPal operations are handled by the PHP server.
This module proxies requests from the local dashboard to the PHP API.

Endpoints:
  GET  /api/v1/market/paypal/config            — Proxy to PHP /api/paypal/config.php
  GET  /api/v1/market/paypal/balance           — Proxy to PHP /api/stripe/balance.php (shared balance)
  POST /api/v1/market/paypal/topup-session     — Worker market-cli/paypal/topup-session (ví USD chung cloud)
  POST /api/v1/market/paypal/quickpay-session  — Worker market-cli/paypal/quickpay-session

Note: capture xác nhận trực tiếp với PayPal ở Worker (idempotent theo capture_id) — không còn IPN PHP.
      Crypto (NOWPayments) CHƯA hợp nhất, vẫn gọi PHP /api/order/usdt-create.php.
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
        # Thanh toán HỢP NHẤT với cloud: cùng ví USD, cùng PayPal, cùng user —
        # phục vụ tại market.tubecreate.com/api/market-cli/paypal/* (Worker), không còn PHP.
        return f"{API_BASE}/paypal"
    except Exception:
        return "https://market.tubecreate.com/api/market-cli/paypal"


def _get_php_stripe_base() -> str:
    """Get the PHP Stripe/Balance API base URL (balance is shared)."""
    try:
        from tubecli.extensions.market.market_service import API_BASE
        return f"{API_BASE}/stripe"
    except Exception:
        return "https://market.tubecreate.com/api/market-cli/stripe"


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
                f"{_get_php_api_base()}/topup-session.php",
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
                f"{_get_php_api_base()}/quickpay-session.php",
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
                print(f"[PayPal Capture Error] HTTP Status: {r.status_code}")
                print(f"[PayPal Capture Error] Response Data: {data}")
                raise HTTPException(r.status_code, data.get("error", "PHP server error"))
            return data
    except HTTPException:
        raise
    except Exception as e:
        print(f"[PayPal Capture Proxy Exception] Error: {str(e)}")
        raise HTTPException(500, f"PayPal capture proxy error: {str(e)}")


# ── Pydantic models for Crypto ────────────────────────────────────────────────
class CryptoTopUpRequest(BaseModel):
    package_id: str          # starter | pro | power | ultimate
    currency: str            # usdttrc20 | usdtbsc | btc | eth | …
    username: Optional[str] = None   # KHÔNG dùng nữa — user suy từ Bearer token; giữ để client cũ không lỗi


def _crypto_base() -> str:
    return f"{_get_php_api_base().rsplit('/paypal', 1)[0]}/crypto"


# ── POST /crypto-session ──────────────────────────────────────────────────────
@paypal_router.post("/crypto-session")
async def create_crypto_session(req: CryptoTopUpRequest, authorization: Optional[str] = Header(None)):
    """Crypto HỢP NHẤT với cloud (NOWPayments trên Worker): cùng ví USD, cùng user.

    Khác bản PHP cũ: (1) bắt buộc Bearer — trước đây client tự khai username, ai cũng giả
    được; (2) gói lạ bị từ chối thay vì mặc định $5; (3) Worker trả thêm payment_id +
    expires_at để UI poll trạng thái và hiện hạn thật.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Đăng nhập để nạp crypto")
    import httpx
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{_crypto_base()}/create.php",
                json={"package_id": req.package_id, "currency": req.currency},
                headers={"Authorization": authorization},
            )
            data = r.json()
            if r.status_code >= 400:
                raise HTTPException(r.status_code, data.get("error") or data.get("message") or "Lỗi tạo đơn crypto")
            return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Crypto proxy error: {str(e)}")


# ── GET /crypto-status ────────────────────────────────────────────────────────
@paypal_router.get("/crypto-status")
async def crypto_status(payment_id: str, authorization: Optional[str] = Header(None)):
    """Poll trạng thái đơn crypto. Worker tự hỏi NOWPayments + cộng ví (idempotent) nếu xong."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Đăng nhập để xem trạng thái")
    import httpx
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                f"{_crypto_base()}/status.php",
                params={"payment_id": payment_id},
                headers={"Authorization": authorization},
            )
            data = r.json()
            if r.status_code >= 400:
                raise HTTPException(r.status_code, data.get("error") or "Lỗi trạng thái crypto")
            return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Crypto status error: {str(e)}")


