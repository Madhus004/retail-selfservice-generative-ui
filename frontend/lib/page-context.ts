// frontend/lib/page-context.ts
//
// Minimal page-context contract between the retailer frontend and the agent.
// Only ORDER_DETAILS currently influences agent behavior (see agent/graph.py's
// pageContext backfill in detect_intent_node/fallback_intent_detection);
// HOME/ORDER_HISTORY exist for completeness and are safe to extend later
// (product pages, cart, checkout) without breaking this contract.
"use client";

import { useEffect } from "react";
import { useAssistant } from "@/components/assistant/AssistantProvider";

export type PageContext =
  | { page: "HOME" }
  | { page: "ORDER_HISTORY" }
  | { page: "ORDER_DETAILS"; orderNumber: string };

export function usePageContext(context: PageContext) {
  const { setPageContext } = useAssistant();
  const contextKey = JSON.stringify(context);

  useEffect(() => {
    setPageContext(context);

    return () => setPageContext(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contextKey, setPageContext]);
}
