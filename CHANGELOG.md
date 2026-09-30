# Better GroBro 3.1.54 — Differences from robertzaage/GroBro

Comparison baseline: `robertzaage/GroBro` main at `e4d59b20ba472853ae6ec0b7a17cf15cd774cb23` (2026-09-18).

## User-relevant differences

- Sets Home Assistant `suggested_display_precision` to 3 for all NOAH Bat1–Bat4 maximum/minimum cell-voltage sensors, preserving the existing 0.001 V scaling while making the displayed millivolt resolution consistent.
- Normalizes shortened NEO identifiers seen in passive `0x0103` diagnostics (for example `BZP4N991ML`) back to the full `QMN000...` device identity while preserving the raw identifier for diagnostics.
- Adds NOAH Battery 2/3/4 maximum and minimum cell-voltage sensors using validated register pairs 375/376, 382/383 and 389/390 with the same scaling and Home Assistant metadata as Battery 1.
- Correctly parses Growatt Function-6 write acknowledgements, eliminating false `Invalid register block range` warnings for valid NOAH writes such as registers 252, 257 and 258.
- Fixes HTTP 403 when using “Save & restart Better GroBro” by removing the forbidden Supervisor options validation endpoint and using the supported self options/restart endpoints.
- Moves expected stable/manual battery remapping messages from WARNING to DEBUG so normal NOAH/NEXA slot stabilization no longer floods the add-on log; real battery mapping problems remain warnings.
- Fixes the integrated log viewer on normal Home Assistant add-on permissions by using the self-log endpoint and isolating the current process session without requiring elevated Supervisor permissions.
- Adds an integrated log viewer that shows only entries from the current add-on startup, and makes ERROR/INFO/DEBUG logging deterministic even when logging handlers already exist.
- Adds real MQTT end-to-end validation for both NEO and NOAH and full localization coverage across all register display names, reducing regression risk without changing entity IDs or user configuration.
- Improves German, French, Spanish and Dutch Home Assistant entity names with idiomatic PV, grid, battery and BMS terminology, including rare device-specific sensors, while keeping technical IDs and MQTT topics unchanged.
- Adds a dedicated Better GroBro Ingress configuration UI that edits the official Home Assistant add-on options. Home Assistant's native Configuration tab remains available as a fallback.
- Shows the actually detected Growatt device families in the overview instead of only a generic device count.
- Adds automatic German, English, French, Spanish and Dutch localization for the Ingress UI, native add-on configuration and Home Assistant entity display names, with English fallback.
- Adds stable NOAH/NEXA battery identities and optional manual Bat2/Bat3/Bat4 assignment from detected serial numbers.
- Improves Home Assistant restart/reconnect recovery and retains important control states so values do not disappear after reloads.
- Removes retained publishing for measurement states and uses device availability instead, preventing stale power values from remaining active when telemetry stops.
- Reduces unnecessary MQTT/Home Assistant churn while preserving real state changes.
- Improves NOAH/NEXA handling, supported-device clock synchronization and optional passive diagnostics.

All other behavior is inherited from Robert Zaage's GroBro.
