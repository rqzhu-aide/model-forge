import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { queryClient } from "./queryClient";
import "katex/dist/katex.min.css";
import "./styles.css";
import "./integrity.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Model Forge could not find its application root.");
}

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
