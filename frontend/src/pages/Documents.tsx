import {
  Badge,
  Button,
  Card,
  Grid,
  Group,
  Modal,
  SegmentedControl,
  Select,
  Stack,
  Table,
  TagsInput,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type DocumentDetail, type DocumentSummary, type TagOut } from "../api/client";
import { CategoryTree, categoryOptions, useCategories } from "../components/CategoryTree";
import { ErrorAlert, Loading, StatusBadge, formatDateTime } from "../components/common";
import { navigate } from "../router";

const STATUS_FILTER = [
  { value: "", label: "전체" },
  { value: "DRAFT", label: "작성 중" },
  { value: "ACTIVE", label: "사용 중" },
  { value: "ENDED", label: "종료" },
];

export function DocumentList() {
  const [category, setCategory] = useState<string | null>(null);
  const [tag, setTag] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const categories = useCategories();
  const tags = useQuery({ queryKey: ["tags"], queryFn: () => api<TagOut[]>("/tags") });
  const params = new URLSearchParams();
  if (category) params.set("category_id", category);
  if (tag) params.set("tag", tag);
  if (status) params.set("status", status);
  if (q.trim()) params.set("q", q.trim());
  const documents = useQuery({
    queryKey: ["documents", params.toString()],
    queryFn: () => api<DocumentSummary[]>(`/documents?${params}`),
  });
  const qc = useQueryClient();
  const remove = useMutation({
    mutationFn: (id: string) => api(`/documents/${id}`, { method: "DELETE" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["documents"] }),
  });
  const categoryName = (id: string | null) => categories.data?.find((c) => c.id === id)?.name ?? "-";

  return (
    <Grid>
      <Grid.Col span={{ base: 12, md: 3 }}>
        <Card withBorder>
          <CategoryTree selected={category} onSelect={setCategory} />
        </Card>
      </Grid.Col>
      <Grid.Col span={{ base: 12, md: 9 }}>
        <Stack>
          <Group justify="space-between">
            <Title order={2}>문서</Title>
            <Button onClick={() => setCreating(true)}>+ 새 문서</Button>
          </Group>
          <Group>
            <SegmentedControl data={STATUS_FILTER} value={status} onChange={setStatus} size="xs" />
            <TextInput placeholder="제목·본문 검색" value={q} onChange={(e) => setQ(e.currentTarget.value)} w={240} />
            <Select
              placeholder="태그"
              clearable
              data={(tags.data ?? []).filter((t) => t.document_count > 0).map((t) => t.name)}
              value={tag}
              onChange={setTag}
              w={160}
            />
          </Group>
          <ErrorAlert error={documents.error ?? remove.error} />
          {documents.isPending ? (
            <Loading />
          ) : (
            <Table striped highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>제목</Table.Th>
                  <Table.Th>카테고리</Table.Th>
                  <Table.Th>상태</Table.Th>
                  <Table.Th>단락</Table.Th>
                  <Table.Th>버전</Table.Th>
                  <Table.Th>수정</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {documents.data?.map((d) => (
                  <Table.Tr key={d.id} style={{ cursor: "pointer" }} onClick={() => navigate(`/documents/${d.id}`)}>
                    <Table.Td>
                      <Text fw={600}>{d.title}</Text>
                      <Group gap={4}>
                        {d.tags.map((t) => (
                          <Badge key={t} size="xs" variant="outline">
                            {t}
                          </Badge>
                        ))}
                      </Group>
                    </Table.Td>
                    <Table.Td>{categoryName(d.category_id)}</Table.Td>
                    <Table.Td>
                      <StatusBadge status={`DOC_${d.status}`} />
                    </Table.Td>
                    <Table.Td>{d.block_count}</Table.Td>
                    <Table.Td>
                      r{d.revision_no}
                      {d.latest_publication_no ? ` · 발행 v${d.latest_publication_no}` : ""}
                    </Table.Td>
                    <Table.Td>{formatDateTime(d.updated_at)}</Table.Td>
                    <Table.Td onClick={(e) => e.stopPropagation()}>
                      <DeleteDocumentButton
                        title={d.title}
                        ended={d.status === "ENDED"}
                        loading={remove.isPending && remove.variables === d.id}
                        onDelete={() => remove.mutate(d.id)}
                      />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
          {documents.data?.length === 0 && <Text c="dimmed">문서가 없습니다.</Text>}
        </Stack>
      </Grid.Col>
      <Modal opened={creating} onClose={() => setCreating(false)} title="새 문서">
        <NewDocumentForm defaultCategory={category} existing={documents.data ?? []} />
      </Modal>
    </Grid>
  );
}

function NewDocumentForm({ defaultCategory, existing }: { defaultCategory: string | null; existing: DocumentSummary[] }) {
  const categories = useCategories();
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<string | null>(defaultCategory);
  const [tags, setTags] = useState<string[]>([]);
  const [copyFrom, setCopyFrom] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () =>
      api<DocumentDetail>("/documents", {
        body: { title, category_id: category, tags, copy_from_document_id: copyFrom },
      }),
    onSuccess: (doc) => navigate(`/documents/${doc.id}`),
  });
  return (
    <Stack>
      <TextInput label="제목" required value={title} onChange={(e) => setTitle(e.currentTarget.value)} data-autofocus />
      <Select label="카테고리" clearable data={categoryOptions(categories.data)} value={category} onChange={setCategory} />
      <TagsInput label="태그" value={tags} onChange={setTags} placeholder="입력 후 Enter" />
      <Select
        label="다른 문서를 복제해서 시작 (선택)"
        clearable
        searchable
        data={existing.map((d) => ({ value: d.id, label: d.title }))}
        value={copyFrom}
        onChange={setCopyFrom}
      />
      <ErrorAlert error={create.error} />
      <Button disabled={!title.trim()} loading={create.isPending} onClick={() => create.mutate()}>
        만들고 편집하기
      </Button>
    </Stack>
  );
}

// 문서 삭제 버튼. 종료 문서는 보관 기록이라 지울 수 없어 이유를 보여 준다.
export function DeleteDocumentButton({
  title,
  ended,
  loading,
  onDelete,
}: {
  title: string;
  ended: boolean;
  loading?: boolean;
  onDelete: () => void;
}) {
  const button = (
    <Button
      size="xs"
      variant="subtle"
      color="red"
      disabled={ended}
      loading={loading}
      onClick={() => window.confirm(`'${title}' 문서를 삭제할까요?
목록과 검색에서 사라집니다.`) && onDelete()}
    >
      삭제
    </Button>
  );
  return ended ? (
    <Tooltip label="종료된 문서는 보관 기록이라 삭제할 수 없습니다">
      <span>{button}</span>
    </Tooltip>
  ) : (
    button
  );
}
