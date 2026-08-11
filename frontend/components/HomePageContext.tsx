// frontend/components/HomePageContext.tsx
//
// Registers page context for the home route. A tiny client marker so
// app/page.tsx itself can stay a plain Server Component.
"use client";

import { usePageContext } from "@/lib/page-context";

export function HomePageContext() {
  usePageContext({ page: "HOME" });
  return null;
}
