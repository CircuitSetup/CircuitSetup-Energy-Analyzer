import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { apiPayload, evidence, hvacAssociations } from "./panel-fixtures.js";

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

async function openDashboardCard(
  page,
  tagName,
  config,
  states = {},
  hassConfig = {},
  dashboardRange = null,
) {
  await page.goto(HARNESS);
  await page.waitForFunction(() => window.__panelReady === true);
  await page.evaluate(({
    tagName: tag,
    cardConfig,
    cardStates,
    nextHassConfig,
    nextDashboardRange,
  }) => {
    if (nextDashboardRange) {
      localStorage.setItem(
        "circuitsetup-energy-analyzer-dashboard-range",
        JSON.stringify(nextDashboardRange),
      );
    } else {
      localStorage.removeItem("circuitsetup-energy-analyzer-dashboard-range");
    }
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
    nextDashboardRange: dashboardRange,
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

test("HVAC associations render ready and learning thermostat gauges", async ({ page }) => {
  await mockPanelApi(page);
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-hvac-associations",
    {
      title: "HVAC & Thermostats",
      entry_id: "entry-1",
      api_path: "circuitsetup_energy_analyzer/hvac_associations",
      labels: { slower: "Slower", faster: "Faster", stable: "Stable" },
    },
    {
      "climate.downstairs": { state: "cool", attributes: { temperature_unit: "°F" } },
      "climate.upstairs": { state: "heat", attributes: { temperature_unit: "°C" } },
      "climate.bedroom": { state: "heat", attributes: { temperature_unit: "°F" } },
    },
  );

  await expect(card.locator("[data-hvac-association]")).toHaveCount(3);
  await expect(card.locator('[data-thermostat="climate.downstairs"] [data-mode="heating"]')).toContainText("92%");
  await expect(card.locator('[data-thermostat="climate.downstairs"] [data-mode="cooling"]')).toContainText("108%");
  await expect(card.locator('[data-thermostat="climate.upstairs"] [data-mode="heating"]')).toContainText("9 min/°C");
  await expect(card.locator('[data-thermostat="climate.upstairs"] [data-mode="heating"] .gauge-value')).toHaveCount(0);
  await expect(card.locator('[data-thermostat="climate.downstairs"] [data-mode="heating"] .trend')).toHaveText("Slower");
  await expect(card.locator('[data-thermostat="climate.bedroom"] [data-mode="cooling"]')).toHaveCount(0);
  for (const mode of ["heating", "cooling"]) {
    await expect(card.locator(`[data-thermostat="climate.downstairs"] [data-mode="${mode}"] svg`)).toHaveAttribute(
      "aria-label",
      new RegExp(`Heat Pump.*Downstairs.*${mode}.*(?:92|108)%.*(?:9|11) min/°F`, "i"),
    );
  }
});

test("HVAC associations show learning, attribution, native detail links, and fit narrow screens", async ({ page }) => {
  await mockPanelApi(page);
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-hvac-associations",
    { title: "HVAC & Thermostats", entry_id: "entry-1", api_path: "circuitsetup_energy_analyzer/hvac_associations" },
    {
      "climate.downstairs": { state: "cool", attributes: { temperature_unit: "°F" } },
      "climate.upstairs": { state: "heat", attributes: { temperature_unit: "°C" } },
      "climate.bedroom": { state: "heat", attributes: { temperature_unit: "°F" } },
    },
  );
  const upstairs = card.locator('[data-thermostat="climate.upstairs"]');
  await expect(upstairs.locator('[data-mode="heating"]')).toContainText("Learning");
  await expect(upstairs.locator('[data-mode="cooling"]')).toContainText("—");
  await expect(card.locator('[data-thermostat="climate.bedroom"]')).toContainText("Needs attention");
  await expect(card.locator('[data-thermostat="climate.bedroom"]')).toContainText("Gas heat: supporting blower attribution.");
  await expect(card.locator('[data-thermostat="climate.downstairs"]')).toContainText("Cooling blower supports air handling");
  await expect(card.locator('[data-thermostat="climate.downstairs"]')).toHaveAttribute(
    "href",
    hvacAssociations.items[0].detail_path,
  );
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await card.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  const axe = await new AxeBuilder({ page }).analyze();
  expect(axe.violations.filter((violation) => ["serious", "critical"].includes(violation.impact))).toEqual([]);
});

test("HVAC associations explain how to set up an empty filtered card on desktop and mobile", async ({ page }) => {
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/hvac_associations")) return false;
    await route.fulfill({ json: { status: "ok", count: 0, items: [] } });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-hvac-associations",
    { title: "HVAC & Thermostats", entry_id: "entry-1", api_path: "circuitsetup_energy_analyzer/hvac_associations" },
    {},
  );

  await expect(card.locator("[data-hvac-associations-empty]")).toContainText(
    "Link a thermostat in the appliance Advanced Settings, then update the generated dashboard.",
  );
  await expect(card.locator(".association-grid")).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(card.locator("[data-hvac-associations-empty]")).toBeVisible();
  expect(await card.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
});

test("HVAC associations retry one failed request", async ({ page }) => {
  test.info().annotations.push(
    { type: "allow-browser-error", description: "503 http://127.0.0.1:4173/api/circuitsetup_energy_analyzer/hvac_associations?entry_id=entry-1" },
    { type: "allow-browser-error", description: "Failed to load resource: the server responded with a status of 503" },
    { type: "allow-browser-error", description: "hvac_associations?entry_id=entry-1: net::ERR_ABORTED" },
  );
  let attempts = 0;
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/hvac_associations")) return false;
    attempts += 1;
    if (attempts === 1) {
      await route.fulfill({ status: 503, body: "" });
      return true;
    }
    return false;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-hvac-associations",
    { entry_id: "entry-1", api_path: "circuitsetup_energy_analyzer/hvac_associations" },
    { "climate.downstairs": { state: "cool", attributes: { temperature_unit: "°F" } } },
  );
  await card.locator("[data-retry-hvac-associations]").click();
  await expect(card.locator("[data-hvac-association]")).toHaveCount(3);
  expect(attempts).toBe(2);
});

test("HVAC associations reload a reused card for a new API key", async ({ page }) => {
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/hvac_associations")) return false;
    const entryId = url.searchParams.get("entry_id");
    await route.fulfill({
      json: {
        status: "ok",
        items: [{
          ...hvacAssociations.items[0],
          entry_id: entryId,
          appliance_name: entryId === "entry-b" ? "Second Heat Pump" : "First Heat Pump",
          thermostat_entity_id: entryId === "entry-b" ? "climate.second" : "climate.first",
          thermostat_name: entryId === "entry-b" ? "Second" : "First",
        }],
      },
    });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-hvac-associations",
    { entry_id: "entry-a", api_path: "circuitsetup_energy_analyzer/hvac_associations" },
    {
      "climate.first": { state: "cool", attributes: { temperature_unit: "°F" } },
      "climate.second": { state: "cool", attributes: { temperature_unit: "°F" } },
    },
  );
  await expect(card).toContainText("First Heat Pump");
  await page.evaluate(() => window.__dashboardCard.setConfig({
    entry_id: "entry-b",
    api_path: "circuitsetup_energy_analyzer/hvac_associations",
  }));
  await expect(card).toContainText("Second Heat Pump");
  await expect(card).not.toContainText("First Heat Pump");
  await expect.poll(() => page.evaluate(() => window.__apiCalls
    .filter((call) => call.apiPath.includes("hvac_associations"))
    .map((call) => call.apiPath))).toEqual([
    "circuitsetup_energy_analyzer/hvac_associations?entry_id=entry-a",
    "circuitsetup_energy_analyzer/hvac_associations?entry_id=entry-b",
  ]);
});

test("HVAC associations reload a reused card for the same API key after an empty response", async ({ page }) => {
  let requests = 0;
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/hvac_associations")) return false;
    requests += 1;
    await route.fulfill({
      json: requests === 1 ? { status: "ok", items: [] } : {
        status: "ok",
        items: [{
          ...hvacAssociations.items[0],
          entry_id: "entry-1",
          appliance_name: "Updated Heat Pump",
          thermostat_entity_id: "climate.updated",
          thermostat_name: "Updated",
        }],
      },
    });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-hvac-associations",
    { entry_id: "entry-1", api_path: "circuitsetup_energy_analyzer/hvac_associations" },
    { "climate.updated": { state: "cool", attributes: { temperature_unit: "°F" } } },
  );
  await expect(card.locator("[data-hvac-associations-empty]")).toBeVisible();
  await page.evaluate(() => window.__dashboardCard.setConfig({
    entry_id: "entry-1",
    api_path: "circuitsetup_energy_analyzer/hvac_associations",
  }));
  await expect(card).toContainText("Updated Heat Pump");
  expect(requests).toBe(2);
});

test("HVAC associations ignore an old in-flight API key", async ({ page }) => {
  let releaseFirst;
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/hvac_associations")) return false;
    const entryId = url.searchParams.get("entry_id");
    const fulfill = () => route.fulfill({
      json: {
        status: "ok",
        items: [{
          ...hvacAssociations.items[0],
          entry_id: entryId,
          appliance_name: entryId === "entry-b" ? "Second Heat Pump" : "First Heat Pump",
          thermostat_entity_id: "climate.downstairs",
        }],
      },
    });
    if (entryId === "entry-a") {
      await new Promise((resolve) => { releaseFirst = async () => { await fulfill(); resolve(); }; });
      return true;
    }
    await fulfill();
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-hvac-associations",
    { entry_id: "entry-a", api_path: "circuitsetup_energy_analyzer/hvac_associations" },
    { "climate.downstairs": { state: "cool", attributes: { temperature_unit: "°F" } } },
  );
  await expect.poll(() => Boolean(releaseFirst)).toBe(true);
  await page.evaluate(() => window.__dashboardCard.setConfig({
    entry_id: "entry-b",
    api_path: "circuitsetup_energy_analyzer/hvac_associations",
  }));
  await expect(card).toContainText("Second Heat Pump");
  await releaseFirst();
  await expect(card).toContainText("Second Heat Pump");
  await expect(card).not.toContainText("First Heat Pump");
});

