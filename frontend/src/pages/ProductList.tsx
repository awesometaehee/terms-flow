import { Group, Select, Stack, Table, Text, TextInput, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, type ProductSummary } from "../api/client";
import { ErrorAlert, Loading, StatusBadge, formatDateTime } from "../components/common";
import { Link } from "../router";

const STATUS_OPTIONS = [
  { value: "", label: "전체 상태" },
  { value: "DRAFT", label: "작성 중" },
  { value: "ACTIVE", label: "판매 중" },
  { value: "ENDED", label: "판매 종료" },
];

export function ProductList() {
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (q.trim()) params.set("q", q.trim());
  const query = useQuery({
    queryKey: ["products", status, q.trim()],
    queryFn: () => api<ProductSummary[]>(`/products?${params}`),
  });

  return (
    <Stack>
      <Title order={2}>상품</Title>
      <Group>
        <Select data={STATUS_OPTIONS} value={status} onChange={(v) => setStatus(v ?? "")} w={160} />
        <TextInput placeholder="상품명·상품 코드 검색" value={q} onChange={(e) => setQ(e.currentTarget.value)} w={280} />
      </Group>
      <ErrorAlert error={query.error} />
      {query.isPending ? (
        <Loading />
      ) : (
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>상품 코드</Table.Th>
              <Table.Th>상품명</Table.Th>
              <Table.Th>법인</Table.Th>
              <Table.Th>상태</Table.Th>
              <Table.Th>판매 구성</Table.Th>
              <Table.Th>최근 발행 버전</Table.Th>
              <Table.Th>수정일</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {query.data?.map((p) => (
              <Table.Tr key={p.id}>
                <Table.Td>{p.product_code}</Table.Td>
                <Table.Td>
                  <Link to={`/products/${p.id}`}>{p.name}</Link>
                </Table.Td>
                <Table.Td>{p.company.name}</Table.Td>
                <Table.Td>
                  <StatusBadge status={p.status} />
                </Table.Td>
                <Table.Td>{p.variant_count}개</Table.Td>
                <Table.Td>{p.latest_document_set_version_no ? `v${p.latest_document_set_version_no}` : "-"}</Table.Td>
                <Table.Td>{formatDateTime(p.updated_at)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      {query.data?.length === 0 && <Text c="dimmed">상품이 없습니다.</Text>}
    </Stack>
  );
}
