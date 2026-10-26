import { AppShell, Group, NavLink, Text, TextInput } from "@mantine/core";
import { useState } from "react";

import { BulkUpdateList, BulkUpdateNew, BulkUpdateResult } from "./pages/BulkUpdates";
import { DocumentEditor } from "./pages/DocumentEditor";
import { DocumentList } from "./pages/Documents";
import { ModuleDetail, ModuleList } from "./pages/Modules";
import { ProductDetail } from "./pages/ProductDetail";
import { ProductList } from "./pages/ProductList";
import { SearchPage } from "./pages/SearchPage";
import { VariableList } from "./pages/Variables";
import { navigate, useRoute } from "./router";
import { SHOW_PRODUCT_FEATURE } from "./features";

const NAV = [
  { path: "documents", label: "문서" },
  { path: "modules", label: "템플릿" },
  { path: "variables", label: "치환 항목" },
  { path: "bulk-updates", label: "일괄 반영 작업" },
];
const PRODUCT_NAV = [{ path: "products", label: "상품 문서 (약관·설명서)" }];

function Page({ route }: { route: string[] }) {
  const [section, id] = route;
  switch (section) {
    case "documents":
      return id ? <DocumentEditor key={id} id={id} /> : <DocumentList />;
    case "modules":
      return id ? <ModuleDetail key={id} id={id} /> : <ModuleList />;
    case "variables":
      return <VariableList />;
    case "search":
      return <SearchPage />;
    case "bulk-updates":
      if (id === "new") return <BulkUpdateNew />;
      return id ? <BulkUpdateResult key={id} id={id} /> : <BulkUpdateList />;
    case "products":
      return id ? <ProductDetail key={id} id={id} /> : <ProductList />;
    default:
      return <DocumentList />;
  }
}

export function App() {
  const route = useRoute();
  const [q, setQ] = useState("");
  return (
    <AppShell header={{ height: 56 }} navbar={{ width: 210, breakpoint: "sm" }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Text fw={800}>KMS</Text>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (q.trim()) navigate(`/search?q=${encodeURIComponent(q.trim())}`);
            }}
          >
            <TextInput placeholder="템플릿·문서 검색" value={q} onChange={(e) => setQ(e.currentTarget.value)} w={320} />
          </form>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs">
        {NAV.map((n) => (
          <NavLink key={n.path} href={`#/${n.path}`} label={n.label} active={route[0] === n.path} />
        ))}
        {SHOW_PRODUCT_FEATURE && (
          <>
            <Text size="xs" c="dimmed" mt="md" mb={4} px="xs">
              상품 기능
            </Text>
            {PRODUCT_NAV.map((n) => (
              <NavLink key={n.path} href={`#/${n.path}`} label={n.label} active={route[0] === n.path} />
            ))}
          </>
        )}
      </AppShell.Navbar>
      <AppShell.Main>
        <Page route={route} />
      </AppShell.Main>
    </AppShell>
  );
}
