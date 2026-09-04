import { expect, test, type Page } from "@playwright/test";

import {
  createOrg,
  createProject,
  createTask,
  openFilesPanel,
  signUp,
  uniqueEmail,
} from "./helpers";

/** A real 1×1 PNG, so storage holds genuine bytes. */
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

async function openTask(page: Page, orgId: string, title: string) {
  await page.goto(`/orgs/${orgId}/tasks`);
  await page.getByRole("link", { name: new RegExp(title) }).click();
  await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);
}

const filesPanel = (page: Page) => page.getByRole("region", { name: "Files" });
const thread = (page: Page) => page.getByRole("region", { name: "Comments" });

/**
 * Exact, because the glyph beside it is labelled "Priority: Normal" and
 * Playwright matches accessible names by substring.
 */
const priorityPicker = (page: Page) =>
  page.getByRole("button", { name: "Priority", exact: true });

const projectPicker = (page: Page) =>
  page.getByRole("button", { name: "Project", exact: true });

/** The toast, as opposed to the history line that says much the same thing. */
const toast = (page: Page, title: string) =>
  page.getByRole("heading", { name: title, exact: true });

test.describe("priority", () => {
  test("a new task is Normal, and the level can be raised", async ({ page }) => {
    await signUp(page, uniqueEmail("pr"));
    const orgId = await createOrg(page, `Priority ${Date.now()}`);
    await createTask(page, orgId, "Patch the hull");
    await openTask(page, orgId, "Patch the hull");

    // Normal is the default and the middle of the range, so raising and
    // lowering cost the same.
    await expect(priorityPicker(page)).toContainText("Normal");

    await priorityPicker(page).click();
    await page.getByRole("option", { name: "Critical" }).click();
    await expect(page.getByText("set the priority to critical")).toBeVisible();
  });

  test("the board can be grouped by priority instead of status", async ({ page }) => {
    await signUp(page, uniqueEmail("pr"));
    const orgId = await createOrg(page, `Priority ${Date.now()}`);
    await createTask(page, orgId, "Bail out the bilge");
    await openTask(page, orgId, "Bail out the bilge");
    await priorityPicker(page).click();
    await page.getByRole("option", { name: "Urgent" }).click();
    await expect(page.getByText("set the priority to urgent")).toBeVisible();

    await page.goto(`/orgs/${orgId}/tasks`);
    // Status columns to begin with.
    await expect(page.getByText("In review", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: /Group the board/ }).click();
    await page.waitForURL(/group=priority/);
    // Six priority columns, and the status ones gone.
    for (const column of ["Critical", "Urgent", "High", "Normal", "Low", "Very low"]) {
      await expect(page.getByText(column, { exact: true }).first()).toBeVisible();
    }
    await expect(page.getByText("In review", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("link", { name: /Bail out the bilge/ })).toBeVisible();

    // The arrangement is in the URL, so a link carries it.
    await page.reload();
    await expect(page.getByText("Critical", { exact: true }).first()).toBeVisible();
  });
});

test.describe("the picker", () => {
  test("typing filters a long list down to one", async ({ page }) => {
    await signUp(page, uniqueEmail("pk"));
    const orgId = await createOrg(page, `Pick ${Date.now()}`);
    for (const name of ["Antifoul", "Rigging", "Sailmaking", "Woodwork"]) {
      await createProject(page, orgId, name);
    }
    await createTask(page, orgId, "Needs a home");
    await openTask(page, orgId, "Needs a home");

    await projectPicker(page).click();
    // The filter is focused on open — choosing is "type, Enter", never a scroll.
    await page.keyboard.type("sail");
    await expect(page.getByRole("option", { name: "Sailmaking" })).toBeVisible();
    await expect(page.getByRole("option", { name: "Rigging" })).toHaveCount(0);
    await page.keyboard.press("Enter");

    await expect(toast(page, "Moved")).toBeVisible();
    // The breadcrumb, which is where you find out where a task now lives.
    await expect(
      page.getByLabel("breadcrumb").getByRole("link", { name: "Sailmaking" }),
    ).toBeVisible();
  });

  test("Escape closes the list, not the dialog behind it", async ({ page }) => {
    // The picker is used inside dialogs, which close on Escape themselves.
    // Dismissing the list must not also throw away the half-typed task.
    await signUp(page, uniqueEmail("pk"));
    const orgId = await createOrg(page, `Pick ${Date.now()}`);
    await createProject(page, orgId, "Refit");

    await page.goto(`/orgs/${orgId}/tasks`);
    await page.getByRole("button", { name: "New task" }).first().click();
    await page.getByLabel("Title").fill("Draft I care about");
    await page.getByRole("dialog").getByLabel("Project", { exact: true }).click();
    await expect(page.getByRole("option", { name: "Refit" })).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(page.getByRole("option", { name: "Refit" })).toHaveCount(0);
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByLabel("Title")).toHaveValue("Draft I care about");
  });

  test("a filter that matches nothing says so", async ({ page }) => {
    await signUp(page, uniqueEmail("pk"));
    const orgId = await createOrg(page, `Pick ${Date.now()}`);
    await createProject(page, orgId, "Antifoul");
    await createTask(page, orgId, "Nowhere to go");
    await openTask(page, orgId, "Nowhere to go");

    await projectPicker(page).click();
    await page.keyboard.type("zzzz");
    await expect(page.getByText(/Nothing matches/)).toBeVisible();
  });
});

