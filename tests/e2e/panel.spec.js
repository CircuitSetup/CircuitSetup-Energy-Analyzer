import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { apiPayload } from "./panel-fixtures.js";

const HARNESS = "/tests/e2e/panel.html";
const browserLogs = new WeakMap();

test.beforeEach(async ({ page }) => {
  const entries = [];
  browserLogs.set(page, entries);
  page.on("console", (message) => entries.push({ type: `console:${message.type()}`, text: message.text() }));
  page.on("pageerror", (error) => entries.push({ type: "pageerror", text: error.message }));
  page.on("requestfailed", (request) => entries.push({
    type: "requestfailed",
    text: `${request.method()} ${request.url()}: ${request.failure()?.errorText || "failed"}`,
  }));
  page.on("response", (response) => {
    if (response.status() >= 400) {
      entries.push({
        type: "http:error",
        text: `${response.status()} ${response.url()}`,
      });
    }
  });
});

test.afterEach(async ({ page }, testInfo) => {
  const entries = browserLogs.get(page) || [];
  const allowedErrors = testInfo.annotations
    .filter(({ type }) => type === "allow-browser-error")
    .map(({ description }) => description);
  const unexpected = entries.filter((entry) => (
    entry.type === "pageerror"
    || entry.type === "requestfailed"
    || entry.type === "console:error"
    || entry.type === "http:error"
  ) && !allowedErrors.some((allowed) => entry.text.includes(allowed)));
  if (testInfo.status !== testInfo.expectedStatus || unexpected.length) {
    await testInfo.attach("browser-console.json", {
      body: Buffer.from(JSON.stringify(entries, null, 2)),
      contentType: "application/json",
    });
  }
  expect(unexpected).toEqual([]);
});

async function mockPanelApi(page, override) {
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const overridden = override ? await override({ request, route, url }) : false;
    if (overridden) return;
    await route.fulfill({ json: apiPayload(url.pathname) });
  });
}

async function openPanel(page, query) {
  await page.goto(`${HARNESS}${query}`);
  await page.waitForFunction(() => window.__panelReady === true);
  const panel = page.locator("circuitsetup-energy-analyzer-panel");
  await expect(panel.locator("[data-loading-skeleton]")).toHaveCount(0);
  await expect(panel.locator("h1")).toBeVisible();
  return panel;
}

async function toHaveNoViolations(page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
}

for (const route of [
  { name: "appliance insights", query: "?appliance_insights=1", heading: "Appliance Insights" },
  { name: "appliance detail", query: "?appliance_detail=1&circuit_id=kitchen", heading: "Kitchen Appliances" },
  { name: "setup health", query: "?setup_health=1", heading: "Setup Health" },
  { name: "NILM workspace", query: "?nilm_workspace=1&circuit_id=mains", heading: "NILM Workspace" },
]) {
  test(`${route.name} renders without browser errors`, async ({ page }) => {
    await mockPanelApi(page);
    const panel = await openPanel(page, route.query);
    await expect(panel.locator("h1")).toHaveText(route.heading);
    await expect(panel.locator(".error")).toHaveCount(0);
  });
}

test("appliance action calls the Home Assistant service", async ({ page }) => {
  await mockPanelApi(page);
  const panel = await openPanel(page, "?appliance_detail=1&circuit_id=kitchen");
  await panel.locator('[data-appliance-detail-action="relearn_baseline"]').click();
  await expect.poll(() => page.evaluate(() => window.__serviceCalls)).toEqual([
    {
      domain: "circuitsetup_energy_analyzer",
      service: "relearn_baseline",
      data: { circuit_id: "kitchen" },
    },
  ]);
});

test("NILM lane tabs support keyboard navigation", async ({ page }) => {
  await mockPanelApi(page);
  const panel = await openPanel(page, "?nilm_workspace=1&circuit_id=mains");
  const needsReview = panel.locator('[data-nilm-lane="needs_review"]');
  await needsReview.focus();
  await needsReview.press("ArrowRight");
  const assigned = panel.locator('[data-nilm-lane="assigned"]');
  await expect(assigned).toBeFocused();
  await expect(assigned).toHaveAttribute("aria-selected", "true");
});

test("major panel routes pass automated accessibility checks", async ({ page }) => {
  await mockPanelApi(page);
  for (const query of [
    "?appliance_insights=1",
    "?appliance_detail=1&circuit_id=kitchen",
    "?setup_health=1",
    "?nilm_workspace=1&circuit_id=mains",
    "?alert_id=alert-kitchen-energy",
  ]) {
    await openPanel(page, query);
    await toHaveNoViolations(page);
  }
});

test("mobile layout has no horizontal page overflow", async ({ page, isMobile }) => {
  test.skip(!isMobile, "Mobile overflow is covered by the mobile project.");
  await mockPanelApi(page);
  await openPanel(page, "?appliance_insights=1");
  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth + 1);
});

