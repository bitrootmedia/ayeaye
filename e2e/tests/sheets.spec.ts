import { expect, test } from "@playwright/test";

import { createOrg, createTask, signUp, uniqueEmail } from "./helpers";

/**
 * A sheet holding text beside checkboxes — the server inventory case.
 *
 * `e2e-sheets.sh` proves the API. What only a browser shows is the cell
 * itself: click to type, Enter to save, Escape to put it back, and that a
 * reset which unticks every box leaves the typed values where they were.
 */
test.describe("sheets", () => {
  test("a text column is typed into in place, and survives a reset", async ({ page }) => {
    await signUp(page, uniqueEmail("sheet"));
    const orgId = await createOrg(page, `Sheets ${Date.now()}`);
    await createTask(page, orgId, "Server inventory");
    await page.getByRole("link", { name: /Server inventory/ }).click();
    await page.waitForURL(/\/tasks\/[0-9a-f-]+$/);

    const card = page.getByRole("region", { name: "Sheets" });
    const sheetButton = page.getByRole("button", { name: "Sheet", exact: true });
    await expect(card.or(sheetButton).first()).toBeVisible();
    await sheetButton.click();
    await card.getByLabel("New sheet name").fill("Servers");
    await card.getByRole("button", { name: "Add sheet" }).click();

    await card.getByLabel("Add a row to Servers").fill("Server1");
    await card.getByRole("button", { name: "Add row to Servers" }).click();
    await expect(card.getByText("Server1", { exact: true })).toBeVisible();

    await card.getByRole("button", { name: "Text" }).click();
    await card.getByLabel("Add a column to Servers").fill("Version");
    await card.getByRole("button", { name: "Add column to Servers" }).click();
    // Wait for it: the add clears the field when it lands, and would wipe
    // the next column's name typed in the meantime.
    await expect(card.getByRole("button", { name: "Server1, Version: empty" })).toBeVisible();
    await card.getByRole("button", { name: "Checkbox" }).click();
    await card.getByLabel("Add a column to Servers").fill("Patched");
    await card.getByRole("button", { name: "Add column to Servers" }).click();
    await expect(card.getByRole("checkbox", { name: "Server1, Patched" })).toBeVisible();

    await card.getByRole("button", { name: "Server1, Version: empty" }).click();
    await card.getByRole("textbox", { name: "Server1, Version" }).fill("1.4.2");
    await card.getByRole("textbox", { name: "Server1, Version" }).press("Enter");
    await expect(card.getByRole("button", { name: "Server1, Version: 1.4.2" })).toBeVisible();

    // Escape puts the old value back rather than saving what was typed.
    await card.getByRole("button", { name: "Server1, Version: 1.4.2" }).click();
    await card.getByRole("textbox", { name: "Server1, Version" }).fill("9.9.9");
    await card.getByRole("textbox", { name: "Server1, Version" }).press("Escape");
    await expect(card.getByRole("button", { name: "Server1, Version: 1.4.2" })).toBeVisible();

    await card.getByRole("checkbox", { name: "Server1, Patched" }).click();
    await expect(card.getByRole("checkbox", { name: "Server1, Patched" })).toBeChecked();
    await card.getByRole("button", { name: "Reset Servers" }).click();
    await expect(card.getByRole("checkbox", { name: "Server1, Patched" })).not.toBeChecked();
    await expect(card.getByRole("button", { name: "Server1, Version: 1.4.2" })).toBeVisible();

    await page.reload();
    await expect(card.getByRole("button", { name: "Server1, Version: 1.4.2" })).toBeVisible();
  });
});
