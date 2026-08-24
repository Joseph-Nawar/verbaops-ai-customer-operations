import { expect, test } from "@playwright/test";

const backendOrigin = "http://127.0.0.1:4100";
const backendToken = "smoke-backend-token";
const orderId = "45fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2";

test("completes the deterministic read-only chat journey through the BFF", async ({ page, request }) => {
  const directBackendRequests: string[] = [];
  page.on("request", (requestEvent) => {
    if (requestEvent.url().startsWith(backendOrigin)) directBackendRequests.push(requestEvent.url());
  });

  await page.goto("/");
  const input = page.getByLabel("Message");
  await input.fill("Where is my order?");
  await input.press("Enter");
  await expect(page.getByText("Please provide your order ID.")).toBeVisible();

  await input.fill(orderId);
  await input.press("Enter");
  await expect(page.getByText("Your order 45fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2 is in transit with Acme and tracking number T-1.")).toBeVisible();

  const state = await request.get(`${backendOrigin}/__state`);
  expect(state.ok()).toBeTruthy();
  expect((await state.json()).conversationCreates).toBe(1);
  expect(directBackendRequests).toEqual([]);
  expect(await page.content()).not.toContain(backendToken);
});
