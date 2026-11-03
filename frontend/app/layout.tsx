import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AppealPilot",
  description: "Turn a denied health-insurance claim into a cited, deadline-tracked appeal.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
