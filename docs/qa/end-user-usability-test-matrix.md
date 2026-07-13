# End-User Usability Test Matrix

| Area | Required automated coverage | Current state |
|---|---|---|
| Comparisons | Same-time daily energy/runtime/count/cost, projection labels/confidence, running/idle power, demand/limits, currency, TOU, DST | Missing or partial |
| NILM identity | Stable key, assignment timeline, runtime/count, alert routing, validation gate, restart, direct-meter conversion | Partial |
| Expectations | Ranking, semantic deduplication, maximum three, setup/electrical priority, expected context, maintenance wording | Partial |
| Needs Attention | Grouping, sorting, resolution, valid actions, normal omission, NILM routes | Missing |
| Session timeline | Direct/NILM/open sessions, maintenance, alerts, local time, mobile, keyboard/session detail | Missing |
| Settings preview | Pure dry run, bounded history, counts, unsupported/insufficient history, apply/reset | Missing |
| Notifications | Categories, quiet hours, cooldown, immediate/daily/weekly modes, NILM confidence, persistence/defaults | Missing |
| Digest | Change ranking, expected-context suppression, resolved omission, NILM review, local week, idempotence | Missing |
| Schedule | Inside/outside/missed, repeated threshold, DST, unavailable schedule, maintenance | Missing |
| Appliance Insights | Direct/NILM listing, filters, sorting, missing data, stable links, mobile | Missing |
| Energy explanation | Runtime, power, cycles, mixed, contextual explanation, uncertainty, bounded contributions | Missing |
| Source trust | Fresh/stale/unavailable/missing/partial, readiness, direct evidence confidence, NILM confidence separation | Partial |
| E2E/accessibility | Major routes/actions, no JS/API errors, keyboard/focus, labels, graph fallback, contrast, touch/mobile, artifacts | Missing browser gate |

## Existing Regression Gates

- `python -m pytest`: 1,484 baseline unit tests
- `python -m pytest tests_homeassistant`: 9 lifecycle/runtime tests
- `python -m ruff check .`
- `./.codex/scripts/verify-pr.ps1 -HomeAssistant` for the final integrated pass

Browser tests must remain a separate job and must not replace unit or Home
Assistant contract coverage.
