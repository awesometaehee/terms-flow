// 변수 값을 바꾼 뒤 띄우는 안내: 이 변수를 쓰는 사용 중 문서를 새 값으로 다시 발행할지 묻는다.
// 기본값을 쓰는 문서는 모두 반영하고, 문서에 값을 따로 입력한 문서는 체크한 것만 새 값으로 바꾼다.
import { Alert, Button, Checkbox, Group, Stack, Text } from "@mantine/core";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, type BulkUpdateDetail, type VariableImpactOut } from "../api/client";
import { newRequestId } from "../lib/diff";
import { Link } from "../router";
import { ErrorAlert } from "./common";

export function VariableApplyBanner({ variableId, onClose }: { variableId: string; onClose: () => void }) {
  const [requestId] = useState(newRequestId);
  const [overwrite, setOverwrite] = useState<string[]>([]);
  const impact = useQuery({
    queryKey: ["variable-impact", variableId, requestId],
    queryFn: () => api<VariableImpactOut>(`/variables/${variableId}/bulk-updates/preview`, { body: {} }),
  });
  const apply = useMutation({
    mutationFn: () =>
      api<BulkUpdateDetail>(`/variables/${variableId}/bulk-updates`, {
        body: { request_id: requestId, overwrite_document_ids: overwrite },
      }),
  });

  if (impact.isError || !impact.data) return null;
  const d = impact.data;
  const total = d.document_targets.length + d.own_value_documents.length;
  if (total === 0) return null;

  if (apply.data) {
    return (
      <Alert color="green" withCloseButton onClose={onClose} title="반영을 시작했습니다">
        <Text size="sm">
          새 값으로 다시 발행하는 중입니다. <Link to={`/bulk-updates/${apply.data.id}`}>진행 결과 보기</Link>
        </Text>
      </Alert>
    );
  }
  const count = d.document_targets.length + overwrite.length;
  return (
    <Alert color="blue" withCloseButton onClose={onClose} title={`[${d.label}] 변수를 쓰는 사용 중 문서 ${total}개`}>
      <Stack gap="xs">
        <Text size="sm">
          새 값 <b>{d.value || "(비움)"}</b>으로 다시 발행할까요?
          {d.document_targets.length > 0 && ` 기본값을 쓰는 문서 ${d.document_targets.length}개는 모두 바뀝니다.`}
        </Text>
        {d.own_value_documents.length > 0 && (
          <>
            <Text size="sm" fw={600}>
              문서에 값을 따로 입력한 문서 {d.own_value_documents.length}개 — 체크한 문서만 새 값으로 바꿉니다
            </Text>
            <Checkbox.Group value={overwrite} onChange={setOverwrite}>
              <Stack gap={4}>
                {d.own_value_documents.map((doc) => (
                  <Checkbox
                    key={doc.document_id}
                    value={doc.document_id}
                    label={`${doc.title} — 지금 값: ${doc.own_value}`}
                  />
                ))}
              </Stack>
            </Checkbox.Group>
          </>
        )}
        <Group gap="xs">
          <Button size="xs" disabled={count === 0} loading={apply.isPending} onClick={() => apply.mutate()}>
            {count > 0 ? `문서 ${count}개에 바로 반영` : "반영할 문서를 고르세요"}
          </Button>
          <Button size="xs" variant="subtle" color="gray" onClick={onClose}>
            나중에
          </Button>
          {d.document_excluded.length > 0 && (
            <Text size="xs" c="dimmed">
              작성 중·종료·이미 반영된 문서 {d.document_excluded.length}개는 그대로 둡니다.
            </Text>
          )}
        </Group>
        <ErrorAlert error={apply.error} />
      </Stack>
    </Alert>
  );
}
