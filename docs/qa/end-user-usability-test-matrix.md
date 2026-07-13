# End-User Usability Test Matrix

| Area | Required automated coverage | Current state |
|---|---|---|
| Comparisons | Same-time daily energy/runtime/count/cost, projection labels/confidence, running/idle power, demand/limits, currency, TOU, DST | Covered by comparison, cost, processor, panel, and user-facing contract tests |
| NILM identity | Stable key, assignment timeline, runtime/count, alert routing, validation gate, restart, direct-meter conversion | Covered by NILM, virtual appliance, panel, storage, and HA lifecycle tests |
| Expectations | Ranking, semantic deduplication, maximum three, setup/electrical priority, expected context, maintenance wording | Covered by expectation-ranking and appliance behavior tests |
| Needs Attention | Grouping, sorting, resolution, valid actions, normal omission, NILM routes | Covered by attention, panel, dashboard, and appliance insight tests |
| Session timeline | Direct/NILM/open sessions, maintenance, alerts, local time, mobile, keyboard/session detail | Covered by session timeline, panel, and browser mobile tests |
| Settings preview | Pure dry run, bounded history, counts, unsupported/insufficient history, apply/reset | Covered by settings preview, service, panel, and storage tests |
| Notifications | Categories, quiet hours, cooldown, immediate/daily/weekly modes, NILM confidence, persistence/defaults | Covered by appliance notification, controller, storage, and panel tests |
| Digest | Change ranking, expected-context suppression, resolved omission, NILM review, local week, idempotence | Covered by weekly digest, notification controller, storage, and panel tests |
| Schedule | Inside/outside/missed, repeated threshold, DST, unavailable schedule, maintenance | Covered by expected schedule, storage, appliance detail, and panel tests |
| Appliance Insights | Direct/NILM listing, filters, sorting, missing data, stable links, mobile | Covered by appliance insight, panel, user-facing, and browser tests |
| Energy explanation | Runtime, power, cycles, mixed, contextual explanation, uncertainty, bounded contributions | Covered by appliance detail and panel tests |
| Source trust | Fresh/stale/unavailable/missing/partial, readiness, direct evidence confidence, NILM confidence separation | Covered by appliance detail, confidence calibration, and panel tests |
| E2E/accessibility | Major routes/actions, no JS/API errors, keyboard/focus, labels, graph fallback, contrast, touch/mobile, artifacts | Static browser gate covers all major routes, comparisons, sessions, feedback, settings preview, NILM decisions, Axe, mobile overflow, retry, and artifacts; the disposable Home Assistant gate covers authentication, real panel routes, a reversible service action, and dashboard create/update |

## Existing Regression Gates

- `python -m pytest`: unit and frontend contract tests
- `python -m pytest tests_homeassistant`: Home Assistant lifecycle/runtime tests
- `python -m ruff check .`
- `npm run test:e2e`: Chromium desktop/mobile, accessibility, action, retry, and overflow tests
- `python -m pytest tests_homeassistant/test_browser_e2e.py -q`: disposable Home Assistant browser smoke test
- `./.codex/scripts/verify-pr.ps1 -HomeAssistant` for the final integrated pass

Browser tests must remain a separate job and must not replace unit or Home
Assistant contract coverage.
