"""
Stripe Payment Routes — TubeCLI Market
Endpoints:
  GET  /api/v1/market/stripe/config            — Publishable key + packages
  GET  /api/v1/market/stripe/balance           — User credit balance
  POST /api/v1/market/stripe/topup-session     — Create TopUp Checkout Session
  POST /api/v1/market/stripe/quickpay-session  — Create Quick Pay (direct item purchase)
  POST /api/v1/market/stripe/webhook           — Stripe webhook receiver
"""
import json
import os
import hashlib
import hmac
import time
from typing import Optional
from fastapi import APIRouter, Request, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

stripe_router = APIRouter(prefix="/stripe", tags=["stripe"])

# ── Credit Packages ──────────────────────────────────────────────────────────
CREDIT_PACKAGES = [
    {"id": "starter",  "name": "Starter",  "credits": 50,   "price_usd": 5.00,  "badge": None,     "color": "#6366f1"},
    {"id": "pro",      "name": "Pro",       "credits": 150,  "price_usd": 12.00, "badge": "Popular","color": "#8b5cf6"},
    {"id": "power",    "name": "Power",     "credits": 500,  "price_usd": 35.00, "badge": "Best Value","color": "#a855f7"},
    {"id": "ultimate", "name": "Ultimate",  "credits": 1500, "price_usd": 90.00, "badge": "Pro",    "color": "#ec4899"},
]

# ── Settings Helpers ─────────────────────────────────────────────────────────
def _get_stripe_settings() -> dict:
    """Read Stripe keys from global_settings.json or environment."""
    # Try env first
    sk = os.environ.get("STRIPE_SECRET_KEY", "")
    pk = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
    ws = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    if not sk:
        try:
            from tubecli.config import DATA_DIR
            settings_path = os.path.join(str(DATA_DIR), "global_settings.json")
            if os.path.exists(settings_path):
                with open(settings_path, "r", encoding="utf-8") as f:
                    s = json.load(f)
                sk = s.get("stripe_secret_key", "")
                pk = s.get("stripe_publishable_key", "")
                ws = s.get("stripe_webhook_secret", "")
        except Exception:
            pass

    # Fallback to environment variables
    if not sk:
        sk = os.environ.get("STRIPE_SECRET_KEY", "")
    if not pk:
        pk = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")

    return {"secret_key": sk, "publishable_key": pk, "webhook_secret": ws}


def _get_stripe():
    """Initialize and return stripe module."""
    try:
        import stripe as _stripe
        cfg = _get_stripe_settings()
        _stripe.api_key = cfg["secret_key"]
        return _stripe
    except ImportError:
        raise HTTPException(503, "stripe library not installed. Run: pip install stripe")


def _get_market_api_base() -> str:
    from tubecli.extensions.market.market_service import API_BASE
    return API_BASE


def _get_php_credits_base() -> str:
    """PHP credits API base — same host as market API."""
    base = _get_market_api_base()
    # e.g. https://api.tubecreate.com/api/market-cli → https://api.tubecreate.com/api/credits
    return base.replace("/api/market-cli", "/api/credits").replace("/market-cli", "/credits")


# ── GET /config ──────────────────────────────────────────────────────────────
@stripe_router.get("/config")
async def stripe_config():
    """Return Stripe publishable key and credit packages (safe for frontend)."""
    cfg = _get_stripe_settings()
    return {
        "publishable_key": cfg["publishable_key"],
        "packages": CREDIT_PACKAGES,
        "currency": "usd",
    }


# ── GET /balance ─────────────────────────────────────────────────────────────
@stripe_router.get("/balance")
async def get_balance(authorization: Optional[str] = Header(None)):
    """Proxy to PHP get_balance.php to get user credit balance."""
    if not authorization:
        return {"balance": 0, "error": "Not authenticated"}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{_get_php_credits_base()}/get_balance.php",
                headers={"Authorization": authorization},
            )
            data = r.json()
            return {"balance": data.get("balance", 0), "status": "success"}
    except Exception as e:
        return {"balance": 0, "error": str(e)}


# ── Pydantic models ──────────────────────────────────────────────────────────
class TopUpRequest(BaseModel):
    package_id: str          # starter | pro | power | ultimate
    success_url: Optional[str] = None
    cancel_url:  Optional[str] = None


