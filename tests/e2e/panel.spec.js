import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { apiPayload, evidence } from "./panel-fixtures.js";

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

async function openDashboardGraphs(page) {
  await page.goto(`${HARNESS}?alert_id=alert-kitchen-energy`);
  await page.waitForFunction(() => window.__panelReady === true);
  await page.evaluate(() => {
    const hass = window.__panel._hass;
    const panelConfig = window.__panel._panel;
    hass.states["sensor.kitchen_power"] = {
      state: "610",
      attributes: { friendly_name: "Kitchen Power", unit_of_measurement: "W" },
    };
    window.__panel.remove();
    const dashboard = document.createElement("circuitsetup-energy-analyzer-dashboard-graphs");
    dashboard.setConfig({
      appliance_power_entities: ["sensor.kitchen_power"],
      detail_path: "/circuitsetup-energy-analyzer-evidence?alert_id=alert-kitchen-energy",
      title: "Appliance energy",
    });
    dashboard.panel = panelConfig;
    dashboard.hass = hass;
    const main = document.createElement("main");
    const heading = document.createElement("h1");
    heading.textContent = "Energy dashboard";
    main.append(heading, dashboard);
    document.body.append(main);
    window.__panel = dashboard;
  });
  const dashboard = page.locator("circuitsetup-energy-analyzer-dashboard-graphs");
  return dashboard;
}

async function openDashboardCard(page, tagName, config, states = {}, hassConfig = {}) {
  await page.goto(HARNESS);
  await page.waitForFunction(() => window.__panelReady === true);
  await page.evaluate(({ tagName: tag, cardConfig, cardStates, nextHassConfig }) => {
    localStorage.removeItem("circuitsetup-energy-analyzer-dashboard-range");
    const hass = window.__panel._hass;
    const panelConfig = window.__panel._panel;
    Object.assign(hass.config, nextHassConfig);
    Object.assign(hass.states, cardStates);
    window.__panel.remove();
    const main = document.createElement("main");
    const heading = document.createElement("h1");
    heading.textContent = cardConfig.title || "Energy dashboard";
    heading.style.cssText = "position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0";
    main.append(heading);
    const card = document.createElement(tag);
    card.panel = panelConfig;
    card.setConfig(cardConfig);
    card.hass = hass;
    main.append(card);
    document.body.append(main);
    window.__dashboardCard = card;
    window.__dashboardHass = hass;
    window.__setDashboardState = (entityId, state) => {
      hass.states[entityId] = state;
      card.hass = hass;
    };
  }, {
    tagName,
    cardConfig: config,
    cardStates: states,
    nextHassConfig: hassConfig,
  });
  return page.locator(tagName);
}

async function openDashboardCards(page, specs, states = {}) {
  await page.goto(HARNESS);
  await page.waitForFunction(() => window.__panelReady === true);
  await page.evaluate(({ cardSpecs, cardStates }) => {
    localStorage.removeItem("circuitsetup-energy-analyzer-dashboard-range");
    const hass = window.__panel._hass;
    const panelConfig = window.__panel._panel;
    Object.assign(hass.states, cardStates);
    window.__panel.remove();
    const main = document.createElement("main");
    for (const spec of cardSpecs) {
      const card = document.createElement(spec.tagName);
      card.panel = panelConfig;
      card.setConfig(spec.config);
      card.hass = hass;
      main.append(card);
    }
    document.body.append(main);
    window.__dashboardCards = [...main.children];
  }, { cardSpecs: specs, cardStates: states });
}

async function toHaveNoViolations(page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
}

test("home energy card omits Active now and separates contribution", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-12T12:00:00.000Z") });
  await mockPanelApi(page, async ({ route, url }) => {
    if (url.pathname.includes("/history/period")) {
      await route.fulfill({
        json: [
          [
            { entity_id: "sensor.mains_power", state: "1000", last_changed: "2026-07-10T00:00:00.000Z" },
            { state: "0", last_changed: "2026-07-12T23:59:59.999Z" },
          ],
          [
            { entity_id: "sensor.mains_cost_today", state: "1.00", last_changed: "2026-07-10T00:00:00.000Z" },
            { state: "2.50", last_changed: "2026-07-12T12:00:00.000Z" },
          ],
          [
            { entity_id: "sensor.oven_power", state: "1", last_changed: "2026-07-10T00:00:00.000Z" },
            { state: "0", last_changed: "2026-07-12T23:59:59.999Z" },
          ],
          [
            { entity_id: "sensor.oven_cost", state: "1.00", last_changed: "2026-07-10T00:00:00.000Z" },
            { state: "2.50", last_changed: "2026-07-12T12:00:00.000Z" },
          ],
        ],
      });
      return true;
    }
    if (!url.pathname.endsWith("/appliance_insights")) return false;
    await route.fulfill({
      json: {
        status: "ok",
        items: ["fridge", "washer", "oven"].map((id, index) => ({
          entry_id: "entry-1",
          circuit_id: id,
          display_name: id,
          daily_totals: ["10", "11"].map((day) => ({
            date: `2026-07-${day}`,
            energy_kwh: index + 1,
            cost: (index + 1) * 0.1,
          })),
        })),
        whole_house: [{
          entry_id: "entry-1",
          circuit_id: "mains",
          daily_totals: ["10", "11"].map((day) => ({
            date: `2026-07-${day}`,
            energy_kwh: 24,
            cost: 1,
          })),
        }],
      },
    });
    return true;
  });
  const states = {
    "sensor.mains_power": { state: "1820", attributes: { unit_of_measurement: "W" } },
    "sensor.mains_energy_today": { state: "12.4", attributes: { unit_of_measurement: "kWh" } },
    "sensor.mains_cost_today": { state: "unavailable", attributes: {} },
    "sensor.mains_average_energy": { state: "11.8", attributes: { unit_of_measurement: "kWh" } },
    "sensor.mains_average_cost": { state: "2.16", attributes: { unit_of_measurement: "USD" } },
    "sensor.mains_known": { state: "1450", attributes: { unit_of_measurement: "W" } },
    "sensor.mains_unassigned": { state: "370", attributes: { unit_of_measurement: "W" } },
    "sensor.mains_coverage": { state: "79.7", attributes: { unit_of_measurement: "%" } },
    "sensor.fridge_activity": { state: "Running", attributes: { is_running: true } },
    "sensor.fridge_power": { state: "100", attributes: { unit_of_measurement: "W" } },
    "sensor.fridge_energy": { state: "1.4", attributes: { unit_of_measurement: "kWh" } },
    "sensor.fridge_cost": { state: "0.28", attributes: { unit_of_measurement: "USD" } },
    "sensor.fridge_health": { state: "Normal", attributes: {} },
    "sensor.washer_activity": { state: "Running", attributes: { is_running: true } },
    "sensor.washer_power": { state: "1200", attributes: { unit_of_measurement: "W" } },
    "sensor.washer_energy": { state: "2.2", attributes: { unit_of_measurement: "kWh" } },
    "sensor.washer_cost": { state: "0.5", attributes: { unit_of_measurement: "USD" } },
    "sensor.washer_health": { state: "Normal", attributes: {} },
    "sensor.oven_activity": { state: "Idle", attributes: { is_running: false } },
    "sensor.oven_power": { state: "0.1", attributes: { unit_of_measurement: "kW" } },
    "sensor.oven_energy": { state: "0.7", attributes: { unit_of_measurement: "kWh" } },
    "sensor.oven_cost": { state: "0.14", attributes: { unit_of_measurement: "USD" } },
    "sensor.oven_health": {
      state: "Ready",
      attributes: { electrical_summary: "Possible Imbalance" },
    },
  };
  const appliances = ["fridge", "washer", "oven"].map((id) => ({
    circuit_id: id,
    name: id[0].toUpperCase() + id.slice(1),
    detail_path: `/circuitsetup-energy-analyzer-evidence?appliance_detail=1&circuit_id=${id}`,
    activity_entity: `sensor.${id}_activity`,
    power_entities: [`sensor.${id}_power`],
    energy_today_entity: `sensor.${id}_energy`,
    cost_today_entity: `sensor.${id}_cost`,
    health_entity: `sensor.${id}_health`,
  }));
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-house-flow",
    {
      title: "Home energy summary",
      entry_id: "entry-1",
      api_path: "circuitsetup_energy_analyzer/appliance_insights",
      primary_mains: {
        power_entities: ["sensor.mains_power"],
        daily_energy_usage_entity: "sensor.mains_energy_today",
        cost_today_entity: "sensor.mains_cost_today",
        average_kwh_per_day_entity: "sensor.mains_average_energy",
        average_cost_per_day_entity: "sensor.mains_average_cost",
        monitored_power_entity: "sensor.mains_known",
        balance_power_entity: "sensor.mains_unassigned",
        monitored_coverage_entity: "sensor.mains_coverage",
      },
      appliances,
      labels: { unavailable: "Unavailable" },
    },
    states,
  );

  await expect(card).not.toContainText("Active now");
  await expect(card.locator("[data-appliance-id]")).toHaveCount(0);
  await expect(card.locator(".contribution")).toHaveCSS("margin-top", "12px");
  await expect(card.locator(".contribution h3")).toHaveText("Appliance Energy/Cost");
  await expect(card.locator(".contribution h3 + .controls")).toBeVisible();
  await expect(card.locator("[data-contribution-window]")).toHaveCount(0);
  await expect(card.locator(".flow-labels .swatch")).toHaveCount(3);
  const clearedTotals = await page.evaluate(() => {
    window.__apiCalls.length = 0;
    window.dispatchEvent(new CustomEvent("circuitsetup-dashboard-range-changed", {
      detail: {
        start: "2026-07-10T00:00:00.000Z",
        end: "2026-07-12T23:59:59.999Z",
        compare: false,
      },
    }));
    return {
      contributions: window.__dashboardCard._rollingContributionByCircuit,
      summary: window.__dashboardCard._rangeSummary,
    };
  });
  expect(clearedTotals).toEqual({ contributions: {}, summary: {} });
  await expect(card.locator(".metric").filter({ hasText: "Energy (Jul 10-12)" })).toContainText("60.4 kWh");
  await expect(card.locator(".metric").filter({ hasText: "Energy (Jul 10-12)" })).toContainText("Average: 11.8 kWh");
  await expect(card.locator(".metric").filter({ hasText: "Cost (Jul 10-12)" })).toContainText("Unavailable");
  await expect(card.locator(".metric").filter({ hasText: "Cost (Jul 10-12)" })).toContainText("Average: $2.16");
  await expect(card).not.toContainText("% more");
  await expect(card).not.toContainText("% less");
  await expect(card.locator(".bar-row").filter({ hasText: "Oven" })).toContainText("6.7 kWh");
  await card.locator('[data-contribution-mode="cost"]').click();
  await expect(card.locator(".bar-row").filter({ hasText: "Oven" })).toContainText("$0.74");
  const historyCalls = await page.evaluate(() => (
    window.__apiCalls.filter(({ apiPath }) => apiPath.includes("history/period/")).length
  ));
  const insightCalls = await page.evaluate(() => (
    window.__apiCalls.filter(({ apiPath }) => apiPath.endsWith("/appliance_insights")).length
  ));
  await page.evaluate(() => {
    window.__setDashboardState("sensor.fridge_energy", {
      state: "2.4",
      attributes: { unit_of_measurement: "kWh" },
    });
    window.__dashboardCard.hass = window.__dashboardHass;
  });
  await card.locator('[data-contribution-mode="energy"]').click();
  await expect(card.locator(".bar-row").filter({ hasText: "Fridge" })).toContainText("4.4 kWh");
  expect(await page.evaluate(() => (
    window.__apiCalls.filter(({ apiPath }) => apiPath.includes("history/period/")).length
  ))).toBe(0);
  expect(await page.evaluate(() => (
    window.__apiCalls.filter(({ apiPath }) => apiPath.endsWith("/appliance_insights")).length
  ))).toBe(insightCalls);
  expect(historyCalls).toBe(0);
  await toHaveNoViolations(page);
  await page.evaluate(() => {
    const root = document.documentElement.style;
    root.setProperty("--card-background-color", "#1f2937");
    root.setProperty("--secondary-background-color", "#374151");
    root.setProperty("--primary-text-color", "#f9fafb");
    root.setProperty("--secondary-text-color", "#d1d5db");
    root.setProperty("--divider-color", "#6b7280");
    root.setProperty("--warning-color", "#fbbf24");
  });
  await toHaveNoViolations(page);
});

