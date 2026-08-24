import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const clientFiles = ["components/chat.tsx", "app/page.tsx", "app/layout.tsx"];

describe("browser secret boundary", () => {
  it("keeps bearer and trusted identity fields out of client modules", async () => {
    const source = await Promise.all(
      clientFiles.map((file) => readFile(resolve(process.cwd(), "src", file), "utf8")),
    );
    const clientSource = source.join("\n");

    expect(clientSource).not.toContain("VERBAOPS_API_TOKEN");
    expect(clientSource).not.toContain("NEXT_PUBLIC_VERBAOPS_API_TOKEN");
    expect(clientSource).not.toMatch(/tenant_id|principal_id|customer_id/);
    expect(clientSource).not.toContain("dangerouslySetInnerHTML");
  });
});
