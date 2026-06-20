import type { Metadata } from "next";

import { Header } from "@/components/header";
import "./globals.css";

export const metadata: Metadata = {
  title: "ProcureSignal",
  description: "AI-powered procurement intelligence",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="mx-auto min-h-screen max-w-5xl px-4 py-6">
          <Header />
          {children}
        </div>
      </body>
    </html>
  );
}
