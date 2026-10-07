"""
Card payment providers that accept Albanian businesses.

* **POK** (pokpay.io): REST API. We create an "SDK order" and send the guest to its confirm URL.
  POK posts to our webhook when the order changes; we then read the order back from POK
  (never trusting the webhook body on its own).
* **Paysera** (Checkout Classic / WebToPay): signed redirect. Paysera calls our callback URL with
  signed data (ss1 = md5(data + project password)); status 1 means paid.
"""

import base64
import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from django.utils.translation import gettext as _

log = logging.getLogger(__name__)


class ProviderError(Exception):
    pass


@dataclass
class Checkout:
    url: str
    external_id: str


@dataclass
class Result:
    paid: bool
    external_id: str = ""
    amount_minor: int | None = None
    currency: str = ""
    uncertain: bool = False  # the provider answered but didn't say clearly whether it is paid


def _http(method: str, url: str, body: dict | None = None, headers: dict | None = None, timeout: int = 20) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  (fixed provider URLs)
            raw = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        raise ProviderError(f"HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ProviderError(str(getattr(e, "reason", e))) from e
    try:
        return json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError as e:
        raise ProviderError(_("The payment provider sent an unexpected answer.")) from e


# ---------- POK ----------


class Pok:
    name = "pok"
    CURRENCIES = {"ALL", "EUR"}

    def __init__(self, key_id: str, key_secret: str, merchant_id: str, test: bool):
        self.key_id, self.key_secret, self.merchant_id = key_id, key_secret, merchant_id
        self.base = "https://api-staging.pokpay.io" if test else "https://api.pokpay.io"

    def _token(self) -> str:
        res = _http("POST", f"{self.base}/auth/sdk/login", {"keyId": self.key_id, "keySecret": self.key_secret})
        token = (res.get("data") or {}).get("accessToken")
        if not token:
            raise ProviderError(_("POK refused the key ID or key secret."))
        return token

    def create(self, link, *, return_url: str, webhook_url: str) -> Checkout:
        if link.currency not in self.CURRENCIES:
            raise ProviderError(_("POK accepts only ALL and EUR."))
        res = _http(
            "POST",
            f"{self.base}/merchants/{urllib.parse.quote(self.merchant_id)}/sdk-orders",
            {
                "amount": f"{link.amount:.2f}",
                "currencyCode": link.currency,
                "autoCapture": True,
                "products": [],
                "description": link.description[:200],
                "merchantCustomReference": link.token,
                "redirectUrl": return_url,
                "webhookUrl": webhook_url,
            },
            {"Authorization": self._token()},
        )
        order = (res.get("data") or {}).get("sdkOrder") or {}
        url = (order.get("_self") or order.get("self") or {}).get("confirmUrl")
        if not order.get("id") or not url:
            raise ProviderError(_("POK did not return a payment page."))
        return Checkout(url=url, external_id=order["id"])

    @staticmethod
    def _is_paid(order: dict) -> bool | None:
        for key in ("isCompleted", "isCaptured", "isPaid", "completed", "captured"):
            if order.get(key) is True:
                return True
        status = str(order.get("status") or order.get("state") or "").upper()
        if status in {"COMPLETED", "CAPTURED", "PAID", "SUCCEEDED", "SUCCESS", "CONFIRMED"}:
            return True
        if status in {"FAILED", "CANCELLED", "CANCELED", "EXPIRED", "REJECTED"}:
            return False
        for key in ("capturedAt", "completedAt", "paidAt", "confirmedAt"):
            if order.get(key):
                return True
        if order.get("transactions") or order.get("transaction"):
            return True
        return None

    def check(self, external_id: str) -> Result:
        res = _http(
            "GET", f"{self.base}/sdk-orders/{urllib.parse.quote(external_id)}", headers={"Authorization": self._token()}
        )
        order = (res.get("data") or {}).get("sdkOrder") or {}
        if order.get("id") != external_id:
            raise ProviderError(_("POK did not find this order."))
        paid = self._is_paid(order)
        amount = order.get("finalAmount") or order.get("amount")
        return Result(
            paid=bool(paid),
            external_id=external_id,
            amount_minor=round(float(amount) * 100) if amount is not None else None,
            currency=order.get("currencyCode", ""),
            uncertain=paid is None,
        )


# ---------- Paysera ----------


class Paysera:
    name = "paysera"
    PAY_URL = "https://bank.paysera.com/pay/"

    def __init__(self, project_id: str, password: str, test: bool):
        self.project_id, self.password, self.test = str(project_id), password, test

    @staticmethod
    def encode(params: dict) -> str:
        return base64.b64encode(urllib.parse.urlencode(params).encode()).decode().translate(str.maketrans("+/", "-_"))

    @staticmethod
    def decode(data: str) -> dict:
        raw = base64.b64decode(data.translate(str.maketrans("-_", "+/")) + "=" * (-len(data) % 4))
        return dict(urllib.parse.parse_qsl(raw.decode("utf-8"), keep_blank_values=True))

    def sign(self, data: str) -> str:
        return hashlib.md5((data + self.password).encode()).hexdigest()  # noqa: S324  (Paysera's protocol)

    def create(self, link, *, return_url: str, cancel_url: str, callback_url: str, lang: str = "ENG") -> Checkout:
        params = {
            "projectid": self.project_id,
            "orderid": link.token,
            "accepturl": return_url,
            "cancelurl": cancel_url,
            "callbackurl": callback_url,
            "version": "1.6",
            "amount": str(link.minor_units),
            "currency": link.currency,
            "paytext": link.description[:255],
            "lang": lang,
            "test": "1" if self.test else "0",
        }
        if link.email:
            params["p_email"] = link.email
        data = self.encode(params)
        return Checkout(
            url=f"{self.PAY_URL}?{urllib.parse.urlencode({'data': data, 'sign': self.sign(data)})}",
            external_id=link.token,
        )

    def parse_callback(self, data: str, ss1: str) -> tuple[dict, Result]:
        if not data or not ss1 or not hmac.compare_digest(self.sign(data), ss1):
            raise ProviderError("bad signature")
        params = self.decode(data)
        if params.get("projectid") != self.project_id:
            raise ProviderError("wrong project")
        amount = params.get("amount", "")
        return params, Result(
            paid=params.get("status") == "1",
            external_id=params.get("requestid", ""),
            amount_minor=int(amount) if amount.isdigit() else None,
            currency=params.get("currency", ""),
        )


def get_provider(hs):
    if not hs.payments_configured:
        return None
    if hs.payment_provider == "pok":
        return Pok(hs.pok_key_id, hs.pok_key_secret, hs.pok_merchant_id, hs.payment_test_mode)
    if hs.payment_provider == "paysera":
        return Paysera(hs.paysera_project_id, hs.paysera_password, hs.payment_test_mode)
    return None
