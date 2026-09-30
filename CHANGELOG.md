# Better GroBro 3.1.39 — Differences from robertzaage/GroBro

Comparison baseline: `robertzaage/GroBro` main at `e4d59b20ba472853ae6ec0b7a17cf15cd774cb23` (2026-09-18).

## User-relevant differences

- Adds a dedicated Better GroBro Ingress configuration UI that edits the official Home Assistant add-on options. Home Assistant's native Configuration tab remains available as a fallback.
- Shows the actually detected Growatt device families in the overview instead of only a generic device count.
- Adds automatic German, English, French and Spanish UI localization based on the Home Assistant language, with English fallback.
- Adds stable NOAH/NEXA battery identities and optional manual Bat2/Bat3/Bat4 assignment from detected serial numbers.
- Makes the battery assignment page follow the configured maximum battery count, so unused Bat positions are not shown.
- Improves Home Assistant restart/reconnect recovery and retains important control states so values do not disappear after reloads.
- Reduces unnecessary MQTT/Home Assistant churn while preserving real state changes.
- Improves NOAH/NEXA handling, supported-device clock synchronization and optional passive diagnostics.

All other behavior is inherited from Robert Zaage's GroBro.
