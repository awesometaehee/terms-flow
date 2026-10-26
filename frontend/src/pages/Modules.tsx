// 모듈 라이브러리: 재사용 단락의 목록과 편집.
// 편집 화면은 제목·분류·본문을 한 번에 고치고 [저장] 하나로 끝난다. 본문을 바꿔 저장하면 새 버전이 쌓이고,
// 이 모듈을 쓰는 사용 중 문서가 있으면 바로 반영할지 묻는다.
import {
  Accordion,
  Alert,
  Badge,
  Button,
  Card,
  Grid,
  Group,
  Modal,
  Select,
  Stack,
  Table,
  TagsInput,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  api,
  type ClauseDetail,
  type ClauseRevisionOut,
  type ClauseSummary,
  type RichDoc,
  type TagOut,
  type VariableOut,
} from "../api/client";
import { ApplyBanner } from "../components/ApplyBanner";
import { DraftBanner, DraftStatus } from "../components/DraftBanner";
import { CategoryTree, categoryOptions, useCategories } from "../components/CategoryTree";
import { ErrorAlert, Loading, formatDateTime } from "../components/common";
import { EMPTY_DOC, RichEditor } from "../editor/RichEditor";
import { VariablesContext, type VariableInfo } from "../editor/variables";
import { newRequestId } from "../lib/diff";
import { SHOW_PRODUCT_FEATURE } from "../features";
import { fetchDraft, formatDraftTime, removeDraft, useDraft } from "../lib/draft";
import { docKey, sameDoc } from "../lib/richdoc";
import { useSaveShortcut } from "../lib/useSaveShortcut";
import { Link, navigate } from "../router";

function useVariableMap(): Record<string, VariableInfo> {
  const variables = useQuery({ queryKey: ["variables"], queryFn: () => api<VariableOut[]>("/variables") });
  return useMemo(
    () => Object.fromEntries((variables.data ?? []).map((v) => [v.key, { key: v.key, label: v.label, value: v.default_value }])),
    [variables.data],
  );
}

// 사용자에게 보이지 않는 내부 식별자 (모듈 키 규칙: 영문 소문자로 시작)
function newModuleKey(): string {
  return `m_${newRequestId().replace(/-/g, "").slice(0, 12).toLowerCase()}`;
}

