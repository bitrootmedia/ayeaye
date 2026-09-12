import { expect, test, type Page } from "@playwright/test";

import { createOrg, createTask, signUp, uniqueEmail } from "./helpers";

/**
 * A comment posted through a token says so, and stays the person's own.
 *
 * The only browser coverage of `messages.via`. The HTTP suite
 * (`scripts/e2e-mcp.sh`) proves the column and the API field; what it cannot
 * prove is that a colleague reading the thread actually sees which lines
 * came through an assistant — which is the entire point of the feature, and
 * the reason the `[Claude]` prefix convention existed before it.
 *
 * It goes the whole way round on purpose: mint a real token in the browser,
 * post over the real `/mcp` transport, then read the thread as a person. A
 * test that inserted the row directly would pass with the verifier's `act`
 * claim removed, which is most of what could break.
 */

/** One JSON-RPC tool call. No handshake — the server is stateless. */
async function callTool(page: Page, token: string, name: string, args: Record<string, string>) {
  const response = await page.request.post("/mcp", {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/json, text/event-stream",
      "MCP-Protocol-Version": "2025-06-18",
    },
    data: { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: args } },
  });
  expect(response.ok()).toBeTruthy();
}

test.describe("agent attribution", () => {
  test("a comment posted through a token is marked, and still yours", async ({ page }) => {
    const email = uniqueEmail("attr");
    await signUp(page, email);
    const orgId = await createOrg(page, `Attribution ${Date.now()}`);
    await createTask(page, orgId, "Fit the new anode");

    // Minted through the account screen, because that is where the name
    // being rendered later actually comes from.
    const minted = await page.request.post("/api/me/tokens", {
      data: { name: "Claude", scope: "write" },
    });
    const { token } = (await minted.json()) as { token: string };

    const tasks = await (await page.request.get(`/api/organisations/${orgId}/tasks`)).json();
    const taskId = (tasks as { id: string; title: string }[]).find(
      (t) => t.title === "Fit the new anode",
    )!.id;

    await callTool(page, token, "comment", {
      organisation_id: orgId,
      task_id: taskId,
      body: "Ordered it this morning.",
    });

    await page.goto(`/orgs/${orgId}/tasks/${taskId}`);
    const thread = page.getByRole("region", { name: "Comments" });
    await expect(thread.getByText("Ordered it this morning.")).toBeVisible();
    // Attribution, not authorship: the comment is still the person's, so
    // both have to be on screen. Asserting only the badge would pass on a
    // thread that had stopped naming the author at all.
    await expect(thread.getByText("via Claude")).toBeVisible();
    await expect(thread.getByText(email)).toBeVisible();

    // And a comment typed here carries no badge — the control case, without
    // which "via Claude" appearing on everything would look like a pass.
    const box = page.getByLabel("Write a comment");
    await box.fill("Typed it myself.");
    await box.press("Enter");
    // Wait on the composer clearing, not just the keypress: the send is
    // async and the assertion below can otherwise outrun the render — the
    // trap `comment-thread.tsx`'s own tests already document.
    await expect(box).toHaveValue("");
    await expect(thread.getByText("Typed it myself.")).toBeVisible();
    await expect(thread.getByText("via Claude")).toHaveCount(1);

    // Photographed alongside everything else `screenshots.spec.ts` covers,
    // because this badge is the only part of the feature a person sees and
    // "the assertion passed" says nothing about whether it looks right.
    await thread.screenshot({ path: "artifacts/shots/attribution-via.png" });
  });
});
