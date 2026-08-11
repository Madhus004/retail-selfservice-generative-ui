// frontend/app/layout.tsx

import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { CopilotKit } from "@copilotkit/react-core";
import { AssistantLauncher } from "@/components/assistant/AssistantLauncher";
import { AssistantPanel } from "@/components/assistant/AssistantPanel";
import { AssistantProvider } from "@/components/assistant/AssistantProvider";
import { RetailHeader } from "@/components/RetailHeader";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Unicorn Apparel",
  description:
    "Unicorn Apparel — D2C apparel retailer with Uni, an AI self-service assistant.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <CopilotKit
          runtimeUrl="/api/copilotkit"
          showDevConsole={false}
          enableInspector={false}
        >
          <AssistantProvider>
            <div className="flex h-screen overflow-hidden">
              <div className="min-w-0 flex-1 overflow-y-auto @container">
                <RetailHeader />
                {children}
              </div>

              <AssistantPanel />
            </div>

            <AssistantLauncher />
          </AssistantProvider>
        </CopilotKit>
      </body>
    </html>
  );
}
