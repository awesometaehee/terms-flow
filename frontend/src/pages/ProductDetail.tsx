import {
  Alert,
  Button,
  Card,
  Checkbox,
  Group,
  Modal,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type PreviewOut, type ProductDetail as Product } from "../api/client";
import { ErrorAlert, HtmlFrame, Loading, StatusBadge, formatWon } from "../components/common";
import { Link } from "../router";
import { DocumentHistory } from "./DocumentHistory";

const NEXT_STATUS: Record<string, { to: string; label: string } | undefined> = {
  DRAFT: { to: "ACTIVE", label: "판매 시작" },
  ACTIVE: { to: "ENDED", label: "판매 종료" },
};

export function ProductDetail({ id }: { id: string }) {
  const qc = useQueryClient();
  const product = useQuery({ queryKey: ["product", id], queryFn: () => api<Product>(`/products/${id}`) });
  const [statusOpen, setStatusOpen] = useState(false);
  const [reason, setReason] = useState("");
  const changeStatus = useMutation({
    mutationFn: (p: Product) =>
      api<Product>(`/products/${id}/status`, {
        body: { status: NEXT_STATUS[p.status]!.to, lock_version: p.lock_version, reason },
      }),
    onSuccess: () => {
      setStatusOpen(false);
      setReason("");
      void qc.invalidateQueries({ queryKey: ["product", id] });
    },
  });

  if (product.isPending) return <Loading />;
  if (!product.data) return <ErrorAlert error={product.error} />;
  const p = product.data;
  const next = NEXT_STATUS[p.status];
  const ended = p.status === "ENDED";

  return (
    <Stack>
      <Link to="/products">← 상품 목록</Link>
      <Group justify="space-between">
        <Group>
          <Title order={2}>{p.name}</Title>
          <StatusBadge status={p.status} />
        </Group>
        {next && (
          <Button variant="light" color={next.to === "ENDED" ? "red" : "green"} onClick={() => setStatusOpen(true)}>
            {next.label}
          </Button>
        )}
      </Group>
      {ended && (
        <Alert color="gray">판매 종료 상품은 읽기 전용입니다. 과거 문서 조회와 다운로드만 할 수 있습니다.</Alert>
      )}
      <Card withBorder>
        <Text size="sm">
          상품 코드 {p.product_code} · 법인 {p.company.name} · 판매 채널 {p.channel} · 환급 방식 {p.refund_type} ·
          유형 {p.bundle_type === "BUNDLE" ? "결합 상품" : "일반"} · 상품 버전 {p.current_revision_no}
        </Text>
        <Table mt="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>구성 코드</Table.Th>
              <Table.Th>이름</Table.Th>
              <Table.Th>금액</Table.Th>
              <Table.Th>품목 그룹</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {p.variants.map((v) => (
              <Table.Tr key={v.id}>
                <Table.Td>{v.variant_code}</Table.Td>
                <Table.Td>{v.display_name}</Table.Td>
                <Table.Td>{formatWon(v.price_amount)}</Table.Td>
                <Table.Td>
                  {((v.composition as { groups?: { label: string }[] }).groups ?? []).map((g) => g.label).join(", ")}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
      <Tabs defaultValue="history">
        <Tabs.List>
          <Tabs.Tab value="history">문서 이력</Tabs.Tab>
          {!ended && <Tabs.Tab value="publish">미리보기·발행</Tabs.Tab>}
        </Tabs.List>
        <Tabs.Panel value="history" pt="md">
          <DocumentHistory productId={id} readOnly={ended} />
        </Tabs.Panel>
        {!ended && (
          <Tabs.Panel value="publish" pt="md">
            <PreviewPublish productId={id} />
          </Tabs.Panel>
        )}
      </Tabs>
      <Modal opened={statusOpen} onClose={() => setStatusOpen(false)} title={next?.label}>
        <Stack>
          {next?.to === "ENDED" && (
            <Alert color="red">판매 종료 후에는 상품과 문서를 바꿀 수 없고, 공통 문구 일괄 수정에서도 제외됩니다.</Alert>
          )}
          <TextInput label="사유" required value={reason} onChange={(e) => setReason(e.currentTarget.value)} />
          <ErrorAlert error={changeStatus.error} />
          <Button disabled={!reason.trim()} loading={changeStatus.isPending} onClick={() => changeStatus.mutate(p)}>
            확인
          </Button>
        </Stack>
      </Modal>
    </Stack>
  );
}

// 3종·통합본 미리보기, 선택 조항 제외, 발행 (가이드 9장 3·4번)
function PreviewPublish({ productId }: { productId: string }) {
  const qc = useQueryClient();
  const [excluded, setExcluded] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const preview = useQuery({
    queryKey: ["preview", productId, excluded],
    queryFn: () => api<PreviewOut>(`/products/${productId}/preview`, { body: { excluded_clause_keys: excluded } }),
  });
  const publish = useMutation({
    mutationFn: () =>
      api(`/products/${productId}/document-sets`, {
        body: { change_reason: reason, excluded_clause_keys: excluded },
      }),
    onSuccess: () => {
      setReason("");
      void qc.invalidateQueries({ queryKey: ["document-sets", productId] });
      void qc.invalidateQueries({ queryKey: ["product", productId] });
    },
  });
  const toggle = (key: string, include: boolean) =>
    setExcluded((cur) => (include ? cur.filter((k) => k !== key) : [...cur, key]));

  if (preview.isPending) return <Loading />;
  if (!preview.data) return <ErrorAlert error={preview.error} />;
  const data = preview.data;
  return (
    <Stack>
      <Tabs defaultValue={data.documents[0]?.document_type}>
        <Tabs.List>
          {data.documents.map((d) => (
            <Tabs.Tab key={d.document_type} value={d.document_type}>
              {d.label}
            </Tabs.Tab>
          ))}
          <Tabs.Tab value="combined">통합본</Tabs.Tab>
        </Tabs.List>
        {data.documents.map((d) => (
          <Tabs.Panel key={d.document_type} value={d.document_type} pt="md">
            <Group align="flex-start" grow>
              <Stack gap="xs" maw={420}>
                <Text size="sm" c="dimmed">
                  템플릿 {d.template_key} r{d.template_revision_no}
                </Text>
                {d.clauses.length === 0 && <Text size="sm">조항 규칙이 없는 문서입니다.</Text>}
                {d.clauses.map((c) => (
                  <Checkbox
                    key={c.clause_key}
                    checked={c.included}
                    disabled={c.required || (!c.included && !excluded.includes(c.clause_key))}
                    onChange={(e) => toggle(c.clause_key, e.currentTarget.checked)}
                    label={`${c.order ? `${c.order}. ` : ""}${c.title} (r${c.revision_no})${c.required ? " · 필수" : ""}`}
                    description={c.reason}
                  />
                ))}
              </Stack>
              <HtmlFrame html={d.html} />
            </Group>
          </Tabs.Panel>
        ))}
        <Tabs.Panel value="combined" pt="md">
          <HtmlFrame html={data.combined_html} />
        </Tabs.Panel>
      </Tabs>
      <Card withBorder>
        <Group align="flex-end">
          <TextInput
            label="발행 사유"
            required
            value={reason}
            onChange={(e) => setReason(e.currentTarget.value)}
            style={{ flex: 1 }}
          />
          <Button disabled={!reason.trim()} loading={publish.isPending} onClick={() => publish.mutate()}>
            새 버전 발행
          </Button>
        </Group>
        <Text size="xs" c="dimmed" mt="xs">
          발행하면 위 미리보기와 같은 조항 버전으로 PDF·PNG를 만들어 새 문서 세트 버전으로 보관합니다. 결과는 문서 이력에서 확인합니다.
        </Text>
        <ErrorAlert error={publish.error} />
        {publish.isSuccess && <Alert color="green">발행을 요청했습니다. 문서 이력에서 진행 상태를 확인하세요.</Alert>}
      </Card>
    </Stack>
  );
}