test("home totals use retained completed days without Recorder history", async ({ page }) => {
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/appliance_insights")) return false;
    await route.fulfill({
      json: {
        status: "ok",
        items: [{
          entry_id: "entry-1",
          circuit_id: "current-only",
          display_name: "Current-only appliance",
          daily_totals: [
            { date: "2026-05-01", energy_kwh: 2, cost: 0.4 },
            { date: "2026-05-02", energy_kwh: 3, cost: 0.6 },
          ],
        }],
        whole_house: [{
          entry_id: "entry-1",
          circuit_id: "mains",
          daily_totals: [
            { date: "2026-05-01", energy_kwh: 8, cost: 1.6 },
            { date: "2026-05-02", energy_kwh: 10, cost: 2 },
          ],
        }],
      },
    });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-house-flow",
    {
      title: "Home energy summary",
      entry_id: "entry-1",
      api_path: "circuitsetup_energy_analyzer/appliance_insights",
      primary_mains: { circuit_id: "mains" },
      appliances: [{ circuit_id: "current-only", name: "Current-only appliance" }],
    },
  );

  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent("circuitsetup-dashboard-range-changed", {
      detail: {
        start: "2026-05-01T00:00:00.000Z",
        end: "2026-05-02T23:59:59.999Z",
        compare: false,
      },
    }));
  });

  await expect(card.locator(".metric").filter({ hasText: "Energy (May 1-2)" })).toContainText("18 kWh");
  await expect(card.locator(".metric").filter({ hasText: "Cost (May 1-2)" })).toContainText("$3.60");
  await expect(card.locator(".bar-row").filter({ hasText: "Current-only appliance" })).toContainText("5 kWh");
  expect(await page.evaluate(() => (
    window.__apiCalls.some(({ apiPath }) => apiPath.includes("history/period/2026-05"))
  ))).toBe(false);
});

test("home totals retry when the first midnight payload is stale", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-12T23:59:00.000Z") });
  let afterMidnight = false;
  let rolloverCalls = 0;
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/appliance_insights")) return false;
    const completedDayReady = afterMidnight && rolloverCalls++ > 0;
    await route.fulfill({
      json: {
        status: "ok",
        items: [{
          entry_id: "entry-1",
          circuit_id: "fridge",
          daily_totals: [
            { date: "2026-07-11", energy_kwh: 1, cost: 0.2 },
            ...(completedDayReady
              ? [{ date: "2026-07-12", energy_kwh: 2, cost: 0.5 }]
              : []),
          ],
        }],
        whole_house: [{
          entry_id: "entry-1",
          circuit_id: "mains",
          daily_totals: [
            { date: "2026-07-11", energy_kwh: 10, cost: 2 },
            ...(completedDayReady
              ? [{ date: "2026-07-12", energy_kwh: 4, cost: 1 }]
              : []),
          ],
        }],
      },
    });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-house-flow",
    {
      title: "Home energy summary",
      entry_id: "entry-1",
      api_path: "circuitsetup_energy_analyzer/appliance_insights",
      primary_mains: {
        circuit_id: "mains",
        daily_energy_usage_entity: "sensor.mains_energy_today",
        cost_today_entity: "sensor.mains_cost_today",
      },
      appliances: [{
        circuit_id: "fridge",
        name: "Fridge",
        energy_today_entity: "sensor.fridge_energy",
        cost_today_entity: "sensor.fridge_cost",
      }],
    },
    {
      "sensor.mains_energy_today": { state: "4", attributes: { unit_of_measurement: "kWh" } },
      "sensor.mains_cost_today": { state: "1", attributes: { unit_of_measurement: "USD" } },
      "sensor.fridge_energy": { state: "2", attributes: { unit_of_measurement: "kWh" } },
      "sensor.fridge_cost": { state: "0.5", attributes: { unit_of_measurement: "USD" } },
    },
  );
  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent("circuitsetup-dashboard-range-changed", {
      detail: {
        start: "2026-07-11T00:00:00.000Z",
        end: "2026-07-12T23:59:59.999Z",
        compare: false,
      },
    }));
  });
  await expect(card.locator(".metric").filter({ hasText: "Energy (Jul 11-12)" })).toContainText("14 kWh");
  await expect(card.locator(".bar-row").filter({ hasText: "Fridge" })).toContainText("3 kWh");
  const insightCalls = await page.evaluate(() => (
    window.__apiCalls.filter(({ apiPath }) => apiPath.endsWith("/appliance_insights")).length
  ));

  await page.clock.fastForward("02:00");
  afterMidnight = true;
  await page.evaluate(() => {
    window.__dashboardHass.states["sensor.mains_energy_today"].state = "0";
    window.__dashboardHass.states["sensor.mains_cost_today"].state = "0";
    window.__dashboardHass.states["sensor.fridge_energy"].state = "0";
    window.__dashboardHass.states["sensor.fridge_cost"].state = "0";
    window.__dashboardCard.hass = window.__dashboardHass;
  });

  await expect.poll(() => page.evaluate(() => (
    window.__apiCalls.filter(({ apiPath }) => apiPath.endsWith("/appliance_insights")).length
  ))).toBe(insightCalls + 1);
  await expect(card.locator(".metric").filter({ hasText: "Energy (Jul 11-12)" })).toContainText("10 kWh");
  await page.clock.fastForward(30_000);
  await expect.poll(() => page.evaluate(() => (
    window.__apiCalls.filter(({ apiPath }) => apiPath.endsWith("/appliance_insights")).length
  ))).toBe(insightCalls + 2);
  await expect(card.locator(".metric").filter({ hasText: "Energy (Jul 11-12)" })).toContainText("14 kWh");
  await expect(card.locator(".metric").filter({ hasText: "Cost (Jul 11-12)" })).toContainText("$3.00");
  await expect(card.locator(".bar-row").filter({ hasText: "Fridge" })).toContainText("3 kWh");
});

