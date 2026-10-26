"""이미지 자료실: 올리기·목록·검색·이름 바꾸기·내려받기·삭제(쓰는 곳이 있으면 막음). 값은 [샘플]."""

from urllib.parse import quote

from fastapi.testclient import TestClient

from tests.kms_helpers import create_document, create_module, doc, module_block, save, text
from tests.test_richtext_layout import png_bytes


def _upload(client: TestClient, name: str) -> dict:
    res = client.post(
        "/api/images",
        content=png_bytes(),
        headers={"Content-Type": "image/png", "X-File-Name": quote(name)},
    )
    assert res.status_code == 201, res.text
    data: dict = res.json()
    return data


def test_upload_list_rename_download(client: TestClient) -> None:
    image = _upload(client, "[샘플] 오마주 사진형.png")
    assert image["name"] == "[샘플] 오마주 사진형.png"
    assert (image["width"], image["height"], image["content_type"]) == (2, 2, "image/png")
    assert image["url"].startswith("/api/assets/")
    # 본문에서 쓰는 주소로 파일을 받을 수 있다
    assert client.get(image["url"]).content == png_bytes()

    _upload(client, "[샘플] 다른 그림.png")
    names = [i["name"] for i in client.get("/api/images", params={"q": "오마주"}).json()]
    assert names == ["[샘플] 오마주 사진형.png"]

    res = client.patch(f"/api/images/{image['id']}", json={"name": "[샘플] 사진형 (최종)"})
    assert res.json()["name"] == "[샘플] 사진형 (최종)"
    res = client.get(f"/api/images/{image['id']}/download")
    assert res.status_code == 200
    assert res.content == png_bytes()
    # 확장자가 없는 이름은 내려받을 때 붙인다
    assert res.headers["content-disposition"].endswith(quote("[샘플] 사진형 (최종).png"))


def test_upload_rejects_non_images(client: TestClient) -> None:
    res = client.post("/api/images", content=b"hello", headers={"Content-Type": "text/plain"})
    assert res.status_code == 422


def test_delete_only_when_unused(client: TestClient) -> None:
    image = _upload(client, "[샘플] 쓰는 그림.png")
    picture = {"type": "image", "attrs": {"src": image["url"]}}
    module = create_module(
        client,
        "img.used",
        {"type": "doc", "content": [picture, doc([text("[샘플]")])["content"][0]]},
    )
    document = create_document(client, title="[샘플] 그림 문서")
    save(client, document, [module_block(module)])

    res = client.delete(f"/api/images/{image['id']}")
    assert res.status_code == 409
    assert res.json()["code"] == "IMAGE_IN_USE"
    assert (
        "[샘플] img.used" in res.json()["message"] and "[샘플] 그림 문서" in res.json()["message"]
    )

    # 템플릿에서 이미지를 빼고, 문서도 지우면 자료실에서 지울 수 있다 (파일은 남는다)
    client.post(
        f"/api/clauses/{module['id']}/revisions",
        json={
            "base_revision_no": 1,
            "content_json": doc([text("[샘플] 그림 없음")]),
            "change_reason": "x",
        },
    )
    client.delete(f"/api/documents/{document['id']}")
    assert client.delete(f"/api/images/{image['id']}").status_code == 204
    assert image["id"] not in [i["id"] for i in client.get("/api/images").json()]
    assert client.get(image["url"]).status_code == 200
