import { Anchor, Badge, Button, Group, Modal, Stack, Table, Tabs, Text } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type DocumentSetDetail, type DocumentSetSummary, fileUrl, versionHtmlUrl } from "../api/client";
import { ErrorAlert, HtmlFrame, Loading, StatusBadge, formatDateTime } from "../components/common";

const DOC_ORDER = ["TERMS", "TERMS_SUMMARY", "PRODUCT_DESCRIPTION", "COMBINED"];
const DOC_LABELS: Record<string, string> = {
  TERMS: "약관",
  TERMS_SUMMARY: "약관 주요 내용",
  PRODUCT_DESCRIPTION: "상품설명서",
  COMBINED: "통합본",
};

// 문서 세트 버전 목록과 버전별 적용 조항·파일 (가이드 9장 6번)
export function DocumentHistory({ productId, readOnly }: { productId: string; readOnly: boolean }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const versions = useQuery({
    queryKey: ["document-sets", productId],
    queryFn: () => api<DocumentSetSummary[]>(`/products/${productId}/document-sets`),
    refetchInterval: (q) => (q.state.data?.some((v) => v.status === "PENDING") ? 2000 : false),
  });
  const qc = useQueryClient();
  const retry = useMutation({
    mutationFn: (id: string) => api(`/document-sets/${id}/retry`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["document-sets", productId] }),
  });

  if (versions.isPending) return <Loading />;
  return (
    <Stack>
      <ErrorAlert error={versions.error ?? retry.error} />
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>버전</Table.Th>
            <Table.Th>상태</Table.Th>
            <Table.Th>사유</Table.Th>
            <Table.Th>발행 시각</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {versions.data?.map((v) => (
            <Table.Tr key={v.id}>
              <Table.Td>v{v.version_no}</Table.Td>
              <Table.Td>
                <Group gap={4}>
                  <StatusBadge status={v.status} />
                  {v.batch_id && <Badge variant="outline">일괄 수정</Badge>}
                </Group>
                {v.failure_reason && (
                  <Text size="xs" c="red">
                    {v.failure_reason}
                  </Text>
                )}
              </Table.Td>
              <Table.Td>{v.change_reason}</Table.Td>
              <Table.Td>{formatDateTime(v.published_at)}</Table.Td>
              <Table.Td>
                <Group gap="xs">
                  <Button size="xs" variant="light" onClick={() => setOpenId(v.id)}>
                    상세·파일
                  </Button>
                  {v.status === "FAILED" && !readOnly && (
                    <Button size="xs" color="orange" loading={retry.isPending} onClick={() => retry.mutate(v.id)}>
                      다시 시도
                    </Button>
                  )}
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {versions.data?.length === 0 && <Text c="dimmed">발행된 문서가 없습니다.</Text>}
      <Modal opened={openId !== null} onClose={() => setOpenId(null)} size="90%" title="문서 세트 버전">
        {openId && <VersionDetail versionId={openId} />}
      </Modal>
    </Stack>
  );
}

function VersionDetail({ versionId }: { versionId: string }) {
  const detail = useQuery({
    queryKey: ["document-set", versionId],
    queryFn: () => api<DocumentSetDetail>(`/document-sets/${versionId}`),
  });
  if (detail.isPending) return <Loading />;
  if (!detail.data) return <ErrorAlert error={detail.error} />;
  const d = detail.data;
  const files = [...d.files].sort(
    (a, b) =>
      DOC_ORDER.indexOf(a.document_type) - DOC_ORDER.indexOf(b.document_type) ||
      a.format.localeCompare(b.format) ||
      (a.page_no ?? 0) - (b.page_no ?? 0),
  );
  return (
    <Tabs defaultValue="files">
      <Tabs.List>
        <Tabs.Tab value="files">파일</Tabs.Tab>
        <Tabs.Tab value="clauses">적용 조항</Tabs.Tab>
        <Tabs.Tab value="view">문서 보기</Tabs.Tab>
      </Tabs.List>
      <Tabs.Panel value="files" pt="md">
        <Text size="sm" c="dimmed" mb="xs">
          v{d.version_no} · 상품 버전 {d.manifest.product_revision_no} · {d.manifest.renderer_version ?? "렌더링 전"}
        </Text>
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>문서</Table.Th>
              <Table.Th>형식</Table.Th>
              <Table.Th>파일</Table.Th>
              <Table.Th>SHA-256</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {files.map((f) => (
              <Table.Tr key={f.id}>
                <Table.Td>{DOC_LABELS[f.document_type]}</Table.Td>
                <Table.Td>
                  {f.format}
                  {f.page_no ? ` ${f.page_no}쪽` : ""}
                </Table.Td>
                <Table.Td>
                  <Anchor href={fileUrl(d.id, f.id)} target="_blank">
                    {f.file_name}
                  </Anchor>
                </Table.Td>
                <Table.Td>
                  <code style={{ fontSize: 11 }}>{f.sha256.slice(0, 16)}…</code>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Tabs.Panel>
      <Tabs.Panel value="clauses" pt="md">
        {d.manifest.documents?.map((doc) => (
          <Stack key={doc.document_type} gap={4} mb="md">
            <Text fw={700}>
              {DOC_LABELS[doc.document_type]} · 템플릿 {doc.template_key} r{doc.template_revision_no}
            </Text>
            {doc.clauses.map((c) => (
              <Text size="sm" key={c.clause_key}>
                {c.order}. {c.title} <code>{c.clause_key}</code> r{c.revision_no} — {c.reason}
              </Text>
            ))}
            {doc.excluded_clauses?.map((c) => (
              <Text size="sm" c="dimmed" key={c.clause_key}>
                제외: {c.title} <code>{c.clause_key}</code> — {c.reason}
              </Text>
            ))}
          </Stack>
        ))}
      </Tabs.Panel>
      <Tabs.Panel value="view" pt="md">
        <HtmlFrame src={versionHtmlUrl(d.id)} />
      </Tabs.Panel>
    </Tabs>
  );
}
