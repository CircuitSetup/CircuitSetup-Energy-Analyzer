# Browser E2E Results

## Gates

Commands:

```powershell
npm run test:e2e
.\.venv\Scripts\python.exe -m pytest tests_homeassistant\test_browser_e2e.py -q
```

Results on July 13, 2026:

```text
Static panel: 21 passed, 5 project-specific skips
Disposable Home Assistant: 1 passed
```

The Chromium matrix runs at 1440 x 1000 and 390 x 844. It loads the shipped
ES-module panel and English translation bundle through a disposable HTTP
harness. The tests exercise Appliance Insights filters, direct Appliance
Detail comparisons and session evidence, Setup Health, alert feedback and
settings preview, NILM decisions and assignment, keyboard tabs, mobile
overflow, and failed-request retry behavior.

A separate pytest gate starts an ephemeral Home Assistant HTTP server, creates
real authentication tokens, loads the integration and shipped panel, and visits
Appliance Insights, Appliance Detail, Setup Health, and the NILM workspace. It
also performs and verifies a reversible integration service mutation, then
creates and updates the recommended dashboard through the authenticated options
flow. This gate uses the standalone Playwright CLI rather than an interactive
browser session.

Playwright keeps screenshots only on failure and retains failure traces and
videos under `test-results/browser/`; the HTML reports are written to separate
static and Home Assistant folders under `playwright-report/`. CI uploads both
directories when the browser job fails, including the captured Home Assistant
log.