test("appliance grid filters live state and loads Activity Summary history", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-12T22:00:00.000Z") });
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.includes("/history/period")) return false;
    await route.fulfill({
      json: [[
        { entity_id: "sensor.fridge_activity", state: "Idle", last_changed: "2026-07-10T00:00:00.000Z" },
        { state: "Running", last_changed: "2026-07-10T04:00:00.000Z" },
        { state: "Idle", last_changed: "2026-07-10T05:00:00.000Z" },
        { state: "Running", last_changed: "2026-07-12T21:00:00.000Z" },
      ]],
    });
    return true;
  });
  const states = {
    "sensor.fridge_activity": {
      state: "Running",
      last_changed: "2026-07-12T21:00:00.000Z",
      attributes: { is_running: true },
    },
    "sensor.fridge_power": { state: "140", attributes: { unit_of_measurement: "W" } },
    "sensor.fridge_energy": { state: "1.4", attributes: { unit_of_measurement: "kWh" } },
    "sensor.fridge_cost": { state: "0.28", attributes: { unit_of_measurement: "USD" } },
    "sensor.fridge_health": { state: "Normal", attributes: {} },
    "sensor.oven_activity": { state: "Idle", attributes: { is_running: false } },
    "sensor.oven_power": { state: "0", attributes: { unit_of_measurement: "W" } },
    "sensor.oven_energy": { state: "3.1", attributes: { unit_of_measurement: "kWh" } },
    "sensor.oven_cost": { state: "0.7", attributes: { unit_of_measurement: "USD" } },
    "sensor.oven_health": {
      state: "Ready",
      attributes: { electrical_summary: "Possible Imbalance" },
    },
  };
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-appliance-grid",
    {
      title: "Appliances",
      appliances: ["fridge", "oven"].map((id) => ({
        circuit_id: id,
        name: id[0].toUpperCase() + id.slice(1),
        icon: id === "fridge" ? "mdi:fridge-outline" : "mdi:stove",
        area: id === "fridge" ? "Kitchen" : "Cooking",
        detail_path: `/circuitsetup-energy-analyzer-evidence?appliance_detail=1&circuit_id=${id}`,
        activity_entity: `sensor.${id}_activity`,
        power_entities: [`sensor.${id}_power`],
        energy_today_entity: `sensor.${id}_energy`,
        cost_today_entity: `sensor.${id}_cost`,
        health_entity: `sensor.${id}_health`,
      })),
      labels: { all: "All", running: "Running", run_timeline: "Run timeline" },
    },
    states,
  );

  const search = card.locator("[data-appliance-search]");
  await search.focus();
  await page.evaluate(() => {
    window.__setDashboardState("sensor.fridge_power", {
      state: "150",
      attributes: { unit_of_measurement: "W" },
    });
  });
  await expect(search).toBeFocused();
  await search.press("Tab");
  await expect(card.locator('[data-appliance-id="fridge"]')).toContainText("150 W");

  await search.pressSequentially("fridge");
  await expect(search).toHaveValue("fridge");
  await expect(search).toBeFocused();
  await expect(card.locator("[data-appliance-id]:visible")).toHaveCount(1);
  await page.evaluate(() => {
    window.__setDashboardState("sensor.fridge_power", {
      state: "150",
      attributes: { unit_of_measurement: "W" },
    });
  });
  await expect(search).toHaveValue("fridge");
  await expect(search).toBeFocused();
  await search.press("Tab");
  await expect(card.locator("[data-appliance-id]:visible")).toHaveCount(1);
  await expect(card.locator('[data-appliance-id="fridge"]')).toContainText("$0.28");
  await search.fill("");
  await search.press("Tab");
  await expect(card.getByRole("tab", { name: "Highest energy" })).toHaveCount(0);
  await expect(card.getByRole("tab", { name: "Highest cost" })).toHaveCount(0);
  await card.getByRole("tab", { name: "Needs attention", exact: true }).click();
  await expect(card.locator("[data-appliance-id]")).toHaveCount(1);
  await expect(card.locator('[data-appliance-id="oven"]')).toContainText(
    "Possible Imbalance",
  );
  await card.getByRole("tab", { name: "Running", exact: true }).click();
  await expect(card.locator("[data-appliance-id]")).toHaveCount(1);
  const timeline = card.locator("[data-timeline-selection]");
  await timeline.focus();
  await page.evaluate(() => {
    window.__setDashboardState("sensor.oven_power", {
      state: "25",
      attributes: { unit_of_measurement: "W" },
    });
  });
  await expect(timeline).toBeFocused();
  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent("circuitsetup-dashboard-range-changed", {
      detail: {
        start: "2026-07-10T00:00:00.000Z",
        end: "2026-07-12T23:59:59.999Z",
        compare: false,
      },
    }));
  });
  await timeline.selectOption("fridge");
  await expect.poll(() => page.evaluate(() => (
    window.__apiCalls.some(({ apiPath }) => (
      apiPath.includes("2026-07-10T00:00:00.000Z")
      && apiPath.includes("end_time=2026-07-12T23%3A59%3A59.999Z")
      && apiPath.includes("sensor.fridge_activity")
    ))
  ))).toBe(true);
  await expect(card.locator("[data-running-band]")).toHaveCount(2);
  const finalBandWidth = await card.locator("[data-running-band]").nth(1).evaluate(
    (band) => Number.parseFloat(band.style.width),
  );
  expect(finalBandWidth).toBeCloseTo(100 / 72, 2);
  await expect(card.locator("[data-timeline-tick]")).toHaveCount(5);
  await expect(card.locator("[data-timeline-tick]").first()).toHaveText("Jul 10");
  await expect(card.locator("[data-timeline-tick]").last()).toHaveText("Jul 12");
  await expect(card.locator(".timeline > h3 + .controls")).toBeVisible();
  await expect(card.locator('[data-appliance-id="fridge"] .appliance-heading ha-icon')).toHaveAttribute("icon", "mdi:fridge-outline");
  const timelineHistoryCalls = await page.evaluate(() => (
    window.__apiCalls.filter(({ apiPath }) => apiPath.includes("sensor.fridge_activity")).length
  ));
  await page.evaluate(() => {
    window.__setDashboardState("sensor.fridge_activity", {
      state: "Idle",
      last_changed: "2026-07-12T22:00:00.000Z",
      attributes: { is_running: false },
    });
  });
  await expect.poll(() => page.evaluate(() => (
    window.__apiCalls.filter(({ apiPath }) => apiPath.includes("sensor.fridge_activity")).length
  ))).toBe(timelineHistoryCalls + 1);
  await card.getByRole("tab", { name: "All", exact: true }).click();
  await card.locator('[data-appliance-id="fridge"]').click();
  await expect(page).toHaveURL(/appliance_detail=1&circuit_id=fridge/);
});

test("activity timeline caps long selections to the latest 31 days", async ({ page }) => {
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.includes("/history/period")) return false;
    await route.fulfill({
      json: [[
        { entity_id: "sensor.fridge_activity", state: "Running", last_changed: "2026-05-31T00:00:00.000Z" },
        { state: "Idle", last_changed: "2026-06-01T00:00:00.000Z" },
      ]],
    });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-appliance-grid",
    {
      title: "Appliances",
      appliances: [{
        circuit_id: "fridge",
        name: "Fridge",
        activity_entity: "sensor.fridge_activity",
      }],
    },
    {
      "sensor.fridge_activity": { state: "Running", attributes: {} },
    },
  );

  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent("circuitsetup-dashboard-range-changed", {
      detail: {
        start: "2026-01-01T00:00:00.000Z",
        end: "2026-06-30T23:59:59.999Z",
        compare: false,
      },
    }));
  });

  await expect.poll(() => page.evaluate(() => (
    window.__apiCalls.map(({ apiPath }) => apiPath)
      .find((apiPath) => apiPath.includes("end_time=2026-06-30")) || ""
  ))).toContain("history/period/2026-05-31T00:00:00.000Z");
  await expect(card.locator("[data-timeline-tick]").first()).toHaveText("May 31");
  await expect(card.locator("[data-timeline-tick]").last()).toHaveText("Jun 30");
});