test("HVAC associations refresh once for referenced state revisions only", async ({ page }) => {
  let requests = 0;
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/hvac_associations")) return false;
    requests += 1;
    await route.fulfill({
      json: requests === 4 ? { ...hvacAssociations, items: [] } : {
        ...hvacAssociations,
        items: [{
          ...hvacAssociations.items[0],
          modes: {
            ...hvacAssociations.items[0].modes,
            heating: {
              ...hvacAssociations.items[0].modes.heating,
              score: [92, 107, 123][requests - 1],
            },
          },
        }],
      },
    });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-hvac-associations",
    {
      entry_id: "entry-1",
      api_path: "circuitsetup_energy_analyzer/hvac_associations",
      revision_entities: ["sensor.heat_pump_health_summary"],
    },
    {
      "climate.downstairs": {
        state: "cool",
        last_updated: "2026-07-29T12:00:00.000Z",
        attributes: { temperature_unit: "°F", temperature: 72 },
      },
      "sensor.downstairs_temperature": {
        state: "72",
        last_updated: "2026-07-29T12:00:00.000Z",
        attributes: { unit_of_measurement: "°F" },
      },
      "sensor.heat_pump_health_summary": {
        state: "Ready",
        attributes: { hvac_association_revision: 1 },
      },
    },
  );
  await expect(card.locator('[data-mode="heating"]')).toContainText("92%");

  await page.evaluate(() => window.__setDashboardState("sensor.unrelated", {
    state: "changed",
    last_updated: "2026-07-29T12:01:00.000Z",
    attributes: {},
  }));
  await expect.poll(() => requests).toBe(1);

  await page.evaluate(() => window.__setDashboardState("sensor.heat_pump_health_summary", {
    state: "Possible issue",
    attributes: { hvac_association_revision: 1, active_alert_count: 1 },
  }));
  await expect.poll(() => requests).toBe(1);

  await page.evaluate(() => window.__setDashboardState("sensor.heat_pump_health_summary", {
    state: "Ready",
    attributes: { hvac_association_revision: 2 },
  }));
  await expect(card.locator('[data-mode="heating"]')).toContainText("107%");
  expect(requests).toBe(2);

  await page.evaluate(() => window.__setDashboardState("climate.downstairs", {
    state: "cool",
    last_updated: "2026-07-29T12:02:00.000Z",
    attributes: { temperature_unit: "°F", temperature: 73 },
  }));
  await expect(card.locator('[data-mode="heating"]')).toContainText("123%");
  expect(requests).toBe(3);

  await page.evaluate(() => window.__setDashboardState("sensor.downstairs_temperature", {
    state: "73",
    last_updated: "2026-07-29T12:03:00.000Z",
    attributes: { unit_of_measurement: "°F" },
  }));
  await expect(card.locator("[data-hvac-associations-empty]")).toBeVisible();
  expect(requests).toBe(4);

  await page.evaluate(() => window.__setDashboardState("climate.downstairs", {
    state: "off",
    last_updated: "2026-07-29T12:04:00.000Z",
    attributes: { temperature_unit: "°F", temperature: 73 },
  }));
  await expect.poll(() => requests).toBe(4);
});

test("HVAC associations keep unrelated updates out of a pending refresh", async ({ page }) => {
  let requests = 0;
  let releaseRefresh;
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/hvac_associations")) return false;
    requests += 1;
    const fulfill = async () => route.fulfill({
      json: {
        ...hvacAssociations,
        items: [{
          ...hvacAssociations.items[0],
          modes: {
            ...hvacAssociations.items[0].modes,
            heating: {
              ...hvacAssociations.items[0].modes.heating,
              score: requests === 1 ? 92 : 107,
            },
          },
        }],
      },
    });
    if (requests === 2) {
      await new Promise((resolve) => { releaseRefresh = async () => { await fulfill(); resolve(); }; });
      return true;
    }
    await fulfill();
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-hvac-associations",
    { entry_id: "entry-1", api_path: "circuitsetup_energy_analyzer/hvac_associations" },
    {
      "climate.downstairs": { state: "cool", attributes: { temperature_unit: "°F", temperature: 72 } },
      "sensor.downstairs_temperature": { state: "72", attributes: { unit_of_measurement: "°F" } },
    },
  );
  await expect(card.locator('[data-mode="heating"]')).toContainText("92%");

  await page.evaluate(() => window.__setDashboardState("climate.downstairs", {
    state: "cool",
    attributes: { temperature_unit: "°F", temperature: 73 },
  }));
  await expect.poll(() => Boolean(releaseRefresh)).toBe(true);

  await page.evaluate(() => window.__setDashboardState("sensor.unrelated", {
    state: "changed",
    attributes: {},
  }));
  await expect.poll(() => requests).toBe(2);
  await releaseRefresh();
  await expect(card.locator('[data-mode="heating"]')).toContainText("107%");
});

test("HVAC associations label ready modes without a trend as stable", async ({ page }) => {
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/hvac_associations")) return false;
    await route.fulfill({
      json: {
        ...hvacAssociations,
        items: [{
          ...hvacAssociations.items[0],
          modes: {
            heating: {
              ...hvacAssociations.items[0].modes.heating,
              trend: null,
            },
          },
        }],
      },
    });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-hvac-associations",
    {
      entry_id: "entry-1",
      api_path: "circuitsetup_energy_analyzer/hvac_associations",
      labels: { stable: "Stable" },
    },
    { "climate.downstairs": { state: "cool", attributes: { temperature_unit: "°F" } } },
  );
  await expect(card.locator('[data-mode="heating"] .trend')).toHaveText("Stable");
});

test("House power flow omits Active now and separates contribution", async ({ page }) => {
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
    "sensor.mains_l1_current": { state: "7", attributes: { unit_of_measurement: "A" } },
    "sensor.mains_l2_current": { state: "9", attributes: { unit_of_measurement: "A" } },
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
        current_entities: ["sensor.mains_l1_current", "sensor.mains_l2_current"],
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
  await expect(card.locator(".flow")).toHaveCount(1);
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
  await expect(card.locator(".flow")).toHaveCount(0);
  await expect(card.locator(".metric").filter({ hasText: "Energy (Jul 10-12)" })).toContainText("60.4 kWh");
  await expect(card.locator(".metric").filter({ hasText: "Energy (Jul 10-12)" }).locator("small"))
    .toHaveText("Average: 35.4 kWh (3 days)");
  await expect(card.locator(".metric").filter({ hasText: "Cost (Jul 10-12)" })).toContainText("$2.92");
  await expect(card.locator(".metric").filter({ hasText: "Cost (Jul 10-12)" }).locator("small"))
    .toHaveText("Average: $6.48 (3 days)");
  await expect(card.locator(".metric").filter({ hasText: "Total Amps (Jul 10-12)" })).toContainText("16 A");
  await expect(card.locator(".metric").filter({ hasText: "Total Amps (Jul 10-12)" }).locator("small"))
    .toHaveText("Average: 48 A (3 days)");
  await expect(card.locator(".metric").filter({ hasText: "House power" })).toHaveCount(0);
  await expect(card).not.toContainText("% more");
  await expect(card).not.toContainText("% less");
  await expect(card.locator(".bar-row").filter({ hasText: "Oven" })).toContainText("6.7 kWh");
  await page.evaluate(() => {
    window.__setDashboardState("sensor.mains_l2_current", {
      state: "unavailable",
      attributes: { unit_of_measurement: "A" },
    });
  });
  await expect(card.locator(".metric").filter({ hasText: "Total Amps (Jul 10-12)" }))
    .toContainText("Unavailable");
  const contributionHistory = card.locator("[data-chart-history]");
  await expect(contributionHistory).toBeVisible();
  expect(await contributionHistory.evaluate((link) => {
    const url = new URL(link.href);
    return {
      entities: url.searchParams.get("entity_id"),
      start: url.searchParams.get("start_date"),
      end: url.searchParams.get("end_date"),
    };
  })).toEqual({
    entities: "sensor.fridge_energy,sensor.washer_energy,sensor.oven_energy",
    start: "2026-07-10T00:00:00.000Z",
    end: "2026-07-12T23:59:59.999Z",
  });
  await card.locator('[data-contribution-mode="cost"]').click();
  await expect(card.locator(".bar-row").filter({ hasText: "Oven" })).toContainText("$0.74");
  await expect.poll(() => contributionHistory.evaluate((link) => (
    new URL(link.href).searchParams.get("entity_id")
  ))).toBe("sensor.fridge_cost,sensor.washer_cost,sensor.oven_cost");
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

test("home summary uses the mains graph history for the amps average", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-12T12:00:00.000Z") });
  await mockPanelApi(page, async ({ route, url }) => {
    if (url.pathname.includes("/history/period")) {
      await route.fulfill({
        json: [
          [
            { entity_id: "sensor.mains_power", state: "1000", last_changed: "2026-07-12T00:00:00.000Z" },
            { state: "2000", last_changed: "2026-07-12T12:00:00.000Z" },
          ],
          [
            { entity_id: "sensor.mains_l1_current", state: "2000", last_changed: "2026-07-12T00:00:00.000Z" },
            { state: "4000", last_changed: "2026-07-12T12:00:00.000Z" },
          ],
          [
            { entity_id: "sensor.mains_l2_current", state: "0.003", last_changed: "2026-07-12T00:00:00.000Z" },
            { state: "0.006", last_changed: "2026-07-12T12:00:00.000Z" },
          ],
        ],
      });
      return true;
    }
    if (!url.pathname.endsWith("/appliance_insights")) return false;
    await route.fulfill({ json: { status: "ok", items: [], whole_house: [] } });
    return true;
  });
  await openDashboardCards(page, [
    {
      tagName: "circuitsetup-energy-analyzer-context-graph",
      config: {
        title: "Mains total power and amps",
        entities: [
          { entity: "sensor.mains_power", name: "Mains total power", series_id: "mains:power", axis: "left" },
          { entity: "sensor.mains_l1_current", name: "Total Amps", series_id: "mains:current", axis: "right" },
          { entity: "sensor.mains_l2_current", name: "Total Amps", series_id: "mains:current", axis: "right" },
        ],
      },
    },
    {
      tagName: "circuitsetup-energy-analyzer-house-flow",
      config: {
        title: "Home energy summary",
        api_path: "circuitsetup_energy_analyzer/appliance_insights",
        primary_mains: {
          power_entities: ["sensor.mains_power"],
          current_entities: ["sensor.mains_l1_current", "sensor.mains_l2_current"],
        },
      },
    },
  ], {
    "sensor.mains_power": { state: "2000", attributes: { unit_of_measurement: "W" } },
    "sensor.mains_l1_current": { state: "4000", attributes: { unit_of_measurement: "mA" } },
    "sensor.mains_l2_current": { state: "0.006", attributes: { unit_of_measurement: "kA" } },
  });

  const summary = page.locator("circuitsetup-energy-analyzer-house-flow");
  const amps = summary.locator(".metric").filter({ hasText: "Total Amps (Jul 12)" });
  await expect(amps).toContainText("10 A");
  await expect(amps.locator("small")).toHaveText("Average: 5 A");
});

test("home summary rejects incomplete mains current history", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-13T12:00:00.000Z") });
  await mockPanelApi(page, async ({ route, url }) => {
    if (url.pathname.includes("/history/period")) {
      await route.fulfill({
        json: [[
          {
            entity_id: "sensor.mains_l1_current",
            state: "4",
            last_changed: "2026-07-12T00:00:00.000Z",
          },
        ]],
      });
      return true;
    }
    if (!url.pathname.endsWith("/appliance_insights")) return false;
    await route.fulfill({ json: { status: "ok", items: [], whole_house: [] } });
    return true;
  });
  await openDashboardCards(page, [
    {
      tagName: "circuitsetup-energy-analyzer-context-graph",
      config: {
        title: "Mains total power and amps",
        entities: [
          { entity: "sensor.mains_l1_current", name: "Total Amps", series_id: "mains:current", axis: "left" },
          { entity: "sensor.mains_l2_current", name: "Total Amps", series_id: "mains:current", axis: "left" },
        ],
      },
    },
    {
      tagName: "circuitsetup-energy-analyzer-house-flow",
      config: {
        title: "Home energy summary",
        api_path: "circuitsetup_energy_analyzer/appliance_insights",
        primary_mains: {
          current_entities: ["sensor.mains_l1_current", "sensor.mains_l2_current"],
        },
      },
    },
  ], {
    "sensor.mains_l1_current": { state: "4", attributes: { unit_of_measurement: "A" } },
    "sensor.mains_l2_current": { state: "6", attributes: { unit_of_measurement: "A" } },
  });
  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent("circuitsetup-dashboard-range-changed", {
      detail: {
        start: "2026-07-12T00:00:00.000Z",
        end: "2026-07-12T23:59:59.999Z",
        compare: false,
      },
    }));
  });

  const amps = page.locator("circuitsetup-energy-analyzer-house-flow")
    .locator(".metric")
    .filter({ hasText: "Total Amps (Jul 12)" });
  await expect(amps).toContainText("Unavailable");
  await expect(amps.locator("small")).toHaveCount(0);
});

