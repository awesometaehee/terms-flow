// 문서 편집기: 모듈·직접 쓴 단락을 끌어서 순서를 바꾸고, 사이에 끼워 넣고, 바로 편집한다.
import { DndContext, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Grid,
  Group,
  Menu,
  Modal,
  Select,
  Stack,
  Table,
  Tabs,
  TagsInput,
  Text,
  TextInput,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  api,
  type ClauseDetail,
  type ClauseRevisionOut,
  type DocumentDetail,
  type DocumentRevisionSummary,
  type PublicationDetail,
  type PublicationSummary,
  type RichDoc,
  type VariableOut,
  documentPreviewUrl,
  publicationFileUrl,
} from "../api/client";
import { categoryOptions, useCategories } from "../components/CategoryTree";
import { ErrorAlert, HtmlFrame, Loading, StatusBadge, formatDateTime } from "../components/common";
import { EMPTY_DOC, RichEditor } from "../editor/RichEditor";
import { VariablesContext, type VariableInfo } from "../editor/variables";
import { ApplyBanner } from "../components/ApplyBanner";
import { newRequestId } from "../lib/diff";
import { useSaveShortcut } from "../lib/useSaveShortcut";
import { sameDoc } from "../lib/richdoc";
import { Link, navigate } from "../router";
import { DeleteDocumentButton } from "./Documents";
import { ModulePicker } from "./ModulePicker";

type LocalBlock = {
  id: string;
  kind: "MODULE" | "TEXT";
  clause_id: string | null;
  clause_key: string | null;
  clause_title: string | null;
  clause_revision_no: number | null;
  latest_revision_no: number | null;
  content: RichDoc;
  original: RichDoc | null;
  // 이 문서에서 원본과 다르게 고쳤는지 (서버 저장 상태 + 이번 편집)
  modified: boolean;
  // 바깥에서 본문을 통째로 바꿀 때 올린다 (원본으로 되돌리기·새 버전으로 바꾸기)
  resetCount: number;
};

type Draft = {
  title: string;
  category_id: string | null;
  tags: string[];
  variable_values: Record<string, string>;
  blocks: LocalBlock[];
};

function toDraft(doc: DocumentDetail): Draft {
  return {
    title: doc.title,
    category_id: doc.category_id,
    tags: doc.tags,
    variable_values: { ...doc.variable_values },
    blocks: doc.blocks.map((b) => ({
      id: b.id,
      kind: b.kind,
      clause_id: b.clause_id,
      clause_key: b.clause_key,
      clause_title: b.clause_title,
      clause_revision_no: b.clause_revision_no,
      latest_revision_no: b.latest_revision_no,
      content: b.content_json as RichDoc,
      original: (b.original_content_json as RichDoc | null) ?? null,
      modified: b.modified,
      resetCount: 0,
    })),
  };
}

function variableKeys(node: RichDoc, out: Set<string>): Set<string> {
  if (node.type === "variable" && typeof node.attrs?.key === "string") out.add(node.attrs.key);
  for (const child of node.content ?? []) variableKeys(child, out);
  return out;
}

