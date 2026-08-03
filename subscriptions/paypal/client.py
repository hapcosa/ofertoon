"""Cliente mínimo y estricto para PayPal Subscriptions.

PORT de `signalsTrading/dashboard/backend/paypal_client.py`, sin tocar la
lógica: la separación entre error determinista (`PayPalAPIError`), problema de
configuración (`PayPalConfigurationError`) y falla reintentable
(`PayPalUnavailable`) es lo que hace que el bot sepa si mostrar "reintentá" o
"no está configurado". Solo cambia el `brand_name`.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os
import time
from typing import Any
from urllib.parse import urlsplit

import httpx


class PayPalConfigurationError(RuntimeError):
    """Configuración local o respuesta PayPal incompatible con el checkout."""


class PayPalAPIError(RuntimeError):
    """PayPal rechazó de forma determinista la solicitud."""


class PayPalUnavailable(RuntimeError):
    """PayPal no respondió de forma concluyente; la operación puede reintentarse."""


@dataclass(frozen=True)
class PayPalPlan:
    id: str
    product_id: str
    name: str
    price_usd: Decimal
    has_trial: bool


@dataclass(frozen=True)
class PayPalSubscription:
    id: str
    status: str
    approval_url: str


class PayPalClient:
    """OAuth client-credentials + operaciones necesarias para el checkout."""

    def __init__(
        self,
        *,
        environment: str,
        client_id: str,
        client_secret: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if environment not in {"sandbox", "live"}:
            raise PayPalConfigurationError("PAYPAL_ENV must be sandbox or live")
        if not client_id or not client_secret:
            raise PayPalConfigurationError("PayPal API credentials are not configured")
        self.environment = environment
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = (
            "https://api-m.sandbox.paypal.com"
            if environment == "sandbox"
            else "https://api-m.paypal.com"
        )
        self._approval_hosts = (
            {"www.sandbox.paypal.com", "sandbox.paypal.com"}
            if environment == "sandbox"
            else {"www.paypal.com", "paypal.com"}
        )
        self._transport = transport
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    @classmethod
    def from_env(cls) -> "PayPalClient":
        return cls(
            environment=os.getenv("PAYPAL_ENV", "sandbox").strip().lower(),
            client_id=os.getenv("PAYPAL_CLIENT_ID", "").strip(),
            client_secret=os.getenv("PAYPAL_CLIENT_SECRET", "").strip(),
        )

    def _http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=False,
            transport=self._transport,
        )

    async def _access_token(self) -> str:
        now = time.monotonic()
        if self._token and now < self._token_expires_at:
            return self._token
        async with self._token_lock:
            now = time.monotonic()
            if self._token and now < self._token_expires_at:
                return self._token
            try:
                async with self._http_client() as client:
                    response = await client.post(
                        f"{self.base_url}/v1/oauth2/token",
                        auth=httpx.BasicAuth(self.client_id, self.client_secret),
                        headers={"Accept": "application/json"},
                        data={"grant_type": "client_credentials"},
                    )
            except httpx.TransportError as exc:
                raise PayPalUnavailable("PayPal OAuth is unavailable") from exc
            if response.status_code >= 500:
                raise PayPalUnavailable("PayPal OAuth is unavailable")
            if response.status_code != 200:
                raise PayPalConfigurationError("PayPal API credentials were rejected")
            try:
                payload = response.json()
                token = payload["access_token"]
                expires_in = int(payload.get("expires_in", 300))
            except (ValueError, KeyError, TypeError) as exc:
                raise PayPalUnavailable("PayPal OAuth returned an invalid response") from exc
            if not isinstance(token, str) or not token.strip():
                raise PayPalUnavailable("PayPal OAuth returned an invalid token")
            self._token = token.strip()
            self._token_expires_at = now + max(30, expires_in - 60)
            return self._token

    @staticmethod
    def _error_issue(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return "request_rejected"
        if isinstance(payload, dict):
            details = payload.get("details")
            if isinstance(details, list) and details and isinstance(details[0], dict):
                issue = details[0].get("issue")
                if isinstance(issue, str) and issue:
                    return issue[:80]
            name = payload.get("name")
            if isinstance(name, str) and name:
                return name[:80]
        return "request_rejected"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        token = await self._access_token()
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        try:
            async with self._http_client() as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=headers,
                    json=json_body,
                )
        except httpx.TransportError as exc:
            raise PayPalUnavailable("PayPal API is unavailable") from exc
        if response.status_code >= 500:
            raise PayPalUnavailable("PayPal API is unavailable")
        if response.status_code < 200 or response.status_code >= 300:
            raise PayPalAPIError(
                f"PayPal rejected the request: {self._error_issue(response)}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise PayPalUnavailable("PayPal API returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise PayPalUnavailable("PayPal API returned an invalid response")
        return payload

    async def get_monthly_plan(self, plan_id: str) -> PayPalPlan:
        payload = await self._request("GET", f"/v1/billing/plans/{plan_id}")
        returned_id = str(payload.get("id") or "").strip()
        product_id = str(payload.get("product_id") or "").strip()
        name = str(payload.get("name") or "").strip()
        if returned_id != plan_id or not product_id or len(product_id) > 64:
            raise PayPalConfigurationError("PayPal returned an unexpected plan")
        if str(payload.get("status") or "").upper() != "ACTIVE":
            raise PayPalConfigurationError("PayPal plan is not active")
        cycles = payload.get("billing_cycles")
        if not isinstance(cycles, list):
            raise PayPalConfigurationError("PayPal plan has no billing cycles")
        regular = [
            cycle
            for cycle in cycles
            if isinstance(cycle, dict)
            and str(cycle.get("tenure_type") or "").upper() == "REGULAR"
        ]
        if len(regular) != 1:
            raise PayPalConfigurationError("PayPal plan must have one regular cycle")
        cycle = regular[0]
        frequency = cycle.get("frequency")
        try:
            interval_count = int(
                frequency.get("interval_count") if isinstance(frequency, dict) else 0
            )
            total_cycles = int(cycle.get("total_cycles") or 0)
        except (TypeError, ValueError) as exc:
            raise PayPalConfigurationError(
                "PayPal plan has invalid billing intervals"
            ) from exc
        if not isinstance(frequency, dict) or (
            str(frequency.get("interval_unit") or "").upper() != "MONTH"
            or interval_count != 1
        ):
            raise PayPalConfigurationError("PayPal plan is not monthly")
        if total_cycles != 0:
            raise PayPalConfigurationError("PayPal regular cycle must be indefinite")
        scheme = cycle.get("pricing_scheme")
        fixed = scheme.get("fixed_price") if isinstance(scheme, dict) else None
        if not isinstance(fixed, dict):
            raise PayPalConfigurationError("PayPal plan has no fixed price")
        if str(fixed.get("currency_code") or "").upper() != "USD":
            raise PayPalConfigurationError("PayPal plan currency must be USD")
        try:
            price = Decimal(str(fixed.get("value")))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise PayPalConfigurationError("PayPal plan price is invalid") from exc
        if price <= 0:
            raise PayPalConfigurationError("PayPal plan price must be positive")
        has_trial = any(
            isinstance(item, dict)
            and str(item.get("tenure_type") or "").upper() == "TRIAL"
            for item in cycles
        )
        return PayPalPlan(
            id=returned_id,
            product_id=product_id,
            name=name or "OfertasCL VIP",
            price_usd=price,
            has_trial=has_trial,
        )

    def _valid_approval_url(self, value: str) -> bool:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https"
            and parsed.hostname in self._approval_hosts
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
            and not parsed.fragment
        )

    async def create_subscription(
        self,
        *,
        plan_id: str,
        custom_id: str,
        request_id: str,
        return_url: str,
        cancel_url: str,
        email: str | None,
    ) -> PayPalSubscription:
        body: dict[str, Any] = {
            "plan_id": plan_id,
            "custom_id": custom_id,
            "application_context": {
                "brand_name": "OfertasCL",
                "shipping_preference": "NO_SHIPPING",
                "user_action": "SUBSCRIBE_NOW",
                "return_url": return_url,
                "cancel_url": cancel_url,
            },
        }
        if email:
            body["subscriber"] = {"email_address": email}
        payload = await self._request(
            "POST",
            "/v1/billing/subscriptions",
            json_body=body,
            request_id=request_id,
        )
        subscription_id = str(payload.get("id") or "").strip()
        status = str(payload.get("status") or "").strip().upper()
        if not subscription_id or len(subscription_id) > 64:
            raise PayPalUnavailable("PayPal returned an invalid subscription id")
        if status not in {"APPROVAL_PENDING", "APPROVED"}:
            raise PayPalUnavailable("PayPal returned an unexpected subscription status")
        response_custom_id = payload.get("custom_id")
        if response_custom_id not in (None, custom_id):
            raise PayPalUnavailable("PayPal returned an unexpected custom id")
        approval_url = ""
        links = payload.get("links")
        if isinstance(links, list):
            for link in links:
                if not isinstance(link, dict):
                    continue
                if str(link.get("rel") or "").lower() != "approve":
                    continue
                candidate = str(link.get("href") or "").strip()
                if self._valid_approval_url(candidate):
                    approval_url = candidate
                    break
        if not approval_url:
            raise PayPalUnavailable("PayPal returned no valid approval URL")
        return PayPalSubscription(
            id=subscription_id,
            status=status,
            approval_url=approval_url,
        )
