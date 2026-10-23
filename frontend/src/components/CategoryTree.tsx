// 모듈·문서 공용 카테고리 트리. 선택·추가·이름 변경·삭제를 한 곳에서 한다.
import { ActionIcon, Group, Menu, NavLink, ScrollArea, Stack, Text } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type CategoryOut } from "../api/client";
import { ErrorAlert } from "./common";

export function useCategories() {
  return useQuery({ queryKey: ["categories"], queryFn: () => api<CategoryOut[]>("/categories") });
}

export function categoryOptions(categories: CategoryOut[] | undefined): { value: string; label: string }[] {
  const out: { value: string; label: string }[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const c of (categories ?? []).filter((x) => x.parent_id === parent)) {
      out.push({ value: c.id, label: `${"　".repeat(depth)}${c.name}` });
      walk(c.id, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}

export function CategoryTree({
  selected,
  onSelect,
}: {
  selected: string | null;
  onSelect: (id: string | null) => void;
}) {
  const qc = useQueryClient();
  const categories = useCategories();
  const refresh = () => qc.invalidateQueries({ queryKey: ["categories"] });
  const create = useMutation({
    mutationFn: (parentId: string | null) => {
      const name = window.prompt("새 카테고리 이름");
      if (!name?.trim()) return Promise.resolve(null);
      return api<CategoryOut>("/categories", { body: { name: name.trim(), parent_id: parentId } });
    },
    onSuccess: refresh,
  });
  const rename = useMutation({
    mutationFn: (c: CategoryOut) => {
      const name = window.prompt("카테고리 이름", c.name);
      if (!name?.trim() || name === c.name) return Promise.resolve(null);
      return api(`/categories/${c.id}`, { method: "PATCH", body: { name: name.trim() } });
    },
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (c: CategoryOut) =>
      window.confirm(`'${c.name}' 카테고리를 지울까요?`)
        ? api(`/categories/${c.id}`, { method: "DELETE" })
        : Promise.resolve(null),
    onSuccess: (_, c) => {
      if (selected === c.id) onSelect(null);
      void refresh();
    },
  });

  const render = (parent: string | null) =>
    (categories.data ?? [])
      .filter((c) => c.parent_id === parent)
      .map((c) => {
        const hasChildren = (categories.data ?? []).some((x) => x.parent_id === c.id);
        return (
          <NavLink
            key={c.id}
            label={c.name}
            active={selected === c.id}
            onClick={() => onSelect(c.id)}
            childrenOffset={14}
            defaultOpened
            py={4}
            rightSection={
              <Menu withinPortal position="bottom-end">
                <Menu.Target>
                  <ActionIcon size="xs" variant="subtle" color="gray" onClick={(e) => e.stopPropagation()}>
                    ⋯
                  </ActionIcon>
                </Menu.Target>
                <Menu.Dropdown onClick={(e) => e.stopPropagation()}>
                  <Menu.Item onClick={() => create.mutate(c.id)}>하위 카테고리 추가</Menu.Item>
                  <Menu.Item onClick={() => rename.mutate(c)}>이름 바꾸기</Menu.Item>
                  <Menu.Item color="red" onClick={() => remove.mutate(c)}>
                    삭제
                  </Menu.Item>
                </Menu.Dropdown>
              </Menu>
            }
          >
            {hasChildren ? render(c.id) : undefined}
          </NavLink>
        );
      });

  return (
    <Stack gap={4}>
      <Group justify="space-between">
        <Text size="sm" fw={700}>
          카테고리
        </Text>
        <ActionIcon size="sm" variant="light" onClick={() => create.mutate(null)} aria-label="카테고리 추가">
          +
        </ActionIcon>
      </Group>
      <ErrorAlert error={create.error ?? rename.error ?? remove.error} />
      <ScrollArea.Autosize mah={420}>
        <NavLink label="전체" active={selected === null} onClick={() => onSelect(null)} py={4} />
        {render(null)}
      </ScrollArea.Autosize>
    </Stack>
  );
}
