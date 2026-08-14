import { expect, test, type Page } from "@playwright/test";

import { createOrg, createTask, signUp, uniqueEmail } from "./helpers";

/** A real 1×1 PNG, so storage holds genuine bytes rather than text in a hat. */
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

async function openTask(page: Page, orgId: string, title: string) {
  await page.goto(`/orgs/${orgId}/tasks`);
  await page.getByRole("link", { name: new RegExp(title) }).click();
  await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);
}

async function attach(page: Page, name: string, mimeType: string, buffer: Buffer) {
  await page.getByLabel("File to upload").setInputFiles({ name, mimeType, buffer });
}

/**
 * The thread, as opposed to the Files panel above it.
 *
 * A file posted in a comment appears in **both** — that's the point of the
 * unified panel — so an unscoped `getByRole("img", …)` matches twice and
 * Playwright rightly refuses to guess. These tests are about the thread.
 */
const thread = (page: Page) => page.getByRole("region", { name: "Comments" });

/**
 * Wait until a file is *staged* — uploaded, confirmed and ready to send.
 *
 * Keyed off the Remove button rather than the filename: the in-flight progress
 * line reads "Uploading dot.png…", so matching the name alone races ahead of
 * the upload and sends a comment with nothing attached.
 */
async function staged(page: Page, name: string) {
  await expect(page.getByRole("button", { name: `Remove ${name}` })).toBeVisible({
    timeout: 15_000,
  });
}

test.describe("attachments", () => {
  test("attach a picture and send it with a comment", async ({ page }) => {
    await signUp(page, uniqueEmail("at"));
    const orgId = await createOrg(page, `Files ${Date.now()}`);
    await createTask(page, orgId, "Photo evidence");
    await openTask(page, orgId, "Photo evidence");

    await attach(page, "dot.png", "image/png", PNG);
    // Staged, not sent: it uploaded and confirmed, and is waiting for a
    // comment to belong to.
    await staged(page, "dot.png");

    await page.getByLabel("Write a comment").fill("Here it is");
    await page.getByRole("button", { name: "Comment" }).click();

    // Rendered inline — a photo of the thing being discussed IS the comment.
    const image = thread(page).getByRole("img", { name: "dot.png" });
    await expect(image).toBeVisible();
    // The bytes really came from storage on the same origin, via Caddy.
    await expect(image).toHaveAttribute("src", /\/media\/comments\//);
  });

  test("a non-image shows as a named file, not a broken picture", async ({ page }) => {
    await signUp(page, uniqueEmail("at"));
    const orgId = await createOrg(page, `Files ${Date.now()}`);
    await createTask(page, orgId, "Paperwork");
    await openTask(page, orgId, "Paperwork");

    await attach(page, "survey.txt", "text/plain", Buffer.from("hull is fine"));
    await staged(page, "survey.txt");
    await page.getByLabel("Write a comment").fill("Survey attached");
    await page.getByRole("button", { name: "Comment" }).click();

    await expect(thread(page).getByRole("link", { name: /survey\.txt/ })).toBeVisible();
    await expect(page.getByRole("img", { name: "survey.txt" })).toHaveCount(0);
  });

  test("a rejected file type says so and stages nothing", async ({ page }) => {
    await signUp(page, uniqueEmail("at"));
    const orgId = await createOrg(page, `Files ${Date.now()}`);
    await createTask(page, orgId, "No executables");
    await openTask(page, orgId, "No executables");

    await attach(page, "virus.exe", "application/x-msdownload", Buffer.from("MZ"));
    await expect(page.getByText(/Couldn't attach virus\.exe/)).toBeVisible();
    await expect(page.getByText("virus.exe", { exact: true })).toHaveCount(0);
  });

  test("a staged file can be removed before sending", async ({ page }) => {
    await signUp(page, uniqueEmail("at"));
    const orgId = await createOrg(page, `Files ${Date.now()}`);
    await createTask(page, orgId, "Changed my mind");
    await openTask(page, orgId, "Changed my mind");

    await attach(page, "dot.png", "image/png", PNG);
    await staged(page, "dot.png");
    await page.getByRole("button", { name: "Remove dot.png" }).click();
    await expect(thread(page).getByText("dot.png")).toHaveCount(0);

    // Not "Nothing attached" — the empty Files panel says "Nothing attached
    // yet", and a comment body that is a prefix of the page's own copy is a
    // test that fails for the wrong reason.
    await page.getByLabel("Write a comment").fill("Just words, no file");
    await page.getByRole("button", { name: "Comment" }).click();
    await expect(thread(page).getByText("Just words, no file")).toBeVisible();
    await expect(page.getByRole("img", { name: "dot.png" })).toHaveCount(0);
  });

  test("several files go on one comment", async ({ page }) => {
    await signUp(page, uniqueEmail("at"));
    const orgId = await createOrg(page, `Files ${Date.now()}`);
    await createTask(page, orgId, "Two files");
    await openTask(page, orgId, "Two files");

    await attach(page, "one.png", "image/png", PNG);
    await staged(page, "one.png");
    await attach(page, "two.png", "image/png", PNG);
    await staged(page, "two.png");

    await page.getByLabel("Write a comment").fill("Both angles");
    await page.getByRole("button", { name: "Comment" }).click();

    await expect(thread(page).getByRole("img", { name: "one.png" })).toBeVisible();
    await expect(thread(page).getByRole("img", { name: "two.png" })).toBeVisible();
  });

  test("the upload goes straight to storage, not through the API", async ({ page }) => {
    // The whole reason for the handshake: a big file must not occupy an API
    // worker. Asserted by watching where the PUT actually goes.
    await signUp(page, uniqueEmail("at"));
    const orgId = await createOrg(page, `Files ${Date.now()}`);
    await createTask(page, orgId, "Direct upload");
    await openTask(page, orgId, "Direct upload");

    const puts: string[] = [];
    page.on("request", (req) => {
      if (req.method() === "PUT") puts.push(new URL(req.url()).pathname);
    });

    await attach(page, "dot.png", "image/png", PNG);
    await staged(page, "dot.png");

    expect(puts.length).toBe(1);
    expect(puts[0]).toMatch(/^\/media\/comments\//);
    // Never /api/… — the bytes don't pass through the application at all.
    expect(puts[0].startsWith("/api/")).toBe(false);
  });
});
