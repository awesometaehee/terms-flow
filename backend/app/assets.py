"""본문에 넣는 이미지 (표·단 안의 상품 사진 등).

이미지는 저장소의 assets/<id>.<확장자> 에 한 번 저장하고 바꾸지 않는다.
본문에는 /api/assets/<파일명> 주소로 들어간다.
발행(PDF)할 때는 같은 파일을 data URI로 넣어 렌더러가 네트워크 없이 그린다.
"""

import base64
import re
import tempfile
import uuid
from pathlib import Path

from app.errors import FieldError, ValidationFailed
from app.storage import open_object, put_file

MAX_BYTES = 10 * 1024 * 1024
# 확장자 → (Content-Type, 파일 앞부분 서명 확인)
TYPES: dict[str, tuple[str, tuple[bytes, ...]]] = {
    "png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    "jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "gif": ("image/gif", (b"GIF87a", b"GIF89a")),
    "webp": ("image/webp", (b"RIFF",)),
}
BY_CONTENT_TYPE = {ctype: ext for ext, (ctype, _) in TYPES.items()}
NAME = re.compile(r"^([0-9a-f]{32})\.(png|jpg|gif|webp)$")


def _invalid(message: str) -> ValidationFailed:
    return ValidationFailed([FieldError(path="file", message=message)])


def save_image(data: bytes, content_type: str) -> str:
    """이미지를 저장하고 본문에 넣을 주소(/api/assets/...)를 돌려준다."""
    ext = BY_CONTENT_TYPE.get(content_type.split(";")[0].strip().lower())
    if ext is None:
        raise _invalid("PNG·JPG·GIF·WEBP 이미지만 올릴 수 있습니다.")
    if not data:
        raise _invalid("빈 파일입니다.")
    if len(data) > MAX_BYTES:
        raise _invalid("이미지는 10MB까지 올릴 수 있습니다.")
    signatures = TYPES[ext][1]
    if not any(data.startswith(sig) for sig in signatures) or (
        ext == "webp" and data[8:12] != b"WEBP"
    ):
        raise _invalid("이미지 파일이 아니거나 형식이 맞지 않습니다.")
    name = f"{uuid.uuid4().hex}.{ext}"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_bytes(data)
        put_file(f"assets/{name}", path, TYPES[ext][0])
    return f"/api/assets/{name}"


def parse_name(name: str) -> tuple[str, str]:
    """(저장 키, Content-Type). 형식이 다르면 ValueError."""
    match = NAME.match(name)
    if not match:
        raise ValueError(name)
    return f"assets/{name}", TYPES[match.group(2)][0]


def data_uri(src: str) -> str:
    """본문의 /api/assets/... 주소를 data URI로 바꾼다 (PDF 렌더링용)."""
    key, content_type = parse_name(src.rsplit("/", 1)[-1])
    with open_object(key) as fh:
        encoded = base64.b64encode(fh.read()).decode("ascii")
    return f"data:{content_type};base64,{encoded}"