test.describe("moving a task between projects", () => {
  test("it can be filed, moved, and taken back out", async ({ page }) => {
    await signUp(page, uniqueEmail("mv"));
    const orgId = await createOrg(page, `Move ${Date.now()}`);
    await createProject(page, orgId, "Refit");
    await createProject(page, orgId, "Delivery");
    await createTask(page, orgId, "Wandering task");
    await openTask(page, orgId, "Wandering task");

    await expect(projectPicker(page)).toContainText("No project");

    await projectPicker(page).click();
    await page.getByRole("option", { name: "Refit" }).click();
    await expect(toast(page, "Moved")).toBeVisible();
    // The breadcrumb follows: access flows down from the project, and the
    // trail is where you find out which one.
    await expect(page.getByLabel("breadcrumb").getByRole("link", { name: "Refit" })).toBeVisible();

    await projectPicker(page).click();
    await page.getByRole("option", { name: "Delivery" }).click();
    await expect(toast(page, "Moved")).toBeVisible();
    await expect(page.getByText("moved it to another project")).toBeVisible();

    await projectPicker(page).click();
    await page.getByRole("option", { name: "No project" }).click();
    await expect(toast(page, "Taken out of its project")).toBeVisible();
    await expect(page.getByText("took it out of its project")).toBeVisible();
  });
});

