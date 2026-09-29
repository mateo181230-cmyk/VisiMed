"""El envío Web Push real (pywebpush + VAPID) contra un «servicio de push» falso local.

No hay red externa: un servidor HTTP en 127.0.0.1 recibe la petición cifrada (RFC 8291,
``aes128gcm``) y la prueba la descifra con la llave privada de la suscripción, como haría el
navegador. Así se comprueba el cifrado, los encabezados y la firma VAPID sin depender de FCM.
"""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import http_ece
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from typer.testing import CliRunner

from uno.cli import app
from uno.config import Settings
from uno.modules.notifications.senders import PushMessage, PushTarget, WebPushSender


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class FakePushService:
    """Guarda las peticiones recibidas y responde con el código configurado."""

    def __init__(self, status: int = 201) -> None:
        self.status = status
        self.requests: list[dict] = []  # type: ignore[type-arg]
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("content-length", "0"))
                outer.requests.append(
                    {
                        "path": self.path,
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                        "body": self.rfile.read(length),
                    }
                )
                self.send_response(outer.status)
                self.end_headers()

            def log_message(self, *args: object) -> None:
                return

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/push/abc"

    def __enter__(self) -> FakePushService:
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def vapid_settings() -> tuple[Settings, str]:
    out = CliRunner().invoke(app, ["vapid-generate"]).output
    values = dict(line.split("=", 1) for line in out.splitlines() if line.startswith("UNO_VAPID"))
    settings = Settings(
        push_backend="webpush",
        vapid_public_key=values["UNO_VAPID_PUBLIC_KEY"],
        vapid_private_key=values["UNO_VAPID_PRIVATE_KEY"],
        vapid_subject="mailto:soporte@ejemplo.com",
    )
    return settings, values["UNO_VAPID_PUBLIC_KEY"]


def browser_subscription() -> tuple[ec.EllipticCurvePrivateKey, bytes, PushTarget]:
    """Lo que generaría el navegador al suscribirse: llave P-256 y secreto de autenticación."""
    key = ec.generate_private_key(ec.SECP256R1())
    auth = b"0123456789abcdef"
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return key, auth, PushTarget(endpoint="", p256dh=b64(public), auth=b64(auth))


async def test_message_is_encrypted_signed_and_decryptable(
    vapid_settings: tuple[Settings, str],
) -> None:
    settings, public_key = vapid_settings
    browser_key, auth, target = browser_subscription()
    with FakePushService(201) as service:
        target = PushTarget(service.endpoint, target.p256dh, target.auth)
        result = await WebPushSender(settings).send(
            target,
            PushMessage(
                title="Visita en 30 min",
                body="10:30 AM · Dra. Méndez",
                url="/",
                tag="v1",
                kind="visit_reminder",
            ),
        )
    assert result.ok and not result.gone
    (req,) = service.requests

    # Cifrado estándar (RFC 8188 / 8291) y vigencia del mensaje.
    assert req["headers"]["content-encoding"] == "aes128gcm"
    assert int(req["headers"]["ttl"]) == 3600
    plaintext = http_ece.decrypt(
        req["body"], private_key=browser_key, auth_secret=auth, version="aes128gcm"
    )
    payload = json.loads(plaintext)
    assert payload == {
        "title": "Visita en 30 min",
        "body": "10:30 AM · Dra. Méndez",
        "url": "/",
        "tag": "v1",
        "kind": "visit_reminder",
    }

    # Identificación VAPID (RFC 8292): JWT ES256 firmado con nuestra llave, verificable con la pública.
    scheme, _, rest = req["headers"]["authorization"].partition(" ")
    assert scheme.lower() == "vapid"
    params = dict(p.strip().split("=", 1) for p in rest.split(","))
    assert params["k"] == public_key
    server_public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(params["k"]))
    claims = jwt.decode(
        params["t"],
        server_public,
        algorithms=["ES256"],
        audience=f"http://127.0.0.1:{service.server.server_port}",
    )
    assert claims["sub"] == "mailto:soporte@ejemplo.com"


@pytest.mark.parametrize(("status", "gone"), [(404, True), (410, True), (500, False), (429, False)])
async def test_push_service_errors_are_classified(
    vapid_settings: tuple[Settings, str], status: int, gone: bool
) -> None:
    settings, _ = vapid_settings
    _, _, target = browser_subscription()
    with FakePushService(status) as service:
        result = await WebPushSender(settings).send(
            PushTarget(service.endpoint, target.p256dh, target.auth),
            PushMessage(title="x", body="y"),
        )
    assert not result.ok
    assert (
        result.gone is gone
    )  # 404/410: la suscripción murió y se desactiva; el resto se reintenta


async def test_unreachable_push_service_is_a_soft_failure(
    vapid_settings: tuple[Settings, str],
) -> None:
    settings, _ = vapid_settings
    _, _, target = browser_subscription()
    result = await WebPushSender(settings).send(
        PushTarget("http://127.0.0.1:9/nope", target.p256dh, target.auth),
        PushMessage(title="x", body="y"),
    )
    assert not result.ok and not result.gone and result.error


def test_webpush_sender_requires_keys() -> None:
    with pytest.raises(RuntimeError, match="VAPID"):
        WebPushSender(Settings(push_backend="webpush"))