test("home summary totals monitored appliances when mains today totals are unavailable", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-26T18:00:00.000Z") });
  await mockPanelApi(page);
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-house-flow",
    {
      title: "Home energy summary",
      api_path: "circuitsetup_energy_analyzer/appliance_insights",
      primary_mains: {
        daily_energy_usage_entity: "sensor.mains_energy_today",
        cost_today_entity: "sensor.mains_cost_today",
      },
      appliances: [
        {
          circuit_id: "fridge",
          name: "Fridge",
          energy_today_entity: "sensor.fridge_energy",
          cost_today_entity: "sensor.fridge_cost",
        },
        {
          circuit_id: "hvac",
          name: "HVAC",
          energy_today_entity: "sensor.hvac_energy",
          cost_today_entity: "sensor.hvac_cost",
        },
      ],
    },
    {
      "sensor.mains_energy_today": { state: "unavailable", attributes: {} },
      "sensor.mains_cost_today": { state: "unavailable", attributes: {} },
      "sensor.fridge_energy": { state: "1.4", attributes: { unit_of_measurement: "kWh" } },
      "sensor.fridge_cost": { state: "0.28", attributes: {} },
      "sensor.hvac_energy": { state: "2.2", attributes: { unit_of_measurement: "kWh" } },
      "sensor.hvac_cost": { state: "0.5", attributes: {} },
    },
  );

  await expect(card.locator(".metric").filter({ hasText: "Energy (Jul 26)" }))
    .toContainText("3.6 kWh");
  await expect(card.locator(".metric").filter({ hasText: "Cost (Jul 26)" }))
    .toContainText("$0.78");
  await page.evaluate(() => {
    window.__setDashboardState("sensor.hvac_energy", {
      state: "unavailable",
      attributes: { unit_of_measurement: "kWh" },
    });
    window.__dashboardCard.hass = window.__dashboardHass;
  });
  await expect(card.locator(".metric").filter({ hasText: "Energy (Jul 26)" }))
    .toContainText("Unavailable");
  await expect(card.locator(".metric").filter({ hasText: "Cost (Jul 26)" }))
    .toContainText("$0.78");
});

test("home totals use retained completed days without Recorder history", async ({ page }) => {
  test.info().annotations.push(
    { type: "allow-browser-error", description: "503 http://127.0.0.1:4173/api/circuitsetup_energy_analyzer/appliance_insights" },
    { type: "allow-browser-error", description: "Failed to load resource: the server responded with a status of 503" },
    { type: "allow-browser-error", description: "appliance_insights: net::ERR_ABORTED" },
  );
  let insightCalls = 0;
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/appliance_insights")) return false;
    insightCalls += 1;
    if (insightCalls === 1) {
      await route.fulfill({ status: 503, body: "" });
      return true;
    }
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
    {},
    {},
    {
      start: "2026-05-01T00:00:00.000Z",
      end: "2026-05-02T23:59:59.999Z",
      compare: false,
    },
  );

  await expect.poll(() => insightCalls).toBe(2);
  await expect(card.locator(".metric").filter({ hasText: "Energy (May 1-2)" })).toContainText("18 kWh");
  await expect(card.locator(".metric").filter({ hasText: "Cost (May 1-2)" })).toContainText("$3.60");
  await expect(card.locator(".bar-row").filter({ hasText: "Current-only appliance" })).toContainText("5 kWh");
  expect(await page.evaluate(() => (
    window.__apiCalls.some(({ apiPath }) => apiPath.includes("history/period/2026-05"))
  ))).toBe(false);
});

test("historical home totals retry after an API failure", async ({ page }) => {
  test.info().annotations.push(
    { type: "allow-browser-error", description: "503 http://127.0.0.1:4173/api/circuitsetup_energy_analyzer/appliance_insights" },
    { type: "allow-browser-error", description: "Failed to load resource: the server responded with a status of 503" },
    { type: "allow-browser-error", description: "appliance_insights: net::ERR_ABORTED" },
  );
  await page.clock.install({ time: new Date("2026-07-12T22:00:00.000Z") });
  let insightCalls = 0;
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/appliance_insights")) return false;
    insightCalls += 1;
    await route.fulfill({ status: 503, body: "" });
    return true;
  });
  await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-house-flow",
    {
      title: "Home energy summary",
      api_path: "circuitsetup_energy_analyzer/appliance_insights",
      primary_mains: { circuit_id: "mains" },
    },
    {},
    {},
    {
      start: "2026-07-10T00:00:00.000Z",
      end: "2026-07-10T23:59:59.999Z",
      compare: false,
    },
  );

  await expect.poll(() => page.evaluate(() => (
    window.__dashboardCard._rangeTotalsReloadTimer
  ))).toBeGreaterThan(0);
  const callsBeforeRetry = insightCalls;
  await page.clock.fastForward(5_000);
  await expect.poll(() => insightCalls).toBeGreaterThan(callsBeforeRetry);
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
  const requestKeyBeforeMidnight = await page.evaluate(() => (
    window.__dashboardCard._contributionLoadKey
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
  expect(await page.evaluate(() => window.__dashboardCard._contributionLoadKey))
    .not.toBe(requestKeyBeforeMidnight);
  await expect(card.locator(".metric").filter({ hasText: "Energy (Jul 11-12)" })).toContainText("10 kWh");
  await page.clock.fastForward(30_000);
  await expect.poll(() => page.evaluate(() => (
    window.__apiCalls.filter(({ apiPath }) => apiPath.endsWith("/appliance_insights")).length
  ))).toBe(insightCalls + 2);
  await expect(card.locator(".metric").filter({ hasText: "Energy (Jul 11-12)" })).toContainText("14 kWh");
  await expect(card.locator(".metric").filter({ hasText: "Cost (Jul 11-12)" })).toContainText("$3.00");
  await expect(card.locator(".bar-row").filter({ hasText: "Fridge" })).toContainText("3 kWh");
});

test("newly mounted home totals retry stale rollover data", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-13T00:01:00.000Z") });
  let insightCalls = 0;
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/appliance_insights")) return false;
    insightCalls += 1;
    await route.fulfill({
      json: {
        status: "ok",
        items: [],
        whole_house: [{
          entry_id: "entry-1",
          circuit_id: "mains",
          daily_totals: [
            { date: "2026-07-11", energy_kwh: 10, cost: 2 },
            ...(insightCalls > 3
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
      primary_mains: { circuit_id: "mains" },
      appliances: [],
    },
    {},
    {},
    {
      start: "2026-07-11T00:00:00.000Z",
      end: "2026-07-12T23:59:59.999Z",
      compare: false,
    },
  );

  await expect(card.locator(".metric").filter({ hasText: "Energy (Jul 11-12)" })).toContainText("10 kWh");
  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent("circuitsetup-dashboard-range-changed", {
      detail: {
        start: "2026-07-10T00:00:00.000Z",
        end: "2026-07-12T23:59:59.999Z",
        compare: false,
      },
    }));
  });
  await expect.poll(() => insightCalls).toBe(2);
  await page.clock.fastForward(30_000);
  await expect.poll(() => insightCalls).toBe(3);
  await expect.poll(() => page.evaluate(() => (
    Boolean(window.__dashboardCard._rangeTotalsReloadTimer)
  ))).toBe(true);
  await page.clock.fastForward(30_000);
  await expect.poll(() => insightCalls).toBe(4);
  await expect(card.locator(".metric").filter({ hasText: "Energy (Jul 10-12)" })).toContainText("14 kWh");
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
  const timelineHistory = card.locator("[data-chart-history]");
  await expect(timelineHistory).toBeVisible();
  expect(await timelineHistory.evaluate((link) => {
    const url = new URL(link.href);
    return {
      entities: url.searchParams.get("entity_id"),
      start: url.searchParams.get("start_date"),
      end: url.searchParams.get("end_date"),
    };
  })).toEqual({
    entities: "sensor.fridge_activity",
    start: "2026-07-10T00:00:00.000Z",
    end: "2026-07-12T23:59:59.999Z",
  });
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
  ))).toBeGreaterThan(timelineHistoryCalls);
  await card.locator('[data-appliance-id="fridge"]').click();
  await expect(page).toHaveURL(/appliance_detail=1&circuit_id=fridge/);
});

test("historical appliance grid uses selected-date totals without live status", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-12T22:00:00.000Z") });
  await mockPanelApi(page, async ({ route, url }) => {
    if (url.pathname.includes("/history/period")) {
      await route.fulfill({
        json: [[
          { entity_id: "sensor.fridge_activity", state: "Idle", last_changed: "2026-07-10T00:00:00.000Z" },
          { state: "Running", last_changed: "2026-07-10T04:00:00.000Z" },
          { state: "Idle", last_changed: "2026-07-10T05:00:00.000Z" },
        ]],
      });
      return true;
    }
    if (!url.pathname.endsWith("/appliance_insights")) return false;
    await route.fulfill({
      json: {
        status: "ok",
        items: [{
          entry_id: "entry-1",
          circuit_id: "fridge",
          daily_totals: [{ date: "2026-07-10", energy_kwh: 2.5, cost: 0.75 }],
        }],
        whole_house: [],
      },
    });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-appliance-grid",
    {
      title: "Appliances",
      entry_id: "entry-1",
      api_path: "circuitsetup_energy_analyzer/appliance_insights",
      appliances: [{
        circuit_id: "fridge",
        name: "Fridge",
        activity_entity: "sensor.fridge_activity",
        power_entities: ["sensor.fridge_power"],
        energy_today_entity: "sensor.fridge_energy",
        cost_today_entity: "sensor.fridge_cost",
        health_entity: "sensor.fridge_health",
      }],
    },
    {
      "sensor.fridge_activity": {
        state: "Running",
        last_changed: "2026-07-12T21:00:00.000Z",
        attributes: {},
      },
      "sensor.fridge_power": { state: "150", attributes: { unit_of_measurement: "W" } },
      "sensor.fridge_energy": { state: "9.9", attributes: { unit_of_measurement: "kWh" } },
      "sensor.fridge_cost": { state: "4.2", attributes: {} },
      "sensor.fridge_health": {
        state: "Ready",
        attributes: { electrical_summary: "Possible Imbalance" },
      },
    },
    {},
    {
      start: "2026-07-10T00:00:00.000Z",
      end: "2026-07-10T23:59:59.999Z",
      compare: false,
    },
  );

  await expect(card.getByRole("tab", { name: "Running", exact: true })).toHaveCount(0);
  await expect(card.getByRole("tab", { name: "Needs attention", exact: true })).toHaveCount(0);
  await expect(card.locator("[data-timeline-selection]")).not.toContainText("Currently running");
  await expect(card.locator("[data-timeline-selection]")).toHaveValue("all");
  const tile = card.locator('[data-appliance-id="fridge"]');
  await expect(tile).toContainText("Energy Jul 10: 2.5 kWh · $0.75");
  await expect(tile).not.toContainText("150 W");
  await expect(tile).toContainText("Health: Possible Imbalance");
});

