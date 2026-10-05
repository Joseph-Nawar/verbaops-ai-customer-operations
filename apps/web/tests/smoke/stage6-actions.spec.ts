import { expect, test } from "@playwright/test";

const backendOrigin = "http://127.0.0.1:4100";
const backendToken = "smoke-backend-token";
const conversationId = "45fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2";
const proposalActionId = "11111111-1111-5111-8111-111111111111";
const approvalActionId = "22222222-2222-5222-8222-222222222222";
const unresolvedActionId = "33333333-3333-5333-8333-333333333333";
const succeededActionId = "44444444-4444-5444-8444-444444444444";
const fingerprint = "a".repeat(64);

test("renders structured action status, reloads it durably, and confirms with only ID/fingerprint", async ({ page, request }) => {
  const browserPostBodies: string[] = [];
  page.on("request", (requestEvent) => {
    if (requestEvent.method() === "POST") browserPostBodies.push(requestEvent.postData() ?? "");
  });

  await page.goto("/");
  await page.getByLabel("Message").fill("Create cancellation request");
  await page.getByLabel("Message").press("Enter");
  const actionCard = page.getByRole("article", { name: /cancel_order action request/i });
  await expect(actionCard).toBeVisible();
  await expect(page.getByText("Review and confirm this request.")).toBeVisible();

  await page.reload();
  await expect(page.getByRole("article", { name: /cancel_order action request/i })).toBeVisible();
  await expect(page.getByText("Review and confirm this request.")).toBeVisible();

  await page.getByRole("button", { name: "Confirm request" }).click();
  await expect(page.getByText("Verified business postcondition succeeded.")).toBeVisible();
  expect(await page.content()).not.toContain(backendToken);
  expect(browserPostBodies).toContain(JSON.stringify({ content: "Create cancellation request" }));
  expect(browserPostBodies).toContain(JSON.stringify({ proposal_fingerprint: fingerprint }));
  expect(browserPostBodies.join("\n")).not.toMatch(/tenant|customer|principal|role|state|idempotency|currency/i);

  const state = await request.get(`${backendOrigin}/__state`);
  expect(state.ok()).toBeTruthy();
  expect((await state.json()).confirmationBodies).toEqual([{ proposal_fingerprint: fingerprint }]);
  expect(await page.evaluate(() => Object.keys(sessionStorage))).toEqual(["verbaops.conversationId"]);
  expect(await page.evaluate(() => sessionStorage.getItem("verbaops.conversationId"))).toBe(conversationId);
  expect(proposalActionId).toMatch(/^[0-9a-f-]{36}$/);
});

test("renders server-derived approval, unresolved, and verified-success views", async ({ page, request }) => {
  await page.goto(`/action-requests/${approvalActionId}`);
  await expect(page.getByText("Waiting for supervisor approval.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Withdraw request" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve request" })).not.toBeVisible();

  const supervisorMode = await request.post(`${backendOrigin}/__mode/supervisor`);
  expect(supervisorMode.ok()).toBeTruthy();
  await page.reload();
  await expect(page.getByRole("button", { name: "Approve request" })).toBeVisible();

  await page.goto(`/action-requests/${unresolvedActionId}`);
  await expect(page.getByText("The result could not be verified yet.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Reconcile request" })).toBeVisible();
  await expect(page.getByText(/failed|succeeded|completed/i)).not.toBeVisible();

  await page.goto(`/action-requests/${succeededActionId}`);
  await expect(page.getByText("Verified business postcondition succeeded.")).toBeVisible();
  await expect(page.getByRole("article", { name: /cancel_order action request/i }).getByRole("button")).toHaveCount(0);
});