test.describe("the files panel", () => {
  test("a picture uploads, shows as a tile, and opens in a popup", async ({ page }) => {
    await signUp(page, uniqueEmail("fl"));
    const orgId = await createOrg(page, `Files ${Date.now()}`);
    await createTask(page, orgId, "Photograph the keel");
    await openTask(page, orgId, "Photograph the keel");
    await openFilesPanel(page);

    await page.getByLabel("File to add to this task").setInputFiles({
      name: "keel.png",
      mimeType: "image/png",
      buffer: PNG,
    });

    const tile = filesPanel(page).getByRole("button", { name: "Open keel.png" });
    await expect(tile).toBeVisible({ timeout: 15_000 });
    await expect(filesPanel(page).getByRole("img", { name: "keel.png" })).toHaveAttribute(
      "src",
      /\/media\/tasks\//,
    );

    // Clicking opens it in place rather than in a new tab — you come back to
    // the task, not to a browser tab.
    await tile.click();
    const popup = page.getByRole("dialog", { name: "keel.png" });
    await expect(popup).toBeVisible();
    // The picture itself, not just the chrome around it — a popup that opens
    // onto a black void is the failure worth catching here.
    await expect(popup.getByRole("img", { name: "keel.png" })).toBeVisible();
    await expect(popup.getByRole("link", { name: "Download the original" })).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(popup).toHaveCount(0);
  });

  test("a file posted in a comment shows in the panel too", async ({ page }) => {
    await signUp(page, uniqueEmail("fl"));
    const orgId = await createOrg(page, `Files ${Date.now()}`);
    await createTask(page, orgId, "One list");
    await openTask(page, orgId, "One list");

    await page
      .getByLabel("File to upload")
      .setInputFiles({ name: "spar.png", mimeType: "image/png", buffer: PNG });
    await expect(page.getByRole("button", { name: "Remove spar.png" })).toBeVisible({
      timeout: 15_000,
    });
    await page.getByLabel("Write a comment").fill("Here's the spar");
    await page.getByRole("button", { name: "Comment" }).click();
    await expect(thread(page).getByRole("img", { name: "spar.png" })).toBeVisible();

    // The point of one panel: you don't hunt a thread to find a file.
    await expect(filesPanel(page).getByRole("button", { name: "Open spar.png" })).toBeVisible({
      timeout: 15_000,
    });
    // …but it can't be deleted from under the comment that refers to it.
    await expect(filesPanel(page).getByRole("button", { name: "Remove spar.png" })).toHaveCount(0);
  });

  test("a non-image is a link, not a tile that opens nothing", async ({ page }) => {
    await signUp(page, uniqueEmail("fl"));
    const orgId = await createOrg(page, `Files ${Date.now()}`);
    await createTask(page, orgId, "Paper trail");
    await openTask(page, orgId, "Paper trail");
    await openFilesPanel(page);

    await page.getByLabel("File to add to this task").setInputFiles({
      name: "survey.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("hull is fine"),
    });

    await expect(filesPanel(page).getByRole("link", { name: "Open survey.txt" })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByRole("img", { name: "survey.txt" })).toHaveCount(0);
  });

  test("a file added here can be removed again", async ({ page }) => {
    await signUp(page, uniqueEmail("fl"));
    const orgId = await createOrg(page, `Files ${Date.now()}`);
    await createTask(page, orgId, "Second thoughts");
    await openTask(page, orgId, "Second thoughts");
    await openFilesPanel(page);

    await page.getByLabel("File to add to this task").setInputFiles({
      name: "wrong.png",
      mimeType: "image/png",
      buffer: PNG,
    });
    await expect(filesPanel(page).getByRole("button", { name: "Open wrong.png" })).toBeVisible({
      timeout: 15_000,
    });

    await filesPanel(page).getByRole("button", { name: "Remove wrong.png" }).click();
    await expect(filesPanel(page).getByRole("button", { name: "Open wrong.png" })).toHaveCount(0);
    await expect(page.getByText("Nothing attached yet")).toBeVisible();
  });
});

