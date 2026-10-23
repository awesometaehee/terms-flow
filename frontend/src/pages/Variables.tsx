// 변수 관리: 본문에 [이름] 칩으로 들어가는 값 자리. 본문에서 {{ 를 입력해 넣고, 값은 문서마다 입력한다.
// 행을 누르면 편집 창이 열리고 [저장]으로만 바뀐다.
import { Button, Group, Modal, Stack, Table, Text, TextInput, Textarea, Title } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type VariableOut } from "../api/client";
import { ErrorAlert, Loading } from "../components/common";
import { VariableApplyBanner } from "../components/VariableApplyBanner";
import { newRequestId } from "../lib/diff";

type Editing = { id: string | null; label: string; default_value: string; description: string };

// 사용자에게 보이지 않는 내부 식별자 (변수 키 규칙: 영문 소문자로 시작)
function newVariableKey(): string {
  return `v_${newRequestId().replace(/-/g, "").slice(0, 12).toLowerCase()}`;
}

export function VariableList() {
  const qc = useQueryClient();
  const variables = useQuery({ queryKey: ["variables"], queryFn: () => api<VariableOut[]>("/variables") });
  const [editing, setEditing] = useState<Editing | null>(null);
  // 값을 바꾼 변수: 이 변수를 쓰는 사용 중 문서에 반영할지 묻는다.
  const [applyFor, setApplyFor] = useState<{ id: string; seq: number } | null>(null);
  const done = () => {
    setEditing(null);
    void qc.invalidateQueries({ queryKey: ["variables"] });
  };
  const save = useMutation({
    mutationFn: (e: Editing) => {
      const body = { label: e.label.trim(), default_value: e.default_value.trim() || null, description: e.description.trim() || null };
      return e.id
        ? api(`/variables/${e.id}`, { method: "PATCH", body })
        : api("/variables", { body: { key: newVariableKey(), ...body } });
    },
    onSuccess: (_data, e) => {
      if (e.id) setApplyFor({ id: e.id, seq: Date.now() });
      done();
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/variables/${id}`, { method: "DELETE" }),
    onSuccess: done,
  });
  const open = (e: Editing) => {
    save.reset();
    remove.reset();
    setEditing(e);
  };

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>변수</Title>
        <Button onClick={() => open({ id: null, label: "", default_value: "", description: "" })}>+ 새 변수</Button>
      </Group>
      <Text size="sm" c="dimmed">
        모듈·문서 본문에서 <b>{"{{"}</b> 를 입력하면 변수를 골라 넣을 수 있습니다. 값은 문서마다 입력하고, 비워 두면
        기본값을 씁니다.
      </Text>
      {applyFor && (
        <VariableApplyBanner
          key={`${applyFor.id}-${applyFor.seq}`}
          variableId={applyFor.id}
          onClose={() => setApplyFor(null)}
        />
      )}
      <ErrorAlert error={variables.error} />
      {variables.isPending ? (
        <Loading />
      ) : (
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>이름</Table.Th>
              <Table.Th>기본값</Table.Th>
              <Table.Th>설명</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {variables.data?.map((v) => (
              <Table.Tr
                key={v.id}
                style={{ cursor: "pointer" }}
                onClick={() =>
                  open({ id: v.id, label: v.label, default_value: v.default_value ?? "", description: v.description ?? "" })
                }
              >
                <Table.Td>
                  <Text fw={600} c="blue.7">
                    [{v.label}]
                  </Text>
                </Table.Td>
                <Table.Td>{v.default_value || <Text c="dimmed">-</Text>}</Table.Td>
                <Table.Td>{v.description}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      {variables.data?.length === 0 && <Text c="dimmed">변수가 없습니다. [+ 새 변수]로 만드세요.</Text>}

      <Modal opened={editing !== null} onClose={() => setEditing(null)} title={editing?.id ? "변수 편집" : "새 변수"}>
        {editing && (
          <Stack>
            <TextInput
              label="이름"
              description="본문에 [이름]으로 보입니다"
              required
              value={editing.label}
              onChange={(e) => setEditing({ ...editing, label: e.currentTarget.value })}
              data-autofocus
            />
            <TextInput
              label="기본값"
              description="문서에서 값을 입력하지 않으면 이 값을 씁니다"
              value={editing.default_value}
              onChange={(e) => setEditing({ ...editing, default_value: e.currentTarget.value })}
            />
            <Textarea
              label="설명"
              autosize
              value={editing.description}
              onChange={(e) => setEditing({ ...editing, description: e.currentTarget.value })}
            />
            <ErrorAlert error={save.error ?? remove.error} />
            <Group justify="space-between">
              {editing.id ? (
                <Button
                  variant="subtle"
                  color="red"
                  loading={remove.isPending}
                  onClick={() => window.confirm(`[${editing.label}] 변수를 지울까요?`) && remove.mutate(editing.id!)}
                >
                  삭제
                </Button>
              ) : (
                <span />
              )}
              <Group>
                <Button variant="default" onClick={() => setEditing(null)}>
                  취소
                </Button>
                <Button disabled={!editing.label.trim()} loading={save.isPending} onClick={() => save.mutate(editing)}>
                  저장
                </Button>
              </Group>
            </Group>
          </Stack>
        )}
      </Modal>
    </Stack>
  );
}
