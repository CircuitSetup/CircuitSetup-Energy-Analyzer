const version = new URL(import.meta.url).search;
const modulePaths = [
  "./energy-analyzer-panel-main.js",
  "./energy-analyzer-dashboard-graphs.js",
];
const [{ registerEnergyAnalyzerPanel }, { registerDashboardGraphs }] = await Promise.all(
  modulePaths.map((path) => import(`${path}${version}`)),
);

registerEnergyAnalyzerPanel(registerDashboardGraphs);