test.describe("creating a task", () => {
  test("shows a toast naming it, with a way straight to it", async ({ page }) => {
    await signUp(page, uniqueEmail("ct"));
    const orgId = await createOrg(page, `Created ${Date.now()}`);
    await page.goto(`/orgs/${orgId}/tasks`);

    await page.getByRole("button", { name: "New task" }).first().click();
    await page.getByLabel("Title").fill("Order the antifoul");
    await page.getByRole("button", { name: "Create", exact: true }).click();

    const createdToast = toast(page, 'Task "Order the antifoul" was created');
    await expect(createdToast).toBeVisible();

    // Ten seconds, not the library default of five — long enough to still be
    // there after typing the next task's title, which is the ordinary case
    // right after creating one.
    await page.waitForTimeout(6_000);
    await expect(createdToast).toBeVisible();

    await page.getByRole("button", { name: "Open" }).click();
    await page.waitForURL(/\/orgs\/[0-9a-f-]+\/tasks\/[0-9a-f-]+$/);
    await expect(page.getByRole("heading", { name: "Order the antifoul" })).toBeVisible();
  });

  /**
   * Reported: type a long description and the dialog becomes unusable — no
   * way to reach the title, no way to reach Create.
   *
   * `Textarea` is `field-sizing-content`, so the field grows with what you
   * type; the popup is centred with `-translate-y-1/2`, so it grew off the
   * top *and* the bottom of the viewport at once, with nothing anywhere
   * allowed to scroll. Every control stayed rendered and "visible"
   * throughout — they were just nowhere a person could get at them, which
   * is why this asserts on geometry rather than on `toBeVisible`.
   *
   * Two claims, and the first is the one that matters: the popup itself
   * fits the viewport. Then Create stays put (the footer is pinned, not
   * scrolled away with the text) and the title is one scroll away rather
   * than gone — `scrollIntoViewIfNeeded` has nothing to scroll on a
   * `fixed` popup with no scroll container inside it, so it fails on the
   * old layout too.
   */
  test("a long description leaves the title and Create reachable", async ({ page }) => {
    await signUp(page, uniqueEmail("ctall"));
    const orgId = await createOrg(page, `Tall ${Date.now()}`);
    await page.goto(`/orgs/${orgId}/tasks`);

    await page.getByRole("button", { name: "New task" }).first().click();
    const title = page.getByLabel("Title");
    await title.fill("Rebuild the windlass");

    // Long enough to overflow any viewport, pasted rather than typed: this
    // is about the layout, and 60 lines of `pressSequentially` is a minute
    // of test time for nothing.
    const description = Array.from(
      { length: 60 },
      (_, i) => `Line ${i + 1}: strip, inspect, grease, reassemble.`,
    ).join("\n");
    await page.getByLabel("Description").fill(description);

    const create = page.getByRole("button", { name: "Create", exact: true });
    const viewport = page.viewportSize()!;
    const box = (await page.getByRole("dialog").boundingBox())!;
    expect(box.y).toBeGreaterThanOrEqual(0);
    expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);

    await expect(create).toBeInViewport();
    await title.scrollIntoViewIfNeeded();
    await expect(title).toBeInViewport();
    await expect(create).toBeInViewport();

    // And it still works: the description survives the scrolling body.
    await create.click();
    await expect(toast(page, 'Task "Rebuild the windlass" was created')).toBeVisible();
    await page.getByRole("button", { name: "Open" }).click();
    await page.waitForURL(/\/orgs\/[0-9a-f-]+\/tasks\/[0-9a-f-]+$/);
    await expect(page.getByText("Line 60: strip, inspect, grease, reassemble.")).toBeVisible();
  });
});

test.describe("going straight from one task to another", () => {
  /**
   * Reported: jump to a second task from ⌘K while already on a task, and the
   * Details card keeps the *first* task's title.
   *
   * Both tasks match the same route, so React Router keeps the component
   * instance and `useState(task.title)` — which only runs on mount — never
   * re-seeds. Everything fed straight from props (the heading, the status
   * pickers) updated, which is what made it look like only "some fields"
   * were stale. `Keyed` in main.tsx is the fix; this is the proof, and it
   * fails loudly without it.
   */
  test("the editable fields belong to the task you arrived at", async ({ page }) => {
    await signUp(page, uniqueEmail("nav"));
    const orgId = await createOrg(page, `Nav ${Date.now()}`);
    await createTask(page, orgId, "Alpha winch overhaul");
    await createTask(page, orgId, "Bravo rudder inspection");

    await openTask(page, orgId, "Alpha winch overhaul");
    await expect(page.getByLabel("Title")).toHaveValue("Alpha winch overhaul");

    // Through the palette, exactly as reported — not a fresh page load,
    // which would remount everything and hide the bug.
    await page.keyboard.press("ControlOrMeta+k");
    await page.getByRole("textbox", { name: "Search" }).fill("Bravo");
    await page.getByText("Bravo rudder inspection").first().click();
    await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);

    await expect(page.getByRole("heading", { name: "Bravo rudder inspection" })).toBeVisible();
    await expect(page.getByLabel("Title")).toHaveValue("Bravo rudder inspection");
  });
});
