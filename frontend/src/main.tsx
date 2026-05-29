import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import "./styles.css";
import { App } from "./App";
import { PodsListPage } from "./pages/PodsListPage";
import { PodDetailPage } from "./pages/PodDetailPage";
import { JobsPage } from "./pages/JobsPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 5_000,
    },
  },
});

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("missing #root in index.html");

createRoot(rootEl).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<App />}>
            <Route index element={<PodsListPage />} />
            <Route path="/pods/:podId" element={<PodDetailPage />} />
            <Route path="/jobs" element={<JobsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
