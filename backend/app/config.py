from functools import lru_cache
from pathlib import Path
from typing import Literal, Self
from urllib.parse import parse_qsl, unquote, urlsplit

from psycopg.conninfo import make_conninfo
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

_REPO_ROOT = Path(__file__).resolve().parents[2]
# 로컬 실행 시 저장소 루트의 schemas/를 가리킨다 (컨테이너에서는 /schemas).
_DEFAULT_SCHEMAS_DIR = _REPO_ROOT / "schemas"


class Settings(BaseSettings):
    # 저장소 루트의 .env를 읽는다. 어느 폴더에서 실행해도 같은 설정을 쓴다.
    model_config = SettingsConfigDict(env_file=(_REPO_ROOT / ".env", ".env"), extra="ignore")

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = ""
    postgres_user: str = ""
    postgres_password: str = ""
    # 호스팅 DB(Supabase 등)의 연결 주소. 있으면 위 POSTGRES_* 대신 쓴다.
    # 예: postgresql://user:password@host:5432/dbname
    database_url_env: str | None = Field(default=None, validation_alias="DATABASE_URL")
    # DATABASE_URL 뒤에 붙은 연결 옵션 (예: sslmode=require). 주소를 읽을 때 채운다.
    postgres_options: dict[str, str] = {}

    # 파일 저장소: local(폴더, 로컬 개발 기본) 또는 s3(S3 호환 스토리지)
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_dir: Path = _REPO_ROOT / "data" / "storage"
    s3_endpoint_url: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str = "terms-flow-documents"
    s3_region: str = "us-east-1"
    # 경로 방식 주소(https://endpoint/bucket/key). Supabase Storage 등에 필요하다.
    s3_force_path_style: bool = False

    schemas_dir: Path = _DEFAULT_SCHEMAS_DIR

    # --- 임시 배포(검토용) 설정. 비워 두면 꺼진다 (로컬 개발 기본) ---
    # 빌드한 화면(frontend/dist)을 API와 같은 주소에서 제공한다. 예: /app/web
    static_dir: Path | None = None
    # 접속 계정 (HTTP Basic). "아이디:비밀번호,아이디2:비밀번호2". /api/health는 열어 둔다.
    basic_auth_users: str | None = None
    # 접속을 허용할 IP·대역 (쉼표로 구분, 예: 203.0.113.10,198.51.100.0/24). 비우면 제한 없음
    allowed_ips: str | None = None
    # 화면을 다른 주소에서 띄울 때만 쓰는 CORS 허용 주소 (쉼표로 구분)
    cors_origins: str | None = None
    # PNG 해상도. 출력 규격 확정 전 기본값 (가이드 14장 6번)
    render_png_dpi: int = 150

    @model_validator(mode="after")
    def _apply_database_url(self) -> Self:
        if self.database_url_env:
            url = urlsplit(self.database_url_env)
            self.postgres_host = url.hostname or self.postgres_host
            self.postgres_port = url.port or self.postgres_port
            self.postgres_db = unquote(url.path.lstrip("/")) or self.postgres_db
            self.postgres_user = unquote(url.username or "") or self.postgres_user
            self.postgres_password = unquote(url.password or "") or self.postgres_password
            self.postgres_options = dict(parse_qsl(url.query))
        missing = [n for n in ("postgres_db", "postgres_user") if not getattr(self, n)]
        if missing:
            raise ValueError(f"DB 설정이 없습니다: {', '.join(missing)} (또는 DATABASE_URL)")
        return self

    def basic_auth_accounts(self) -> dict[str, str]:
        accounts: dict[str, str] = {}
        for item in (self.basic_auth_users or "").split(","):
            user, sep, password = item.strip().partition(":")
            if sep and user and password:
                accounts[user] = password
        return accounts

    @property
    def database_url(self) -> str:
        # 비밀번호에 특수문자가 있어도 깨지지 않게 URL을 만든다.
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
            query=self.postgres_options,
        ).render_as_string(hide_password=False)

    @property
    def database_conninfo(self) -> str:
        """psycopg 연결 문자열 (Procrastinate용)."""
        return make_conninfo(
            host=self.postgres_host,
            port=self.postgres_port,
            dbname=self.postgres_db,
            user=self.postgres_user,
            password=self.postgres_password,
            **self.postgres_options,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
