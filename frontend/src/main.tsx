import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import "./styles.css";
import { AppShell } from "./components/AppShell";
import { ToastProvider } from "./ui/primitives";
import { PodsListPage } from "./pages/PodsListPage";
import { PodDetailPage } from "./pages/PodDetailPage";
import { EpisodePage } from "./pages/EpisodePage";
import { CreatePodPage } from "./pages/CreatePodPage";
import { SettingsPage } from "./pages/SettingsPage";
import { JobsPage } from "./pages/JobsPage";
import { TemplatesPage } from "./pages/TemplatesPage";
import { DirectorPage } from "./pages/DirectorPage";
import { RunPage } from "./pages/RunPage";
import { RecreationPage } from "./pages/RecreationPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 5_000 },
  },
});

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("missing #root in index.html");

createRoot(rootEl).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<AppShell />}>
              <Route index element={<PodsListPage />} />
              <Route path="/create" element={<CreatePodPage />} />
              <Route path="/pods/:podId" element={<PodDetailPage />} />
              <Route path="/pods/:podId/episodes/:episodeId" element={<EpisodePage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/jobs" element={<JobsPage />} />
              <Route path="/templates" element={<TemplatesPage />} />
              <Route path="/director" element={<DirectorPage />} />
              <Route path="/recreations" element={<RecreationPage />} />
              <Route path="/runs/:runId" element={<RunPage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