class QuickPayRequest(BaseModel):
    item_public_id: str      # market item to purchase
    item_title: str
    item_price_credits: float
    success_url: Optional[str] = None
    cancel_url:  Optional[str] = None


# ── POST /topup-session ──────────────────────────────────────────────────────
@stripe_router.post("/topup-session")
async def create_topup_session(req: TopUpRequest, authorization: Optional[str] = Header(None)):
    """
    Create a Stripe Checkout Session for buying credits.
    Returns: { checkout_url, session_id }
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Đăng nhập để nạp credits")

    token = authorization.replace("Bearer ", "")

    # Resolve package
    pkg = next((p for p in CREDIT_PACKAGES if p["id"] == req.package_id), None)
    if not pkg:
        raise HTTPException(400, f"Package '{req.package_id}' không tồn tại")

    # Get username from PHP API
    username = await _resolve_username(token)
    if not username:
        raise HTTPException(401, "Không xác định được tài khoản")

    stripe = _get_stripe()
    amount_cents = int(pkg["price_usd"] * 100)

    # Build return URLs
    base_url = req.success_url or "http://localhost:5295/market"
    success_url = f"{base_url}?stripe_success=1&package={pkg['id']}&credits={pkg['credits']}"
    cancel_url  = req.cancel_url or f"{base_url}?stripe_cancel=1"

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": amount_cents,
                    "product_data": {
                        "name": f"TubeCLI Credits — {pkg['name']} ({pkg['credits']} credits)",
                        "description": f"Nạp {pkg['credits']} credits vào tài khoản {username}",
                        "images": [],
                    },
                },
                "quantity": 1,
            }],
            metadata={
                "type":     "topup",
                "username": username,
                "token":    token[:32],     # partial token for logging only
                "credits":  str(pkg["credits"]),
                "package":  pkg["id"],
            },
            success_url=success_url,
            cancel_url=cancel_url,
            # Optional: prefill email if known
            # customer_email=user_email,
        )
        return {"status": "success", "checkout_url": session.url, "session_id": session.id}
    except Exception as e:
        raise HTTPException(500, f"Stripe error: {str(e)}")


# ── POST /quickpay-session ───────────────────────────────────────────────────
@stripe_router.post("/quickpay-session")
async def create_quickpay_session(req: QuickPayRequest, authorization: Optional[str] = Header(None)):
    """
    Create a Stripe Checkout Session for direct item purchase (no credits).
    Price is calculated as: credits × $0.10/credit
    Returns: { checkout_url, session_id }
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Đăng nhập để mua item")

    token = authorization.replace("Bearer ", "")
    username = await _resolve_username(token)
    if not username:
        raise HTTPException(401, "Không xác định được tài khoản")

    stripe = _get_stripe()

    # Convert credits to USD: 1 credit = $0.10
    price_usd   = req.item_price_credits * 0.10
    amount_cents = int(price_usd * 100)

    if amount_cents < 50:  # Stripe minimum $0.50
        amount_cents = 50

    base_url    = req.success_url or "http://localhost:5295/market"
    success_url = f"{base_url}?stripe_quickpay_success=1&item_id={req.item_public_id}"
    cancel_url  = req.cancel_url or f"{base_url}?stripe_cancel=1"

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": amount_cents,
                    "product_data": {
                        "name": f"TubeCLI Market — {req.item_title}",
                        "description": f"Mua extension '{req.item_title}' — {req.item_price_credits} credits",
                    },
                },
                "quantity": 1,
            }],
            metadata={
                "type":         "quickpay",
                "username":     username,
                "token":        token[:32],
                "item_id":      req.item_public_id,
                "item_title":   req.item_title,
                "credits_cost": str(req.item_price_credits),
            },
            success_url=success_url,
            cancel_url=cancel_url,
        )
        return {"status": "success", "checkout_url": session.url, "session_id": session.id}
    except Exception as e:
        raise HTTPException(500, f"Stripe error: {str(e)}")


