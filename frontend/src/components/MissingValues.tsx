// 일괄 반영 시 값이 비어 발행할 수 없는 변수의 값을 그 자리에서 입력받는다.
// 입력한 값은 값이 비어 있는 문서에만 들어가고, 이미 값이 있는 문서는 그대로 둔다.
import { Alert, SimpleGrid, Text, TextInput } from "@mantine/core";

import type { Schemas } from "../api/client";

export type MissingVariable = Schemas["MissingVariable"];

export function allFilled(missing: MissingVariable[], values: Record<string, string>): boolean {
  return missing.every((m) => values[m.key]?.trim());
}

export function MissingValues({
  missing,
  values,
  onChange,
}: {
  missing: MissingVariable[];
  values: Record<string, string>;
  onChange: (values: Record<string, string>) => void;
}) {
  if (missing.length === 0) return null;
  return (
    <Alert color="orange" variant="light" title="새 변수 값을 입력하세요">
      <Text size="sm" mb="xs">
        이 값이 없으면 PDF를 만들 수 없습니다. 입력한 값은 값이 비어 있는 문서에만 들어갑니다.
      </Text>
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        {missing.map((m) => (
          <TextInput
            key={m.key}
            label={`[${m.label}]`}
            description={`값이 없는 문서 ${m.documents}개`}
            value={values[m.key] ?? ""}
            onChange={(e) => onChange({ ...values, [m.key]: e.currentTarget.value })}
          />
        ))}
      </SimpleGrid>
    </Alert>
  );
}