test("appliance grid shows learning days only for a single-day range", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-24T12:00:00.000Z") });
  await mockPanelApi(page);
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-appliance-grid",
    {
      title: "Appliances",
      appliances: [{
        circuit_id: "fridge",
        name: "Fridge",
        activity_entity: "sensor.fridge_activity",
        power_entities: ["sensor.fridge_power"],
        energy_today_entity: "sensor.fridge_energy",
        cost_today_entity: "sensor.fridge_cost",
        health_entity: "sensor.fridge_health",
      }],
    },
    {
      "sensor.fridge_activity": { state: "Idle", attributes: {} },
      "sensor.fridge_power": { state: "0", attributes: { unit_of_measurement: "W" } },
      "sensor.fridge_energy": { state: "1.4", attributes: { unit_of_measurement: "kWh" } },
      "sensor.fridge_cost": { state: "0.28", attributes: { unit_of_measurement: "USD" } },
      "sensor.fridge_health": {
        state: "Learning",
        attributes: {
          learning_days_complete: 3,
          learning_days_required: 7,
        },
      },
    },
  );

  const tile = card.locator('[data-appliance-id="fridge"]');
  await expect(tile).toContainText("Health: Learning · 4 of 7 days left");
  await page.evaluate(() => {
    window.__setDashboardState("sensor.fridge_health", {
      state: "Learning",
      attributes: {
        learning_days_complete: 0,
        learning_days_required: 0,
      },
    });
  });
  await expect(tile).toContainText("Health: Learning");
  await expect(tile).not.toContainText("days left");
  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent("circuitsetup-dashboard-range-changed", {
      detail: {
        start: "2026-07-23T00:00:00.000Z",
        end: "2026-07-24T23:59:59.999Z",
        compare: false,
      },
    }));
  });
  await expect(tile).not.toContainText("4 of 7 days left");
  await expect(tile).not.toContainText("Health:");
});

test("historical appliance totals retry after a transient API failure", async ({ page }) => {
  test.info().annotations.push(
    { type: "allow-browser-error", description: "503 http://127.0.0.1:4173/api/circuitsetup_energy_analyzer/appliance_insights" },
    { type: "allow-browser-error", description: "Failed to load resource: the server responded with a status of 503" },
    { type: "allow-browser-error", description: "appliance_insights: net::ERR_ABORTED" },
  );
  await page.clock.install({ time: new Date("2026-07-12T22:00:00.000Z") });
  let insightCalls = 0;
  let allowSuccess = false;
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/appliance_insights")) return false;
    insightCalls += 1;
    if (!allowSuccess) {
      await route.fulfill({ status: 503, body: "" });
      return true;
    }
    await route.fulfill({
      json: {
        status: "ok",
        items: [{
          entry_id: "entry-1",
          circuit_id: "fridge",
          daily_totals: [{ date: "2026-07-10", energy_kwh: 2.5, cost: 0.75 }],
        }],
        whole_house: [],
      },
    });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-appliance-grid",
    {
      title: "Appliances",
      entry_id: "entry-1",
      api_path: "circuitsetup_energy_analyzer/appliance_insights",
      appliances: [{ circuit_id: "fridge", name: "Fridge" }],
    },
    {},
    {},
    {
      start: "2026-07-10T00:00:00.000Z",
      end: "2026-07-10T23:59:59.999Z",
      compare: false,
    },
  );

  await expect.poll(() => insightCalls).toBeGreaterThan(0);
  await expect.poll(() => page.evaluate(() => (
    window.__dashboardCard._applianceRangeReloadTimer
  ))).toBeGreaterThan(0);
  const callsBeforeRetry = insightCalls;
  allowSuccess = true;
  await page.clock.fastForward(5_000);
  await expect.poll(() => insightCalls).toBeGreaterThan(callsBeforeRetry);
  await expect(card.locator('[data-appliance-id="fridge"]'))
    .toContainText("Energy Jul 10: 2.5 kWh · $0.75");
});

test("current-inclusive appliance totals update without reloading retained history", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-12T22:00:00.000Z") });
  let insightCalls = 0;
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/appliance_insights")) return false;
    insightCalls += 1;
    await route.fulfill({
      json: {
        status: "ok",
        items: [{
          entry_id: "entry-1",
          circuit_id: "fridge",
          daily_totals: [
            { date: "2026-07-10", energy_kwh: 1, cost: 0.1 },
            { date: "2026-07-11", energy_kwh: 2, cost: 0.2 },
          ],
        }],
        whole_house: [],
      },
    });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-appliance-grid",
    {
      title: "Appliances",
      entry_id: "entry-1",
      api_path: "circuitsetup_energy_analyzer/appliance_insights",
      appliances: [{
        circuit_id: "fridge",
        name: "Fridge",
        energy_today_entity: "sensor.fridge_energy",
        cost_today_entity: "sensor.fridge_cost",
      }],
    },
    {
      "sensor.fridge_energy": { state: "3", attributes: { unit_of_measurement: "kWh" } },
      "sensor.fridge_cost": { state: "0.3", attributes: {} },
    },
    {},
    {
      start: "2026-07-10T00:00:00.000Z",
      end: "2026-07-12T23:59:59.999Z",
      compare: false,
    },
  );
  const tile = card.locator('[data-appliance-id="fridge"]');
  await expect(tile).toContainText("Energy Jul 10-12: 6 kWh · $0.60");

  await page.evaluate(() => {
    window.__dashboardHass.states["sensor.fridge_energy"] = {
      state: "4",
      attributes: { unit_of_measurement: "kWh" },
    };
    window.__dashboardHass.states["sensor.fridge_cost"] = {
      state: "0.4",
      attributes: {},
    };
    window.__dashboardCard.hass = window.__dashboardHass;
  });

  await expect(tile).toContainText("Energy Jul 10-12: 7 kWh · $0.70");
  expect(insightCalls).toBe(1);
});

test("appliance grid switches today's selection to historical layout after midnight", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-12T23:59:00.000Z") });
  await mockPanelApi(page);
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-appliance-grid",
    {
      title: "Appliances",
      appliances: [{
        circuit_id: "fridge",
        name: "Fridge",
        activity_entity: "sensor.fridge_activity",
        energy_today_entity: "sensor.fridge_energy",
      }],
    },
    {
      "sensor.fridge_activity": {
        state: "Running",
        attributes: { is_running: true },
      },
      "sensor.fridge_energy": {
        state: "3",
        attributes: { unit_of_measurement: "kWh" },
      },
    },
  );
  await expect(card.getByRole("tab", { name: "Running", exact: true })).toHaveCount(1);
  await expect(card.locator('[data-appliance-id="fridge"]')).toContainText("Energy today");

  await page.clock.fastForward(2 * 60_000);
  await page.evaluate(() => {
    window.__dashboardCard.hass = window.__dashboardHass;
  });

  await expect(card.getByRole("tab", { name: "Running", exact: true })).toHaveCount(0);
  await expect(card.locator('[data-appliance-id="fridge"]')).toContainText("Energy Jul 12");
  await expect(card.locator('[data-appliance-id="fridge"]')).not.toContainText("Energy today");
});

test("appliance totals retry when the first post-midnight payload is stale", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-12T23:59:00.000Z") });
  let insightCalls = 0;
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/appliance_insights")) return false;
    insightCalls += 1;
    await route.fulfill({
      json: {
        status: "ok",
        items: [{
          circuit_id: "fridge",
          daily_totals: insightCalls > 1
            ? [{ date: "2026-07-12", energy_kwh: 2.5, cost: 0.75 }]
            : [],
        }],
        whole_house: [],
      },
    });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-appliance-grid",
    {
      title: "Appliances",
      api_path: "circuitsetup_energy_analyzer/appliance_insights",
      appliances: [{
        circuit_id: "fridge",
        name: "Fridge",
        energy_today_entity: "sensor.fridge_energy",
      }],
    },
    {
      "sensor.fridge_energy": {
        state: "2.5",
        attributes: { unit_of_measurement: "kWh" },
      },
    },
    { time_zone: "UTC" },
  );

  await page.clock.fastForward(2 * 60_000);
  await page.evaluate(() => {
    window.__dashboardHass.states["sensor.fridge_energy"].state = "0";
    window.__dashboardCard.hass = window.__dashboardHass;
  });

  await expect.poll(() => insightCalls).toBe(1);
  await expect.poll(() => page.evaluate(() => (
    window.__dashboardCard._applianceRangeReloadTimer
  ))).toBeGreaterThan(0);
  await page.clock.fastForward(30_000);
  await expect.poll(() => insightCalls).toBe(2);
  await expect(card.locator('[data-appliance-id="fridge"]'))
    .toContainText("Energy Jul 12: 2.5 kWh · $0.75");
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
        energy_cost_history: "Energy and cost history",
        unavailable: "Unavailable",
      },
    },
    {},
  );

  await expect(card).toBeHidden();
  await expect(card).not.toContainText("Energy and costs");
  await expect(card).not.toContainText("Today versus normal");
  await expect(card.locator(".metric")).toHaveCount(0);
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
  await expect(card).toBeVisible();
  await expect(card).toContainText("Energy and costs");
  await expect(card).toContainText("Energy and cost history");
  await expect(card.locator("svg.chart").first()).toBeVisible();
  const completedHistoryLink = card.locator("[data-chart-history]");
  await expect(completedHistoryLink).toBeVisible();
  expect(await completedHistoryLink.evaluate((link) => {
    const url = new URL(link.href);
    return {
      entities: url.searchParams.get("entity_id"),
      start: url.searchParams.get("start_date"),
      end: url.searchParams.get("end_date"),
    };
  })).toEqual({
    entities: null,
    start: "2026-07-03T12:00:00.000Z",
    end: "2026-07-10T11:59:59.999Z",
  });
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