export function ModuleList() {
  const [category, setCategory] = useState<string | null>(null);
  const [tag, setTag] = useState<string | null>(null);
  const [q, setQ] = useState("");
  // 새 모듈 창: 임시저장 키(새로 쓰기·이어 쓰기)와 이어 쓸 내용
  const [creating, setCreating] = useState<{ key: string; initial: ModuleForm | null } | null>(null);
  const drafts = useQuery({
    queryKey: ["drafts", "module-new"],
    queryFn: () => api<{ key: string; title: string | null; updated_at: string }[]>("/drafts?prefix=module-new:"),
  });
  const openNew = () => setCreating({ key: `module-new:${newRequestId().replace(/-/g, "")}`, initial: null });
  const continueDraft = async (key: string) => {
    const draft = await fetchDraft<ModuleForm>(key);
    if (draft) setCreating({ key, initial: draft.value });
    else void drafts.refetch();
  };
  const closeNew = () => {
    setCreating(null);
    // 창을 닫을 때 남은 내용을 보내므로 잠시 뒤 목록을 새로 읽는다.
    window.setTimeout(() => void drafts.refetch(), 600);
  };
  const categories = useCategories();
  const tags = useQuery({ queryKey: ["tags"], queryFn: () => api<TagOut[]>("/tags") });
  const params = new URLSearchParams();
  if (category) params.set("category_id", category);
  if (tag) params.set("tag", tag);
  if (q.trim()) params.set("q", q.trim());
  const modules = useQuery({
    queryKey: ["clauses", params.toString()],
    queryFn: () => api<ClauseSummary[]>(`/clauses?${params}`),
  });
  // 상품 기능을 숨기면 상품 템플릿 전용 모듈도 목록에서 뺀다.
  const visibleModules = (modules.data ?? []).filter((m) => SHOW_PRODUCT_FEATURE || !m.document_type);
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
            <Title order={2}>템플릿</Title>
            <Button onClick={() => openNew()}>+ 새 템플릿</Button>
          </Group>
          {(drafts.data?.length ?? 0) > 0 && (
            <Card withBorder padding="sm" bg="yellow.0">
              <Text size="sm" fw={600} mb={6}>
                작성 중인 새 템플릿 {drafts.data!.length}개 (만들기 전 · 자동 임시저장)
              </Text>
              <Stack gap={4}>
                {drafts.data!.map((d) => (
                  <Group key={d.key} justify="space-between" wrap="nowrap">
                    <Text size="sm" lineClamp={1}>
                      {d.title || "(제목 없음)"}{" "}
                      <Text span size="xs" c="dimmed">
                        {formatDraftTime(Date.parse(d.updated_at))}
                      </Text>
                    </Text>
                    <Group gap={4} wrap="nowrap">
                      <Button size="compact-xs" variant="light" onClick={() => continueDraft(d.key)}>
                        이어 쓰기
                      </Button>
                      <Button
                        size="compact-xs"
                        variant="subtle"
                        color="red"
                        onClick={() =>
                          window.confirm(`'${d.title || "(제목 없음)"}' 임시저장본을 지울까요?`) &&
                          void removeDraft(d.key).then(() => drafts.refetch())
                        }
                      >
                        삭제
                      </Button>
                    </Group>
                  </Group>
                ))}
              </Stack>
            </Card>
          )}
          <Group>
            <TextInput placeholder="제목·본문 검색" value={q} onChange={(e) => setQ(e.currentTarget.value)} w={260} />
            <Select
              placeholder="태그"
              clearable
              data={(tags.data ?? []).filter((t) => t.module_count > 0).map((t) => t.name)}
              value={tag}
              onChange={setTag}
              w={160}
            />
          </Group>
          <ErrorAlert error={modules.error} />
          {modules.isPending ? (
            <Loading />
          ) : (
            <Table striped highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>제목</Table.Th>
                  <Table.Th>카테고리</Table.Th>
                  <Table.Th>최근 수정</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {visibleModules.map((m) => (
                  <Table.Tr key={m.id} style={{ cursor: "pointer" }} onClick={() => navigate(`/modules/${m.id}`)}>
                    <Table.Td>
                      <Text fw={600}>{m.title}</Text>
                      <Text size="xs" c="dimmed" lineClamp={1}>
                        {m.excerpt}
                      </Text>
                      <Group gap={4}>
                        {SHOW_PRODUCT_FEATURE && m.document_type && (
                          <Badge size="xs" color="grape" variant="light">
                            상품 문서용
                          </Badge>
                        )}
                        {m.tags.map((t) => (
                          <Badge key={t} size="xs" variant="outline">
                            {t}
                          </Badge>
                        ))}
                      </Group>
                    </Table.Td>
                    <Table.Td>{categoryName(m.category_id)}</Table.Td>
                    <Table.Td>{formatDateTime(m.updated_at)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
          {modules.data && visibleModules.length === 0 && <Text c="dimmed">템플릿이 없습니다. [+ 새 템플릿]로 만드세요.</Text>}
        </Stack>
      </Grid.Col>
      {/* 표·단 나누기를 편하게 만들 수 있도록 넓게 연다 */}
      <Modal opened={creating !== null} onClose={closeNew} title="새 템플릿" size="90%">
        {creating && (
          <NewModuleForm
            key={creating.key}
            defaultCategory={category}
            draftKey={creating.key}
            initial={creating.initial}
          />
        )}
      </Modal>
    </Grid>
  );
}

function NewModuleForm({
  defaultCategory,
  draftKey,
  initial,
}: {
  defaultCategory: string | null;
  // 자동 임시저장 키 ("module-new:<id>"). 이어 쓰기면 initial에 그때 내용
  draftKey: string;
  initial: ModuleForm | null;
}) {
  const qc = useQueryClient();
  const categories = useCategories();
  const variableMap = useVariableMap();
  const [title, setTitle] = useState(initial?.title ?? "");
  const [category, setCategory] = useState<string | null>(initial ? initial.categoryId : defaultCategory);
  const [tags, setTags] = useState<string[]>(initial?.tags ?? []);
  const [content, setContent] = useState<RichDoc>(initial?.content ?? EMPTY_DOC);
  // 자동 임시저장: 창을 닫거나 다른 PC로 옮겨도 모듈 목록의 '작성 중인 새 모듈'에서 이어 쓴다. 만들면 지운다.
  const form: ModuleForm = { title, categoryId: category, tags, content };
  const dirty = !!title.trim() || tags.length > 0 || !sameDoc(content, EMPTY_DOC);
  const local = useDraft<ModuleForm>(draftKey, form, dirty, "new", { title: title.trim() || null, check: false });
  const create = useMutation({
    mutationFn: () =>
      api<ClauseDetail>("/clauses", {
        body: { clause_key: newModuleKey(), title, category_id: category, tags, content_json: content },
      }),
    onSuccess: (m) => {
      // 임시본을 지운 뒤에 목록을 새로 읽는다.
      void local.clear().then(() => qc.invalidateQueries({ queryKey: ["drafts", "module-new"] }));
      navigate(`/modules/${m.id}`);
    },
  });
  return (
    <VariablesContext.Provider value={variableMap}>
      <Stack>
        <TextInput label="제목" required value={title} onChange={(e) => setTitle(e.currentTarget.value)} data-autofocus />
        <Group grow>
          <Select label="카테고리" clearable data={categoryOptions(categories.data)} value={category} onChange={setCategory} />
          <TagsInput label="태그" value={tags} onChange={setTags} placeholder="입력 후 Enter" />
        </Group>
        <Card withBorder padding="lg" className="editor-card-tall">
          <RichEditor content={content} onChange={setContent} />
        </Card>
        <Group justify="flex-end">
          <DraftStatus savedAt={local.savedAt} failed={local.failed} />
        </Group>
        <ErrorAlert error={create.error} />
        <Button disabled={!title.trim()} loading={create.isPending} onClick={() => create.mutate()}>
          만들기
        </Button>
      </Stack>
    </VariablesContext.Provider>
  );
}

type ModuleForm = { title: string; categoryId: string | null; tags: string[]; content: RichDoc };

// 임시본 비교용 (본문은 정규화)
function formKey(f: ModuleForm): string {
  return JSON.stringify({ ...f, content: docKey(f.content) });
}

function formFrom(m: ClauseDetail): ModuleForm {
  const latest = m.revisions[m.revisions.length - 1];
  return { title: m.title, categoryId: m.category_id, tags: m.tags, content: latest.content_json as RichDoc };
}

export function ModuleDetail({ id }: { id: string }) {
  const qc = useQueryClient();
  const categories = useCategories();
  const variableMap = useVariableMap();
  const module = useQuery({ queryKey: ["clause", id], queryFn: () => api<ClauseDetail>(`/clauses/${id}`) });
  const [form, setForm] = useState<ModuleForm | null>(null);
  const [resetCount, setResetCount] = useState(0);
  const [savedRevision, setSavedRevision] = useState<number | null>(null);
  const [viewing, setViewing] = useState<number | null>(null);

  // 처음 불러올 때와 저장한 뒤 서버 내용으로 맞춘다.
  useEffect(() => {
    if (module.data) {
      setForm(formFrom(module.data));
      setResetCount((n) => n + 1);
    }
  }, [module.data]);

  const original = module.data ? formFrom(module.data) : null;
  const metaChanged =
    !!form &&
    !!original &&
    (form.title.trim() !== original.title ||
      form.categoryId !== original.categoryId ||
      form.tags.join("\u0000") !== original.tags.join("\u0000"));
  const contentChanged = !!form && !!original && !sameDoc(form.content, original.content);
  const dirty = metaChanged || contentChanged;
  // 자동 임시저장 (이 브라우저). 저장하면 지운다.
  const local = useDraft<ModuleForm>(
    `module:${id}`,
    form,
    dirty,
    module.data ? String(module.data.latest_revision_no) : null,
  );

  const save = useMutation({
    mutationFn: async () => {
      const m = module.data!;
      if (metaChanged) {
        await api(`/clauses/${id}`, {
          method: "PATCH",
          body: form!.categoryId
            ? { title: form!.title.trim(), category_id: form!.categoryId, tags: form!.tags }
            : { title: form!.title.trim(), clear_category: true, tags: form!.tags },
        });
      }
      if (contentChanged) {
        const rev = await api<ClauseRevisionOut>(`/clauses/${id}/revisions`, {
          body: { base_revision_no: m.latest_revision_no, content_json: form!.content, change_reason: "수정" },
        });
        return rev.revision_no;
      }
      return null;
    },
    onSuccess: (revisionNo) => {
      local.clear();
      if (revisionNo) setSavedRevision(revisionNo);
      void qc.invalidateQueries({ queryKey: ["clause", id] });
      void qc.invalidateQueries({ queryKey: ["clauses"] });
    },
  });
  const remove = useMutation({
    mutationFn: () => api(`/clauses/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["clauses"] });
      navigate("/modules");
    },
  });
  const deleted = !!module.data?.deleted;
  useSaveShortcut(() => save.mutate(), !deleted && dirty && !save.isPending && !!form?.title.trim());

  if (module.isPending || !form) return module.error ? <ErrorAlert error={module.error} /> : <Loading />;
  const m = module.data!;
  const latest = m.revisions[m.revisions.length - 1];
  const viewed = m.revisions.find((r) => r.revision_no === viewing);
  const change = (patch: Partial<ModuleForm>) => setForm((f) => (f ? { ...f, ...patch } : f));

  return (
    <VariablesContext.Provider value={variableMap}>
      <Stack>
        <Link to="/modules">← 템플릿 목록</Link>
        <Group justify="space-between" align="flex-start">
          <Group style={{ flex: 1 }}>
            <TextInput
              value={form.title}
              readOnly={deleted}
              onChange={(e) => change({ title: e.currentTarget.value })}
              variant="unstyled"
              size="xl"
              styles={{ input: { fontWeight: 700, fontSize: 26 } }}
              style={{ flex: 1 }}
              placeholder="제목"
            />
            {SHOW_PRODUCT_FEATURE && m.document_type && <Badge color="grape" variant="light">상품 문서용</Badge>}
          </Group>
          {!deleted && (
          <Group>
            <DraftStatus savedAt={local.savedAt} failed={local.failed} />
            <Button
              variant="subtle"
              color="red"
              loading={remove.isPending}
              onClick={() =>
                window.confirm(`'${m.title}' 템플릿을 삭제할까요?\n종료된 문서와 발행본에 남은 내용은 그대로 둡니다.`) &&
                remove.mutate()
              }
            >
              삭제
            </Button>
            {dirty && (
              <Button
                variant="subtle"
                color="gray"
                onClick={() => {
                  setForm(formFrom(m));
                  setResetCount((n) => n + 1);
                }}
              >
                되돌리기
              </Button>
            )}
            <Button onClick={() => save.mutate()} disabled={!dirty || !form.title.trim()} loading={save.isPending}>
              {dirty ? "저장" : "저장됨"}
            </Button>
          </Group>
          )}
        </Group>
        {local.found && !deleted && formKey(local.found.value) !== formKey(form) && (
          <DraftBanner
            draft={local.found}
            stale={local.found.base !== String(m.latest_revision_no)}
            onRestore={() => {
              setForm(local.found!.value);
              setResetCount((n) => n + 1);
              local.dismiss();
            }}
            onDiscard={local.clear}
          />
        )}
        {dirty && (
          <Text size="xs" c="orange">
            저장하지 않은 변경이 있습니다 (Ctrl+S로 저장).
          </Text>
        )}
        {deleted && (
          <Alert color="gray" title="삭제된 템플릿입니다">
            목록과 검색에서 빠졌고 문서에 새로 넣을 수 없습니다. 이 템플릿을 쓰던 종료 문서의 기록을 위해 내용만 보여
            줍니다.
          </Alert>
        )}
        <ErrorAlert error={save.error ?? remove.error} />
        {savedRevision && (
          <ApplyBanner key={savedRevision} clauseId={id} revisionNo={savedRevision} onClose={() => setSavedRevision(null)} />
        )}

        <Group grow>
          <Select
            label="카테고리"
            readOnly={deleted}
            clearable
            data={categoryOptions(categories.data)}
            value={form.categoryId}
            onChange={(v) => change({ categoryId: v })}
          />
          <TagsInput label="태그" readOnly={deleted} value={form.tags} onChange={(v) => change({ tags: v })} placeholder="입력 후 Enter" />
        </Group>
        <Card withBorder padding="lg">
          <RichEditor
            content={form.content}
            editable={!deleted}
            onChange={(doc) => change({ content: doc })}
            resetKey={`${latest.id}-${resetCount}`} />
        </Card>

        <Accordion variant="contained">
          <Accordion.Item value="history">
            <Accordion.Control>이전 버전 ({m.revisions.length}개)</Accordion.Control>
            <Accordion.Panel>
              <Table>
                <Table.Tbody>
                  {[...m.revisions].reverse().map((r) => (
                    <Table.Tr key={r.id}>
                      <Table.Td w={60}>r{r.revision_no}</Table.Td>
                      <Table.Td>
                        <Text size="sm" lineClamp={1}>
                          {r.content}
                        </Text>
                      </Table.Td>
                      <Table.Td w={170}>{formatDateTime(r.created_at)}</Table.Td>
                      <Table.Td w={90}>
                        <Button size="compact-xs" variant="subtle" onClick={() => setViewing(r.revision_no)}>
                          보기
                        </Button>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>

        <Modal opened={viewed !== undefined} onClose={() => setViewing(null)} title={`${m.title} · r${viewing}`} size="80%">
          {viewed && (
            <Stack>
              <RichEditor content={viewed.content_json as RichDoc} editable={false} resetKey={viewed.id} />
              {viewed.revision_no !== latest.revision_no && (
                <Group justify="flex-end">
                  <Button
                    variant="light"
                    onClick={() => {
                      change({ content: viewed.content_json as RichDoc });
                      setResetCount((n) => n + 1);
                      setViewing(null);
                    }}
                  >
                    이 버전 내용으로 되돌려 편집
                  </Button>
                </Group>
              )}
            </Stack>
          )}
        </Modal>
      </Stack>
    </VariablesContext.Provider>
  );
}
