# Better GroBro 3.1.45 — Differences from robertzaage/GroBro

Comparison baseline: `robertzaage/GroBro` main at `e4d59b20ba472853ae6ec0b7a17cf15cd774cb23` (2026-09-18).

## User-relevant differences

- Adds a dedicated Better GroBro Ingress configuration UI that edits the official Home Assistant add-on options. Home Assistant's native Configuration tab remains available as a fallback.
- Shows the actually detected Growatt device families in the overview instead of only a generic device count.
- Adds automatic German, English, French, Spanish and Dutch localization for the Ingress UI, native add-on configuration and Home Assistant entity display names, with English fallback.
- Adds stable NOAH/NEXA battery identities and optional manual Bat2/Bat3/Bat4 assignment from detected serial numbers.
- Improves Home Assistant restart/reconnect recovery and retains important control states so values do not disappear after reloads.
- Removes retained publishing for measurement states and uses device availability instead, preventing stale power values from remaining active when telemetry stops.
- Reduces unnecessary MQTT/Home Assistant churn while preserving real state changes.
- Removes the optional total_increasing decrease filter so legitimate daily, monthly and yearly energy counter resets always pass through unchanged.
- Improves NOAH/NEXA handling, supported-device clock synchronization and optional passive diagnostics.

All other behavior is inherited from Robert Zaage's GroBro.