test("energy and cost card follows the dashboard range and preserves cost source", async ({ page }) => {
  const dailyTotals = Array.from({ length: 10 }, (_, index) => ({
    date: `2026-07-${String(index + 1).padStart(2, "0")}`,
    energy_kwh: index + 1,
    cost: index === 9 ? null : (index + 1) * 0.2,
    cost_source: index < 5 ? "recorded" : index === 9 ? "unavailable" : "estimated",
  }));
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/appliance_insights")) return false;
    await route.fulfill({
      json: {
        status: "ok",
        items: [{
          entry_id: "entry-1",
          circuit_id: "fridge",
          appliance_key: "circuit:fridge",
          display_name: "Fridge",
          daily_totals: dailyTotals.slice(-2),
        }],
        whole_house: [{
          entry_id: "entry-1",
          circuit_id: "mains",
          display_name: "Whole home",
          daily_totals: dailyTotals,
        }],
      },
    });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-energy-cost",
    {
      title: "Energy and costs",
      entry_id: "entry-1",
      api_path: "circuitsetup_energy_analyzer/appliance_insights",
      primary_mains: { circuit_id: "mains" },
      labels: {
        seven_days: "7 days",
        thirty_days: "30 days",
        whole_house: "Whole house",
        completed_history: "Completed-day history",
        unavailable: "Unavailable",
      },
    },
    {},
  );

  await expect(card).not.toContainText("Today versus normal");
  await expect(card.locator(".metric")).toHaveCount(0);
  await expect(card).toContainText("Completed-day history");
  await page.evaluate(() => {
    window.__dashboardHass.config.time_zone = "Pacific/Auckland";
    window.__dashboardCard.hass = window.__dashboardHass;
    window.dispatchEvent(new CustomEvent("circuitsetup-dashboard-range-changed", {
      detail: {
        start: "2026-07-03T12:00:00.000Z",
        end: "2026-07-10T11:59:59.999Z",
        compare: false,
      },
    }));
  });
  await expect(card.locator("svg.chart").first()).toBeVisible();
  await expect(card.locator("[data-energy-bar]")).toHaveCount(7);
  await expect(card.locator("[data-history-days]")).toHaveCount(0);
  await expect(card.locator(".contribution")).toHaveCount(0);
  await card.locator('[data-cost-source="recorded"]').first().focus();
  await expect(card.locator(".chart-frame").first().locator("[data-chart-tooltip]")).toHaveAttribute("aria-hidden", "false");
  await expect(card.locator(".chart-frame").first().locator("[data-chart-tooltip]")).toContainText("$0.80");
  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent("circuitsetup-dashboard-range-changed", {
      detail: {
        start: "2026-06-30T12:00:00.000Z",
        end: "2026-07-10T11:59:59.999Z",
        compare: false,
      },
    }));
  });
  await expect(card.locator("[data-energy-bar]")).toHaveCount(10);
  await expect(card.locator('[data-cost-source="recorded"]')).toHaveCount(5);
  await expect(card.locator('[data-cost-source="estimated"]')).toHaveCount(4);
  await expect(card).toContainText("Unavailable");
  await expect(card).not.toContainText("Water flow context");
  await toHaveNoViolations(page);
});

test("water context graph combines paired appliance watts with one flow series", async ({ page }) => {
  const historyRequests = [];
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.includes("/history/period")) return false;
    historyRequests.push(url.searchParams.get("filter_entity_id"));
    const hoursAgo = (hours) => new Date(Date.now() - hours * 60 * 60 * 1000).toISOString();
    await route.fulfill({
      json: [
        [
          { entity_id: "sensor.washer_power", state: "0", last_changed: hoursAgo(24) },
          { state: "900", last_changed: hoursAgo(2) },
          { state: "0", last_changed: hoursAgo(0) },
        ],
        [
          { entity_id: "sensor.dishwasher_power", state: "0", last_changed: hoursAgo(24) },
          { state: "1200", last_changed: hoursAgo(4) },
          { state: "0", last_changed: hoursAgo(0) },
        ],
        [
          { entity_id: "sensor.laundry_flow", state: "0", last_changed: hoursAgo(24) },
          { state: "2.3", last_changed: hoursAgo(3) },
          { state: "0", last_changed: hoursAgo(0) },
        ],
      ],
    });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-context-graph",
    {
      title: "Water flow context",
      y_axis_label: "W",
      water_contexts: [
        {
          name: "Washer",
          correlation_entity: "sensor.washer_water_context",
          power_entities: ["sensor.washer_power"],
        },
        {
          name: "Dishwasher",
          correlation_entity: "sensor.dishwasher_water_context",
          power_entities: ["sensor.dishwasher_power"],
        },
      ],
    },
    {
      "sensor.washer_water_context": {
        state: "correlated",
        attributes: { flow_sensor_entities: ["sensor.laundry_flow"] },
      },
      "sensor.dishwasher_water_context": {
        state: "correlated",
        attributes: { flow_sensor_entities: ["sensor.laundry_flow"] },
      },
      "sensor.washer_power": {
        state: "0",
        attributes: { friendly_name: "Washer power", unit_of_measurement: "W" },
      },
      "sensor.dishwasher_power": {
        state: "0",
        attributes: { friendly_name: "Dishwasher power", unit_of_measurement: "W" },
      },
      "sensor.laundry_flow": {
        state: "0",
        attributes: { friendly_name: "Laundry flow meter", unit_of_measurement: "gal/min" },
      },
    },
  );

  await expect(card.locator("[data-context-hours]")).toHaveCount(0);
  await expect(card.locator("svg.chart")).toHaveAttribute("data-chart-right-axis", "gal/min");
  await expect(card.locator(".legend")).toContainText("Washer power");
  await expect(card.locator(".legend")).toContainText("Dishwasher power");
  await expect(card.locator(".legend-item").filter({ hasText: "Laundry flow meter" })).toHaveCount(1);
  const waterRequest = historyRequests.find((request) => request.includes("sensor.washer_power"));
  expect(waterRequest.split(",")).toEqual([
    "sensor.washer_power",
    "sensor.dishwasher_power",
    "sensor.laundry_flow",
  ]);
  await toHaveNoViolations(page);
  await page.evaluate(() => {
    window.__setDashboardState("sensor.washer_water_context", {
      state: "not_correlated",
      attributes: {},
    });
    window.__setDashboardState("sensor.dishwasher_water_context", {
      state: "not_correlated",
      attributes: {},
    });
  });
  await expect(card).toBeHidden();
});

test("dashboard date range is shared with graph history requests", async ({ page }) => {
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.includes("/history/period")) return false;
    await route.fulfill({
      json: [[
        {
          entity_id: "sensor.fridge_power",
          state: "120",
          last_changed: "2026-07-09T23:00:00.000Z",
        },
        { state: "160", last_changed: "2026-07-12T23:00:00.000Z" },
      ]],
    });
    return true;
  });
  await openDashboardCards(page, [
    {
      tagName: "circuitsetup-energy-analyzer-date-range",
      config: { labels: { compare: "Compare", download_data: "Download data" } },
    },
    {
      tagName: "circuitsetup-energy-analyzer-context-graph",
      config: {
        title: "All appliance power",
        entities: [{
          entity: "sensor.fridge_power",
          name: "Fridge",
          series_id: "circuit:fridge",
          axis: "left",
        }],
      },
    },
  ], {
    "sensor.fridge_power": {
      state: "160",
      attributes: { unit_of_measurement: "W" },
    },
  });
  await page.evaluate(() => {
    window.__wsCalls = [];
    window.__dashboardCards[1]._hass.callWS = async (request) => {
      window.__wsCalls.push(request);
      return {
        "sensor.fridge_power": [
          { start: Date.parse("2026-07-10T00:00:00.000Z"), mean: 140 },
          { start: Date.parse("2026-07-12T23:00:00.000Z"), mean: 160 },
        ],
      };
    };
  });
  const selector = page.locator("circuitsetup-energy-analyzer-date-range");
  await selector.locator("ha-date-range-picker").evaluate((picker) => {
    picker.dispatchEvent(new CustomEvent("value-changed", {
      bubbles: true,
      composed: true,
      detail: {
        value: {
          startDate: new Date("2026-07-10T00:00:00.000Z"),
          endDate: new Date("2026-07-12T23:59:59.999Z"),
        },
      },
    }));
  });

  await expect.poll(() => page.evaluate(() => window.__wsCalls.length)).toBe(1);
  expect(await page.evaluate(() => window.__wsCalls[0])).toEqual({
    type: "recorder/statistics_during_period",
    start_time: "2026-07-10T00:00:00.000Z",
    end_time: "2026-07-12T23:59:59.999Z",
    statistic_ids: ["sensor.fridge_power"],
    period: "hour",
    types: ["mean"],
  });
  await expect(page.locator(`[data-chart-time="${Date.parse("2026-07-10T00:00:00.000Z")}"]`)).toHaveCount(1);
  await expect(page.locator(`[data-chart-time="${Date.parse("2026-07-09T23:00:00.000Z")}"]`)).toHaveCount(0);
  await expect(selector).toContainText("Jul 10-12");
  await selector.locator("[data-range-previous]").click();
  await expect.poll(() => page.evaluate(() => (
    JSON.parse(localStorage.getItem("circuitsetup-energy-analyzer-dashboard-range")).start
  ))).toBe("2026-07-07T00:00:00.000Z");
  await selector.locator("[data-range-next]").click();
  await expect.poll(() => page.evaluate(() => (
    JSON.parse(localStorage.getItem("circuitsetup-energy-analyzer-dashboard-range")).start
  ))).toBe("2026-07-10T00:00:00.000Z");
  await selector.locator("[data-range-now]").click();
  const nowRange = await page.evaluate(() => (
    JSON.parse(localStorage.getItem("circuitsetup-energy-analyzer-dashboard-range"))
  ));
  expect(Date.parse(nowRange.end) - Date.parse(nowRange.start) + 1).toBe(3 * 24 * 60 * 60 * 1000);
  expect(Date.parse(nowRange.end)).toBeGreaterThan(Date.now());
  expect(Date.parse(nowRange.end)).toBeLessThan(Date.now() + 24 * 60 * 60 * 1000);
});

