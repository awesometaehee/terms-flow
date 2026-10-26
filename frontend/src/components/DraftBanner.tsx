// 화면을 열 때 남아 있던 임시저장본(다른 PC에서 쓴 것 포함)을 불러올지 묻는다.
import { Alert, Button, Group, Text } from "@mantine/core";

import { formatDraftTime, type StoredDraft } from "../lib/draft";

export function DraftBanner<T>({
  draft,
  stale,
  onRestore,
  onDiscard,
}: {
  draft: StoredDraft<T>;
  // 임시본을 만든 뒤 다른 곳에서 저장된 내용이 있는지
  stale: boolean;
  onRestore: () => void;
  onDiscard: () => void;
}) {
  return (
    <Alert color="yellow" title={`저장하지 않은 임시저장본이 있습니다 (${formatDraftTime(draft.savedAt)})`}>
      <Text size="sm" mb="xs">
        {stale
          ? "그 뒤에 다른 곳에서 저장된 내용이 있습니다. 불러오면 그 변경 위에 임시본 내용을 덮어씁니다."
          : "이 PC나 다른 PC에서 쓰다가 저장하지 않은 내용입니다. 불러온 뒤 [저장]을 눌러야 반영됩니다."}
      </Text>
      <Group gap="xs">
        <Button size="xs" color="yellow" onClick={onRestore}>
          불러오기
        </Button>
        <Button size="xs" variant="subtle" color="gray" onClick={onDiscard}>
          버리기
        </Button>
      </Group>
    </Alert>
  );
}

// [저장] 버튼 옆에 두는 자동 임시저장 상태
export function DraftStatus({ savedAt, failed }: { savedAt: number | null; failed?: boolean }) {
  if (failed) {
    return (
      <Text size="xs" c="red" span title="네트워크나 서버 문제로 임시저장하지 못했습니다. [저장]으로 저장하세요.">
        임시저장 실패
      </Text>
    );
  }
  if (!savedAt) return null;
  return (
    <Text size="xs" c="dimmed" span title="저장하지 않은 변경을 자동으로 보관했습니다. 다른 PC에서도 이어 쓸 수 있습니다.">
      임시저장됨 {formatDraftTime(savedAt)}
    </Text>
  );
}
