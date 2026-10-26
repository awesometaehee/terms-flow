// 이미지 자료실: 상품 사진 등을 올려 두고 템플릿·문서에 골라 넣는다. 원본을 내려받을 수 있다.
// 편집기에서 올리거나 붙여 넣은 이미지도 여기에 쌓인다.
import { Button, Card, Group, Image, Modal, SimpleGrid, Stack, Text, TextInput, Title } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { api } from "../api/client";
import { ErrorAlert, Loading, formatDateTime } from "../components/common";
import {
  IMAGE_ACCEPT,
  type LibraryImage,
  downloadUrl,
  formatBytes,
  listLibraryImages,
  uploadLibraryImage,
} from "../lib/images";

export function ImageLibrary() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [viewing, setViewing] = useState<LibraryImage | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploadErrors, setUploadErrors] = useState<string[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);
  const images = useQuery({ queryKey: ["images", q], queryFn: () => listLibraryImages(q) });

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      const errors: string[] = [];
      for (const file of files) {
        try {
          await uploadLibraryImage(file);
        } catch (e) {
          errors.push((e as Error).message);
        }
      }
      return errors;
    },
    onSuccess: (errors) => {
      setUploadErrors(errors);
      void qc.invalidateQueries({ queryKey: ["images"] });
    },
  });
  const addFiles = (list: FileList | null) => list?.length && upload.mutate(Array.from(list));

  return (
    <Stack
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => e.currentTarget === e.target && setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        addFiles(e.dataTransfer.files);
      }}
    >
      <Group justify="space-between">
        <Title order={2}>이미지</Title>
        <Button loading={upload.isPending} onClick={() => fileInput.current?.click()}>
          + 이미지 올리기
        </Button>
        <input
          ref={fileInput}
          type="file"
          accept={IMAGE_ACCEPT}
          multiple
          hidden
          aria-label="올릴 이미지 파일"
          onChange={(e) => {
            addFiles(e.currentTarget.files);
            e.currentTarget.value = "";
          }}
        />
      </Group>
      <Text size="sm" c="dimmed">
        상품 사진 등을 올려 두면 템플릿·문서에서 <b>/</b> → <b>자료실 이미지</b>로 골라 넣을 수 있습니다. 여러 장을 한 번에 고르거나
        이 화면에 끌어다 놓아도 됩니다 (PNG·JPG·GIF·WEBP, 10MB까지).
      </Text>
      <Card withBorder padding="sm" className={`image-drop${dragging ? " is-dragging" : ""}`}>
        <Text size="sm" c="dimmed" ta="center">
          {upload.isPending ? "올리는 중…" : "여기에 이미지 파일을 끌어다 놓으세요"}
        </Text>
      </Card>
      {uploadErrors.map((m) => (
        <Text key={m} size="sm" c="red">
          {m}
        </Text>
      ))}
      <TextInput placeholder="이름으로 찾기" value={q} onChange={(e) => setQ(e.currentTarget.value)} w={280} />
      <ErrorAlert error={images.error} />
      {images.isPending ? (
        <Loading />
      ) : (
        <SimpleGrid cols={{ base: 2, sm: 3, md: 4, lg: 6 }}>
          {images.data?.map((img) => (
            <Card key={img.id} withBorder padding="xs" style={{ cursor: "pointer" }} onClick={() => setViewing(img)}>
              <Card.Section className="image-thumb">
                <img src={img.url} alt={img.name} loading="lazy" />
              </Card.Section>
              <Text size="sm" fw={600} lineClamp={1} mt={6} title={img.name}>
                {img.name}
              </Text>
              <Text size="xs" c="dimmed">
                {img.width && img.height ? `${img.width}×${img.height} · ` : ""}
                {formatBytes(img.size_bytes)}
              </Text>
            </Card>
          ))}
        </SimpleGrid>
      )}
      {images.data?.length === 0 && (
        <Text c="dimmed">{q ? "찾는 이미지가 없습니다." : "올린 이미지가 없습니다. [+ 이미지 올리기]로 올리세요."}</Text>
      )}
      <Modal opened={viewing !== null} onClose={() => setViewing(null)} title="이미지" size="xl">
        {viewing && <ImageDetail key={viewing.id} image={viewing} onClose={() => setViewing(null)} />}
      </Modal>
    </Stack>
  );
}

function ImageDetail({ image, onClose }: { image: LibraryImage; onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState(image.name);
  const done = () => void qc.invalidateQueries({ queryKey: ["images"] });
  const rename = useMutation({
    mutationFn: () => api<LibraryImage>(`/images/${image.id}`, { method: "PATCH", body: { name } }),
    onSuccess: done,
  });
  const remove = useMutation({
    mutationFn: () => api(`/images/${image.id}`, { method: "DELETE" }),
    onSuccess: () => {
      done();
      onClose();
    },
  });
  return (
    <Stack>
      <Image src={image.url} alt={image.name} fit="contain" mah={420} />
      <Group align="flex-end">
        <TextInput label="이름" value={name} onChange={(e) => setName(e.currentTarget.value)} style={{ flex: 1 }} />
        <Button
          variant="default"
          disabled={!name.trim() || name.trim() === image.name}
          loading={rename.isPending}
          onClick={() => rename.mutate()}
        >
          이름 저장
        </Button>
      </Group>
      <Text size="sm" c="dimmed">
        {image.width && image.height ? `${image.width}×${image.height}px · ` : ""}
        {formatBytes(image.size_bytes)} · {formatDateTime(image.created_at)} 올림
      </Text>
      <ErrorAlert error={rename.error ?? remove.error} />
      <Group justify="space-between">
        <Button
          variant="subtle"
          color="red"
          loading={remove.isPending}
          onClick={() => window.confirm(`'${image.name}' 이미지를 자료실에서 지울까요?`) && remove.mutate()}
        >
          삭제
        </Button>
        <Button component="a" href={downloadUrl(image)} download>
          원본 내려받기
        </Button>
      </Group>
    </Stack>
  );
}
