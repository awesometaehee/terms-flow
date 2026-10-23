from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]
# 로컬 실행 시 저장소 루트의 schemas/를 가리킨다 (컨테이너에서는 /schemas).
_DEFAULT_SCHEMAS_DIR = _REPO_ROOT / "schemas"


class Settings(BaseSettings):
    # 저장소 루트의 .env를 읽는다. 어느 폴더에서 실행해도 같은 설정을 쓴다.
    model_config = SettingsConfigDict(env_file=(_REPO_ROOT / ".env", ".env"), extra="ignore")

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str
    postgres_user: str
    postgres_password: str

    # 파일 저장소: local(폴더, 로컬 개발 기본) 또는 s3(S3 호환 스토리지)
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_dir: Path = _REPO_ROOT / "data" / "storage"
    s3_endpoint_url: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str = "terms-flow-documents"
    s3_region: str = "us-east-1"

    schemas_dir: Path = _DEFAULT_SCHEMAS_DIR
    # PNG 해상도. 출력 규격 확정 전 기본값 (가이드 14장 6번)
    render_png_dpi: int = 150

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_conninfo(self) -> str:
        """psycopg 연결 문자열 (Procrastinate용)."""
        return (
            f"host={self.postgres_host} port={self.postgres_port} dbname={self.postgres_db} "
            f"user={self.postgres_user} password={self.postgres_password}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