# ── POST /webhook ────────────────────────────────────────────────────────────
@stripe_router.post("/webhook")
async def stripe_webhook(request: Request):
    """
    Receive Stripe webhook events. Verify signature, then:
    - checkout.session.completed (topup)    → add credits to user
    - checkout.session.completed (quickpay) → mark item as purchased
    """
    payload     = await request.body()
    sig_header  = request.headers.get("stripe-signature", "")
    cfg         = _get_stripe_settings()
    webhook_secret = cfg.get("webhook_secret", "")

    try:
        stripe = _get_stripe()
        if webhook_secret and webhook_secret != "whsec_":
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        else:
            # Dev mode: no signature verification
            event = stripe.Event.construct_from(
                json.loads(payload), stripe.api_key
            )
    except Exception as e:
        raise HTTPException(400, f"Webhook error: {str(e)}")

    event_type = event["type"]
    session    = event["data"]["object"]

    if event_type == "checkout.session.completed":
        payment_status = session.get("payment_status", "")
        metadata       = session.get("metadata", {})
        session_id     = session.get("id", "")
        event_type_m   = metadata.get("type", "topup")

        if payment_status == "paid":
            if event_type_m == "topup":
                await _handle_topup(metadata, session_id)
            elif event_type_m == "quickpay":
                await _handle_quickpay(metadata, session_id)

    return {"received": True, "event": event_type}


# ── Helpers ──────────────────────────────────────────────────────────────────
async def _resolve_username(token: str) -> Optional[str]:
    """Get username from token — tries local market auth DB first, then PHP API."""
    # 1. Try local market auth (fast, no network)
    try:
        from tubecli.extensions.market.market_service import market_service
        # market_service caches the logged-in user profile
        profile = getattr(market_service, '_cached_profile', None)
        if profile:
            uname = profile.get('username') or profile.get('user_id') or profile.get('id')
            if uname:
                return str(uname)
    except Exception:
        pass

    # 2. Try PHP API (network call)
    try:
        import httpx
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.get(
                f"{_get_market_api_base()}/user.php",
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code == 200:
                data = r.json()
                profile = data.get("profile") or data.get("user") or data
                uname = profile.get("username") or profile.get("user_id")
                if uname:
                    return str(uname)
    except Exception as e:
        print(f"[Stripe] PHP resolve_username error: {e}")

    # 3. Fallback: use first 16 chars of token as identifier (allows checkout to proceed)
    #    The webhook will receive the metadata and can re-verify
    if token and len(token) >= 8:
        return f"user_{token[:12]}"

    return None


async def _handle_topup(metadata: dict, session_id: str):
    """Add credits to user via PHP add_credits.php."""
    username = metadata.get("username", "")
    credits  = int(metadata.get("credits", 0))
    package  = metadata.get("package", "")

    if not username or credits <= 0:
        print(f"[Stripe Webhook] TopUp: missing metadata username={username} credits={credits}")
        return

    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{_get_php_credits_base()}/add_credits.php",
                json={
                    "username":    username,
                    "amount":      credits,
                    "order_id":    session_id,
                    "description": f"Stripe TopUp — {package} ({credits} credits)",
                },
                headers={"X-Internal-Secret": "tubecli_internal_2026"},
            )
            result = r.json()
            print(f"[Stripe Webhook] TopUp result for {username}: {result}")
    except Exception as e:
        print(f"[Stripe Webhook] TopUp failed for {username}: {e}")


async def _handle_quickpay(metadata: dict, session_id: str):
    """Mark item as purchased via PHP buy.php after Quick Pay."""
    username   = metadata.get("username", "")
    item_id    = metadata.get("item_id", "")
    item_title = metadata.get("item_title", "")

    if not username or not item_id:
        return

    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            # Tell market PHP to mark as purchased (bypassing credit check)
            r = await client.post(
                f"{_get_market_api_base()}/buy.php",
                json={
                    "item_id":        item_id,
                    "stripe_session": session_id,
                    "bypass_credits": True,
                },
                headers={"X-Internal-Secret": "tubecli_internal_2026"},
            )
            result = r.json()
            print(f"[Stripe Webhook] QuickPay purchase for {username} item={item_id}: {result}")
    except Exception as e:
        print(f"[Stripe Webhook] QuickPay mark-purchased failed: {e}")
