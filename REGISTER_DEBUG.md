# GroBro Register Debug

This branch adds passive Modbus register logging for reverse engineering NOAH, NEXA, NEO and other Growatt devices.

## Safety model

The debug feature is passive. It does not send additional Modbus read requests and it does not write registers. It only records register blocks that GroBro already receives and successfully parses.

## Home Assistant options

The add-on exposes these options:

- `REGISTER_DEBUG`: enable/disable passive register logging.
- `REGISTER_DEBUG_DIR`: output directory. Default: `/share/GroBro/register_debug`.
- `REGISTER_DEBUG_MAX_REGISTER`: highest register number written to the debug file. Default: `3000`.
- `REGISTER_DEBUG_CHANGES_ONLY`: when `true`, unchanged values are skipped after their first observation.

The debug build uses the slug `grobro_register_debug` so it can be distinguished from the upstream add-on.

## Output

The logger writes:

`/share/GroBro/register_debug/registers.jsonl`

Each line is one received register and contains:

- capture timestamp
- device timestamp, when present
- device serial
- Modbus function
- block start/end
- register number
- uint16 value
- int16 value
- hex value
- high byte / low byte
- previous value
- changed flag

Example:

```json
{"device_id":"0PVP...","function":4,"block_start":0,"block_end":120,"register":102,"uint16":100,"int16":100,"hex":"0x0064","high_byte":0,"low_byte":100,"previous":100,"changed":false}
```

## Important limitation

`REGISTER_DEBUG_MAX_REGISTER=3000` does **not** actively scan registers 0-3000. It means that any received register up to 3000 is retained. If a device only transmits 0-120, GroBro cannot discover 121-3000 without adding active read requests. Active scanning is intentionally not part of this branch.

## Recommended capture

For discovery work, leave `REGISTER_DEBUG_CHANGES_ONLY: false` for the first capture so repeated values and correlations are preserved. Afterward, `true` can be used for longer runs with smaller files.
