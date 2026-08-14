import { expect, test, type Page } from "@playwright/test";

import { createOrg, createTask, signUp, uniqueEmail } from "./helpers";

/**
 * Chromium's fake capture device: a synthetic audio track, and the permission
 * prompt auto-accepted. That makes the whole recording path — getUserMedia,
 * MediaRecorder, the upload, the waveform — genuinely testable rather than
 * something only a human with a microphone can check.
 */
test.use({
  launchOptions: {
    args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
  },
});

async function openTask(page: Page, orgId: string, title: string) {
  await page.goto(`/orgs/${orgId}/tasks`);
  await page.getByRole("link", { name: new RegExp(title) }).click();
  await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);
}

async function record(page: Page, ms = 1200) {
  await page.getByRole("button", { name: "Record a voice note" }).click();
  await expect(page.getByLabel("Recording time")).toBeVisible();
  await page.waitForTimeout(ms);
}

test.describe("voice notes", () => {
  test("record, send, and play it back", async ({ page }) => {
    await signUp(page, uniqueEmail("vn"));
    const orgId = await createOrg(page, `Voice ${Date.now()}`);
    await createTask(page, orgId, "Say something");
    await openTask(page, orgId, "Say something");

    await record(page);
    // The send button IS the send: recording it was the decision.
    await page.getByRole("button", { name: "Send voice note" }).click();

    await expect(page.getByText("Voice note")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("button", { name: /^Play voice-note/ })).toBeVisible();
  });

  test("the recorder counts up, and cancelling throws it away", async ({ page }) => {
    await signUp(page, uniqueEmail("vn"));
    const orgId = await createOrg(page, `Voice ${Date.now()}`);
    await createTask(page, orgId, "Never mind");
    await openTask(page, orgId, "Never mind");

    await record(page, 1500);
    // Ticking, so a long note doesn't feel like a hang.
    await expect(page.getByLabel("Recording time")).toHaveText(/0:0[1-9]/);

    // Cancel is its own button — not "let go and hope".
    await page.getByRole("button", { name: "Discard recording" }).click();
    await expect(page.getByRole("button", { name: "Record a voice note" })).toBeVisible();
    await expect(page.getByText("Voice note")).toHaveCount(0);
  });

  test("the upload carries the BARE content type", async ({ page }) => {
    // The trap from PLAN.md §6. MediaRecorder reports
    // `audio/webm;codecs=opus`; a presigned signature covers Content-Type byte
    // for byte, so sending the codec parameter fails with
    // SignatureDoesNotMatch — an error that says nothing about codecs.
    await signUp(page, uniqueEmail("vn"));
    const orgId = await createOrg(page, `Voice ${Date.now()}`);
    await createTask(page, orgId, "Bare type");
    await openTask(page, orgId, "Bare type");

    const puts: { type: string; status: number }[] = [];
    page.on("response", async (res) => {
      if (res.request().method() === "PUT") {
        puts.push({
          type: res.request().headers()["content-type"] ?? "",
          status: res.status(),
        });
      }
    });

    await record(page);
    await page.getByRole("button", { name: "Send voice note" }).click();
    await expect(page.getByText("Voice note")).toBeVisible({ timeout: 20_000 });

    expect(puts.length).toBe(1);
    expect(puts[0].type).not.toContain("codecs");
    expect(puts[0].type).toMatch(/^audio\/(webm|mp4)$/);
    // Storage accepted it, which is the actual proof the signature matched.
    expect(puts[0].status).toBe(200);
  });

  test("a typed draft survives sending a voice note", async ({ page }) => {
    // Deliberate: the draft is a separate message the person hasn't finished,
    // so it isn't swept along with the audio.
    await signUp(page, uniqueEmail("vn"));
    const orgId = await createOrg(page, `Voice ${Date.now()}`);
    await createTask(page, orgId, "Keep my draft");
    await openTask(page, orgId, "Keep my draft");

    await page.getByLabel("Write a comment").fill("still writing this");
    await record(page);
    await page.getByRole("button", { name: "Send voice note" }).click();
    await expect(page.getByText("Voice note")).toBeVisible({ timeout: 20_000 });

    await expect(page.getByLabel("Write a comment")).toHaveValue("still writing this");
  });

  test("the waveform is decoded from the real audio", async ({ page }) => {
    // Not a decoration: the bars come from decodeAudioData over the actual
    // bytes, so they show where the sound is. When a browser can't decode the
    // container it falls back to a plain bar rather than inventing a shape.
    await signUp(page, uniqueEmail("vn"));
    const orgId = await createOrg(page, `Voice ${Date.now()}`);
    await createTask(page, orgId, "Show me the shape");
    await openTask(page, orgId, "Show me the shape");

    await record(page, 1500);
    await page.getByRole("button", { name: "Send voice note" }).click();
    await expect(page.getByText("Voice note")).toBeVisible({ timeout: 20_000 });

    const waveform = page.getByLabel("Waveform");
    await expect(waveform).toBeVisible({ timeout: 20_000 });

    // Chromium's fake device produces a tone, so the bars must not all be the
    // same height — that would mean we drew a placeholder.
    const heights = await waveform.locator("span").evaluateAll((bars) =>
      bars.map((b) => (b as HTMLElement).style.height),
    );
    expect(heights.length).toBeGreaterThan(8);
    expect(new Set(heights).size).toBeGreaterThan(1);
  });
});