test("energy and cost history includes live monitored totals for today", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-26T18:00:00.000Z") });
  let insightCalls = 0;
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/appliance_insights")) return false;
    insightCalls += 1;
    const completed = {
      date: "2026-07-26",
      energy_kwh: 3.6,
      cost: 0.78,
      cost_source: "recorded",
    };
    await route.fulfill({
      json: {
        status: "ok",
        items: insightCalls > 1 ? [
          {
            entry_id: "entry-1",
            circuit_id: "fridge",
            display_name: "Fridge",
            daily_totals: insightCalls > 2 ? [completed] : [],
          },
          {
            entry_id: "entry-1",
            circuit_id: "hvac",
            display_name: "HVAC",
            daily_totals: [completed],
          },
        ] : [],
        whole_house: insightCalls > 1 ? [{
          entry_id: "entry-1",
          circuit_id: "mains",
          daily_totals: [completed],
        }] : [],
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
      primary_mains: {
        circuit_id: "mains",
        daily_energy_usage_entity: "sensor.mains_energy_today",
        cost_today_entity: "sensor.mains_cost_today",
      },
      appliances: [
        {
          circuit_id: "fridge",
          energy_today_entity: "sensor.fridge_energy",
          cost_today_entity: "sensor.fridge_cost",
        },
        {
          circuit_id: "hvac",
          energy_today_entity: "sensor.hvac_energy",
          cost_today_entity: "sensor.hvac_cost",
        },
      ],
      labels: {
        no_history: "No running history is available for this period.",
      },
    },
    {
      "sensor.mains_energy_today": { state: "unavailable", attributes: {} },
      "sensor.mains_cost_today": { state: "unavailable", attributes: {} },
      "sensor.fridge_energy": { state: "1.4", attributes: { unit_of_measurement: "kWh" } },
      "sensor.fridge_cost": { state: "0.28", attributes: {} },
      "sensor.hvac_energy": { state: "2.2", attributes: { unit_of_measurement: "kWh" } },
      "sensor.hvac_cost": { state: "0.5", attributes: {} },
    },
    { time_zone: "UTC" },
    {
      start: "2026-07-25T00:00:00.000Z",
      end: "2026-07-26T23:59:59.999Z",
      compare: false,
    },
  );

  await expect(card).toContainText("Energy and cost history");
  await expect(card).not.toContainText("No running history");
  await expect(card.locator("[data-energy-bar]")).toHaveCount(1);
  await expect(card.locator('[data-cost-source="current"]')).toHaveCount(1);
  await page.evaluate(() => {
    window.__setDashboardState("sensor.mains_cost_today", { state: "1.23", attributes: {} });
    window.__setDashboardState("sensor.hvac_energy", {
      state: "unavailable",
      attributes: { unit_of_measurement: "kWh" },
    });
    window.__dashboardCard.hass = window.__dashboardHass;
  });
  await expect(card.locator("[data-energy-bar]")).toHaveCount(0);
  await expect(card.locator('[data-cost-source="current"]')).toHaveCount(1);
  await page.clock.fastForward("06:01:00");
  await page.evaluate(() => {
    window.__setDashboardState("sensor.mains_energy_today", {
      state: "0.2",
      attributes: { unit_of_measurement: "kWh" },
    });
    window.__setDashboardState("sensor.mains_cost_today", { state: "0.04", attributes: {} });
    window.__dashboardCard.hass = window.__dashboardHass;
  });
  await expect.poll(() => insightCalls).toBe(2);
  await expect.poll(() => page.evaluate(() => (
    Boolean(window.__dashboardCard._insightsReloadTimer)
  ))).toBe(true);
  await page.clock.fastForward(30_000);
  await expect.poll(() => insightCalls).toBe(3);
  await expect(card.locator("[data-energy-bar]")).toHaveCount(1);
  await expect(card.locator('[data-cost-source="recorded"]')).toHaveCount(1);
  await expect(card.locator('[data-cost-source="current"]')).toHaveCount(0);
});

test("no-mains energy history retries the selected appliance after midnight", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-27T00:01:00.000Z") });
  let insightCalls = 0;
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/appliance_insights")) return false;
    insightCalls += 1;
    const completed = {
      date: "2026-07-26",
      energy_kwh: 2.4,
      cost: 0.48,
      cost_source: "recorded",
    };
    await route.fulfill({
      json: {
        status: "ok",
        items: [
          {
            entry_id: "other-entry",
            circuit_id: "other",
            display_name: "Other entry",
            daily_totals: [completed],
          },
          {
            entry_id: "entry-1",
            circuit_id: "fridge",
            display_name: "Fridge",
            daily_totals: insightCalls > 1 ? [completed] : [],
          },
          {
            entry_id: "entry-1",
            circuit_id: "hvac",
            display_name: "HVAC",
            daily_totals: [completed],
          },
        ],
        whole_house: [],
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
      appliances: [],
    },
    {},
    { time_zone: "UTC" },
    {
      start: "2026-07-25T00:00:00.000Z",
      end: "2026-07-26T23:59:59.999Z",
      compare: false,
    },
  );

  await expect(card.locator("[data-energy-selection]")).toHaveValue("fridge");
  await expect.poll(() => page.evaluate(() => (
    Boolean(window.__dashboardCard._insightsReloadTimer)
  ))).toBe(true);
  await page.clock.fastForward(30_000);
  await expect.poll(() => insightCalls).toBe(2);
  await expect(card.locator("[data-energy-bar]")).toHaveCount(1);
});

test("no-mains energy history waits for an appliance selection", async ({ page }) => {
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/appliance_insights")) return false;
    await route.fulfill({
      json: { status: "ok", items: [], whole_house: [] },
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
      appliances: [{
        circuit_id: "fridge",
        energy_today_entity: "sensor.fridge_energy",
        cost_today_entity: "sensor.fridge_cost",
      }],
    },
    {
      "sensor.fridge_energy": { state: "1.4", attributes: {} },
      "sensor.fridge_cost": { state: "0.28", attributes: {} },
    },
  );

  await expect(card.locator("[data-energy-selection] option")).toHaveCount(0);
  await expect(card.locator("[data-energy-bar]")).toHaveCount(0);
  await expect(card.locator('[data-cost-source="current"]')).toHaveCount(0);
});

test("Now resets the dashboard date range shared with graph history requests", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-24T12:00:00.000Z") });
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
  await expect(selector).toContainText("Jul 10–Jul 12");
  await selector.locator("[data-range-previous]").click();
  await expect.poll(() => page.evaluate(() => (
    JSON.parse(localStorage.getItem("circuitsetup-energy-analyzer-dashboard-range")).start
  ))).toBe("2026-07-07T00:00:00.000Z");
  await selector.locator("[data-range-next]").click();
  await expect.poll(() => page.evaluate(() => (
    JSON.parse(localStorage.getItem("circuitsetup-energy-analyzer-dashboard-range")).start
  ))).toBe("2026-07-10T00:00:00.000Z");
  await selector.locator("[data-range-now]").dispatchEvent("click");
  const nowRange = await page.evaluate(() => (
    JSON.parse(localStorage.getItem("circuitsetup-energy-analyzer-dashboard-range"))
  ));
  expect(nowRange).toEqual({
    start: "2026-07-24T00:00:00.000Z",
    end: "2026-07-24T23:59:59.999Z",
    compare: false,
  });
  await expect.poll(() => page.evaluate(() => (
    localStorage.getItem("circuitsetup-energy-analyzer-dashboard-range-preset")
  ))).toBe("today");
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
  const historyLink = card.locator("[data-chart-history]");
  await expect(historyLink).toBeVisible();
  await expect.poll(() => historyLink.evaluate((link) => (
    new URL(link.href).searchParams.get("entity_id")
  ))).toBe("sensor.dryer_l1_power,sensor.dryer_l2_power");
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
  await historyLink.click();
  await expect(page).toHaveURL(/\/history\?.*back=1/);
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
      if (window.__wsCalls.length === 2) throw new Error("temporary statistics failure");
      const result = {
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
      return window.__wsCalls.length === 3
        ? new Promise((resolve) => {
          window.__resolveStatisticsTail = () => resolve(result);
        })
        : result;
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
  await page.waitForFunction(() => window.__dashboardCard._historyRefreshInFlight === false);
  await page.evaluate(() => {
    window.__dashboardCard.hass = window.__dashboardHass;
  });
  await expect.poll(() => page.evaluate(() => window.__wsCalls.length)).toBe(3);
  expect(await page.evaluate(() => window.__wsCalls[2])).toEqual({
    type: "recorder/statistics_during_period",
    start_time: "2026-07-24T01:59:59.000Z",
    end_time: "2026-07-24T23:59:59.999Z",
    statistic_ids: ["sensor.fridge_power"],
    period: "hour",
    types: ["mean"],
  });
  await page.evaluate(() => {
    window.__dashboardCard.hass = window.__dashboardHass;
    window.__resolveStatisticsTail();
  });
  await page.waitForFunction(() => window.__dashboardCard._historyRefreshInFlight === false);
  await page.evaluate(() => {
    window.__dashboardCard.hass = window.__dashboardHass;
  });
  await page.waitForTimeout(50);
  expect(await page.evaluate(() => window.__wsCalls.length)).toBe(3);
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
        { state: "60", last_changed: "2026-07-12T23:45:00.000Z" },
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
  await page.evaluate(() => {
    window.__dashboardCard._historyRefreshDue = true;
    window.__dashboardCard._render();
  });
  await expect.poll(() => page.evaluate(() => window.__wsCalls.length)).toBe(2);
  expect(await page.evaluate(() => window.__wsCalls[1].start_time))
    .toBe("2026-07-12T22:59:59.000Z");
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

test("dashboard date picker calendar survives current-range refreshes", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-26T12:00:00.000Z") });
  await page.addInitScript(() => {
    customElements.define("ha-date-range-picker", class extends HTMLElement {
      connectedCallback() {
        this.innerHTML = "<button type=\"button\">Calendar</button>";
      }
    });
  });
  await mockPanelApi(page);
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-date-range",
    {},
    {},
    { time_zone: "UTC" },
    {
      start: "2026-07-26T00:00:00.000Z",
      end: "2026-07-26T23:59:59.999Z",
      compare: false,
    },
  );
  await page.waitForFunction(() => window.__dashboardCard._loading === false);
  await card.locator("ha-date-range-picker button").click();
  await card.locator("ha-date-range-picker").evaluate((picker) => {
    window.__openDatePicker = picker;
  });
  expect(await page.evaluate(() => window.__dashboardCard._datePickerOpen)).toBe(true);
  expect(await page.evaluate(() => ({
    minimal: window.__openDatePicker.minimal,
    placement: window.__openDatePicker.popoverPlacement,
  }))).toEqual({ minimal: true, placement: "top-start" });

  await page.evaluate(() => {
    window.dispatchEvent(new Event("circuitsetup-dashboard-data-changed"));
    window.__dashboardCard.hass = window.__dashboardHass;
  });

  expect(await page.evaluate(() => (
    window.__openDatePicker.isConnected
    && window.__dashboardCard.shadowRoot.querySelector("ha-date-range-picker")
      === window.__openDatePicker
  ))).toBe(true);
  await page.evaluate(() => {
    window.__openDatePicker.dispatchEvent(new CustomEvent("picker-closed"));
  });
  expect(await page.evaluate(() => window.__dashboardCard._datePickerOpen)).toBe(false);
});

