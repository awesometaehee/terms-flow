"""임시 배포(검토용) 구성: 접근 제한, DATABASE_URL, 가상 데이터. 계정·값은 시험용 가짜다."""

import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import demo_seed
from app.access import AccessControl
from app.config import Settings


def _app(**settings: str) -> TestClient:
    inner = FastAPI()

    @inner.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @inner.get("/api/things")
    def things() -> list[int]:
        return [1]

    config = Settings(_env_file=None, postgres_db="x", postgres_user="x", **settings)  # type: ignore[arg-type]
    inner.add_middleware(AccessControl, settings=config)
    return TestClient(inner)


def _basic(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_basic_auth_protects_everything_but_health() -> None:
    client = _app(basic_auth_users="reviewer:test-pw-1,owner:test-pw-2")
    assert client.get("/api/health").status_code == 200
    res = client.get("/api/things")
    assert res.status_code == 401
    assert res.headers["www-authenticate"].startswith("Basic ")
    assert client.get("/api/things", headers=_basic("reviewer", "wrong")).status_code == 401
    assert client.get("/api/things", headers=_basic("nobody", "test-pw-1")).status_code == 401
    ok = client.get("/api/things", headers=_basic("owner", "test-pw-2"))
    assert ok.status_code == 200
    assert ok.headers["x-robots-tag"] == "noindex, nofollow"


def test_ip_allowlist() -> None:
    # TestClient의 접속 주소는 "testclient"라 IP가 아니므로 막힌다.
    blocked = _app(allowed_ips="203.0.113.0/24")
    assert blocked.get("/api/things").status_code == 403
    assert blocked.get("/api/health").status_code == 200


def test_no_settings_means_open() -> None:
    assert _app().get("/api/things").status_code == 200


def test_database_url_overrides_postgres_settings() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        DATABASE_URL="postgresql://app%40user:p%40ss@db.internal:6543/review",
    )
    assert (settings.postgres_host, settings.postgres_port, settings.postgres_db) == (
        "db.internal",
        6543,
        "review",
    )
    assert (settings.postgres_user, settings.postgres_password) == ("app@user", "p@ss")


def test_database_url_keeps_connection_options() -> None:
    # Supabase 연결 주소처럼 sslmode가 붙은 경우
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        DATABASE_URL="postgresql://app.ref:pw@pooler.example.com:5432/postgres?sslmode=require",
    )
    assert settings.postgres_options == {"sslmode": "require"}
    assert settings.database_url.endswith("/postgres?sslmode=require")
    assert "sslmode=require" in settings.database_conninfo


def test_demo_seed_creates_valid_sample_data_once(client: TestClient) -> None:
    assert demo_seed.seed(if_empty=True).startswith("가상 데이터를 넣었습니다")
    titles = [c["title"] for c in client.get("/api/clauses").json()]
    assert len(titles) == 4 and all(t.startswith("[샘플]") for t in titles)
    docs = client.get("/api/documents").json()
    assert sorted(d["status"] for d in docs) == ["ACTIVE", "DRAFT"]
    assert all(d["title"].startswith("[샘플]") for d in docs)
    preview = client.get(
        f"/api/documents/{next(d['id'] for d in docs if d['status'] == 'ACTIVE')}/preview"
    )
    assert "[샘플]상조(주)" in preview.text  # 치환 항목 기본값이 채워진다
    # 다시 실행해도 늘어나지 않는다
    assert demo_seed.seed(if_empty=True).startswith("이미 데이터가 있어")
    assert len(client.get("/api/clauses").json()) == 4


@pytest.mark.parametrize("value", ["", "no-colon", ":nouser", "user:"])
def test_bad_account_entries_are_ignored(value: str) -> None:
    config = Settings(_env_file=None, postgres_db="x", postgres_user="x", basic_auth_users=value)  # type: ignore[arg-type]
    assert config.basic_auth_accounts() == {}


def test_s3_path_style_for_supabase(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import storage

    config = Settings(
        _env_file=None,  # type: ignore[call-arg]
        postgres_db="x",
        postgres_user="x",
        storage_backend="s3",
        s3_endpoint_url="https://example-ref.supabase.co/storage/v1/s3",
        s3_access_key="test-key",
        s3_secret_key="test-secret",
        s3_bucket="kms-review",
        s3_region="ap-northeast-2",
        s3_force_path_style=True,
    )
    monkeypatch.setattr(storage, "get_settings", lambda: config)
    storage.get_s3_client.cache_clear()
    try:
        url = storage.get_s3_client().generate_presigned_url(
            "get_object", Params={"Bucket": "kms-review", "Key": "assets/a.png"}, ExpiresIn=60
        )
    finally:
        storage.get_s3_client.cache_clear()
    # 버킷이 호스트가 아니라 경로에 들어간다
    assert url.startswith("https://example-ref.supabase.co/storage/v1/s3/kms-review/assets/a.png?")