test("dashboard graph combines dual-phase appliance power into one series", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-24T03:00:00.000Z") });
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.includes("/history/period")) return false;
    const tail = decodeURIComponent(url.pathname).includes("2026-07-24T01:59:59.000Z");
    await route.fulfill({
      json: tail ? [
        [
          {
            entity_id: "sensor.dryer_l1_power",
            state: "0.5",
            last_changed: "2026-07-24T02:00:00.000Z",
          },
          { state: "0.6", last_changed: "2026-07-24T02:30:00.000Z" },
        ],
        [{
          entity_id: "sensor.dryer_l2_power",
          state: "800",
          last_changed: "2026-07-24T02:15:00.000Z",
        }],
      ] : [
        [
          {
            entity_id: "sensor.dryer_l1_power",
            state: "0.4",
            last_changed: "2026-07-24T00:00:00.000Z",
          },
          { state: "unavailable", last_changed: "2026-07-24T01:00:00.000Z" },
          { state: "0.5", last_changed: "2026-07-24T02:00:00.000Z" },
        ],
        [
          {
            entity_id: "sensor.dryer_l2_power",
            state: "600",
            last_changed: "2026-07-24T00:30:00.000Z",
          },
          { state: "700", last_changed: "2026-07-24T01:30:00.000Z" },
        ],
      ],
    });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-context-graph",
    {
      title: "All appliance power",
      y_axis_label: "W",
      entities: [
        {
          entity: "sensor.dryer_l1_power",
          name: "Dryer",
          series_id: "circuit:dryer",
          axis: "left",
        },
        {
          entity: "sensor.dryer_l2_power",
          name: "Dryer",
          series_id: "circuit:dryer",
          axis: "left",
        },
      ],
    },
    {
      "sensor.dryer_l1_power": {
        state: "0.5",
        attributes: { unit_of_measurement: "kW" },
      },
      "sensor.dryer_l2_power": {
        state: "700",
        attributes: { unit_of_measurement: "W" },
      },
    },
  );

  await expect(card.locator(".legend-item").filter({ hasText: "Dryer" })).toHaveCount(1);
  await expect(card.locator(`[data-chart-time="${Date.parse("2026-07-24T01:00:00.000Z")}"]`)).toHaveAttribute("data-chart-value", "600");
  await expect(card.locator('[data-chart-name="Dryer"][data-chart-value="1,200"]')).toHaveCount(1);
  const historyCalls = await page.evaluate(() => (
    window.__apiCalls.filter(({ apiPath }) => apiPath.includes("history/period/")).length
  ));
  await page.clock.fastForward("01:01");
  await page.evaluate(() => {
    window.__dashboardCard.hass = window.__dashboardHass;
  });
  await expect.poll(() => page.evaluate(() => (
    window.__apiCalls.map(({ apiPath }) => apiPath)
      .find((apiPath) => apiPath.includes("2026-07-24T01:59:59.000Z")) || ""
  ))).toContain("2026-07-24T01:59:59.000Z");
  expect(await page.evaluate(() => (
    window.__apiCalls.filter(({ apiPath }) => apiPath.includes("history/period/")).length
  ))).toBe(historyCalls + 1);
  await expect(card.locator(`[data-chart-time="${Date.parse("2026-07-24T02:00:00.000Z")}"]`)).toHaveCount(1);
  await expect(card.locator('[data-chart-name="Dryer"][data-chart-value="1,400"]')).toHaveCount(1);
});

test("dashboard graphs use Recorder statistics for long ranges", async ({ page }) => {
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.includes("/history/period")) return false;
    await route.fulfill({ json: [] });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-context-graph",
    {
      title: "All appliance power",
      entities: [{
        entity: "sensor.fridge_power",
        name: "Fridge",
        series_id: "circuit:fridge",
        axis: "left",
      }],
    },
    {
      "sensor.fridge_power": {
        state: "160",
        attributes: { unit_of_measurement: "W" },
      },
    },
  );
  await page.evaluate(() => {
    window.__wsCalls = [];
    window.__dashboardHass.callWS = async (request) => {
      window.__wsCalls.push(request);
      return {
        "sensor.fridge_power": [
          { start: Date.parse("2026-01-03T00:00:00.000Z"), mean: null },
          { start: Date.parse("2026-01-02T00:00:00.000Z"), mean: 0 },
          { start: Date.parse("2026-01-01T00:00:00.000Z"), mean: 100 },
          { start: Date.parse("2026-06-30T00:00:00.000Z"), mean: 140 },
        ],
      };
    };
    window.dispatchEvent(new CustomEvent("circuitsetup-dashboard-range-changed", {
      detail: {
        start: "2026-01-01T00:00:00.000Z",
        end: "2026-06-30T23:59:59.999Z",
        compare: false,
      },
    }));
  });

  await expect.poll(() => page.evaluate(() => window.__wsCalls.length)).toBe(1);
  expect(await page.evaluate(() => window.__wsCalls[0])).toEqual({
    type: "recorder/statistics_during_period",
    start_time: "2026-01-01T00:00:00.000Z",
    end_time: "2026-06-30T23:59:59.999Z",
    statistic_ids: ["sensor.fridge_power"],
    period: "day",
    types: ["mean"],
  });
  expect(await page.evaluate(() => (
    window.__apiCalls.some(({ apiPath }) => apiPath.includes("history/period/2026-01"))
  ))).toBe(false);
  await expect(card.locator(".legend")).toContainText("Fridge");
  await expect(card.locator(`[data-chart-time="${Date.parse("2026-01-02T00:00:00.000Z")}"][data-chart-value="0"]`)).toHaveCount(1);
  await expect(card.locator(`[data-chart-time="${Date.parse("2026-01-03T00:00:00.000Z")}"]`)).toHaveCount(0);

  await page.evaluate(() => {
    window.__apiCalls.length = 0;
    window.__wsCalls.length = 0;
    window.__dashboardHass.config.time_zone = "America/New_York";
    window.dispatchEvent(new CustomEvent("circuitsetup-dashboard-range-changed", {
      detail: {
        start: "2026-10-10T04:00:00.000Z",
        end: "2026-11-10T04:59:59.999Z",
        compare: false,
      },
    }));
  });
  await expect.poll(() => page.evaluate(() => window.__wsCalls.length)).toBe(1);
  expect(await page.evaluate(() => window.__wsCalls[0])).toEqual({
    type: "recorder/statistics_during_period",
    start_time: "2026-10-10T04:00:00.000Z",
    end_time: "2026-11-10T04:59:59.999Z",
    statistic_ids: ["sensor.fridge_power"],
    period: "hour",
    types: ["mean"],
  });
  expect(await page.evaluate(() => (
    window.__apiCalls.some(({ apiPath }) => apiPath.includes("history/period/2026-10-10"))
  ))).toBe(false);
});

test("multi-day graph refresh keeps Recorder statistics granularity", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-24T03:00:00.000Z") });
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.includes("/history/period")) return false;
    await route.fulfill({
      json: [[{
        entity_id: "sensor.fridge_power",
        state: "120",
        last_changed: "2026-07-24T02:00:00.000Z",
      }]],
    });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-context-graph",
    {
      title: "All appliance power",
      entities: [{
        entity: "sensor.fridge_power",
        name: "Fridge",
        axis: "left",
      }],
    },
    {
      "sensor.fridge_power": {
        state: "120",
        attributes: { unit_of_measurement: "W" },
      },
    },
  );
  await expect(card.locator("svg.chart")).toBeVisible();
  await page.evaluate(() => {
    window.__apiCalls.length = 0;
    window.__wsCalls = [];
    window.__dashboardHass.callWS = async (request) => {
      window.__wsCalls.push(request);
      return {
        "sensor.fridge_power": window.__wsCalls.length === 1
          ? [
            { start: Date.parse("2026-07-22T00:00:00.000Z"), mean: 80 },
            { start: Date.parse("2026-07-24T02:00:00.000Z"), mean: 120 },
          ]
          : [
            { start: Date.parse("2026-07-24T02:00:00.000Z"), mean: 120 },
            { start: Date.parse("2026-07-24T02:30:00.000Z"), mean: 140 },
          ],
      };
    };
    window.dispatchEvent(new CustomEvent("circuitsetup-dashboard-range-changed", {
      detail: {
        start: "2026-07-22T00:00:00.000Z",
        end: "2026-07-24T23:59:59.999Z",
        compare: false,
      },
    }));
  });
  await expect.poll(() => page.evaluate(() => window.__wsCalls.length)).toBe(1);

  await page.clock.fastForward("01:01");
  await page.evaluate(() => {
    window.__dashboardCard.hass = window.__dashboardHass;
  });

  await expect.poll(() => page.evaluate(() => window.__wsCalls.length)).toBe(2);
  expect(await page.evaluate(() => window.__wsCalls[1])).toEqual({
    type: "recorder/statistics_during_period",
    start_time: "2026-07-24T01:59:59.000Z",
    end_time: "2026-07-24T23:59:59.999Z",
    statistic_ids: ["sensor.fridge_power"],
    period: "hour",
    types: ["mean"],
  });
  expect(await page.evaluate(() => (
    window.__apiCalls.some(({ apiPath }) => apiPath.includes("history/period/"))
  ))).toBe(false);
});