test("dashboard date picker applies repeated ranges before the stock close finishes", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-26T12:00:00.000Z") });
  await page.addInitScript(() => {
    customElements.define("ha-date-range-picker", class extends HTMLElement {
      connectedCallback() {
        this.innerHTML = "<button type=\"button\">Calendar</button>";
      }
    });
  });
  await mockPanelApi(page);
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-date-range",
    {},
    {},
    { time_zone: "UTC" },
    {
      start: "2026-07-26T00:00:00.000Z",
      end: "2026-07-26T23:59:59.999Z",
      compare: false,
    },
  );

  for (const range of [
    ["2026-07-23T00:00:00.000Z", "2026-07-24T23:59:59.999Z"],
    ["2026-07-24T00:00:00.000Z", "2026-07-26T23:59:59.999Z"],
  ]) {
    await card.locator("ha-date-range-picker button").click();
    await card.locator("ha-date-range-picker").evaluate((picker, selected) => {
      window.__openDatePicker = picker;
      picker.dispatchEvent(new CustomEvent("value-changed", {
        detail: {
          value: {
            startDate: new Date(selected[0]),
            endDate: new Date(selected[1]),
          },
        },
      }));
    }, range);
    await expect.poll(() => page.evaluate(() => (
      JSON.parse(localStorage.getItem("circuitsetup-energy-analyzer-dashboard-range"))
    ))).toEqual({
      start: range[0],
      end: range[1],
      compare: false,
    });
    expect(await page.evaluate(() => ({
      connected: window.__openDatePicker.isConnected,
      open: window.__dashboardCard._datePickerOpen,
    }))).toEqual({ connected: true, open: true });
    await page.evaluate(() => {
      window.__openDatePicker.dispatchEvent(new CustomEvent("picker-closed"));
    });
    await expect.poll(() => page.evaluate(() => (
      window.__dashboardCard._datePickerOpen
    ))).toBe(false);
  }
});

test("dashboard date picker applies one calendar click as a single day", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-26T12:00:00.000Z") });
  await page.addInitScript(() => {
    customElements.define("ha-date-range-picker", class extends HTMLElement {
      constructor() {
        super();
        this.attachShadow({ mode: "open" });
        this.updateComplete = Promise.resolve();
      }

      open() {
        this._wrapper = document.createElement("wa-popover");
        this.shadowRoot.replaceChildren(this._wrapper);
      }

      show() {
        const inner = document.createElement("date-range-picker");
        inner.attachShadow({ mode: "open" });
        this._calendar = document.createElement("calendar-range");
        inner.shadowRoot.append(this._calendar);
        inner.updateComplete = Promise.resolve();
        this._wrapper.dispatchEvent(new CustomEvent("wa-after-show"));
        this.shadowRoot.append(inner);
      }

      selectSingle(date) {
        this._calendar.dispatchEvent(new CustomEvent("rangestart", {
          detail: new Date(date),
        }));
        this.dispatchEvent(new CustomEvent("value-changed", {
          detail: {
            value: {
              startDate: this.startDate,
              endDate: this.endDate,
            },
          },
        }));
      }
    });
  });
  await mockPanelApi(page);
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-date-range",
    {},
    {},
    { time_zone: "America/New_York" },
    {
      start: "2026-07-22T04:00:00.000Z",
      end: "2026-07-24T03:59:59.999Z",
      compare: false,
    },
  );

  await card.locator("[data-range-open]").click();
  await card.locator("ha-date-range-picker").evaluate((picker) => {
    picker.show();
  });
  await card.locator("ha-date-range-picker").evaluate((picker) => {
    picker.selectSingle("2026-07-24T00:00:00.000Z");
  });
  await expect.poll(() => page.evaluate(() => (
    JSON.parse(localStorage.getItem("circuitsetup-energy-analyzer-dashboard-range"))
  ))).toEqual({
    start: "2026-07-24T04:00:00.000Z",
    end: "2026-07-25T03:59:59.999Z",
    compare: false,
  });
});

test("dashboard date picker survives a live refresh that races its open event", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-26T12:00:00.000Z") });
  await page.addInitScript(() => {
    customElements.define("ha-date-range-picker", class extends HTMLElement {
      open() {
        window.__openDatePicker = this;
      }
    });
  });
  await mockPanelApi(page);
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-date-range",
    {},
    {},
    { time_zone: "UTC" },
    {
      start: "2026-07-26T00:00:00.000Z",
      end: "2026-07-26T23:59:59.999Z",
      compare: false,
    },
  );

  await card.locator("[data-range-open]").click();
  await page.evaluate(() => {
    window.__dashboardCard.hass = window.__dashboardHass;
  });

  expect(await page.evaluate(() => (
    window.__openDatePicker.isConnected
    && window.__dashboardCard.shadowRoot.querySelector("ha-date-range-picker")
      === window.__openDatePicker
  ))).toBe(true);
});

test("dashboard date picker receives Home Assistant before connecting", async ({ page }) => {
  await page.addInitScript(() => {
    window.__datePickerConnectedWithoutHass = false;
    customElements.define("ha-date-range-picker", class extends HTMLElement {
      connectedCallback() {
        if (!this.hass) window.__datePickerConnectedWithoutHass = true;
      }
    });
  });
  await mockPanelApi(page);
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-date-range",
    {},
    {},
  );

  await expect(card.locator("ha-date-range-picker")).toHaveCount(1);
  expect(await card.locator("ha-date-range-picker").evaluate((picker) => ({
    connectedWithoutHass: window.__datePickerConnectedWithoutHass,
    receivedHass: picker.hass === window.__dashboardHass,
  }))).toEqual({
    connectedWithoutHass: false,
    receivedHass: true,
  });
});

test("dashboard date selector loads every stock Energy control", async ({ page }) => {
  await page.addInitScript(() => {
    customElements.define("ha-date-range-picker", class extends HTMLElement {});
    window.__dateControlHelperLoads = 0;
    window.loadCardHelpers = async () => ({
      createCardElement() {
        window.__dateControlHelperLoads += 1;
        for (const tag of ["ha-dropdown", "ha-dropdown-item", "ha-ripple", "ha-spinner"]) {
          if (!customElements.get(tag)) customElements.define(tag, class extends HTMLElement {});
        }
      },
    });
  });
  await mockPanelApi(page);
  await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-date-range",
    {},
    {},
  );

  await expect.poll(() => page.evaluate(() => window.__dateControlHelperLoads)).toBe(1);
  expect(await page.evaluate(() => (
    ["ha-dropdown", "ha-dropdown-item", "ha-ripple", "ha-spinner"]
      .every((tag) => Boolean(customElements.get(tag)))
  ))).toBe(true);
});

test("dashboard date selector mirrors stock Energy controls and presets", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-24T12:00:00.000Z") });
  await mockPanelApi(page);
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-date-range",
    {},
    {},
  );

  await expect(card.locator(".row > .backdrop")).toHaveCount(1);
  await expect(card.locator(".content > .date-picker-icon ha-date-range-picker")).toHaveCount(1);
  await expect(card.locator(".date-range ha-ripple")).toHaveCount(1);
  await expect(card.locator(".date-range ha-spinner.loading-indicator")).toHaveCount(1);
  const narrow = await card.evaluate((element) => element._narrow);
  await expect(card.locator(".date-actions ha-button[data-range-now]")).toHaveCount(narrow ? 0 : 1);
  await expect(card.locator(".date-actions > .overflow > ha-icon-button[data-range-previous]")).toHaveCount(1);
  await expect(card.locator(".date-actions > .overflow > ha-icon-button[data-range-next]")).toHaveCount(1);
  await expect(card.locator("ha-dropdown ha-dropdown-item[data-range-compare]")).toHaveCount(1);
  await expect(card.locator("ha-dropdown ha-dropdown-item[data-range-download]")).toHaveCount(1);
  expect(await card.locator("ha-date-range-picker").evaluate((picker) => (
    Object.keys(picker.ranges || {})
  ))).toEqual([
    "Today",
    "Yesterday",
    "This week",
    "This month",
    "This quarter",
    "This year",
    "Last 7 days",
    "Last 30 days",
    "Last 365 days",
    "Last 12 months",
  ]);
});

test("dashboard date preset applies before the picker closes", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-24T12:00:00.000Z") });
  await page.addInitScript(() => {
    customElements.define("ha-date-range-picker", class extends HTMLElement {});
  });
  await mockPanelApi(page);
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-date-range",
    {},
    {},
    { time_zone: "UTC" },
    {
      start: "2026-07-24T00:00:00.000Z",
      end: "2026-07-24T23:59:59.999Z",
      compare: false,
    },
  );

  await card.locator("ha-date-range-picker").evaluate((picker) => {
    const [startDate, endDate] = picker.ranges.Yesterday;
    picker.dispatchEvent(new CustomEvent("value-changed", {
      detail: { value: { startDate, endDate } },
    }));
    picker.dispatchEvent(new CustomEvent("preset-selected", {
      detail: { index: 1 },
    }));
    window.__rangeWhenPresetCloses = JSON.parse(
      localStorage.getItem("circuitsetup-energy-analyzer-dashboard-range"),
    );
  });

  expect(await page.evaluate(() => window.__rangeWhenPresetCloses)).toEqual({
    start: "2026-07-23T00:00:00.000Z",
    end: "2026-07-23T23:59:59.999Z",
    compare: false,
  });
  expect(await page.evaluate(() => (
    localStorage.getItem("circuitsetup-energy-analyzer-dashboard-range-preset")
  ))).toBe("yesterday");
});

test("dashboard date selector shows the stock delayed loading indicator", async ({ page }) => {
  await mockPanelApi(page);
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-date-range",
    {},
    {},
  );

  await card.locator("[data-range-previous]").click();
  await expect(card.locator("ha-spinner.loading-indicator")).toHaveClass(/is-loading/, {
    timeout: 1_000,
  });
  await page.evaluate(() => {
    window.dispatchEvent(new Event("circuitsetup-dashboard-data-changed"));
  });
  await expect(card.locator("ha-spinner.loading-indicator")).not.toHaveClass(/is-loading/);
});

test("dashboard date selector uses stock responsive overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await mockPanelApi(page);
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-date-range",
    {},
    {},
  );
  await expect.poll(() => card.evaluate((element) => element._narrow)).toBe(true);
  await expect(card.locator("ha-button[data-range-now]")).toHaveCount(0);
  await expect(card.locator("ha-dropdown-item[data-range-now]")).toHaveCount(1);
  await expect(card.locator(".overflow > ha-icon-button[data-range-previous]")).toHaveCount(1);

  await card.evaluate((element) => {
    element.style.width = "250px";
    element._measure();
  });
  await expect.poll(() => card.evaluate((element) => element._collapseButtons)).toBe(true);
  await expect(card.locator(".overflow > ha-icon-button[data-range-previous]")).toHaveCount(0);
  await expect(card.locator("ha-dropdown-item[data-range-previous]")).toHaveCount(1);
});

