"""임시 배포(검토용) 접근 제한. 설정이 없으면 아무것도 하지 않는다 (로컬 개발).

- HTTP Basic 계정 (BASIC_AUTH_USERS): 화면·API 모두. 헬스체크(/api/health)만 열어 둔다.
- 허용 IP (ALLOWED_IPS): 프록시 뒤라면 uvicorn --proxy-headers로 실제 접속 IP를 받는다.
- 검색 엔진 수집 막기 (X-Robots-Tag)
"""

import base64
import binascii
import ipaddress
import secrets

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings

OPEN_PATHS = {"/api/health"}
REALM = "KMS review"


def _networks(value: str | None) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    return [
        ipaddress.ip_network(v.strip(), strict=False) for v in (value or "").split(",") if v.strip()
    ]


class AccessControl:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.accounts = settings.basic_auth_accounts()
        self.networks = _networks(settings.allowed_ips)

    def _allowed_ip(self, scope: Scope) -> bool:
        if not self.networks:
            return True
        client = scope.get("client")
        try:
            address = ipaddress.ip_address(client[0]) if client else None
        except ValueError:
            return False
        return address is not None and any(address in net for net in self.networks)

    def _authorized(self, scope: Scope) -> bool:
        if not self.accounts:
            return True
        header = dict(scope.get("headers") or []).get(b"authorization", b"")
        scheme, _, encoded = header.partition(b" ")
        if scheme.lower() != b"basic":
            return False
        try:
            user, _, password = (
                base64.b64decode(encoded, validate=True).decode("utf-8").partition(":")
            )
        except (binascii.Error, UnicodeDecodeError):
            return False
        expected = self.accounts.get(user)
        # 계정이 없을 때도 같은 시간이 걸리게 비교한다.
        return secrets.compare_digest(
            password.encode(), (expected or secrets.token_hex(16)).encode()
        ) and (expected is not None)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in OPEN_PATHS:
            await self.app(scope, receive, send)
            return
        if not self._allowed_ip(scope):
            await _plain(send, 403, "허용된 곳에서만 접속할 수 있습니다.")
            return
        if not self._authorized(scope):
            await _plain(
                send,
                401,
                "로그인이 필요합니다.",
                [(b"www-authenticate", f'Basic realm="{REALM}", charset="UTF-8"'.encode())],
            )
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                message["headers"] = [*headers, (b"x-robots-tag", b"noindex, nofollow")]
            await send(message)

        await self.app(scope, receive, send_with_headers)


async def _plain(
    send: Send, status: int, text: str, headers: list[tuple[bytes, bytes]] | None = None
) -> None:
    body = text.encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                (b"x-robots-tag", b"noindex, nofollow"),
                *(headers or []),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