export function DocumentEditor({ id }: { id: string }) {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["document", id], queryFn: () => api<DocumentDetail>(`/documents/${id}`) });
  const variables = useQuery({ queryKey: ["variables"], queryFn: () => api<VariableOut[]>("/variables") });
  const categories = useCategories();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [dirty, setDirty] = useState(false);
  const [picker, setPicker] = useState<number | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [publishOpen, setPublishOpen] = useState(false);

  // 서버 상태를 불러오면(처음·저장 후) 편집 상태를 맞춘다.
  useEffect(() => {
    if (query.data) {
      setDraft(toDraft(query.data));
      setDirty(false);
    }
  }, [query.data]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const change = (fn: (d: Draft) => Draft) => {
    setDraft((d) => (d ? fn(d) : d));
    setDirty(true);
  };
  const updateBlock = (blockId: string, patch: Partial<LocalBlock>) =>
    change((d) => ({ ...d, blocks: d.blocks.map((b) => (b.id === blockId ? { ...b, ...patch } : b)) }));

  const save = useMutation({
    mutationFn: (reason?: string) =>
      api<DocumentDetail>(`/documents/${id}`, {
        method: "PUT",
        body: {
          lock_version: query.data!.lock_version,
          change_reason: reason ?? "저장",
          title: draft!.title,
          category_id: draft!.category_id,
          tags: draft!.tags,
          variable_values: draft!.variable_values,
          blocks: draft!.blocks.map((b) =>
            b.kind === "MODULE"
              ? {
                  id: b.id,
                  kind: b.kind,
                  clause_id: b.clause_id,
                  clause_revision_no: b.clause_revision_no,
                  content_json: b.modified ? b.content : null,
                }
              : { id: b.id, kind: b.kind, content_json: b.content },
          ),
        },
      }),
    onSuccess: (data) => {
      qc.setQueryData(["document", id], data);
      void qc.invalidateQueries({ queryKey: ["document-revisions", id] });
    },
  });

  useSaveShortcut(() => save.mutate(undefined), dirty && !save.isPending && query.data?.status !== "ENDED");

  // 문서에서 고친 모듈 단락을 원본 모듈에도 저장한다. 저장하지 않은 변경이 있으면 먼저 문서를 저장한다.
  const [applyTarget, setApplyTarget] = useState<{ clauseId: string; revisionNo: number } | null>(null);
  const promote = useMutation({
    mutationFn: async (block: LocalBlock) => {
      let lockVersion = query.data!.lock_version;
      if (dirty) lockVersion = (await save.mutateAsync(undefined)).lock_version;
      const revision = await api<ClauseRevisionOut>(`/documents/${id}/blocks/${block.id}/promote`, {
        body: { lock_version: lockVersion, change_reason: "문서에서 수정한 내용 반영" },
      });
      return { clauseId: block.clause_id!, revisionNo: revision.revision_no };
    },
    onSuccess: (target) => {
      setApplyTarget(target);
      void qc.invalidateQueries({ queryKey: ["document", id] });
      void qc.invalidateQueries({ queryKey: ["document-revisions", id] });
    },
  });

  const changeStatus = useMutation({
    mutationFn: (status: "ACTIVE" | "ENDED") =>
      api<DocumentDetail>(`/documents/${id}/status`, {
        body: { status, lock_version: query.data!.lock_version, reason: status === "ACTIVE" ? "사용 시작" : "사용 종료" },
      }),
    onSuccess: (data) => qc.setQueryData(["document", id], data),
  });
  const remove = useMutation({
    mutationFn: () => api(`/documents/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["documents"] });
      navigate("/documents");
    },
  });

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));
  const usedKeys = useMemo(() => {
    const keys = new Set<string>();
    draft?.blocks.forEach((b) => variableKeys(b.content, keys));
    return keys;
  }, [draft?.blocks]);
  const variableMap = useMemo(() => {
    const map: Record<string, VariableInfo> = {};
    for (const v of variables.data ?? []) {
      map[v.key] = { key: v.key, label: v.label, value: draft?.variable_values[v.key] || v.default_value };
    }
    return map;
  }, [variables.data, draft?.variable_values]);

  if (query.isPending || !draft) return query.error ? <ErrorAlert error={query.error} /> : <Loading />;
  const doc = query.data!;
  const readOnly = doc.status === "ENDED";

  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return;
    change((d) => {
      const from = d.blocks.findIndex((b) => b.id === e.active.id);
      const to = d.blocks.findIndex((b) => b.id === e.over!.id);
      return { ...d, blocks: arrayMove(d.blocks, from, to) };
    });
  };

  // 고른 모듈들을 고른 순서대로 index 위치에 한 번에 넣는다.
  const insertModules = async (index: number, clauseIds: string[]) => {
    const clauses = await Promise.all(clauseIds.map((cid) => api<ClauseDetail>(`/clauses/${cid}`)));
    insertBlocks(
      index,
      clauses.map((clause) => {
        const latest = clause.revisions[clause.revisions.length - 1];
        return {
          id: newRequestId(),
          kind: "MODULE",
          clause_id: clause.id,
          clause_key: clause.clause_key,
          clause_title: clause.title,
          clause_revision_no: latest.revision_no,
          latest_revision_no: latest.revision_no,
          content: latest.content_json as RichDoc,
          original: latest.content_json as RichDoc,
          modified: false,
          resetCount: 0,
        };
      }),
    );
  };
  const insertBlocks = (index: number, blocks: LocalBlock[]) =>
    change((d) => ({ ...d, blocks: [...d.blocks.slice(0, index), ...blocks, ...d.blocks.slice(index)] }));
  const insertBlock = (index: number, block: LocalBlock) => insertBlocks(index, [block]);
  const insertText = (index: number) =>
    insertBlock(index, {
      id: newRequestId(),
      kind: "TEXT",
      clause_id: null,
      clause_key: null,
      clause_title: null,
      clause_revision_no: null,
      latest_revision_no: null,
      content: EMPTY_DOC,
      original: null,
      modified: false,
      resetCount: 0,
    });

  const moveBlock = (blockId: string, delta: number) =>
    change((d) => {
      const from = d.blocks.findIndex((b) => b.id === blockId);
      const to = from + delta;
      if (from < 0 || to < 0 || to >= d.blocks.length) return d;
      return { ...d, blocks: arrayMove(d.blocks, from, to) };
    });

  const updateToLatest = async (block: LocalBlock) => {
    const clause = await api<ClauseDetail>(`/clauses/${block.clause_id}`);
    const latest = clause.revisions[clause.revisions.length - 1];
    updateBlock(block.id, {
      clause_revision_no: latest.revision_no,
      latest_revision_no: latest.revision_no,
      content: latest.content_json as RichDoc,
      original: latest.content_json as RichDoc,
      modified: false,
      resetCount: block.resetCount + 1,
    });
  };

  return (
    <VariablesContext.Provider value={variableMap}>
      <Stack>
        <Group justify="space-between" align="flex-start">
          <Stack gap={4} style={{ flex: 1 }}>
            <Link to="/documents">← 문서 목록</Link>
            <Group>
              <TextInput
                value={draft.title}
                onChange={(e) => {
                  const title = e.currentTarget.value;
                  change((d) => ({ ...d, title }));
                }}
                readOnly={readOnly}
                variant="unstyled"
                size="xl"
                styles={{ input: { fontWeight: 700, fontSize: 26 } }}
                style={{ flex: 1 }}
              />
              <StatusBadge status={`DOC_${doc.status}`} />
            </Group>
          </Stack>
          <Group>
            <DeleteDocumentButton
              title={doc.title}
              ended={readOnly}
              loading={remove.isPending}
              onDelete={() => remove.mutate()}
            />
            {doc.status === "DRAFT" && (
              <Button variant="light" color="green" disabled={dirty} onClick={() => changeStatus.mutate("ACTIVE")}>
                사용 시작
              </Button>
            )}
            {doc.status === "ACTIVE" && (
              <Button
                variant="light"
                color="red"
                disabled={dirty}
                onClick={() => window.confirm("종료하면 더 이상 수정·발행할 수 없습니다. 종료할까요?") && changeStatus.mutate("ENDED")}
              >
                사용 종료
              </Button>
            )}
            <Button variant="default" onClick={() => setPreviewOpen(true)} disabled={dirty}>
              미리보기
            </Button>
            {!readOnly && (
              <>
                <Button variant="light" onClick={() => setPublishOpen(true)} disabled={dirty}>
                  발행 (PDF·PNG)
                </Button>
                <Button onClick={() => save.mutate(undefined)} disabled={!dirty} loading={save.isPending}>
                  {dirty ? "저장" : "저장됨"}
                </Button>
              </>
            )}
          </Group>
        </Group>
        {readOnly && <Alert color="gray">종료된 문서는 읽기 전용입니다.</Alert>}
        {dirty && !readOnly && (
          <Text size="xs" c="orange">
            저장하지 않은 변경이 있습니다 (Ctrl+S로 저장). 미리보기·발행·상태 변경은 저장 후에 할 수 있습니다.
          </Text>
        )}
        <ErrorAlert error={save.error ?? changeStatus.error ?? promote.error ?? remove.error} />
        {applyTarget && (
          <ApplyBanner
            key={`${applyTarget.clauseId}-${applyTarget.revisionNo}`}
            clauseId={applyTarget.clauseId}
            revisionNo={applyTarget.revisionNo}
            onClose={() => setApplyTarget(null)}
          />
        )}

        <Grid>
          <Grid.Col span={{ base: 12, lg: 8 }}>
            <Card withBorder padding="xl">
              <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
                <SortableContext items={draft.blocks.map((b) => b.id)} strategy={verticalListSortingStrategy}>
                  {!readOnly && <InsertLine onModule={() => setPicker(0)} onText={() => insertText(0)} />}
                  {draft.blocks.map((block, index) => (
                    <div key={block.id}>
                      <BlockCard
                        block={block}
                        readOnly={readOnly}
                        lockVersion={doc.lock_version}
                        promoting={promote.isPending && promote.variables?.id === block.id}
                        onPromote={() => promote.mutate(block)}
                        onContent={(content) => {
                          // 에디터가 내용 변화 없이 보내는 갱신은 무시한다 (불필요한 '저장 안 됨' 방지).
                          if (sameDoc(content, block.content)) return;
                          updateBlock(block.id, {
                            content,
                            modified: block.kind === "MODULE" && !sameDoc(content, block.original),
                          });
                        }}
                        onRevert={() =>
                          updateBlock(block.id, { content: block.original!, modified: false, resetCount: block.resetCount + 1 })
                        }
                        onUpdateLatest={() => void updateToLatest(block)}
                        onRemove={() => change((d) => ({ ...d, blocks: d.blocks.filter((b) => b.id !== block.id) }))}
                        onMove={(delta) => moveBlock(block.id, delta)}
                        onCopy={() => insertBlock(index + 1, { ...block, id: newRequestId() })}
                        isFirst={index === 0}
                        isLast={index === draft.blocks.length - 1}
                      />
                      {!readOnly && <InsertLine onModule={() => setPicker(index + 1)} onText={() => insertText(index + 1)} />}
                    </div>
                  ))}
                </SortableContext>
              </DndContext>
              {draft.blocks.length === 0 && (
                <Text c="dimmed" ta="center" py="xl">
                  선 위의 + 를 눌러 모듈을 가져오거나 단락을 직접 쓰세요.
                </Text>
              )}
            </Card>
          </Grid.Col>
          <Grid.Col span={{ base: 12, lg: 4 }}>
            <Tabs defaultValue="info">
              <Tabs.List>
                <Tabs.Tab value="info">정보·변수</Tabs.Tab>
                <Tabs.Tab value="publications">발행</Tabs.Tab>
                <Tabs.Tab value="revisions">변경 이력</Tabs.Tab>
              </Tabs.List>
              <Tabs.Panel value="info" pt="md">
                <Stack>
                  <Select
                    label="카테고리"
                    clearable
                    data={categoryOptions(categories.data)}
                    value={draft.category_id}
                    onChange={(v) => change((d) => ({ ...d, category_id: v }))}
                    disabled={readOnly}
                  />
                  <TagsInput label="태그" value={draft.tags} onChange={(v) => change((d) => ({ ...d, tags: v }))} disabled={readOnly} />
                  <Text fw={700} size="sm" mt="sm">
                    변수 값
                  </Text>
                  {[...usedKeys].length === 0 && <Text size="sm" c="dimmed">본문에 쓰인 변수가 없습니다.</Text>}
                  {[...usedKeys].map((key) => {
                    const v = variables.data?.find((x) => x.key === key);
                    return (
                      <TextInput
                        key={key}
                        label={`[${v?.label ?? key}]`}
                        description={v?.description ?? undefined}
                        placeholder={v?.default_value ? `기본값: ${v.default_value}` : "값 입력 (발행 시 필수)"}
                        value={draft.variable_values[key] ?? ""}
                        onChange={(e) => {
                          const value = e.currentTarget.value;
                          change((d) => ({ ...d, variable_values: { ...d.variable_values, [key]: value } }));
                        }}
                        disabled={readOnly}
                      />
                    );
                  })}
                </Stack>
              </Tabs.Panel>
              <Tabs.Panel value="publications" pt="md">
                <Publications documentId={id} readOnly={readOnly} />
              </Tabs.Panel>
              <Tabs.Panel value="revisions" pt="md">
                <Revisions documentId={id} />
              </Tabs.Panel>
            </Tabs>
          </Grid.Col>
        </Grid>
      </Stack>

      <ModulePicker
        opened={picker !== null}
        onClose={() => setPicker(null)}
        onPick={(clauseIds) => {
          const index = picker ?? draft.blocks.length;
          setPicker(null);
          void insertModules(index, clauseIds);
        }}
      />
      <Modal opened={previewOpen} onClose={() => setPreviewOpen(false)} size="80%" title="미리보기 (저장된 내용)">
        <HtmlFrame src={documentPreviewUrl(id)} height={760} />
      </Modal>
      <PublishModal opened={publishOpen} onClose={() => setPublishOpen(false)} documentId={id} />
    </VariablesContext.Provider>
  );
}

function InsertLine({ onModule, onText }: { onModule: () => void; onText: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`insert-line${open ? " is-open" : ""}`}>
      <Menu opened={open} onChange={setOpen} withinPortal position="bottom">
        <Menu.Target>
          <ActionIcon className="insert-button" radius="xl" size="sm" color="indigo" aria-label="여기에 추가">
            +
          </ActionIcon>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Item onClick={onModule}>모듈 가져오기</Menu.Item>
          <Menu.Item onClick={onText}>빈 단락 쓰기</Menu.Item>
        </Menu.Dropdown>
      </Menu>
    </div>
  );
}

function BlockCard({
  block,
  readOnly,
  lockVersion,
  promoting,
  onPromote,
  onContent,
  onRevert,
  onUpdateLatest,
  onRemove,
  onMove,
  onCopy,
  isFirst,
  isLast,
}: {
  block: LocalBlock;
  readOnly: boolean;
  lockVersion: number;
  promoting: boolean;
  onPromote: () => void;
  onContent: (doc: RichDoc) => void;
  onRevert: () => void;
  onUpdateLatest: () => void;
  onRemove: () => void;
  onMove: (delta: -1 | 1) => void;
  onCopy: () => void;
  isFirst: boolean;
  isLast: boolean;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: block.id, disabled: readOnly });
  const outdated =
    block.kind === "MODULE" && !block.modified && (block.latest_revision_no ?? 0) > (block.clause_revision_no ?? 0);
  const hasModuleActions = (block.kind === "MODULE" && block.modified) || outdated;

  // 손잡이: 끌면 순서 변경, 클릭하면 메뉴. 끌기를 마친 직후의 클릭은 메뉴를 열지 않는다.
  const [handleMenu, setHandleMenu] = useState(false);
  const justDragged = useRef(false);
  useEffect(() => {
    if (isDragging) justDragged.current = true;
  }, [isDragging]);
  return (
    <div
      ref={setNodeRef}
      className={`block-card${isDragging ? " is-dragging" : ""}`}
      style={{ transform: CSS.Transform.toString(transform), transition }}
    >
      <Group align="flex-start" gap="xs" wrap="nowrap">
        {!readOnly && (
          <Menu
            opened={handleMenu}
            onChange={(open) => {
              if (open && justDragged.current) {
                justDragged.current = false;
                return;
              }
              setHandleMenu(open);
            }}
            withinPortal
            position="bottom-start"
          >
            <Menu.Target>
              <span
                className="drag-handle"
                title="클릭: 메뉴 · 끌기: 순서 바꾸기"
                {...attributes}
                {...listeners}
                onPointerDown={(e) => {
                  justDragged.current = false;
                  listeners?.onPointerDown?.(e);
                }}
              >
                ⋮⋮
              </span>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item disabled={isFirst} onClick={() => onMove(-1)}>
                ↑ 위로 이동
              </Menu.Item>
              <Menu.Item disabled={isLast} onClick={() => onMove(1)}>
                ↓ 아래로 이동
              </Menu.Item>
              <Menu.Item onClick={onCopy}>⧉ 복사 (아래에 붙여넣기)</Menu.Item>
              <Menu.Divider />
              <Menu.Item color="red" onClick={onRemove}>
                삭제
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
        )}
        <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
          <Group gap={6}>
            {block.kind === "MODULE" ? (
              <Badge size="xs" variant="light" color="indigo">
                <Anchor href={`#/modules/${block.clause_id}`} size="xs" c="inherit">
                  {block.clause_title}
                </Anchor>
              </Badge>
            ) : (
              <Badge size="xs" variant="light" color="gray">
                직접 쓴 단락
              </Badge>
            )}
            {block.modified && (
              <Badge size="xs" color="orange" variant="light">
                문서에서 수정됨
              </Badge>
            )}
            {outdated && (
              <Badge size="xs" color="blue" variant="outline">
                원본 모듈이 바뀜
              </Badge>
            )}
            {!readOnly && hasModuleActions && (
              <Menu withinPortal position="bottom-end">
                <Menu.Target>
                  <ActionIcon size="xs" variant="subtle" color="gray" ml="auto" aria-label="모듈 메뉴">
                    ⋯
                  </ActionIcon>
                </Menu.Target>
                <Menu.Dropdown>
                  {block.kind === "MODULE" && block.modified && <Menu.Item onClick={onRevert}>원본으로 되돌리기</Menu.Item>}
                  {outdated && <Menu.Item onClick={onUpdateLatest}>원본 모듈의 새 내용으로 바꾸기</Menu.Item>}
                  {block.kind === "MODULE" && block.modified && (
                    <Menu.Item disabled={promoting} onClick={onPromote}>
                      원본 모듈에도 저장
                    </Menu.Item>
                  )}
                </Menu.Dropdown>
              </Menu>
            )}
          </Group>
          <RichEditor
            content={block.content}
            onChange={onContent}
            editable={!readOnly}
            // 서버에서 다시 불러온 경우(lock_version 변경)와 되돌리기·새 버전 적용 때만 본문을 교체한다.
            resetKey={`${lockVersion}-${block.resetCount}`}
          />
        </Stack>
      </Group>
    </div>
  );
}

