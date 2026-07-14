const version = new URL(import.meta.url).search;
const modulePaths = [
  "./energy-analyzer-panel-main.js",
  "./energy-analyzer-dashboard-graphs.js",
  "./energy-analyzer-panel-shell.js",
  "./energy-analyzer-appliance-views.js",
  "./energy-analyzer-nilm-workspace.js",
  "./energy-analyzer-evidence-views.js",
];
const [
  { registerEnergyAnalyzerPanel, PANEL_METHOD_DEPENDENCIES },
  { registerDashboardGraphs },
  { PanelShellMethods },
  { createApplianceViewMethods },
  { createNilmWorkspaceMethods },
  { createEvidenceViewMethods },
] = await Promise.all(
  modulePaths.map((path) => import(`${path}${version}`)),
);

registerEnergyAnalyzerPanel(registerDashboardGraphs, [
  PanelShellMethods,
  createApplianceViewMethods(PANEL_METHOD_DEPENDENCIES),
  createNilmWorkspaceMethods(PANEL_METHOD_DEPENDENCIES),
  createEvidenceViewMethods(PANEL_METHOD_DEPENDENCIES),
]);
