// 문서에 넣을 모듈 고르기: 검색·카테고리·태그로 찾아 여러 개를 체크하고, 넣을 순서를 정한 뒤 한 번에 넣는다.
import { DndContext, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Checkbox,
  Grid,
  Group,
  Modal,
  ScrollArea,
  Select,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, type ClauseDetail, type ClauseSummary, type RichDoc, type TagOut } from "../api/client";
import { categoryOptions, useCategories } from "../components/CategoryTree";
import { Loading } from "../components/common";
import { RichEditor } from "../editor/RichEditor";

type Picked = { id: string; title: string };

export function ModulePicker({
  opened,
  onClose,
  onPick,
}: {
  opened: boolean;
  onClose: () => void;
  // 고른 모듈 ID (넣을 순서대로)
  onPick: (clauseIds: string[]) => void;
}) {
  const [q, setQ] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [tag, setTag] = useState<string | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [picked, setPicked] = useState<Picked[]>([]);
  const categories = useCategories();
  const tags = useQuery({ queryKey: ["tags"], queryFn: () => api<TagOut[]>("/tags"), enabled: opened });
  const params = new URLSearchParams();
  if (q.trim()) params.set("q", q.trim());
  if (category) params.set("category_id", category);
  if (tag) params.set("tag", tag);
  const modules = useQuery({
    queryKey: ["clauses", params.toString()],
    queryFn: () => api<ClauseSummary[]>(`/clauses?${params}`),
    enabled: opened,
  });
  const detail = useQuery({
    queryKey: ["clause", previewId],
    queryFn: () => api<ClauseDetail>(`/clauses/${previewId}`),
    enabled: previewId !== null,
  });
  const latest = detail.data?.revisions[detail.data.revisions.length - 1];
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  const isPicked = (id: string) => picked.some((p) => p.id === id);
  const toggle = (m: { id: string; title: string }) =>
    setPicked((list) => (list.some((p) => p.id === m.id) ? list.filter((p) => p.id !== m.id) : [...list, m]));
  const move = (index: number, delta: number) =>
    setPicked((list) => {
      const to = index + delta;
      return to < 0 || to >= list.length ? list : arrayMove(list, index, to);
    });
  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return;
    setPicked((list) =>
      arrayMove(
        list,
        list.findIndex((p) => p.id === e.active.id),
        list.findIndex((p) => p.id === e.over!.id),
      ),
    );
  };
  const close = () => {
    setPicked([]);
    setPreviewId(null);
    onClose();
  };
  const submit = () => {
    const ids = picked.map((p) => p.id);
    setPicked([]);
    setPreviewId(null);
    onPick(ids);
  };

  return (
    <Modal opened={opened} onClose={close} size="90%" title="모듈 가져오기">
      <Stack>
        <Group grow>
          <TextInput placeholder="제목·본문 검색" value={q} onChange={(e) => setQ(e.currentTarget.value)} data-autofocus />
          <Select placeholder="카테고리" clearable data={categoryOptions(categories.data)} value={category} onChange={setCategory} />
          <Select
            placeholder="태그"
            clearable
            data={(tags.data ?? []).filter((t) => t.module_count > 0).map((t) => t.name)}
            value={tag}
            onChange={setTag}
          />
        </Group>
        <Grid>
          <Grid.Col span={4}>
            <Group justify="space-between" mb={6}>
              <Text size="sm" fw={600}>
                모듈 목록
              </Text>
              <Button
                size="compact-xs"
                variant="subtle"
                disabled={!modules.data?.length}
                onClick={() =>
                  setPicked((list) => [
                    ...list,
                    ...(modules.data ?? []).filter((m) => !list.some((p) => p.id === m.id)).map((m) => ({ id: m.id, title: m.title })),
                  ])
                }
              >
                보이는 것 모두 선택
              </Button>
            </Group>
            <ScrollArea h={440}>
              {modules.isPending && <Loading />}
              <Stack gap={6}>
                {modules.data?.map((m) => (
                  <Card
                    key={m.id}
                    withBorder
                    padding="xs"
                    style={{
                      cursor: "pointer",
                      borderColor: m.id === previewId ? "var(--mantine-color-indigo-5)" : undefined,
                      background: isPicked(m.id) ? "var(--mantine-color-indigo-0)" : undefined,
                    }}
                    onClick={() => setPreviewId(m.id)}
                  >
                    <Group wrap="nowrap" align="flex-start" gap="xs">
                      <Checkbox
                        mt={2}
                        checked={isPicked(m.id)}
                        onChange={() => toggle(m)}
                        onClick={(e) => e.stopPropagation()}
                        aria-label={`${m.title} 선택`}
                      />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <Text fw={600} size="sm" lineClamp={1}>
                          {m.title}
                        </Text>
                        <Text size="xs" c="dimmed" lineClamp={2}>
                          {m.excerpt}
                        </Text>
                        <Group gap={4} mt={2}>
                          {m.tags.map((t) => (
                            <Badge key={t} size="xs" variant="outline">
                              {t}
                            </Badge>
                          ))}
                        </Group>
                      </div>
                    </Group>
                  </Card>
                ))}
                {modules.data?.length === 0 && <Text c="dimmed" size="sm">모듈이 없습니다.</Text>}
              </Stack>
            </ScrollArea>
          </Grid.Col>

          <Grid.Col span={4}>
            <Group justify="space-between" mb={6}>
              <Text size="sm" fw={600}>
                넣을 순서 ({picked.length}개)
              </Text>
              <Group gap={4}>
                <Button
                  size="compact-xs"
                  variant="subtle"
                  disabled={picked.length < 2}
                  onClick={() => setPicked((list) => [...list].sort((a, b) => a.title.localeCompare(b.title, "ko")))}
                >
                  제목순 정렬
                </Button>
                <Button size="compact-xs" variant="subtle" color="gray" disabled={!picked.length} onClick={() => setPicked([])}>
                  모두 빼기
                </Button>
              </Group>
            </Group>
            <Card withBorder h={440} padding="xs" style={{ overflow: "auto" }}>
              {picked.length === 0 ? (
                <Text c="dimmed" size="sm">
                  왼쪽에서 넣을 모듈을 체크하세요. 체크한 순서대로 쌓이고, 끌어서 순서를 바꿀 수 있습니다.
                </Text>
              ) : (
                <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
                  <SortableContext items={picked.map((p) => p.id)} strategy={verticalListSortingStrategy}>
                    <Stack gap={4}>
                      {picked.map((p, i) => (
                        <PickedRow
                          key={p.id}
                          item={p}
                          index={i}
                          last={i === picked.length - 1}
                          active={p.id === previewId}
                          onPreview={() => setPreviewId(p.id)}
                          onMove={(delta) => move(i, delta)}
                          onRemove={() => toggle(p)}
                        />
                      ))}
                    </Stack>
                  </SortableContext>
                </DndContext>
              )}
            </Card>
          </Grid.Col>

          <Grid.Col span={4}>
            <Text size="sm" fw={600} mb={6}>
              미리보기
            </Text>
            <Card withBorder h={440} style={{ overflow: "auto" }}>
              {latest ? (
                <Stack>
                  <Text fw={700}>{detail.data?.title}</Text>
                  <RichEditor content={latest.content_json as RichDoc} editable={false} resetKey={latest.id} />
                </Stack>
              ) : (
                <Text c="dimmed" size="sm">
                  모듈을 누르면 내용을 미리 볼 수 있습니다.
                </Text>
              )}
            </Card>
          </Grid.Col>
        </Grid>
        <Group justify="flex-end">
          <Button variant="default" onClick={close}>
            취소
          </Button>
          <Button disabled={picked.length === 0} onClick={submit}>
            {picked.length > 0 ? `${picked.length}개 넣기` : "모듈을 고르세요"}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function PickedRow({
  item,
  index,
  last,
  active,
  onPreview,
  onMove,
  onRemove,
}: {
  item: Picked;
  index: number;
  last: boolean;
  active: boolean;
  onPreview: () => void;
  onMove: (delta: number) => void;
  onRemove: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: item.id });
  return (
    <Card
      ref={setNodeRef}
      withBorder
      padding={6}
      onClick={onPreview}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.6 : 1,
        cursor: "pointer",
        borderColor: active ? "var(--mantine-color-indigo-5)" : undefined,
      }}
    >
      <Group wrap="nowrap" gap={6}>
        <span className="drag-handle" {...attributes} {...listeners} title="끌어서 순서 바꾸기" onClick={(e) => e.stopPropagation()}>
          ⠿
        </span>
        <Text size="xs" c="dimmed" w={18}>
          {index + 1}.
        </Text>
        <Text size="sm" lineClamp={1} style={{ flex: 1 }}>
          {item.title}
        </Text>
        <Group gap={2} wrap="nowrap" onClick={(e) => e.stopPropagation()}>
          <ActionIcon size="sm" variant="subtle" color="gray" disabled={index === 0} onClick={() => onMove(-1)} aria-label="위로">
            ↑
          </ActionIcon>
          <ActionIcon size="sm" variant="subtle" color="gray" disabled={last} onClick={() => onMove(1)} aria-label="아래로">
            ↓
          </ActionIcon>
          <ActionIcon size="sm" variant="subtle" color="red" onClick={onRemove} aria-label="빼기">
            ×
          </ActionIcon>
        </Group>
      </Group>
    </Card>
  );
}