function PublishModal({ opened, onClose, documentId }: { opened: boolean; onClose: () => void; documentId: string }) {
  const qc = useQueryClient();
  const publish = useMutation({
    mutationFn: () => api(`/documents/${documentId}/publications`, { body: { change_reason: "발행" } }),
    onSuccess: () => {
      onClose();
      void qc.invalidateQueries({ queryKey: ["publications", documentId] });
    },
  });
  return (
    <Modal opened={opened} onClose={onClose} title="PDF·PNG 발행">
      <Stack>
        <Text size="sm">저장된 내용으로 PDF와 페이지별 PNG를 만듭니다. 결과는 오른쪽 [발행] 탭에서 내려받을 수 있습니다.</Text>
        <ErrorAlert error={publish.error} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            취소
          </Button>
          <Button loading={publish.isPending} onClick={() => publish.mutate()}>
            발행
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function Publications({ documentId, readOnly }: { documentId: string; readOnly: boolean }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState<string | null>(null);
  const list = useQuery({
    queryKey: ["publications", documentId],
    queryFn: () => api<PublicationSummary[]>(`/documents/${documentId}/publications`),
    refetchInterval: (q) => (q.state.data?.some((p) => p.status === "PENDING") ? 2000 : false),
  });
  const detail = useQuery({
    queryKey: ["publication", open],
    queryFn: () => api<PublicationDetail>(`/publications/${open}`),
    enabled: open !== null,
  });
  const retry = useMutation({
    mutationFn: (pubId: string) => api(`/publications/${pubId}/retry`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["publications", documentId] }),
  });
  if (list.isPending) return <Loading />;
  return (
    <Stack gap="xs">
      <ErrorAlert error={list.error ?? retry.error} />
      {list.data?.length === 0 && <Text size="sm" c="dimmed">발행 이력이 없습니다.</Text>}
      {list.data?.map((p) => (
        <Card key={p.id} withBorder padding="xs">
          <Group justify="space-between">
            <Group gap={6}>
              <Text fw={700}>v{p.version_no}</Text>
              <StatusBadge status={p.status} />
              {p.batch_id && <Badge size="xs" variant="outline">일괄 수정</Badge>}
            </Group>
            <Group gap={4}>
              {p.status === "PUBLISHED" && (
                <Button size="compact-xs" variant="light" onClick={() => setOpen(p.id)}>
                  파일
                </Button>
              )}
              {p.status === "FAILED" && !readOnly && (
                <Button size="compact-xs" color="orange" onClick={() => retry.mutate(p.id)}>
                  다시 시도
                </Button>
              )}
            </Group>
          </Group>
          <Text size="xs" c="dimmed">
            {p.change_reason} · 문서 r{p.revision_no} · {formatDateTime(p.published_at ?? p.created_at)}
          </Text>
          {p.failure_reason && (
            <Text size="xs" c="red">
              {p.failure_reason}
            </Text>
          )}
        </Card>
      ))}
      <Modal opened={open !== null} onClose={() => setOpen(null)} title="발행 파일" size="lg">
        {detail.data && (
          <Stack>
            <Text size="xs" c="dimmed">
              {detail.data.renderer_version}
            </Text>
            <Table>
              <Table.Tbody>
                {detail.data.files.map((f) => (
                  <Table.Tr key={f.id}>
                    <Table.Td>
                      {f.format}
                      {f.page_no ? ` ${f.page_no}쪽` : ""}
                    </Table.Td>
                    <Table.Td>
                      <Anchor href={publicationFileUrl(detail.data.id, f.id)} target="_blank">
                        {f.file_name}
                      </Anchor>
                    </Table.Td>
                    <Table.Td>
                      <code style={{ fontSize: 11 }}>{f.sha256.slice(0, 12)}…</code>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
            <HtmlFrame src={documentPreviewUrl(documentId, detail.data.revision_no)} height={480} />
          </Stack>
        )}
      </Modal>
    </Stack>
  );
}

function Revisions({ documentId }: { documentId: string }) {
  const [open, setOpen] = useState<number | null>(null);
  const list = useQuery({
    queryKey: ["document-revisions", documentId],
    queryFn: () => api<DocumentRevisionSummary[]>(`/documents/${documentId}/revisions`),
  });
  if (list.isPending) return <Loading />;
  return (
    <Stack gap={4}>
      {list.data?.map((r) => (
        <Group key={r.revision_no} justify="space-between" wrap="nowrap">
          <Text size="sm">
            r{r.revision_no} · {r.change_reason}
            <Text span size="xs" c="dimmed">
              {" "}
              {formatDateTime(r.created_at)}
            </Text>
          </Text>
          <Button size="compact-xs" variant="subtle" onClick={() => setOpen(r.revision_no)}>
            보기
          </Button>
        </Group>
      ))}
      <Modal opened={open !== null} onClose={() => setOpen(null)} title={`리비전 r${open}`} size="80%">
        {open !== null && <HtmlFrame src={documentPreviewUrl(documentId, open)} height={720} />}
      </Modal>
    </Stack>
  );
}
