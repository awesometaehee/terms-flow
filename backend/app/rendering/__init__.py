"""문서 조합과 렌더링.

- composer: 상품 스냅샷·템플릿·조항으로 문서 계획(DocumentPlan)을 만든다 (DB·렌더러 없음).
- loader: DB에서 조합 입력을 읽는다. 새 발행은 최신 리비전, 재현은 manifest의 리비전 ID.
- html: 문서 계획을 HTML로 만든다 (미리보기와 PDF가 같은 HTML을 쓴다).
- output: HTML → PDF(Chromium) → PNG(pdftoppm), 통합본 PDF(pypdf).
- publisher: worker 작업. 파일을 저장소에 올리고 문서 세트 버전을 발행한다.
"""

# 렌더링 결과(HTML 구조·CSS·파일 구성)가 바뀌면 올린다. manifest의 renderer_version에 기록된다.
RENDERER_VERSION = "1"