test("dashboard date selector reattaches its resize observer", async ({ page }) => {
  await page.addInitScript(() => {
    window.__dateSelectorObserveCalls = 0;
    window.ResizeObserver = class {
      observe() {
        window.__dateSelectorObserveCalls += 1;
      }

      disconnect() {}
    };
  });
  await mockPanelApi(page);
  await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-date-range",
    {},
    {},
  );
  await expect.poll(() => page.evaluate(() => window.__dateSelectorObserveCalls)).toBe(1);

  await page.evaluate(() => {
    const card = window.__dashboardCard;
    const parent = card.parentElement;
    card.remove();
    parent.append(card);
  });

  await expect.poll(() => page.evaluate(() => window.__dateSelectorObserveCalls)).toBe(2);
});

test("dashboard date selector uses stock month navigation within history bounds", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-24T12:00:00.000Z") });
  await mockPanelApi(page);
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-date-range",
    {},
    {},
    { time_zone: "UTC" },
    {
      start: "2026-06-01T00:00:00.000Z",
      end: "2026-06-30T23:59:59.999Z",
      compare: false,
    },
  );

  await card.locator("[data-range-previous]").click();
  await expect.poll(() => page.evaluate(() => (
    JSON.parse(localStorage.getItem("circuitsetup-energy-analyzer-dashboard-range"))
  ))).toEqual({
    start: "2026-05-01T00:00:00.000Z",
    end: "2026-05-31T23:59:59.999Z",
    compare: false,
  });

  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent("circuitsetup-dashboard-range-changed", {
      detail: {
        start: "2026-06-01T00:00:00.000Z",
        end: "2026-06-30T23:59:59.999Z",
        compare: false,
      },
    }));
  });
  await card.locator("[data-range-now]").click();
  await expect.poll(() => page.evaluate(() => (
    JSON.parse(localStorage.getItem("circuitsetup-energy-analyzer-dashboard-range"))
  ))).toEqual({
    start: "2026-07-24T00:00:00.000Z",
    end: "2026-07-24T23:59:59.999Z",
    compare: false,
  });
  await expect.poll(() => page.evaluate(() => (
    localStorage.getItem("circuitsetup-energy-analyzer-dashboard-range-preset")
  ))).toBe("today");
});

test("dashboard date selector preserves partial current calendar preset navigation", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-24T12:00:00.000Z") });
  await mockPanelApi(page);
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-date-range",
    {},
    {},
    { time_zone: "UTC" },
  );
  const cases = [
    {
      index: 2,
      key: "this_week",
      start: "2026-07-19T00:00:00.000Z",
      end: "2026-07-25T23:59:59.999Z",
      previous: ["2026-07-12T00:00:00.000Z", "2026-07-18T23:59:59.999Z"],
    },
    {
      index: 3,
      key: "this_month",
      start: "2026-07-01T00:00:00.000Z",
      end: "2026-07-31T23:59:59.999Z",
      previous: ["2026-06-01T00:00:00.000Z", "2026-06-30T23:59:59.999Z"],
    },
    {
      index: 4,
      key: "this_quarter",
      start: "2026-07-01T00:00:00.000Z",
      end: "2026-09-30T23:59:59.999Z",
      previous: ["2026-04-01T00:00:00.000Z", "2026-06-30T23:59:59.999Z"],
    },
    {
      index: 5,
      key: "this_year",
      start: "2026-01-01T00:00:00.000Z",
      end: "2026-12-31T23:59:59.999Z",
      previous: ["2025-01-01T00:00:00.000Z", "2025-12-31T23:59:59.999Z"],
    },
  ];

  for (const item of cases) {
    await card.locator("ha-date-range-picker").evaluate((picker, preset) => {
      picker.dispatchEvent(new CustomEvent("value-changed", {
        bubbles: true,
        composed: true,
        detail: {
          value: {
            startDate: new Date(preset.start),
            endDate: new Date(preset.end),
          },
        },
      }));
      picker.dispatchEvent(new CustomEvent("preset-selected", {
        bubbles: true,
        composed: true,
        detail: { index: preset.index },
      }));
    }, item);
    await expect.poll(() => page.evaluate(() => [
      window.__dashboardCard._rangePresetKey,
      localStorage.getItem("circuitsetup-energy-analyzer-dashboard-range-preset"),
    ])).toEqual([item.key, item.key]);
    await card.locator("[data-range-previous]").click();
    await expect.poll(() => page.evaluate(() => {
      const range = JSON.parse(
        localStorage.getItem("circuitsetup-energy-analyzer-dashboard-range"),
      );
      return [range.start, range.end];
    })).toEqual(item.previous);
  }
});

test("dashboard date selector matches stock cross-year date formatting", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-24T12:00:00.000Z") });
  await mockPanelApi(page);
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-date-range",
    {},
    {},
    { time_zone: "UTC" },
    {
      start: "2025-12-31T00:00:00.000Z",
      end: "2026-01-01T23:59:59.999Z",
      compare: false,
    },
  );

  await expect(card.locator("[data-range-label]")).toHaveText("Dec 31–Jan 1");
  await expect(card.locator("[data-range-subtitle]")).toHaveText("2025–2026");
});

test("dashboard date range is bounded by retained history and today", async ({ page }) => {
  test.info().annotations.push(
    { type: "allow-browser-error", description: "503 http://127.0.0.1:4173/api/circuitsetup_energy_analyzer/appliance_insights" },
    { type: "allow-browser-error", description: "Failed to load resource: the server responded with a status of 503" },
    { type: "allow-browser-error", description: "appliance_insights: net::ERR_ABORTED" },
  );
  await page.clock.install({ time: new Date("2026-07-24T12:00:00.000Z") });
  let insightCalls = 0;
  let failNext = false;
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/appliance_insights")) return false;
    insightCalls += 1;
    if (failNext) {
      failNext = false;
      await route.fulfill({ status: 503, body: "" });
      return true;
    }
    await route.fulfill({
      json: {
        status: "ok",
        items: [{
          entry_id: "entry-1",
          daily_totals: [
            { date: "2026-07-10", energy_kwh: 1 },
            { date: "2026-07-11", energy_kwh: 2 },
          ],
        }],
        whole_house: [{
          entry_id: "entry-1",
          daily_totals: [{ date: "2026-07-12", energy_kwh: 10 }],
        }],
      },
    });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-date-range",
    {
      api_path: "circuitsetup_energy_analyzer/appliance_insights",
      entry_id: "entry-1",
    },
    {},
    { time_zone: "UTC" },
    {
      start: "2026-07-11T00:00:00.000Z",
      end: "2026-07-11T23:59:59.999Z",
      compare: false,
    },
  );
  await expect.poll(() => page.evaluate(() => (
    window.__dashboardCard._historyBoundsLoaded
  ))).toBe(true);
  failNext = true;
  const callsBeforeFailure = insightCalls;
  await page.evaluate(() => {
    window.__dashboardCard._historyBoundsLoaded = false;
    window.__dashboardCard._render();
  });
  await expect.poll(() => insightCalls).toBe(callsBeforeFailure + 1);
  await expect.poll(() => page.evaluate(() => (
    window.__dashboardCard._historyBoundsReloadTimer
  ))).toBeGreaterThan(0);
  await page.clock.fastForward(5_000);
  await expect.poll(() => insightCalls).toBe(callsBeforeFailure + 2);
  await expect.poll(() => card.locator("[data-range-previous]").getAttribute("disabled"))
    .toBeNull();

  await card.locator("ha-date-range-picker").evaluate((picker) => {
    picker.dispatchEvent(new CustomEvent("value-changed", {
      bubbles: true,
      composed: true,
      detail: {
        value: {
          startDate: new Date("2026-07-01T00:00:00.000Z"),
          endDate: new Date("2026-07-03T23:59:59.999Z"),
        },
      },
    }));
  });
  await expect.poll(() => page.evaluate(() => (
    JSON.parse(localStorage.getItem("circuitsetup-energy-analyzer-dashboard-range"))
  ))).toEqual({
    start: "2026-07-10T00:00:00.000Z",
    end: "2026-07-12T23:59:59.999Z",
    compare: false,
  });

  await card.locator("ha-date-range-picker").evaluate((picker) => {
    picker.dispatchEvent(new CustomEvent("value-changed", {
      bubbles: true,
      composed: true,
      detail: {
        value: {
          startDate: new Date("2026-08-01T00:00:00.000Z"),
          endDate: new Date("2026-08-03T23:59:59.999Z"),
        },
      },
    }));
  });
  await expect.poll(() => page.evaluate(() => (
    JSON.parse(localStorage.getItem("circuitsetup-energy-analyzer-dashboard-range"))
  ))).toEqual({
    start: "2026-07-22T00:00:00.000Z",
    end: "2026-07-24T23:59:59.999Z",
    compare: false,
  });
  await expect(card.locator("[data-range-next]")).toHaveAttribute("disabled", "");
});

test("historical graph tooltip survives Home Assistant state updates", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-07-12T12:00:00.000Z") });
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.includes("/history/period")) return false;
    await route.fulfill({
      json: [[
        {
          entity_id: "sensor.fridge_power",
          state: "100",
          last_changed: "2026-07-10T00:00:00.000Z",
        },
        { state: "150", last_changed: "2026-07-10T12:00:00.000Z" },
      ]],
    });
    return true;
  });
  const card = await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-context-graph",
    {
      title: "All appliance power",
      y_axis_label: "W",
      entities: [{
        entity: "sensor.fridge_power",
        name: "Fridge",
        series_id: "circuit:fridge",
        axis: "left",
      }],
    },
    {
      "sensor.fridge_power": {
        state: "200",
        attributes: { unit_of_measurement: "W" },
      },
    },
    {},
    {
      start: "2026-07-10T00:00:00.000Z",
      end: "2026-07-10T23:59:59.999Z",
      compare: false,
    },
  );
  const point = card.locator("[data-chart-point]").first();
  await expect(point).toBeVisible();
  await point.evaluate((element) => {
    const svg = element.closest("svg");
    const rect = svg.getBoundingClientRect();
    svg.dispatchEvent(new PointerEvent("pointermove", {
      bubbles: true,
      clientX: rect.left + rect.width / 2,
      clientY: rect.top + rect.height / 2,
    }));
  });
  await expect(card.locator("[data-chart-tooltip]")).toHaveAttribute("aria-hidden", "false");
  await page.evaluate(() => {
    window.__inspectedHistoricalPoint = window.__dashboardCard.shadowRoot
      .querySelector("[data-chart-point]");
    window.__dashboardCard.hass = window.__dashboardHass;
  });

  expect(await page.evaluate(() => window.__inspectedHistoricalPoint.isConnected)).toBe(true);
  await expect(card.locator("[data-chart-tooltip]")).toHaveAttribute("aria-hidden", "false");
});

