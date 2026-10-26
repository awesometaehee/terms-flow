import { Badge, Card, Group, Stack, Text, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { api, type SearchOut } from "../api/client";
import { ErrorAlert, Loading } from "../components/common";
import { navigate, useQueryParam } from "../router";

export function SearchPage() {
  const q = useQueryParam("q") ?? "";
  const result = useQuery({
    queryKey: ["search", q],
    queryFn: () => api<SearchOut>(`/search?q=${encodeURIComponent(q)}`),
    enabled: q.trim().length > 0,
  });
  return (
    <Stack>
      <Title order={2}>검색: {q}</Title>
      <ErrorAlert error={result.error} />
      {result.isFetching && <Loading />}
      {result.data?.hits?.length === 0 && <Text c="dimmed">결과가 없습니다.</Text>}
      {result.data?.hits?.map((h) => (
        <Card
          key={`${h.kind}-${h.id}`}
          withBorder
          style={{ cursor: "pointer" }}
          onClick={() => navigate(h.kind === "MODULE" ? `/modules/${h.id}` : `/documents/${h.id}`)}
        >
          <Group gap={6}>
            <Badge size="sm" color={h.kind === "MODULE" ? "indigo" : "teal"} variant="light">
              {h.kind === "MODULE" ? "템플릿" : "문서"}
            </Badge>
            <Text fw={700}>{h.title}</Text>
            <Text size="xs" c="dimmed">
              {h.subtitle}
            </Text>
          </Group>
          <Text size="sm" mt={4}>
            {h.excerpt}
          </Text>
          <Group gap={4} mt={4}>
            {h.tags.map((t) => (
              <Badge key={t} size="xs" variant="outline">
                {t}
              </Badge>
            ))}
          </Group>
        </Card>
      ))}
    </Stack>
  );
}
