# Frontend And Panel Modularization Audit

## Size And Ownership

| File | Size | Responsibilities |
|---|---:|---|
| `panel.py` | 3,451 lines | View registration, evidence, appliance detail/history, Setup Health, NILM workspace/history/validation, recommendations, routes |
| `frontend/energy-analyzer-panel.js` | 6,020 lines | Route state, API calls, actions, styles, every panel view, graphs, formatting, dashboard graph card |
| `appliance_detail.py` | 1,152 lines | Detail read model, comparisons, expectations, NILM detail, alerts |
| `coordinator.py` | 1,741 lines | Analyzer state, manager construction, orchestration, compatibility facade |

The generated graph reports zero Python import cycles, so extraction can be
compatibility-first rather than a redesign.

## Stable Contracts

Do not change the panel path, five current API paths, service names, entity IDs,
dashboard paths, query-mode precedence, or custom-element names. Keep
`energy-analyzer-panel.js` as the static entrypoint, and bump
`panel.PANEL_MODULE_VERSION` for every shipped frontend change.

## Extraction Order

1. Move pure formatters and API/request helpers.
2. Move backend route classes and payload builders behind compatibility exports.
3. Move Appliance Detail, Needs Attention, and Appliance Insights components.
4. Move NILM workspace/graph/session components and lazy-load that route.
5. Move remaining evidence, Setup Health, settings preview, and digest views.
6. Move `AnalyzerState` and manager construction only after product behavior is
   stable.

Each step keeps the stable entry modules and adds module-load/route
characterization tests. Do not add a framework or build system solely for the
split.

## Accessibility Baseline

The panel already uses semantic buttons/labels, live feedback, focus recovery,
roving NILM tabs, graph labels, and responsive CSS. It still needs graph text or
table fallbacks, browser keyboard/focus verification, contrast checks, mobile
overflow screenshots, and failure artifacts.
