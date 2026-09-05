# GroBro Register Debug

This fork adds passive Modbus register logging for reverse engineering NOAH, NEXA, NEO and other Growatt devices.

## Safety model

The debug feature is passive. It does not send additional Modbus read requests and it does not write registers. It only records register blocks that GroBro already receives and successfully parses.

## Home Assistant options

The add-on exposes these options:

- `REGISTER_DEBUG`: enable/disable passive register logging.
- `REGISTER_DEBUG_DIR`: output directory. Default: `/share/GroBro/register_debug`.
- `REGISTER_DEBUG_MAX_REGISTER`: highest confirmed Modbus register number written to the debug file. Default: `3000`.
- `REGISTER_DEBUG_CHANGES_ONLY`: when `true`, unchanged values are skipped after their first observation. Default: `true`.

The debug build uses the slug `grobro_register_debug` so it can be distinguished from the upstream add-on.

## Output

The logger writes:

`/share/GroBro/register_debug/registers.jsonl`

For ordinary Modbus blocks each line contains:

- capture timestamp
- device timestamp, when present
- device serial
- Modbus function
- block start/end
- confirmed register number
- uint16 value
- int16 value
- hex value
- high byte / low byte
- previous value
- changed flag

With `REGISTER_DEBUG_CHANGES_ONLY: true`, the first observation of every register is still written, so static values such as firmware bytes or SOH candidates are not lost.

## NOAH 0x0103 messages

GroBro also receives a special NOAH/NEXA message type `0x0103`. The current decoder exposes a sequence of 16-bit values but does not prove the Modbus start address. These values are therefore logged as `value_index` with `addressing: unknown` and are **not** labelled as real register numbers until protocol evidence confirms their addresses.

## Important limitation

`REGISTER_DEBUG_MAX_REGISTER=3000` does **not** actively scan registers 0-3000. It means that any received, correctly addressed Modbus register up to 3000 is retained. If a device only transmits 0-120, GroBro cannot discover 121-3000 without active read requests. Active scanning is intentionally not part of this fork.

## Recommended capture

Leave `REGISTER_DEBUG_CHANGES_ONLY: true` for normal discovery runs. This records the complete initial state and then only changed values, which keeps the file manageable while preserving static register values. Set it to `false` only for short correlation captures where repeated unchanged samples are specifically needed.
