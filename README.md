# CircuitSetup Energy Analyzer

CircuitSetup Energy Analyzer is a Home Assistant custom integration for analyzing CircuitSetup 6 Channel Energy Meter data exposed by ESPHome ATM90E32 sensors.

The integration learns conservative per-circuit baselines for single-phase appliances, dual-phase appliances, mixed circuits, and opt-in experimental mains NILM discovery. It exposes diagnostic entities, persistent notifications for important events, and Repairs for integration or source-data problems.

## Installation

This repository is structured for HACS as a custom integration. The integration files live under `custom_components/circuitsetup_energy_analyzer`.
