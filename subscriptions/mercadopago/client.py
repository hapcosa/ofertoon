"""Cliente mínimo y estricto para MercadoPago Suscripciones (preapproval).

Mismo reparto de errores que `subscriptions/paypal/client.py` y por la misma
razón: el bot necesita distinguir "no está configurado" de "rechazado" de "no
disponible, reintentá" para mostrar el mensaje correcto.

A diferencia de PayPal, MercadoPago no tiene un paso de OAuth: el access token
es un secreto de larga vida (`TEST-...` en sandbox, `APP_USR-...` en
producción) que se manda directo como Bearer. Por eso este cliente no cachea
ni refresca nada — es más simple que el de PayPal porque MercadoPago lo es.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os
from typing import Any
from urllib.parse import urlsplit

import httpx


class MercadoPagoConfigurationError(RuntimeError):
    """Configuración local o respuesta de MercadoPago incompatible con el checkout."""


class MercadoPagoAPIError(RuntimeError):
    """MercadoPago rechazó de forma determinista la solicitud."""


class MercadoPagoUnavailable(RuntimeError):
    """MercadoPago no respondió de forma concluyente; la operación puede reintentarse."""


@dataclass(frozen=True)
class MercadoPagoPlan:
    id: str
    price_clp: int


@dataclass(frozen=True)
class MercadoPagoPreapproval:
    id: str
    status: str
    init_point: str


# Dominios reales de checkout de MercadoPago que el `init_point`/`sandbox_init_point`
# puede devolver (el país de la cuenta decide el TLD). Igual que
# `PayPalClient._valid_approval_url`: un link fuera de esta lista no se muestra
# nunca, aunque la respuesta HTTP haya sido 200 — una URL de pago inventada o
# redirigida es peor que no mostrar botón.
_APPROVAL_HOST_SUFFIXES = (
    "mercadopago.com",
    "mercadopago.com.ar",
    "mercadopago.com.mx",
    "mercadopago.cl",
)


def _host_allowed(hostname: str) -> bool:
    return any(
        hostname == suffix or hostname.endswith(f".{suffix}")
        for suffix in _APPROVAL_HOST_SUFFIXES
    )


class MercadoPagoClient:
    """Bearer token fijo + las dos operaciones que necesita el checkout."""

    def __init__(
        self,
        *,
        access_token: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not access_token or not access_token.strip():
            raise MercadoPagoConfigurationError(
                "MercadoPago access token is not configured"
            )
        self.access_token = access_token.strip()
        self.base_url = "https://api.mercadopago.com"
        self._transport = transport

    @classmethod
    def from_env(cls) -> "MercadoPagoClient":
        return cls(access_token=os.getenv("MERCADOPAGO_ACCESS_TOKEN", "").strip())

    def _http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=False,
            transport=self._transport,
        )

    @staticmethod
    def _error_issue(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return "request_rejected"
        if isinstance(payload, dict):
            message = payload.get("message")
            if isinstance(message, str) and message:
                return message[:80]
        return "request_rejected"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["X-Idempotency-Key"] = idempotency_key
        try:
            async with self._http_client() as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=headers,
                    json=json_body,
                )
        except httpx.TransportError as exc:
            raise MercadoPagoUnavailable("MercadoPago API is unavailable") from exc
        if response.status_code >= 500:
            raise MercadoPagoUnavailable("MercadoPago API is unavailable")
        if response.status_code == 401:
            raise MercadoPagoConfigurationError(
                "MercadoPago access token was rejected"
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise MercadoPagoAPIError(
                f"MercadoPago rejected the request: {self._error_issue(response)}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MercadoPagoUnavailable(
                "MercadoPago API returned invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise MercadoPagoUnavailable("MercadoPago API returned an invalid response")
        return payload

    async def get_monthly_plan(self, plan_id: str) -> MercadoPagoPlan:
        payload = await self._request("GET", f"/preapproval_plan/{plan_id}")
        returned_id = str(payload.get("id") or "").strip()
        if returned_id != plan_id:
            raise MercadoPagoConfigurationError(
                "MercadoPago returned an unexpected plan"
            )
        if str(payload.get("status") or "").strip().lower() != "active":
            raise MercadoPagoConfigurationError("MercadoPago plan is not active")
        recurring = payload.get("auto_recurring")
        if not isinstance(recurring, dict):
            raise MercadoPagoConfigurationError("MercadoPago plan has no auto_recurring")
        try:
            frequency = int(recurring.get("frequency"))
        except (TypeError, ValueError) as exc:
            raise MercadoPagoConfigurationError(
                "MercadoPago plan has an invalid frequency"
            ) from exc
        if (
            frequency != 1
            or str(recurring.get("frequency_type") or "").strip().lower() != "months"
        ):
            raise MercadoPagoConfigurationError("MercadoPago plan is not monthly")
        if str(recurring.get("currency_id") or "").strip().upper() != "CLP":
            raise MercadoPagoConfigurationError("MercadoPago plan currency must be CLP")
        try:
            amount = Decimal(str(recurring.get("transaction_amount")))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise MercadoPagoConfigurationError(
                "MercadoPago plan amount is invalid"
            ) from exc
        # CLP no tiene subunidad: regla 3 de CLAUDE.md, nunca float para dinero.
        # Si MercadoPago alguna vez devuelve un monto con decimales, es señal de
        # un plan mal creado, no algo para redondear en silencio.
        if amount <= 0 or amount != amount.to_integral_value():
            raise MercadoPagoConfigurationError(
                "MercadoPago plan amount must be a positive integer CLP"
            )
        return MercadoPagoPlan(id=returned_id, price_clp=int(amount))

    def _valid_init_point(self, value: str) -> bool:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and _host_allowed(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
            and not parsed.fragment
        )

    async def create_preapproval(
        self,
        *,
        plan_id: str,
        external_reference: str,
        idempotency_key: str,
        back_url: str,
        payer_email: str | None,
    ) -> MercadoPagoPreapproval:
        body: dict[str, Any] = {
            "preapproval_plan_id": plan_id,
            "external_reference": external_reference,
            "back_url": back_url,
            "status": "pending",
        }
        if payer_email:
            body["payer_email"] = payer_email
        payload = await self._request(
            "POST",
            "/preapproval",
            json_body=body,
            idempotency_key=idempotency_key,
        )
        preapproval_id = str(payload.get("id") or "").strip()
        status = str(payload.get("status") or "").strip().lower()
        if not preapproval_id or len(preapproval_id) > 64:
            raise MercadoPagoUnavailable(
                "MercadoPago returned an invalid preapproval id"
            )
        if status not in {"pending", "authorized"}:
            raise MercadoPagoUnavailable(
                "MercadoPago returned an unexpected preapproval status"
            )
        response_reference = payload.get("external_reference")
        if response_reference not in (None, external_reference):
            raise MercadoPagoUnavailable(
                "MercadoPago returned an unexpected external reference"
            )
        init_point = str(payload.get("init_point") or "").strip()
        if not init_point or not self._valid_init_point(init_point):
            raise MercadoPagoUnavailable("MercadoPago returned no valid init point")
        return MercadoPagoPreapproval(
            id=preapproval_id,
            status=status,
            init_point=init_point,
        )

    async def get_preapproval(self, preapproval_id: str) -> dict[str, Any]:
        """Recurso autoritativo para aplicar `subscription_preapproval`."""
        return await self._request("GET", f"/preapproval/{preapproval_id}")

    async def get_authorized_payment(self, authorized_payment_id: str) -> dict[str, Any]:
        """Recurso autoritativo para aplicar `subscription_authorized_payment`."""
        return await self._request(
            "GET", f"/authorized_payments/{authorized_payment_id}"
        )
