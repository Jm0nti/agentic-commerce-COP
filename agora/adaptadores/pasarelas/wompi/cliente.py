"""HTTP puro contra la API de Wompi. Sin topes, sin mandato, sin persistencia.

Es la mitad de `boveda/nucleo.py:ClienteWompi` que sobrevive intacta a la
particion de `Boveda` (`docs/historico/analisis-codigo.md`, hallazgo 1): hablar con
Wompi. La otra mitad -- resolver mandatos, aplicar topes duros, decidir que
hacer con el resultado -- ya no esta aqui; vive en `aplicacion/
ejecutar_intencion.py` y en `AdaptadorWompi` (`adaptador.py`, en este mismo
paquete), que es quien traduce lo que este cliente devuelve a los tipos del
dominio.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx

from ....model.commons.errores import ErrorDePasarela, PasarelaNoDisponible
from .config import ConfiguracionWompi


class ClienteWompi:
    def __init__(
        self, config: ConfiguracionWompi, cliente_http: httpx.Client | None = None
    ) -> None:
        self._config = config
        self.http = cliente_http or httpx.Client(timeout=25.0)

    @property
    def url(self) -> str:
        return self._config.url_base

    def firma_integridad(self, referencia: str, centavos: int, moneda: str = "COP") -> str:
        return hashlib.sha256(
            f"{referencia}{centavos}{moneda}{self._config.secreto_integridad}".encode(
                "utf-8"
            )
        ).hexdigest()

    # -- HTTP ----------------------------------------------------------- #

    def _pedir(
        self, metodo: str, path: str, llave: str, cuerpo: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            r = self.http.request(
                metodo,
                f"{self.url}{path}",
                headers={"Authorization": f"Bearer {llave}"},
                json=cuerpo,
            )
        except httpx.HTTPError as exc:
            # Red, timeout, DNS. Reintentar es correcto -- y seguro, porque
            # `crear_transaccion` deriva la referencia de la intencion y no
            # cambia entre intentos (ADR-6).
            raise PasarelaNoDisponible(f"Wompi no respondio: {exc}") from exc

        try:
            payload = r.json()
        except ValueError as exc:
            raise PasarelaNoDisponible(
                f"Wompi {r.status_code} devolvio un cuerpo que no es JSON"
            ) from exc

        if r.status_code >= 500:
            raise PasarelaNoDisponible(f"Wompi {r.status_code}", detalle_proveedor=payload)
        if r.status_code >= 400:
            raise ErrorDePasarela(
                f"Wompi {r.status_code}: {json.dumps(payload, ensure_ascii=False)[:300]}",
                detalle_proveedor=payload,
            )
        return payload

    # -- piezas ----------------------------------------------------------- #

    def aceptaciones(self) -> tuple[str, str]:
        d = self._pedir(
            "GET", f"/merchants/{self._config.llave_publica}", self._config.llave_publica
        )["data"]
        return (
            d["presigned_acceptance"]["acceptance_token"],
            d["presigned_personal_data_auth"]["acceptance_token"],
        )

    def crear_token_nequi(self, telefono: str) -> dict[str, Any]:
        return self._pedir(
            "POST", "/tokens/nequi", self._config.llave_publica,
            {"phone_number": telefono},
        )["data"]

    def consultar_token_nequi(self, token: str) -> dict[str, Any]:
        return self._pedir(
            "GET", f"/tokens/nequi/{token}", self._config.llave_publica
        )["data"]

    def crear_fuente_de_pago(self, token: str, correo: str) -> dict[str, Any]:
        acc, per = self.aceptaciones()
        return self._pedir(
            "POST", "/payment_sources", self._config.llave_privada,
            {
                "type": "NEQUI",
                "token": token,
                "customer_email": correo,
                "acceptance_token": acc,
                "accept_personal_auth": per,
            },
        )["data"]

    def revocar_fuente_de_pago(self, id_externo: str) -> dict[str, Any]:
        payload = self._pedir(
            "PUT", f"/payment_sources/{id_externo}/void", self._config.llave_privada
        )
        return payload.get("data") or {}

    def crear_transaccion(
        self,
        id_externo_fuente: str,
        centavos: int,
        referencia: str,
        correo: str,
        pagador: dict[str, str] | None,
    ) -> dict[str, Any]:
        """`pagador` no es cosmetico: un cobro sin `customer_data`, sin IP y
        con un correo de dominio reservado es exactamente el perfil que el
        motor antifraude de Wompi lee como fraude -- ver
        `docs/hallazgo-afe.md` (memoria del proyecto) y `docs/decline-afe.md`.
        """
        acc, per = self.aceptaciones()
        cuerpo: dict[str, Any] = {
            "amount_in_cents": centavos,
            "currency": "COP",
            "customer_email": correo,
            "reference": referencia,
            "signature": self.firma_integridad(referencia, centavos),
            "payment_source_id": int(id_externo_fuente),
            "acceptance_token": acc,
            "accept_personal_auth": per,
        }
        if pagador:
            cuerpo["customer_data"] = pagador
        return self._pedir("POST", "/transactions", self._config.llave_privada, cuerpo)["data"]

    def consultar_transaccion(self, id_externo: str) -> dict[str, Any]:
        return self._pedir(
            "GET", f"/transactions/{id_externo}", self._config.llave_publica
        )["data"]
