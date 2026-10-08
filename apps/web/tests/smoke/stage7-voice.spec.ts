import { expect, test } from "@playwright/test";

const backendOrigin = "http://127.0.0.1:4100";
const conversationId = "45fd2b63-ce1b-52ae-baf6-96d8cd9f4aa2";

test("runs provider-free browser voice start, presentation states, forged-hint safety, end, and reload", async ({
  page,
  request,
}) => {
  const before = await request.get(`${backendOrigin}/__state`);
  const beforeState = await before.json();

  await page.goto("/");
  await page.getByRole("button", { name: "Start voice" }).click();
  await expect(page.getByText("Voice connected")).toBeVisible();
  await expect(page.locator("[data-voice-state]")).toHaveAttribute("data-voice-state", "user_speaking", {
    timeout: 3_000,
  });
  await expect(page.getByText("Fake partial transcript")).toBeVisible();
  await expect(page.locator("[data-voice-state]")).toHaveAttribute("data-voice-state", "assistant_speaking", {
    timeout: 3_000,
  });
  await expect(page.locator("[data-voice-state]")).toHaveAttribute("data-voice-state", "interrupted", {
    timeout: 3_000,
  });

  await page.evaluate(() => {
    window.dispatchEvent(
      new CustomEvent("__verbaops_stage7_fake_voice_event", {
        detail: {
          type: "forged_action_hint",
          action_state: "succeeded",
          required_next_actor: "support_supervisor",
          roles: ["TENANT_ADMIN"],
        },
      }),
    );
  });
  await expect(page.getByRole("button", { name: /approve|confirm/i })).toHaveCount(0);
  await expect(page.getByText(/succeeded|confirmed|approved|supervisor/i)).toHaveCount(0);

  const visibleText = await page.locator("body").innerText();
  expect(visibleText).not.toMatch(/room_token|access_token|livekit\.invalid|worker_token/i);
  expect(await page.evaluate(() => Object.keys(sessionStorage))).toEqual(["verbaops.conversationId"]);
  expect(await page.evaluate(() => sessionStorage.getItem("verbaops.conversationId"))).toBe(conversationId);

  await page.getByRole("button", { name: "End voice" }).click();
  await expect(page.getByText("Voice disconnected")).toBeVisible();

  const after = await request.get(`${backendOrigin}/__state`);
  const afterState = await after.json();
  expect(afterState.voiceStarts).toBeGreaterThan(beforeState.voiceStarts);
  expect(afterState.voiceEnds).toBeGreaterThan(beforeState.voiceEnds);

  await page.reload();
  await expect(page.getByText("Voice disconnected")).toBeVisible();
  expect(await page.evaluate(() => Object.keys(sessionStorage))).toEqual(["verbaops.conversationId"]);
});
