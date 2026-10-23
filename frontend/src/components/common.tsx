import { Alert, Badge, Center, List, Loader } from "@mantine/core";

import { ApiError } from "../api/client";

const STATUS: Record<string, { label: string; color: string }> = {
  DRAFT: { label: "작성 중", color: "gray" },
  ACTIVE: { label: "판매 중", color: "green" },
  ENDED: { label: "판매 종료", color: "dark" },
  PENDING: { label: "생성 중", color: "blue" },
  PUBLISHED: { label: "발행됨", color: "green" },
  FAILED: { label: "실패", color: "red" },
  RUNNING: { label: "진행 중", color: "blue" },
  SUCCEEDED: { label: "성공", color: "green" },
  SKIPPED: { label: "건너뜀", color: "yellow" },
  DOC_DRAFT: { label: "작성 중", color: "gray" },
  DOC_ACTIVE: { label: "사용 중", color: "green" },
  DOC_ENDED: { label: "종료", color: "dark" },
};

export function StatusBadge({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, color: "gray" };
  return (
    <Badge color={s.color} variant="light">
      {s.label}
    </Badge>
  );
}

export function ErrorAlert({ error }: { error: unknown }) {
  if (!error) return null;
  const body = error instanceof ApiError ? error.body : null;
  return (
    <Alert color="red" title={body?.message ?? String(error)}>
      {body && body.errors && body.errors.length > 0 && (
        <List size="sm">
          {body.errors.map((e) => (
            <List.Item key={e.path + e.message}>
              <code>{e.path}</code> {e.message}
            </List.Item>
          ))}
        </List>
      )}
    </Alert>
  );
}

export function Loading() {
  return (
    <Center py="xl">
      <Loader />
    </Center>
  );
}

export function formatDateTime(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString("ko-KR") : "-";
}

export function formatWon(amount: number): string {
  return `${amount.toLocaleString("ko-KR")}원`;
}

// 발행된 문서 HTML 표시. 스크립트를 실행하지 않도록 sandbox를 둔다.
export function HtmlFrame({ html, src, height = 640 }: { html?: string; src?: string; height?: number }) {
  return (
    <iframe
      title="문서 미리보기"
      sandbox=""
      srcDoc={html}
      src={html === undefined ? src : undefined}
      style={{ width: "100%", height, border: "1px solid var(--mantine-color-gray-4)", background: "white" }}
    />
  );
}
