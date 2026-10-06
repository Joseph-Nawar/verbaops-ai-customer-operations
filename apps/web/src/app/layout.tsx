import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "VerbaOps AI",
  description: "NovaCommerce customer operations with server-owned action status",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>): React.JSX.Element {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
