// 모듈을 새로 저장한 뒤 띄우는 안내: 이 모듈을 쓰는 사용 중 문서(·판매 중 상품)에 바로 반영할지 묻는다.
// 반영 대상이 없으면 아무것도 보이지 않는다.
import { Alert, Anchor, Button, Group, Text } from "@mantine/core";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, type BulkUpdateDetail, type ImpactOut } from "../api/client";
import { newRequestId } from "../lib/diff";
import { Link } from "../router";
import { ErrorAlert } from "./common";
import { MissingValues, allFilled } from "./MissingValues";

export function ApplyBanner({
  clauseId,
  revisionNo,
  onClose,
}: {
  clauseId: string;
  revisionNo: number;
  onClose: () => void;
}) {
  const [requestId] = useState(newRequestId);
  const [values, setValues] = useState<Record<string, string>>({});
  const impact = useQuery({
    queryKey: ["impact", clauseId, revisionNo],
    queryFn: () => api<ImpactOut>("/bulk-updates/preview", { body: { clause_id: clauseId, revision_no: revisionNo } }),
  });
  const apply = useMutation({
    mutationFn: () =>
      api<BulkUpdateDetail>("/bulk-updates", {
        body: { request_id: requestId, clause_id: clauseId, revision_no: revisionNo, change_reason: "모듈 수정 반영", variable_values: values },
      }),
  });

  if (impact.isError) return null; // 더 새 버전이 생겼거나 하는 경우: 안내만 생략
  const docs = impact.data?.document_targets.length ?? 0;
  const products = impact.data?.targets.length ?? 0;
  if (!impact.data || docs + products === 0) return null;

  if (apply.data) {
    return (
      <Alert color="green" withCloseButton onClose={onClose} title="반영을 시작했습니다">
        <Text size="sm">
          새 내용으로 다시 발행하는 중입니다.{" "}
          <Link to={`/bulk-updates/${apply.data.id}`}>진행 결과 보기</Link>
        </Text>
      </Alert>
    );
  }
  const missing = impact.data.missing_variables ?? [];
  const targets = [docs ? `사용 중 문서 ${docs}개` : "", products ? `판매 중 상품 ${products}개` : ""].filter(Boolean).join(", ");
  return (
    <Alert color="blue" withCloseButton onClose={onClose} title={`${targets}가 이 모듈을 쓰고 있습니다`}>
      <Text size="sm" mb="xs">
        지금 바꾼 내용으로 다시 발행할까요? 문서에서 따로 고친 단락과 종료된 문서는 그대로 둡니다.
      </Text>
      <MissingValues missing={missing} values={values} onChange={setValues} />
      <Group gap="xs" mt={missing.length ? "xs" : 0}>
        <Button size="xs" disabled={!allFilled(missing, values)} loading={apply.isPending} onClick={() => apply.mutate()}>
          바로 반영
        </Button>
        <Anchor size="sm" href={`#/bulk-updates/new?clause=${clauseId}&revision=${revisionNo}`}>
          대상 자세히 보기
        </Anchor>
        <Button size="xs" variant="subtle" color="gray" onClick={onClose}>
          나중에
        </Button>
      </Group>
      <ErrorAlert error={apply.error} />
    </Alert>
  );
}