test("multi-day graphs fall back only for missing statistic ids", async ({ page }) => {
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.includes("/history/period")) return false;
    const ids = url.searchParams.get("filter_entity_id");
    await route.fulfill({
      json: ids === "sensor.legacy_power" ? [[
        {
          entity_id: "sensor.legacy_power",
          state: "40",
          last_changed: "2026-07-10T00:00:00.000Z",
        },
        { state: "60", last_changed: "2026-07-12T23:00:00.000Z" },
      ]] : [],
    });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-context-graph",
    {
      title: "Mixed statistics support",
      entities: [
        { entity: "sensor.fridge_power", name: "Fridge", axis: "left" },
        { entity: "sensor.legacy_power", name: "Legacy", axis: "left" },
      ],
    },
    {
      "sensor.fridge_power": {
        state: "120",
        attributes: { unit_of_measurement: "W" },
      },
      "sensor.legacy_power": {
        state: "60",
        attributes: { unit_of_measurement: "W" },
      },
    },
  );
  await page.evaluate(() => {
    window.__apiCalls.length = 0;
    window.__wsCalls = [];
    window.__dashboardHass.callWS = async (request) => {
      window.__wsCalls.push(request);
      return {
        "sensor.fridge_power": [
          { start: Date.parse("2026-07-10T00:00:00.000Z"), mean: 100 },
          { start: Date.parse("2026-07-12T23:00:00.000Z"), mean: 120 },
        ],
      };
    };
    window.dispatchEvent(new CustomEvent("circuitsetup-dashboard-range-changed", {
      detail: {
        start: "2026-07-10T00:00:00.000Z",
        end: "2026-07-12T23:59:59.999Z",
        compare: false,
      },
    }));
  });

  await expect.poll(() => page.evaluate(() => (
    window.__apiCalls.map(({ apiPath }) => apiPath)
      .find((apiPath) => apiPath.includes("filter_entity_id=sensor.legacy_power")) || ""
  ))).toContain("history/period/2026-07-10T00:00:00.000Z");
  expect(await page.evaluate(() => (
    window.__apiCalls.some(({ apiPath }) => (
      apiPath.includes("filter_entity_id=sensor.fridge_power")
    ))
  ))).toBe(false);
  await expect(card.locator(".legend")).toContainText("Fridge");
  await expect(card.locator(".legend")).toContainText("Legacy");
});

test("state updates do not duplicate a pending graph history load", async ({ page }) => {
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.includes("/history/period")) return false;
    await route.fulfill({
      json: [[{
        entity_id: "sensor.fridge_power",
        state: "120",
        last_changed: new Date().toISOString(),
      }]],
    });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-context-graph",
    {
      title: "All appliance power",
      entities: [{
        entity: "sensor.fridge_power",
        name: "Fridge",
        axis: "left",
      }],
    },
    {
      "sensor.fridge_power": {
        state: "120",
        attributes: { unit_of_measurement: "W" },
      },
    },
  );
  await expect(card.locator("svg.chart")).toBeVisible();
  await page.evaluate(() => {
    window.__pendingHistoryCalls = 0;
    window.__dashboardHass.callApi = async () => {
      window.__pendingHistoryCalls += 1;
      return new Promise((resolve) => {
        window.__resolvePendingHistory = resolve;
      });
    };
    window.__dashboardCard._historyKey = "";
    window.__dashboardCard._historyLoadedAt = 0;
    window.__dashboardCard._render();
  });
  await expect.poll(() => page.evaluate(() => window.__pendingHistoryCalls)).toBe(1);

  await page.evaluate(() => {
    window.__dashboardCard.hass = window.__dashboardHass;
  });
  await page.waitForTimeout(50);
  expect(await page.evaluate(() => window.__pendingHistoryCalls)).toBe(1);
  await page.evaluate(() => {
    window.__resolvePendingHistory([[
      {
        entity_id: "sensor.fridge_power",
        state: "120",
        last_changed: new Date().toISOString(),
      },
    ]]);
  });
});

test("dashboard comparison overlays previous data and downloads CSV", async ({ page }) => {
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.includes("/history/period")) return false;
    const start = decodeURIComponent(url.pathname.split("/history/period/")[1]);
    const previous = start.startsWith("2026-07-07");
    await route.fulfill({
      json: [[
        {
          entity_id: "sensor.fridge_power",
          state: previous ? "80" : "120",
          last_changed: previous
            ? "2026-07-07T00:00:00.000Z"
            : "2026-07-10T00:00:00.000Z",
        },
        {
          state: previous ? "100" : "160",
          last_changed: previous
            ? "2026-07-09T23:00:00.000Z"
            : "2026-07-12T23:00:00.000Z",
        },
      ], [
        {
          entity_id: "sensor.freezer_power",
          state: previous ? "180" : "220",
          last_changed: previous
            ? "2026-07-07T00:00:00.000Z"
            : "2026-07-10T00:00:00.000Z",
        },
        {
          state: previous ? "200" : "260",
          last_changed: previous
            ? "2026-07-09T23:00:00.000Z"
            : "2026-07-12T23:00:00.000Z",
        },
      ]],
    });
    return true;
  });
  await openDashboardCards(page, [
    {
      tagName: "circuitsetup-energy-analyzer-date-range",
      config: { labels: { compare: "Compare", download_data: "Download data" } },
    },
    {
      tagName: "circuitsetup-energy-analyzer-context-graph",
      config: {
        title: "All appliance power",
        entities: [{
          entity: "sensor.fridge_power",
          name: "Fridge",
          series_id: "circuit:fridge",
          axis: "left",
        }, {
          entity: "sensor.freezer_power",
          name: "Fridge",
          series_id: "circuit:freezer",
          axis: "left",
        }],
      },
    },
  ], {
    "sensor.fridge_power": {
      state: "160",
      attributes: { unit_of_measurement: "W" },
    },
    "sensor.freezer_power": {
      state: "260",
      attributes: { unit_of_measurement: "W" },
    },
  });
  await page.evaluate(() => {
    window.__dashboardCards[1]._hass.callWS = async (request) => {
      const previous = request.start_time.startsWith("2026-07-07");
      const start = previous ? "2026-07-07T00:00:00.000Z" : "2026-07-10T00:00:00.000Z";
      const end = previous ? "2026-07-09T23:00:00.000Z" : "2026-07-12T23:00:00.000Z";
      return {
        "sensor.fridge_power": [
          { start: Date.parse(start), mean: previous ? 80 : 120 },
          { start: Date.parse(end), mean: previous ? 100 : 160 },
        ],
        "sensor.freezer_power": [
          { start: Date.parse(start), mean: previous ? 180 : 220 },
          { start: Date.parse(end), mean: previous ? 200 : 260 },
        ],
      };
    };
  });
  const selector = page.locator("circuitsetup-energy-analyzer-date-range");
  await selector.locator("ha-date-range-picker").evaluate((picker) => {
    picker.dispatchEvent(new CustomEvent("value-changed", {
      bubbles: true,
      composed: true,
      detail: {
        value: {
          startDate: new Date("2026-07-10T00:00:00.000Z"),
          endDate: new Date("2026-07-12T23:59:59.999Z"),
        },
      },
    }));
  });
  await selector.locator("[data-range-compare]").click();
  const graph = page.locator("circuitsetup-energy-analyzer-context-graph");

  await expect(graph.locator(".legend")).toContainText("Fridge (previous)");
  await expect(graph.locator('polyline[stroke-dasharray="6 4"]')).toHaveCount(2);
  const downloadPromise = page.waitForEvent("download");
  await selector.locator("[data-range-download]").click();
  const download = await downloadPromise;
  const csv = await download.createReadStream().then(async (stream) => {
    const chunks = [];
    for await (const chunk of stream) chunks.push(chunk);
    return Buffer.concat(chunks).toString("utf8");
  });
  expect(csv).toContain("Fridge");
  expect(csv).toContain("Fridge (2)");
  expect(csv).toContain("Fridge (previous)");
  expect(csv).toContain("Fridge (previous) (2)");
  expect(csv).toContain("2026-07-07T00:00:00.000Z");
});

test("dashboard date navigation uses calendar days across DST", async ({ page }) => {
  await mockPanelApi(page);
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-date-range",
    {},
    {},
  );
  await page.evaluate(() => {
    window.__dashboardHass.config.time_zone = "America/New_York";
    window.__dashboardCard.hass = window.__dashboardHass;
    window.dispatchEvent(new CustomEvent("circuitsetup-dashboard-range-changed", {
      detail: {
        start: "2026-03-08T05:00:00.000Z",
        end: "2026-03-09T03:59:59.999Z",
        compare: true,
      },
    }));
  });
  await card.locator("[data-range-previous]").click();
  const previous = await page.evaluate(() => (
    JSON.parse(localStorage.getItem("circuitsetup-energy-analyzer-dashboard-range"))
  ));

  expect(previous).toEqual({
    start: "2026-03-07T05:00:00.000Z",
    end: "2026-03-08T04:59:59.999Z",
    compare: true,
  });
});

test("dashboard initializes today in the Home Assistant timezone", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-24T20:00:00.000Z") });
  await mockPanelApi(page);
  await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-date-range",
    {},
    {},
    { time_zone: "Pacific/Auckland" },
  );

  const range = await page.evaluate(() => (
    JSON.parse(localStorage.getItem("circuitsetup-energy-analyzer-dashboard-range"))
  ));
  expect(range).toEqual({
    start: "2026-07-24T12:00:00.000Z",
    end: "2026-07-25T11:59:59.999Z",
    compare: false,
  });
});

