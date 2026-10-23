import { Alert, Box, Button, Card, Group, SimpleGrid, Stack, Table, Text, TextInput, Title } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  type BulkUpdateDetail,
  type BulkUpdateSummary,
  type ImpactOut,
  type ImpactDocument,
  type ImpactProduct,
  type PreviewOut,
  api,
  documentPreviewUrl,
  versionHtmlUrl,
} from "../api/client";
import { ErrorAlert, HtmlFrame, Loading, StatusBadge, formatDateTime } from "../components/common";
import { MissingValues, allFilled } from "../components/MissingValues";
import { diffLines, downloadText, newRequestId, toCsv } from "../lib/diff";
import { Link, navigate, useQueryParam } from "../router";

// --- 영향 분석·실행 (가이드 7장 2~4단계, 9장 5번) ------------------------------------

export function BulkUpdateNew() {
  const clauseId = useQueryParam("clause") ?? "";
  const revisionNo = Number(useQueryParam("revision"));
  // 같은 화면에서 다시 눌러도 같은 요청 ID를 보내 작업이 중복 생성되지 않게 한다.
  const [requestId] = useState(newRequestId);
  const [reason, setReason] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const impact = useQuery({
    queryKey: ["impact", clauseId, revisionNo],
    queryFn: () => api<ImpactOut>("/bulk-updates/preview", { body: { clause_id: clauseId, revision_no: revisionNo } }),
  });
  const run = useMutation({
    mutationFn: () =>
      api<BulkUpdateDetail>("/bulk-updates", {
        body: { request_id: requestId, clause_id: clauseId, revision_no: revisionNo, change_reason: reason, variable_values: values },
      }),
    onSuccess: (job) => navigate(`/bulk-updates/${job.id}`),
  });

  if (impact.isPending) return <Loading />;
  if (!impact.data) return <ErrorAlert error={impact.error} />;
  const d = impact.data;
  return (
    <Stack>
      <Link to={`/modules/${clauseId}`}>← 모듈</Link>
      <Title order={2}>공통 모듈 일괄 반영 · 영향 분석</Title>
      <Text>
        <code>{d.clause_key}</code> {d.title} — r{d.previous_revision?.revision_no ?? "-"} → r{d.revision.revision_no}
      </Text>
      <Card withBorder>
        <Text fw={700} mb="xs">
          변경 전후 문구
        </Text>
        <TextDiff before={d.previous_revision?.content ?? ""} after={d.revision.content} />
      </Card>

      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Card withBorder>
          <Text fw={700} mb="xs">
            적용 대상 문서 (사용 중) {d.document_targets.length}개
          </Text>
          <DocumentImpactTable rows={d.document_targets} />
        </Card>
        <Card withBorder>
          <Text fw={700} mb="xs">
            제외 문서 {d.document_excluded.length}개
          </Text>
          <DocumentImpactTable rows={d.document_excluded} withReason />
        </Card>
      </SimpleGrid>

      {(d.targets.length > 0 || d.excluded.length > 0) && (
        <SimpleGrid cols={{ base: 1, md: 2 }}>
          <Card withBorder>
            <Text fw={700} mb="xs">
              적용 대상 상품 (판매 중) {d.targets.length}개
            </Text>
            <ImpactTable rows={d.targets} />
          </Card>
          <Card withBorder>
            <Text fw={700} mb="xs">
              제외 상품 {d.excluded.length}개
            </Text>
            <ImpactTable rows={d.excluded} withReason />
          </Card>
        </SimpleGrid>
      )}

      {d.document_targets[0] ? (
        <DocumentPreview target={d.document_targets[0]} />
      ) : (
        d.targets[0] && <RepresentativePreview product={d.targets[0]} />
      )}

      <Card withBorder>
        <Stack>
          <Alert color="blue">
            실행하면 사용 중 문서(와 판매 중 상품)마다 새 버전을 만들어 PDF·PNG로 발행합니다. 기존 발행본, 종료된
            문서·상품, 문서에서 고친 단락은 바뀌지 않습니다. 실행 직전에 대상을 다시 확인합니다.
          </Alert>
          <MissingValues missing={d.missing_variables ?? []} values={values} onChange={setValues} />
          <TextInput label="수정 사유" required value={reason} onChange={(e) => setReason(e.currentTarget.value)} />
          <ErrorAlert error={run.error} />
          <Button
            disabled={
              !reason.trim() ||
              !allFilled(d.missing_variables ?? [], values) ||
              d.targets.length + d.document_targets.length === 0
            }
            loading={run.isPending}
            onClick={() => run.mutate()}
          >
            문서 {d.document_targets.length}개
            {d.targets.length > 0 ? ` · 상품 ${d.targets.length}개` : ""}에 적용
          </Button>
        </Stack>
      </Card>
    </Stack>
  );
}

