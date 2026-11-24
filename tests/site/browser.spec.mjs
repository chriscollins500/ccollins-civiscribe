import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("homepage is readable, local, and free of console errors", async ({
  page,
  baseURL,
}, testInfo) => {
  const errors = [];
  const external = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error")
      errors.push(`${message.text()} (${message.location().url})`);
  });
  page.on("request", (request) => {
    if (new URL(request.url()).origin !== new URL(baseURL).origin)
      external.push(request.url());
  });
  await page.goto("./");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Your image",
  );
  await expect(
    page.getByRole("link", { name: "Make your first save" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
  expect(external).toEqual([]);
  await page.screenshot({
    path: testInfo.outputPath("homepage.png"),
    fullPage: true,
  });
});

test("representative pages pass Axe in dark and light themes", async ({
  page,
}) => {
  for (const theme of ["dark", "light"]) {
    for (const route of [
      "./",
      "guides/",
      "guides/settings-reference/",
      "playground/",
      "reference/api-and-mcp/",
      "changelog/",
    ]) {
      await page.goto(route);
      await page.evaluate((value) => {
        document.documentElement.dataset.theme = value;
      }, theme);
      const result = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
        .analyze();
      expect(
        result.violations.map((v) => ({
          id: v.id,
          nodes: v.nodes.map((n) => n.target),
        })),
        `${theme} ${route}`,
      ).toEqual([]);
    }
  }
});

test("search works by button and keyboard, and closes with Escape", async ({
  page,
}) => {
  await page.goto("./");
  await page
    .getByRole("button", { name: "Search the site", exact: true })
    .click();
  await page.getByRole("searchbox").fill("counter");
  await expect(
    page.getByRole("dialog").getByRole("link", { name: /Counters, your way/ }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.keyboard.press("Control+k");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("searchbox").fill('<img src=x onerror="alert(1)">');
  await expect(page.locator(".search-status")).toContainText("No matches");
  await expect(page.locator(".search-results img")).toHaveCount(0);
});

test("filename recipes, counter growth, format change, and unsafe paths", async ({
  page,
}) => {
  await page.goto("playground/#filenames");
  await page.getByRole("button", { name: "The classic", exact: true }).click();
  await expect(page.locator("#filename-output")).toHaveText(
    "ComfyUI_00001_.png",
  );
  await page.locator("#filename-pattern").fill("%model_noext%_%counter:2%");
  await page.locator("#filename-counter").fill("123");
  await page.locator("#filename-format").selectOption("jpeg");
  await expect(page.locator("#filename-output")).toHaveText(
    "DreamModel.v2_123.jpg",
  );
  await page.locator("#filename-pattern").fill("../outside");
  await expect(page.locator("#filename-pattern")).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await expect(page.locator("#filename-error")).not.toBeEmpty();
});

test("workflow selection never borrows another branch's identity", async ({
  page,
}) => {
  await page.goto("playground/#workflow");
  await page
    .getByRole("button", { name: "Landscape branch", exact: true })
    .click();
  await expect(page.locator("#branch-facts")).toContainText("456");
  await expect(page.locator("#branch-facts")).not.toContainText("WarmLight");
  await page
    .getByRole("button", { name: "Mystery-resource branch", exact: true })
    .click();
  await expect(page.locator("#branch-facts")).toContainText("Unresolved");
  await expect(page.locator(".branch-row.is-active")).toHaveCount(1);
});

test("format decisions preserve workflow and transparency priorities", async ({
  page,
}) => {
  await page.goto("playground/#formats");
  await expect(page.locator("#format-choice")).toHaveText("PNG");
  await page.locator("#format-workflow").uncheck();
  await page.locator("#format-compact").check();
  await expect(page.locator("#format-choice")).toHaveText("WebP");
  await page.locator("#format-lossless").uncheck();
  await expect(page.locator("#format-choice")).toHaveText("JPEG");
  await page.locator("#format-alpha").check();
  await expect(page.locator("#format-choice")).not.toHaveText("JPEG");
});

test("native save-report example loads and copy uses the intended text", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: async (value) => {
          window.__copiedExample = value;
        },
      },
    });
  });
  await page.goto("playground/#metadata");
  await page.locator("#metadata-view").selectOption("report");
  await expect(page.locator("#metadata-code")).toContainText(
    '"schema": "ccollins-civiscribe.save-result"',
  );
  await expect(page.locator("#metadata-code")).toContainText(
    '"metadataStatus": "complete"',
  );
  await page.getByRole("button", { name: "Copy example", exact: true }).click();
  expect(
    await page.evaluate(() => JSON.parse(window.__copiedExample).schema),
  ).toBe("ccollins-civiscribe.save-result");
});

test("theme persists and reduced motion is respected", async ({ page }) => {
  await page.goto("./");
  await page.getByRole("button", { name: "Switch to light theme" }).click();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(
    await page.evaluate(
      () => getComputedStyle(document.documentElement).scrollBehavior,
    ),
  ).toBe("auto");
});

test("all generated pages load without horizontal overflow", async ({
  page,
  request,
}) => {
  const response = await request.get("search-index.json");
  const entries = await response.json();
  for (const entry of entries) {
    const result = await page.goto(entry.url);
    expect(result.status(), entry.url).toBe(200);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      entry.url,
    ).toBe(true);
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  }
});

test("guides remain usable without JavaScript", async ({
  browser,
  baseURL,
}) => {
  const context = await browser.newContext({
    javaScriptEnabled: false,
    viewport: { width: 390, height: 844 },
  });
  try {
    const page = await context.newPage();
    await page.goto(`${baseURL}guides/quick-start/`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator(".prose")).toContainText("Images input");
    await page
      .locator(".prose")
      .getByRole("link", { name: "Filenames and folders", exact: true })
      .click();
    await expect(page).toHaveURL(/guides\/filenames-and-folders\//);
  } finally {
    await context.close();
  }
});