test("HVAC context graph overlays outdoor temperature on a selectable right axis", async ({ page }) => {
  let historyRequestCount = 0;
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.includes("/history/period")) return false;
    historyRequestCount += 1;
    const requestNumber = historyRequestCount;
    if (requestNumber === 1) {
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    const hoursAgo = (hours) => new Date(Date.now() - hours * 60 * 60 * 1000).toISOString();
    const peakPower = requestNumber === 1 ? "2.3" : "9.9";
    await route.fulfill({
      json: [
        [
          { entity_id: "sensor.hvac_power", state: "0", last_changed: hoursAgo(24) },
          { state: peakPower, last_changed: hoursAgo(4) },
          { state: "0.8", last_changed: hoursAgo(0) },
        ],
        [
          { entity_id: "sensor.aux_heat_power", state: "0", last_changed: hoursAgo(24) },
          { state: "1000", last_changed: hoursAgo(4) },
          { state: "500", last_changed: hoursAgo(0) },
        ],
        [
          { entity_id: "sensor.outdoor_temperature", state: "78", last_changed: hoursAgo(24) },
          { state: "91", last_changed: hoursAgo(4) },
          { state: "84", last_changed: hoursAgo(0) },
        ],
      ],
    });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-context-graph",
    {
      title: "HVAC activity and outdoor temperature",
      entities: [
        { entity: "sensor.hvac_power", name: "HVAC power", axis: "left" },
        { entity: "sensor.aux_heat_power", name: "Aux heat power", axis: "left" },
        { entity: "sensor.outdoor_temperature", name: "Outdoor temperature", axis: "right" },
      ],
    },
    {
      "sensor.hvac_power": { state: "0.8", attributes: { unit_of_measurement: "kW" } },
      "sensor.aux_heat_power": { state: "500", attributes: { unit_of_measurement: "W" } },
      "sensor.outdoor_temperature": { state: "84", attributes: { unit_of_measurement: "°F" } },
    },
  );

  await expect(card.locator("h2")).toHaveCSS("font-size", "24px");
  await expect(card.locator("h2")).toHaveCSS("font-weight", "400");
  await expect(card.locator(".dashboard-card")).toHaveCSS("font-size", "14px");
  await expect(card.locator("[data-context-hours]")).toHaveCount(0);
  await expect(card.locator(".legend-marker")).toHaveCount(3);
  await expect(card.locator("[data-chart-point]").first()).toHaveCSS("fill", "rgb(72, 143, 194)");
  const chart = card.locator("svg.chart");
  const fullSpan = await chart.evaluate((element) => (
    Number(element.dataset.chartEnd) - Number(element.dataset.chartStart)
  ));
  const chartBox = await chart.boundingBox();
  await chart.dblclick({ position: { x: chartBox.width / 2, y: chartBox.height / 2 } });
  await expect.poll(() => chart.evaluate((element) => (
    Number(element.dataset.chartEnd) - Number(element.dataset.chartStart)
  ))).toBeLessThan(fullSpan * 0.6);
  await expect(card.locator("[data-chart-reset]")).toBeVisible();
  await card.locator("[data-chart-reset]").click();
  await expect.poll(() => chart.evaluate((element) => (
    Number(element.dataset.chartEnd) - Number(element.dataset.chartStart)
  ))).toBe(fullSpan);
  await expect(card.locator("[data-chart-reset]")).toHaveCount(0);
  await page.evaluate(() => {
    window.__dashboardCard._hass.callWS = async () => ({
      "sensor.hvac_power": [
        { start: Date.now() - 24 * 60 * 60 * 1000, mean: 0 },
        { start: Date.now() - 4 * 60 * 60 * 1000, mean: 9.9 },
        { start: Date.now(), mean: 0.8 },
      ],
      "sensor.aux_heat_power": [
        { start: Date.now() - 24 * 60 * 60 * 1000, mean: 0 },
        { start: Date.now() - 4 * 60 * 60 * 1000, mean: 1000 },
        { start: Date.now(), mean: 500 },
      ],
      "sensor.outdoor_temperature": [
        { start: Date.now() - 24 * 60 * 60 * 1000, mean: 78 },
        { start: Date.now() - 4 * 60 * 60 * 1000, mean: 91 },
        { start: Date.now(), mean: 84 },
      ],
    });
    const end = new Date();
    const start = new Date(end.getTime() - 30 * 24 * 60 * 60 * 1000);
    window.dispatchEvent(new CustomEvent("circuitsetup-dashboard-range-changed", {
      detail: { start: start.toISOString(), end: end.toISOString(), compare: false },
    }));
  });
  await expect(card.locator("svg.chart")).toHaveAttribute("data-chart-right-axis", "°F");
  await expect(card.locator(".axis-label").filter({ hasText: "kW" })).toHaveCount(1);
  await expect(card.locator('[data-chart-name="Aux heat power"][data-chart-value="1"]')).toHaveAttribute("data-chart-unit", "kW");
  await expect(card.locator("svg.chart")).toHaveAttribute("aria-label", /9.9/);
  await expect(card.locator(".legend")).toContainText("HVAC power");
  await expect(card.locator(".legend")).toContainText("Outdoor temperature");
  await page.waitForTimeout(300);
  await expect(card.locator("svg.chart")).toHaveAttribute("aria-label", /9.9/);
  await toHaveNoViolations(page);
});

test("dashboard summary cards use the shared header style", async ({ page }) => {
  await mockPanelApi(page);
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-summary",
    {
      title: "Billing Cycle",
      entities: [{ entity: "sensor.billing_cost", name: "Cost so far" }],
    },
    {
      "sensor.billing_cost": { state: "42.10", attributes: { unit_of_measurement: "USD" } },
    },
  );

  await expect(card.locator("h2")).toHaveCSS("font-size", "24px");
  await expect(card.locator(".summary-row")).toContainText("Cost so far");
  await expect(card.locator(".summary-row")).toContainText("$42.10");
  await toHaveNoViolations(page);
});

test("analyzer detail links render as a tight vertical list", async ({ page }) => {
  await mockPanelApi(page);
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-summary",
    {
      title: "Detail links",
      links: [
        { name: "Fridge details", path: "/fridge" },
        { name: "Washer details", path: "/washer" },
      ],
    },
  );

  await expect(card.locator(".summary-list")).toHaveCSS("gap", "0px");
  await expect(card.locator(".summary-link")).toHaveCount(2);
  const links = await card.locator(".summary-link").evaluateAll((rows) => (
    rows.map((row) => row.getBoundingClientRect().toJSON())
  ));
  expect(links[1].top).toBe(links[0].bottom);
});

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

test("Appliance Detail omits session timeline and page-level controls", async ({ page }) => {
  await mockPanelApi(page);
  const panel = await openPanel(page, "?appliance_detail=1&circuit_id=kitchen");
  await expect(panel.getByRole("heading", { name: "Today vs Normal" })).toBeVisible();
  await expect(panel.getByText("Session Timeline")).toHaveCount(0);
  await expect(panel.locator(".session-strip")).toHaveCount(0);
  await expect(panel.getByText("Appliance Notifications")).toHaveCount(0);
  await expect(panel.locator("[data-appliance-notifications]")).toHaveCount(0);
  await expect(panel.getByText("Expected Schedule")).toHaveCount(0);
  await expect(panel.locator("[data-expected-schedule]")).toHaveCount(0);
  await expect(panel.locator("[data-appliance-detail-action]")).toHaveCount(0);
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

test("matched alert graph ends at evidence and keeps comparison compact", async ({ page }) => {
  await mockPanelApi(page);
  const panel = await openPanel(page, "?alert_id=alert-kitchen-energy");
  const chart = panel.locator("svg.chart");
  await expect(chart).toBeVisible();
  await expect(chart).toHaveAttribute("aria-label", /7:30PM/);

  const layout = await panel.locator(".comparison-scale").evaluate((scale) => {
    const track = scale.querySelector(".comparison-track").getBoundingClientRect();
    const observed = scale.querySelector(".comparison-marker.observed strong").getBoundingClientRect();
    const thresholdLabel = scale.querySelector(".comparison-marker.threshold span").getBoundingClientRect();
    const observedLabel = scale.querySelector(".comparison-marker.observed span").getBoundingClientRect();
    const thresholdValue = scale.querySelector(".comparison-marker.threshold strong").getBoundingClientRect();
    return {
      height: scale.getBoundingClientRect().height,
      observedGap: observed.top - track.bottom,
      markersOverlap: (
        thresholdLabel.right > observedLabel.left
        || thresholdValue.right > observed.left
      ),
    };
  });
  expect(layout.height).toBeLessThanOrEqual(100);
  expect(layout.observedGap).toBeLessThanOrEqual(35);
  expect(layout.markersOverlap).toBe(false);
});

test("chart mouseover shows a clamped Home Assistant-style tooltip", async ({ page }) => {
  await mockPanelApi(page);
  const panel = await openPanel(page, "?alert_id=alert-kitchen-energy");
  const chart = panel.locator("svg.chart");
  const tooltip = panel.locator("[data-chart-tooltip]");

  await panel.locator("[data-chart-point]").last().hover({ force: true });
  await expect(tooltip).toBeVisible();
  await expect(tooltip).toContainText("Kitchen Power");
  await expect(tooltip).toContainText("610 W");
  await expect(panel.locator('[data-chart-point][data-selected="true"]')).toHaveCount(1);
  await expect(panel.locator('[data-chart-crosshair][data-visible="true"]')).toHaveCount(1);

  const bounds = await panel.locator("[data-chart-frame]").evaluate((frame) => {
    const frameRect = frame.getBoundingClientRect();
    const tooltipRect = frame.querySelector("[data-chart-tooltip]").getBoundingClientRect();
    return {
      left: tooltipRect.left - frameRect.left,
      right: frameRect.right - tooltipRect.right,
      top: tooltipRect.top - frameRect.top,
      bottom: frameRect.bottom - tooltipRect.bottom,
    };
  });
  expect(bounds.left).toBeGreaterThanOrEqual(0);
  expect(bounds.right).toBeGreaterThanOrEqual(0);
  expect(bounds.top).toBeGreaterThanOrEqual(0);
  expect(bounds.bottom).toBeGreaterThanOrEqual(0);

  await page.mouse.move(0, 0);
  await expect(tooltip).toBeHidden();
  await expect(chart.locator('[data-chart-point][data-selected="true"]')).toHaveCount(0);
});

test("matched low-side alert keeps comparison markers apart", async ({ page }) => {
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/alert_evidence")) return false;
    await route.fulfill({
      json: {
        ...evidence,
        alert: {
          ...evidence.alert,
          observed_value: 1.6,
          expected_value: 2.0,
          baseline_value: 2.0,
          threshold: 1.8,
        },
      },
    });
    return true;
  });
  const panel = await openPanel(page, "?alert_id=alert-kitchen-energy");
  const markersOverlap = await panel.locator(".comparison-scale").evaluate((scale) => {
    const threshold = scale.querySelector(".comparison-marker.threshold span").getBoundingClientRect();
    const observed = scale.querySelector(".comparison-marker.observed span").getBoundingClientRect();
    return threshold.right > observed.left && observed.right > threshold.left;
  });
  expect(markersOverlap).toBe(false);
});