test("dashboard chart legend colors stay distinct", async ({ page }) => {
  await mockPanelApi(page);
  await openDashboardCard(
    page,
    "circuitsetup-energy-analyzer-date-range",
    {},
    {},
  );

  const colors = await page.evaluate(() => {
    [
      "--energy-grid-consumption-color",
      "--energy-solar-color",
      "--energy-battery-out-color",
      "--energy-battery-in-color",
      "--energy-water-color",
      "--energy-gas-color",
    ].forEach((name) => document.documentElement.style.setProperty(name, "#123456"));
    const container = document.createElement("div");
    container.innerHTML = window.__dashboardCard._chartSvg(
      Array.from({ length: 12 }, (_, index) => ({
        name: `Series ${index + 1}`,
        points: [
          { time: Date.parse("2026-07-24T00:00:00.000Z"), value: index },
          { time: Date.parse("2026-07-24T01:00:00.000Z"), value: index + 1 },
        ],
      })),
      {
        graph_window_start: "2026-07-24T00:00:00.000Z",
        graph_window_end: "2026-07-24T01:00:00.000Z",
      },
    );
    document.body.append(container);
    return [...container.querySelectorAll(".legend-marker")]
      .map((marker) => getComputedStyle(marker).color);
  });

  expect(new Set(colors).size).toBe(colors.length);
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
  await expect(card.locator("[data-chart-point]").first()).toHaveCSS("fill", "rgb(41, 107, 174)");
  const chart = card.locator("svg.chart");
  const fullSpan = await chart.evaluate((element) => (
    Number(element.dataset.chartEnd) - Number(element.dataset.chartStart)
  ));
  const chartBox = await chart.boundingBox();
  await chart.dblclick({ position: { x: chartBox.width / 2, y: chartBox.height / 2 } });
  await expect.poll(() => chart.evaluate((element) => (
    Number(element.dataset.chartEnd) - Number(element.dataset.chartStart)
  ))).toBeLessThan(fullSpan * 0.6);
  await expect.poll(() => card.locator("[data-chart-history]").evaluate((link) => {
    const url = new URL(link.href);
    return Number(new Date(url.searchParams.get("end_date")))
      - Number(new Date(url.searchParams.get("start_date")));
  })).toBeLessThan(fullSpan * 0.6);
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

test("historical dashboard keeps live summary and house status current", async ({ page }) => {
  await mockPanelApi(page);
  await openDashboardCards(
    page,
    [
      {
        tagName: "circuitsetup-energy-analyzer-summary",
        config: {
          title: "Billing Cycle",
          entities: [{ entity: "sensor.billing_cost", name: "Cost so far" }],
        },
      },
      {
        tagName: "circuitsetup-energy-analyzer-house-flow",
        config: {
          title: "Live status",
          mode: "mains",
          setup_health_entity: "sensor.setup_health",
          primary_mains: {
            power_entities: ["sensor.mains_power"],
          },
        },
      },
    ],
    {
      "sensor.billing_cost": { state: "42.10", attributes: { unit_of_measurement: "USD" } },
      "sensor.mains_power": { state: "100", attributes: { unit_of_measurement: "W" } },
      "sensor.setup_health": { state: "Ready", attributes: {} },
    },
  );
  const summary = page.locator("circuitsetup-energy-analyzer-summary");
  const house = page.locator("circuitsetup-energy-analyzer-house-flow");
  await expect(summary).toContainText("$42.10");
  await expect(house).toContainText("House power: 100 W");
  await expect(house).toContainText("Ready");

  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent("circuitsetup-dashboard-range-changed", {
      detail: {
        start: "2026-07-10T00:00:00.000Z",
        end: "2026-07-10T23:59:59.999Z",
        compare: false,
      },
    }));
    const hass = window.__dashboardCards[0]._hass;
    hass.states["sensor.billing_cost"] = {
      state: "43.20",
      attributes: { unit_of_measurement: "USD" },
    };
    hass.states["sensor.mains_power"] = {
      state: "250",
      attributes: { unit_of_measurement: "W" },
    };
    hass.states["sensor.setup_health"] = { state: "Needs attention", attributes: {} };
    for (const card of window.__dashboardCards) card.hass = hass;
  });

  await expect(summary).toContainText("$43.20");
  await expect(house).toContainText("House power: 250 W");
  await expect(house).toContainText("Needs attention");
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
  const predictiveHealth = panel.locator("[data-appliance-health]");
  await expect(predictiveHealth).toBeVisible();
  await expect(predictiveHealth).toContainText("Possible degradation");
  await expect(predictiveHealth).toContainText("30%");
  await expect(predictiveHealth).toContainText("season: summer");
  await expect(panel.getByText("Session Timeline")).toHaveCount(0);
  await expect(panel.locator(".session-strip")).toHaveCount(0);
  await expect(panel.getByText("Appliance Notifications")).toHaveCount(0);
  await expect(panel.locator("[data-appliance-notifications]")).toHaveCount(0);
  await expect(panel.getByText("Expected Schedule")).toHaveCount(0);
  await expect(panel.locator("[data-expected-schedule]")).toHaveCount(0);
  await expect(panel.locator("[data-appliance-detail-action]")).toHaveCount(0);
});

test("Appliance Detail shows weather-adjusted HVAC efficiency", async ({ page }) => {
  await mockPanelApi(page);
  const panel = await openPanel(page, "?appliance_detail=1&circuit_id=kitchen");
  const efficiency = panel.locator("[data-hvac-efficiency]");

  await expect(efficiency).toBeVisible();
  await expect(efficiency).toContainText("80 / 100");
  await expect(efficiency).toContainText("100 is the learned baseline");
  await expect(efficiency).toContainText("Upstairs");
  await expect(efficiency).toContainText("Downstairs");
  await expect(efficiency).toContainText("10 min/°F");
  await expect(efficiency).toContainText("12.5 min/°F");
  await expect(efficiency).toContainText("Outdoor: 95°F");
  await expect(efficiency).toContainText("Gas-furnace blower proxy");
  await expect(efficiency).toContainText("Cooling blower supports air handling");
});

test("Appliance Detail omits unavailable HVAC efficiency metrics", async ({ page }) => {
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/appliance_detail")) return false;
    const payload = structuredClone(apiPayload(url.pathname));
    payload.detail.hvac_efficiency = {
      status: "learning",
      summary_score: null,
      trend: null,
      threshold_pct: 25,
      learning: {
        reference_count: 2,
        recent_count: 0,
        required_reference: 9,
        required_recent: 3,
      },
      heating: [{
        thermostat_entity_id: "climate.upstairs",
        thermostat_name: "Upstairs",
        status: "learning",
        score: null,
        baseline_minutes_per_degree: null,
        recent_minutes_per_degree: null,
        outdoor_temperature_f: null,
        attribution: "direct",
        supporting_blower_ids: [],
      }],
      cooling: [],
    };
    await route.fulfill({ json: payload });
    return true;
  });
  const panel = await openPanel(page, "?appliance_detail=1&circuit_id=kitchen");
  const efficiency = panel.locator("[data-hvac-efficiency]");

  await expect(efficiency).toContainText("Upstairs");
  await expect(efficiency).toContainText("2 of 9 reference episodes");
  await expect(efficiency).not.toContainText("0 / 100");
  await expect(efficiency).not.toContainText("0 min/°F");
  await expect(efficiency).not.toContainText("Outdoor: 0°F");
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

test("Suggested Settings uses a compact support column", async ({ page, isMobile }) => {
  test.skip(isMobile, "The desktop layout is covered here; mobile already stacks the card.");
  await mockPanelApi(page, async ({ route, url }) => {
    if (!url.pathname.endsWith("/alert_evidence")) return false;
    await route.fulfill({
      json: {
        ...evidence,
        setting_recommendations: evidence.setting_recommendations.map((recommendation) => ({
          ...recommendation,
          evidence_preview: "Observed Days: 12; Daily P95: 2.5 kWh",
        })),
      },
    });
    return true;
  });

  for (const query of [
    "?review_suggested_settings=1&circuit_id=kitchen",
    "?appliance_detail=1&circuit_id=kitchen",
  ]) {
    const panel = await openPanel(page, query);
    const layout = panel.locator(".recommendation-layout").first();
    await expect(layout.locator(".recommendation-evidence")).toContainText("Observed Days: 12");
    const card = await layout.evaluate((element) => {
      const heading = element.querySelector(".recommendation-heading");
      const summary = element.querySelector(".recommendation-summary");
      const support = element.querySelector(".recommendation-support");
      const expectedEffect = support.querySelector("p > strong");
      const evidence = support.querySelector(".recommendation-evidence > strong");
      const historicalImpact = support.querySelector(".setting-impact-preview > strong");
      const limitations = support.querySelector(".setting-impact-preview .muted > strong");
      return {
        headingPresent: Boolean(heading),
        headingBottom: heading?.getBoundingClientRect().bottom || 0,
        headingFontSize: Number.parseFloat(getComputedStyle(heading).fontSize),
        summaryTop: summary.getBoundingClientRect().top,
        summaryLeft: summary.getBoundingClientRect().left,
        supportTop: support.getBoundingClientRect().top,
        supportLeft: support.getBoundingClientRect().left,
        supportAlignContent: getComputedStyle(support).alignContent,
        expectedEffectFontSize: Number.parseFloat(getComputedStyle(expectedEffect).fontSize),
        evidenceFontSize: Number.parseFloat(getComputedStyle(evidence).fontSize),
        historicalImpactFontSize: Number.parseFloat(getComputedStyle(historicalImpact).fontSize),
        limitationsFontSize: Number.parseFloat(getComputedStyle(limitations).fontSize),
      };
    });
    expect(card.headingPresent).toBe(true);
    expect(card.summaryTop).toBeGreaterThan(card.headingBottom);
    expect(card.supportTop).toBeGreaterThan(card.headingBottom);
    expect(card.supportLeft).toBeGreaterThan(card.summaryLeft);
    expect(card.supportAlignContent).toBe("start");
    expect(card.expectedEffectFontSize).toBeLessThan(card.headingFontSize);
    expect(card.evidenceFontSize).toBeLessThan(card.headingFontSize);
    expect(card.historicalImpactFontSize).toBeLessThan(card.headingFontSize);
    expect(card.limitationsFontSize).toBeLessThan(card.headingFontSize);
  }
});

test("alert responses and setting preview actions call their services", async ({ page, isMobile }) => {
  test.skip(isMobile, "Mobile route and accessibility coverage runs separately.");
  await mockPanelApi(page);
  const panel = await openPanel(page, "?alert_id=alert-kitchen-energy");

  await panel.locator('[data-alert-decision][value="mark_expected"]').check();
  await panel.locator("#apply_alert_decision").click();
  await panel.locator('[data-alert-decision][value="mark_confirmed"]').check();
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
    "mark_alert_confirmed",
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
