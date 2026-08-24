import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "VerbaOps AI",
  description: "Read-only NovaCommerce support chat",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>): React.JSX.Element {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