test("dashboard chart keeps detail link without chart data disclosure", async ({ page, isMobile }) => {
  await mockPanelApi(page);
  const dashboard = await openDashboardGraphs(page);
  const detailLink = dashboard.locator("[data-dashboard-alert-detail]");

  const chart = dashboard.locator("svg.chart");
  await expect(chart).toBeVisible();
  await expect(chart).toHaveAttribute("aria-label", /Alert evidence chart with 1 series and 3 points\./);
  await expect(detailLink).toBeVisible();
  await expect(dashboard.locator(".chart-data-fallback")).toHaveCount(0);
  await expect(dashboard.locator(".chart-data-summary")).toHaveCount(0);
  await expect(dashboard.getByText("View chart data")).toHaveCount(0);
  await dashboard.locator("[data-chart-point]").last().hover({ force: true });
  await expect(dashboard.locator("[data-chart-tooltip]")).toContainText("610 W");

  const layout = await dashboard.evaluate((host) => {
    const chart = host.shadowRoot.querySelector("svg.chart").getBoundingClientRect();
    return { chartLeft: chart.left, chartRight: chart.right, viewportWidth: window.innerWidth };
  });
  expect(layout.chartLeft).toBeGreaterThanOrEqual(0);
  expect(layout.chartRight).toBeLessThanOrEqual(layout.viewportWidth + 1);
  if (isMobile) {
    expect(layout.viewportWidth).toBe(390);
  }
  await toHaveNoViolations(page);
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

test("Appliance Detail exposes ranges and comparisons", async ({ page, isMobile }) => {
  await mockPanelApi(page);
  const panel = await openPanel(page, "?appliance_detail=1&circuit_id=kitchen");

  await expect(panel.locator(".appliance-detail-facts")).toHaveCount(1);
  await expect(panel.locator(".appliance-detail-facts .metric-heading")).toHaveText([
    "Activity",
    "Power",
    "Confidence",
    "Health",
    "Energy",
    "Runtime Today",
    "Runs Today",
  ]);
  await expect(panel.getByRole("heading", { name: "Today vs Normal" })).toBeVisible();
  await expect(panel.getByText("Projected end of day")).toBeVisible();
  const dailyCost = panel.locator("[data-appliance-daily-cost]");
  await expect(dailyCost).toBeVisible();
  await expect(dailyCost.locator("svg.chart")).toHaveCount(1);
  await expect(dailyCost.locator('[data-chart-right-axis="$"]')).toBeVisible();
  await expect(dailyCost.locator('polyline[stroke-dasharray="6 4"]')).toHaveCount(1);
  await expect(dailyCost).toContainText("Cost Today");
  await expect(dailyCost).toContainText("Average Cost per Day");
  await expect(dailyCost).toContainText("kWh Today");
  await expect(dailyCost).toContainText("Average kWh per Day");
  await expect(dailyCost.locator(".metric-heading")).toHaveText([
    "kWh Today",
    "Average kWh per Day",
    "Cost Today",
    "Average Cost per Day",
  ]);
  await expect(panel.getByRole("heading", { name: "What To Check First" })).toHaveCount(0);
  await expect(panel.getByText("Cost Today", { exact: true })).toHaveCount(1);
  const horizontalOverflow = await panel.evaluate((host) => (
    host.shadowRoot.scrollWidth > host.shadowRoot.clientWidth
  ));
  expect(horizontalOverflow).toBe(false);

  await panel.locator('[data-appliance-history-graph-zoom="0.5"]').click();
  await expect.poll(() => page.evaluate(() => {
    const graphWindow = window.__panel._applianceDetailHistoryGraphWindow();
    return Math.round((graphWindow.end - graphWindow.start) / 3_600_000);
  })).toBe(24);
  const beforePan = await page.evaluate(() => window.__panel._applianceDetailHistoryGraphWindow().start);
  await panel.locator('[data-appliance-history-graph-pan="-0.5"]').click();
  await expect.poll(() => page.evaluate(() => window.__panel._applianceDetailHistoryGraphWindow().start)).toBeLessThan(beforePan);
  await panel.locator('[data-appliance-history-graph-zoom="2"]').click();
  await expect.poll(() => page.evaluate(() => {
    const graphWindow = window.__panel._applianceDetailHistoryGraphWindow();
    return Math.round((graphWindow.end - graphWindow.start) / 3_600_000);
  })).toBe(168);

  const period = panel.locator("[data-appliance-history-period]");
  await period.selectOption("24");
  await expect(period).toHaveValue("24");
});

test("Appliance Detail omits a cost axis without an effective rate", async ({ page }) => {
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/appliance_detail")) return false;
    const payload = apiPayload(url.pathname);
    await route.fulfill({
      json: {
        ...payload,
        daily_totals: payload.daily_totals.map((row) => ({ ...row, cost: null })),
      },
    });
    return true;
  });
  const panel = await openPanel(page, "?appliance_detail=1&circuit_id=kitchen");
  const dailyCost = panel.locator("[data-appliance-daily-cost]");

  await expect(dailyCost.locator("svg.chart")).toHaveCount(1);
  await expect(dailyCost.locator("[data-chart-right-axis]")).toHaveCount(0);
  await expect(dailyCost.locator('polyline[stroke-dasharray="6 4"]')).toHaveCount(0);
});

test("Review Evidence keeps recommendation data, graph, and actions in order", async ({ page, isMobile }) => {
  test.skip(isMobile, "Mobile route and accessibility coverage runs separately.");
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/alert_evidence") || !url.searchParams.has("recommendation_id")) {
      return false;
    }
    const selected = {
      ...evidence.setting_recommendations[0],
      evidence_preview: "Observed Days: 12; Daily P95: 2.5 kWh",
      actions: {
        ...evidence.setting_recommendations[0].actions,
        dismiss: {
          domain: "circuitsetup_energy_analyzer",
          service: "dismiss_setting_recommendation",
          data: { recommendation_id: "energy-threshold" },
        },
      },
    };
    await route.fulfill({ json: { ...evidence, selected_recommendation: selected } });
    return true;
  });
  const panel = await openPanel(page, "?circuit_id=kitchen&recommendation_id=energy-threshold");

  await expect(panel.locator("h1")).toHaveText("Review Evidence");
  await expect(panel.getByText("Reviewing evidence for Kitchen Appliances Daily Energy Threshold.")).toHaveCount(1);
  await expect(panel.locator(".recommendation-values")).toContainText("2.2 kWh");
  await expect(panel.locator("[data-recommendation-evidence-graph] svg.chart")).toBeVisible();
  const order = await panel.locator(".selected-recommendation-evidence").evaluate((section) => ({
    data: section.querySelector(".recommendation-values").getBoundingClientRect().top,
    graph: section.querySelector("svg.chart").getBoundingClientRect().top,
    actions: section.querySelector(".recommendation-evidence-actions").getBoundingClientRect().top,
  }));
  expect(order.data).toBeLessThan(order.graph);
  expect(order.graph).toBeLessThan(order.actions);
  await expect(panel.getByText("Respond to this alert")).toHaveCount(0);
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
  const preview = recommendations.locator(".setting-impact-preview");
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