function TextDiff({ before, after }: { before: string; after: string }) {
  return (
    <Box style={{ fontFamily: "monospace", fontSize: 13, whiteSpace: "pre-wrap" }}>
      {diffLines(before, after).map((line, i) => (
        <div
          key={i}
          style={{
            background: line.kind === "added" ? "#e6f6e6" : line.kind === "removed" ? "#fde8e8" : undefined,
            textDecoration: line.kind === "removed" ? "line-through" : undefined,
          }}
        >
          {line.kind === "added" ? "+ " : line.kind === "removed" ? "- " : "  "}
          {line.text || " "}
        </div>
      ))}
    </Box>
  );
}

function ImpactTable({ rows, withReason }: { rows: ImpactProduct[]; withReason?: boolean }) {
  if (rows.length === 0) return <Text c="dimmed">없음</Text>;
  return (
    <Table>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>상품</Table.Th>
          <Table.Th>상태</Table.Th>
          <Table.Th>현재 발행본</Table.Th>
          {withReason && <Table.Th>사유</Table.Th>}
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {rows.map((r) => (
          <Table.Tr key={r.product_id}>
            <Table.Td>
              <Link to={`/products/${r.product_id}`}>{r.name}</Link>
              <Text size="xs" c="dimmed">
                {r.product_code}
              </Text>
            </Table.Td>
            <Table.Td>
              <StatusBadge status={r.status} />
            </Table.Td>
            <Table.Td>
              {r.current_version_no ? `v${r.current_version_no}` : "-"}
              {r.current_clause_revision_no ? ` (모듈 r${r.current_clause_revision_no})` : ""}
            </Table.Td>
            {withReason && <Table.Td>{r.reason}</Table.Td>}
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

// 작업 이름: 모듈 반영은 "모듈 r3", 변수 반영은 "변수 [수수료] → 2,000원"
export function jobTitle(j: BulkUpdateSummary): string {
  return j.kind === "VARIABLE"
    ? `변수 [${j.variable_label}] → ${j.variable_value || "(비움)"}`
    : `${j.clause_title} r${j.revision_no}`;
}

function DocumentImpactTable({
  rows,
  withReason,
  variable,
}: {
  rows: ImpactDocument[];
  withReason?: boolean;
  variable?: boolean;
}) {
  if (rows.length === 0) return <Text c="dimmed">없음</Text>;
  return (
    <Table>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>문서</Table.Th>
          <Table.Th>상태</Table.Th>
          <Table.Th>{variable ? "문서 입력값" : "바뀔 단락"}</Table.Th>
          {withReason && <Table.Th>사유</Table.Th>}
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {rows.map((r) => (
          <Table.Tr key={r.document_id}>
            <Table.Td>
              <Link to={`/documents/${r.document_id}`}>{r.title}</Link>
              {r.current_publication_no && (
                <Text size="xs" c="dimmed">
                  발행 v{r.current_publication_no}
                </Text>
              )}
            </Table.Td>
            <Table.Td>
              <StatusBadge status={`DOC_${r.status}`} />
            </Table.Td>
            <Table.Td>
              {variable ? (
                (r.own_value ?? <Text c="dimmed">기본값 사용</Text>)
              ) : (
                <>
                  {r.outdated_blocks}
                  {r.modified_blocks > 0 ? ` (수정됨 ${r.modified_blocks})` : ""}
                </>
              )}
            </Table.Td>
            {withReason && <Table.Td>{r.reason}</Table.Td>}
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

// 대표 문서: 변경 전(저장된 현재 문서)만 보여 준다. 변경 후는 실행 뒤 새 발행본에서 확인한다.
function DocumentPreview({ target }: { target: ImpactDocument }) {
  return (
    <Card withBorder>
      <Text fw={700} mb="xs">
        대표 문서 · {target.title} (현재 내용)
      </Text>
      <HtmlFrame src={documentPreviewUrl(target.document_id)} height={480} />
    </Card>
  );
}

function RepresentativePreview({ product }: { product: ImpactProduct }) {
  const after = useQuery({
    queryKey: ["preview", product.product_id, []],
    queryFn: () => api<PreviewOut>(`/products/${product.product_id}/preview`, { body: { excluded_clause_keys: [] } }),
  });
  return (
    <Card withBorder>
      <Text fw={700} mb="xs">
        대표 상품 미리보기 · {product.name}
      </Text>
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Stack gap={4}>
          <Text size="sm" c="dimmed">
            변경 전 (발행본 v{product.current_version_no ?? "-"})
          </Text>
          {product.current_version_id ? (
            <HtmlFrame src={versionHtmlUrl(product.current_version_id)} height={520} />
          ) : (
            <Text c="dimmed">발행본 없음</Text>
          )}
        </Stack>
        <Stack gap={4}>
          <Text size="sm" c="dimmed">
            변경 후 (미리보기)
          </Text>
          {after.data ? <HtmlFrame html={after.data.combined_html} height={520} /> : <ErrorAlert error={after.error} />}
        </Stack>
      </SimpleGrid>
    </Card>
  );
}

// --- 작업 결과 (가이드 7장 6단계) ------------------------------------------------------

export function BulkUpdateResult({ id }: { id: string }) {
  const qc = useQueryClient();
  const job = useQuery({
    queryKey: ["bulk-update", id],
    queryFn: () => api<BulkUpdateDetail>(`/bulk-updates/${id}`),
    refetchInterval: (q) => (q.state.data && !q.state.data.finished ? 2000 : false),
  });
  const [values, setValues] = useState<Record<string, string>>({});
  const retry = useMutation({
    mutationFn: () =>
      api<BulkUpdateDetail>(`/bulk-updates/${id}/retry`, { method: "POST", body: { variable_values: values } }),
    onSuccess: (data) => {
      setValues({});
      qc.setQueryData(["bulk-update", id], data);
    },
  });

  if (job.isPending) return <Loading />;
  if (!job.data) return <ErrorAlert error={job.error} />;
  const j = job.data;
  const failed = j.items.filter((i) => i.result === "FAILED");
  const missing = j.missing_variables ?? [];
  const exportFailed = () =>
    downloadText(
      `일괄반영_실패목록_${jobTitle(j).replace(/[\\/:*?"<>|\s]+/g, "_")}.csv`,
      toCsv(
        ["상품 코드", "상품명", "결과", "사유"],
        failed.map((i) => [i.code ?? "", i.name, i.result, i.message]),
      ),
    );

  return (
    <Stack>
      <Link to="/bulk-updates">← 일괄 반영 작업</Link>
      <Title order={2}>
        일괄 반영 결과 · {jobTitle(j)}
      </Title>
      <Text size="sm" c="dimmed">
        {formatDateTime(j.created_at)} · 사유: {j.change_reason} · 요청 ID {j.request_id}
      </Text>
      <SimpleGrid cols={{ base: 2, md: 5 }}>
        <Stat label="대상" value={j.counts.total} />
        <Stat label="성공" value={j.counts.succeeded} color="green" />
        <Stat label="진행 중" value={j.counts.running} color="blue" />
        <Stat label="실패" value={j.counts.failed} color="red" />
        <Stat label="건너뜀" value={j.counts.skipped} color="orange" />
      </SimpleGrid>
      <MissingValues missing={missing} values={values} onChange={setValues} />
      <Group>
        <Button color="orange" disabled={failed.length === 0 || !allFilled(missing, values)} loading={retry.isPending} onClick={() => retry.mutate()}>
          실패 {failed.length}건 다시 시도
        </Button>
        <Button variant="light" disabled={failed.length === 0} onClick={exportFailed}>
          실패 목록 내려받기 (CSV)
        </Button>
      </Group>
      <ErrorAlert error={retry.error} />
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>대상</Table.Th>
            <Table.Th>결과</Table.Th>
            <Table.Th>새 버전</Table.Th>
            <Table.Th>사유</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {j.items.map((i) => (
            <Table.Tr key={i.target_id}>
              <Table.Td>
                <Link to={i.target_type === "DOCUMENT" ? `/documents/${i.target_id}` : `/products/${i.target_id}`}>
                  {i.name}
                </Link>
                <Text size="xs" c="dimmed">
                  {i.target_type === "DOCUMENT" ? "문서" : `상품 ${i.code}`}
                </Text>
              </Table.Td>
              <Table.Td>
                <StatusBadge status={i.result} />
              </Table.Td>
              <Table.Td>{i.version_no ? `v${i.version_no}` : "-"}</Table.Td>
              <Table.Td>{i.message}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {j.document_excluded.length > 0 && (
        <Card withBorder>
          <Text fw={700} mb="xs">
            실행 시 제외된 문서 {j.document_excluded.length}개
          </Text>
          <DocumentImpactTable rows={j.document_excluded} withReason variable={j.kind === "VARIABLE"} />
        </Card>
      )}
      {j.excluded.length > 0 && (
        <Card withBorder>
          <Text fw={700} mb="xs">
            실행 시 제외된 상품 {j.excluded.length}개
          </Text>
          <ImpactTable rows={j.excluded} withReason />
        </Card>
      )}
    </Stack>
  );
}

function Stat({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <Card withBorder padding="sm">
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="xl" fw={700} c={color}>
        {value}
      </Text>
    </Card>
  );
}

export function BulkUpdateList() {
  const jobs = useQuery({ queryKey: ["bulk-updates"], queryFn: () => api<BulkUpdateSummary[]>("/bulk-updates") });
  if (jobs.isPending) return <Loading />;
  return (
    <Stack>
      <Title order={2}>일괄 반영 작업</Title>
      <Text size="sm" c="dimmed">
        새 작업은 모듈 화면에서 새 버전을 저장한 뒤 영향 분석을 거쳐 실행합니다.
      </Text>
      <ErrorAlert error={jobs.error} />
      <Table striped highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>실행 시각</Table.Th>
            <Table.Th>반영한 것</Table.Th>
            <Table.Th>사유</Table.Th>
            <Table.Th>결과</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {jobs.data?.map((j) => (
            <Table.Tr key={j.id} style={{ cursor: "pointer" }} onClick={() => navigate(`/bulk-updates/${j.id}`)}>
              <Table.Td>{formatDateTime(j.created_at)}</Table.Td>
              <Table.Td>{jobTitle(j)}</Table.Td>
              <Table.Td>{j.change_reason}</Table.Td>
              <Table.Td>
                성공 {j.counts.succeeded} · 실패 {j.counts.failed} · 건너뜀 {j.counts.skipped}
                {!j.finished && ` · 진행 중 ${j.counts.running}`}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {jobs.data?.length === 0 && <Text c="dimmed">작업이 없습니다.</Text>}
    </Stack>
  );
}
