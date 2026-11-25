import { expect, test } from "@playwright/test";

const token = process.env.HA_ACCESS_TOKEN;
const refreshToken = process.env.HA_REFRESH_TOKEN;
const clientId = process.env.HA_CLIENT_ID;
const configEntryId = process.env.HA_CONFIG_ENTRY_ID;
const authHeaders = { Authorization: "Bearer " + token };

test("real Home Assistant loads panel routes and accepts a reversible mutation", async ({ page }) => {
  expect(token).toBeTruthy();
  await page.setExtraHTTPHeaders({ Authorization: "Bearer " + token });
  await page.addInitScript(({ accessToken, refresh, client }) => {
    localStorage.setItem("hassTokens", JSON.stringify({
      access_token: accessToken,
      refresh_token: refresh,
      expires: Date.now() + 30 * 60 * 1000,
      expires_in: 1800,
      clientId: client,
      hassUrl: window.location.origin,
    }));
  }, { accessToken: token, refresh: refreshToken, client: clientId });

  const browserErrors = [];
  const failedIntegrationResponses = [];
  page.on("pageerror", (error) => {
    const detail = error.stack || error.message || String(error);
    if (detail.includes("circuitsetup_energy_analyzer")) {
      browserErrors.push(detail);
    }
  });
  page.on("console", (message) => {
    if (
      message.type() === "error"
      && message.location().url.includes("circuitsetup_energy_analyzer")
    ) {
      browserErrors.push(JSON.stringify({
        text: message.text(),
        location: message.location(),
      }));
    }
  });
  page.on("response", (response) => {
    if (
      response.url().includes("circuitsetup_energy_analyzer")
      && response.status() >= 400
    ) {
      failedIntegrationResponses.push(
        [response.status(), response.url()].join(" "),
      );
    }
  });
  await page.route("**/api/history/period/**", (route) => route.fulfill({ json: [] }));

  const routes = [
    ["?appliance_insights=1", "Appliance Insights"],
    [`?appliance_detail=1&circuit_id=fridge&entry_id=${configEntryId}`, "Kitchen Fridge"],
    ["?setup_health=1", "Setup Health"],
    ["?nilm_workspace=1&circuit_id=mains", "Load Separation"],
  ];
  for (const [query, heading] of routes) {
    await page.goto("/circuitsetup-energy-analyzer-evidence" + query);
    const panel = page.locator("circuitsetup-energy-analyzer-panel");
    await expect(panel.locator("h1")).toHaveText(heading, { timeout: 30_000 });
    expect(await panel.textContent()).not.toMatch(
      /\b(?:config_panel|panel)\.[a-z0-9_.]+\b/i,
    );
  }

  const evidenceRoute = "/circuitsetup-energy-analyzer-evidence";
  await page.goto(evidenceRoute + "?appliance_detail=1&circuit_id=fridge");
  const panel = page.locator("circuitsetup-energy-analyzer-panel");
  await expect(panel.getByRole("heading", { name: "Choose a meter" })).toBeVisible();
  await expect(panel.locator("[data-alert-decision]")).toHaveCount(0);
  await panel.getByRole("link", { name: /garage/i }).click();
  await expect(panel.locator("h1")).toHaveText("Garage Fridge");
  const evidence = panel.getByRole("link", { name: "Open Evidence", exact: true });
  await expect(evidence).toHaveAttribute("href", /entry_id=browser-garage/);
  await evidence.click();
  await page.reload();
  await expect(panel).toContainText("Garage Fridge used more energy than usual.");
  expect(new URL(page.url()).searchParams.get("alert_id")).toBe(process.env.HA_SHARED_ALERT_ID);
  await panel.locator('[data-alert-decision][value="mark_expected"]').check();
  await panel.locator("#apply_alert_decision").click();
  await expect(panel).toContainText("Marked as expected behavior.");

  await page.goto(evidenceRoute + `?circuit_id=fridge&entry_id=${configEntryId}`);
  await expect(panel.locator("h1")).toHaveText("Kitchen Fridge", {
    timeout: 30_000,
  });
  const tuning = panel.locator('details[data-alert-disclosure="tune"]:not([open]) > summary');
  if (await tuning.count()) await tuning.click();
  await panel.locator("#relearn_baseline").click();
  await expect(panel.locator("#cancel_action_confirmation")).toBeVisible();
  await expect(panel.locator("#confirm_action")).toBeVisible();
  await panel.locator("#cancel_action_confirmation").click();
  await expect(panel.locator("ha-dialog")).toHaveCount(0);
  if (await tuning.count()) await tuning.click();
  await panel.locator("#relearn_baseline").click();
  await panel.locator("#confirm_action").click();
  await expect(panel.locator("ha-dialog")).toHaveCount(0);
  expect(browserErrors).toEqual([]);
  expect(failedIntegrationResponses).toEqual([]);
});

test("real Home Assistant creates and updates the recommended dashboard", async ({ request }) => {
  expect(token).toBeTruthy();
  expect(configEntryId).toBeTruthy();

  for (let attempt = 0; attempt < 2; attempt += 1) {
    const started = await request.post(
      "/api/config/config_entries/options/flow",
      {
        data: { handler: configEntryId },
        headers: authHeaders,
      },
    );
    expect(started.ok(), await started.text()).toBeTruthy();
    const menu = await started.json();
    expect(menu.type).toBe("menu");
    expect(menu.menu_options).toContain("dashboard");

    const selected = await request.post(
      `/api/config/config_entries/options/flow/${menu.flow_id}`,
      {
        data: { next_step_id: "dashboard" },
        headers: authHeaders,
      },
    );
    expect(selected.ok(), await selected.text()).toBeTruthy();
    const form = await selected.json();
    expect(form.type).toBe("form");
    expect(form.step_id).toBe("dashboard");

    const submitted = await request.post(
      `/api/config/config_entries/options/flow/${menu.flow_id}`,
      {
        data: {
          dashboard_layout: "simple",
          apply_entity_detail_profile: false,
          remove_dashboard: false,
        },
        headers: authHeaders,
      },
    );
    expect(submitted.ok(), await submitted.text()).toBeTruthy();
    expect((await submitted.json()).type).toBe("create_entry");
  }
});
