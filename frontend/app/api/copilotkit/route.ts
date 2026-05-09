// frontend/app/api/copilotkit/route.ts

import {
  CopilotRuntime,
  OpenAIAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";
import { HttpAgent } from "@ag-ui/client";

const serviceAdapter = new OpenAIAdapter();

const runtime = new CopilotRuntime({
  agents: {
    uni: new HttpAgent({
      url: "http://127.0.0.1:8000/agent/ag-ui",
    }),
  },
});

export const POST = async (request: Request) => {
  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    runtime,
    serviceAdapter,
    endpoint: "/api/copilotkit",
  });

  return handleRequest(request);
};