test("Appliance Insights filters attention and NILM appliances", async ({ page, isMobile }) => {
  test.skip(isMobile, "Mobile route and overflow coverage runs separately.");
  await mockPanelApi(page);
  const panel = await openPanel(page, "?appliance_insights=1");
  await expect(panel.locator("tbody tr")).toHaveCount(3);

  await panel.locator('[data-appliance-insights-filter="needs_attention"]').check();
  await expect(panel.locator("tbody tr")).toHaveCount(2);
  await expect(panel.locator("tbody")).not.toContainText("Bedroom Fan");

  await panel.locator('[data-appliance-insights-filter="nilm_estimated"]').check();
  await expect(panel.locator("tbody tr")).toHaveCount(1);
  await expect(panel.locator("tbody")).toContainText("Dishwasher Estimate");
});

test("Appliance Detail exposes ranges, comparisons, and session evidence", async ({ page, isMobile }) => {
  test.skip(isMobile, "Mobile route and accessibility coverage runs separately.");
  await mockPanelApi(page);
  const panel = await openPanel(page, "?appliance_detail=1&circuit_id=kitchen");

  await expect(panel.getByRole("heading", { name: "Today vs Normal" })).toBeVisible();
  await expect(panel.getByText("Projected end of day")).toBeVisible();
  const session = panel.locator('[data-session-id="direct-session-1"]');
  await session.locator("summary").click();
  await expect(session.getByRole("link", { name: "Open Evidence" })).toBeVisible();

  const period = panel.locator("[data-appliance-history-period]");
  await period.selectOption("24");
  await expect(period).toHaveValue("24");
});

test("alert responses and setting preview actions call their services", async ({ page, isMobile }) => {
  test.skip(isMobile, "Mobile route and accessibility coverage runs separately.");
  await mockPanelApi(page);
  const panel = await openPanel(page, "?alert_id=alert-kitchen-energy");

  await panel.locator('[data-alert-decision][value="mark_expected"]').check();
  await panel.locator("#apply_alert_decision").click();
  await panel.locator('[data-alert-decision][value="mark_unhelpful"]').check();
  await panel.locator("#apply_alert_decision").click();

  const recommendations = panel.locator('[data-alert-disclosure="recommendations"]');
  await recommendations.locator("summary").first().click();
  const preview = recommendations.locator("details.setting-impact-preview");
  await preview.locator("summary").click();
  await expect(preview).toContainText("24");
  await expect(preview).toContainText("Recent history only.");
  await recommendations.locator('[data-recommendation-action="apply"]').click();

  await panel.locator('[data-alert-disclosure="recommendations"] summary').first().click();
  await panel.locator('[data-recommendation-action="reset"]').click();
  await expect.poll(() => page.evaluate(() => window.__serviceCalls.map((call) => call.service))).toEqual([
    "mark_alert_expected",
    "mark_alert_unhelpful",
    "apply_setting_recommendation",
    "reset_setting_recommendation",
  ]);
});

test("NILM review supports decisions, validation, and interval labeling", async ({ page, isMobile }) => {
  test.skip(isMobile, "Mobile route and keyboard coverage runs separately.");
  await mockPanelApi(page);
  const panel = await openPanel(page, "?nilm_workspace=1&circuit_id=mains");

  await panel.locator('[data-nilm-decision][value="mark_expected"]').check();
  await panel.locator("[data-nilm-apply-decision]").click();

  const secondary = panel.locator("[data-nilm-secondary-details]");
  await secondary.locator("summary").click();
  await panel.locator('[data-nilm-session-action="validate"]').click();

  await panel.locator('[data-nilm-lane="assigned"]').click();
  await panel.locator('[data-nilm-assignment-action="validate_history"]').click();

  await panel.locator("[data-nilm-open-interval-editor]").click();
  await panel.locator('[data-nilm-label-interval-input="label"]').fill("Dishwasher");
  await panel.locator('[data-nilm-label-interval-input="appliance_profile"]').selectOption("dishwasher");
  await panel.locator('[data-nilm-label-interval-input="start"]').fill("2026-07-13T18:00");
  await panel.locator('[data-nilm-label-interval-input="end"]').fill("2026-07-13T18:45");
  await panel.locator('[data-nilm-label-interval-action="save"]').click();

  await expect.poll(() => page.evaluate(() => window.__serviceCalls.map((call) => call.service))).toEqual([
    "mark_nilm_signature_expected",
    "validate_nilm_session",
    "validate_nilm_assignment_history",
    "label_nilm_interval",
  ]);
});

test("failed NILM request can be retried", async ({ page }) => {
  test.info().annotations.push(
    { type: "allow-browser-error", description: "500 http://127.0.0.1:4173/api/circuitsetup_energy_analyzer/nilm_workspace" },
    { type: "allow-browser-error", description: "Failed to load resource: the server responded with a status of 500" },
  );
  let attempts = 0;
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/nilm_workspace")) return false;
    attempts += 1;
    if (attempts === 1) {
      await route.fulfill({ status: 500, json: { message: "forced E2E failure" } });
      return true;
    }
    return false;
  });
  const panel = await openPanel(page, "?nilm_workspace=1&circuit_id=mains");
  const retry = panel.locator("[data-retry-nilm-workspace]");
  await expect(retry).toBeVisible();
  await retry.click();
  await expect(panel.locator("[data-retry-nilm-workspace]")).toHaveCount(0);
  await expect(panel.locator('[data-nilm-lane="needs_review"]')).toBeVisible();
  expect(attempts).toBe(2);
});
