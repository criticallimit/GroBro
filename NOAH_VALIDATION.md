# NOAH validation checkpoint

This file records findings from passive analysis of a real Growatt NOAH 2000 stack before proposing upstream changes.

## Test system

- 3 physical NOAH battery modules
- Main device ID: `0PVP50ZR175T00E8`
- Firmware: `19.19.14`
- Capture set: 2314 complete input-register snapshots (`0-124`) plus raw `0x0103` packets and targeted holding-register reads
- Capture date: 2026-09-05
- Captured operating states include Idle, Charging and Discharging

## Confirmed / strongly validated input registers

- `R2`: output power
- `R7`: total PV power. Reconstructed PV1+PV2 power from `R92/R93` and `R95/R96` correlates with R7 at ~0.9996.
- `R10`: battery system state (Idle / Charging / Discharging)
- `R11`: signed charging/discharging power using the existing -30000 offset. It closely tracks PV power minus output power and conversion losses.
- `R12`: battery count (`bat_cnt`). Constant `3` across all 2314 complete snapshots and matches the three physical modules.
- `R13`: total battery SOC
- `R29/R41/R53`: battery 1/2/3 SOC
- `R30/R42/R54`: battery 1/2/3 temperature using the existing offset/scaling
- `R72/R74/R76/R78`: PV energy today/month/year/device-total; their step behaviour is consistent with the existing 0.1 kWh scaling
- `R90/R91`: charge/discharge limit
- `R92/R93`: PV1 voltage/current
- `R94`: PV1 temperature
- `R95/R96`: PV2 voltage/current
- `R97`: PV2 temperature
- `R98`: system temperature. Observed raw range `2982-3114`, consistent with ~29.82-31.14 C using 0.01 scaling
- `R99/R100`: maximum/minimum cell voltage using 0.001 V scaling. Observed values remain in the ~3.279-3.348 V range with only a few millivolts of spread, strongly supporting the cell-voltage interpretation
- `R101`: battery cycle count (232 in this capture)
- `R102`: battery SOH (100 in this capture)
- `R109`: output voltage using 0.01 V scaling is strongly supported. Across all three operating states it remains physically plausible; during discharge it is typically ~37.85-46.51 V, with a median around 40.77 V. Combining it with R2 yields plausible output current.
- `R119/R120`: firmware `19.19.14` appears exactly once per normal telemetry packet

## Battery serials and firmware

- Battery 1 is represented by the main device ID
- Battery 2 and 3 serial numbers are present in every complete 0-124 telemetry packet in their existing serial-part fields
- No separate per-battery firmware copies were found
- No separate per-battery SOH/current/power triplets were established from the normal cyclic block

## Confirmed 0x0103 embedded holding-register block

Multiple real raw `0x0103` packets contain a standard register block at byte offset `583`:

- start register: `250`
- end register: `374`
- count: `125`
- followed by exactly the normal two-byte Growatt trailer

Known values inside this embedded block match independently read holding registers:

- `R250 = 100`
- `R251 = 5`
- `R254/R255/R256/R257/R258` match Slot 1 fields

Across observed captures, only known Slot 1 fields changed:
- earlier capture: `R256 1 -> 0`, `R257 0 -> 300`
- newer capture: `R257 0 -> 200`

All other observed unknown suffix values remained stable. This strongly validates that the embedded range really is Holding Registers 250-374.

## Unknown 0x0103 values that must remain debug-only

Observed unchanged across the complete embedded blocks:

- `R299 = 800`
- `R300 = 257`
- `R301-R304 = 0xFFFF`

The pattern is interesting because `257` is the register address of `slot1_power` and `800 W` is its known maximum, suggesting configuration/descriptor metadata rather than live telemetry. However, this is not sufficient evidence to assign public semantics. These registers must remain unlabelled and read-only/debug-only until independently validated.

## Documentation corrections

### NOAH default power

NOAH `default_power` is `R252`.

This is supported by historical upstream commit `5a61c5a71198e899652cfb4bb3a652031efffb07`, which explicitly introduced `default_power` for NOAH at register 252. `R322` is used by NEXA. Generic documentation must distinguish the two devices.

### Battery-count auto detection

For current NOAH telemetry, `R12` (`bat_cnt`) is the preferred battery-count source. On the validated three-module stack it is `3` in every one of 2314 complete snapshots. Serial-part presence remains a conservative fallback only when explicit battery count telemetry is unavailable.

## Home Assistant compatibility rule

Do not rename existing entity names, unique IDs, state topics or device identifiers without an explicit migration plan.

## Status

Validated mappings may be considered for an upstream PR after remaining unknowns are resolved. Unconfirmed registers such as R299-R304 must not be exposed as Home Assistant entities or writable controls.
