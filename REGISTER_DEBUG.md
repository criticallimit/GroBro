# GroBro Register Debug

This fork adds passive Modbus register logging for reverse engineering NOAH, NEXA, NEO and other Growatt devices.

## Safety model

The debug feature is passive. It does not send additional Modbus read requests and it does not write registers. It only records register blocks that GroBro already receives and successfully parses.

## Home Assistant options

The add-on exposes these options:

- `REGISTER_DEBUG`: enable/disable passive register logging.
- `REGISTER_DEBUG_DIR`: output directory. Default: `/share/GroBro/register_debug`.
- `REGISTER_DEBUG_MAX_REGISTER`: highest confirmed Modbus register number written to the debug file. Default: `65535` (the full 16-bit Modbus address range).
- `REGISTER_DEBUG_CHANGES_ONLY`: when `true`, unchanged values are skipped after their first observation. Default: `true`.
- `DUMP_MESSAGES`: enable/disable complete raw MQTT packet capture.
- `DUMP_DIR`: raw MQTT capture directory. Default for the add-on: `/share/GroBro/dump`.

The debug build uses the slug `grobro_register_debug` so it can be distinguished from the upstream add-on.

## Register-debug output

The passive register logger writes:

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

## Consolidated raw-message output

When `DUMP_MESSAGES: true`, this debug fork writes all raw MQTT packets to a single append-only file instead of creating one `.bin` file per packet:

`/share/GroBro/dump/messages.jsonl`

Each line contains the capture timestamp, MQTT topic, original payload length and the complete unmodified payload encoded as Base64. Decoding `payload_base64` reconstructs exactly the raw bytes that older builds stored in individual `.bin` files.

This format avoids thousands of small files while preserving the information needed for byte-level reverse engineering.

## NOAH 0x0103 messages

GroBro also receives a special NOAH/NEXA message type `0x0103`. Its prefix contains additional structured data whose complete meaning is not yet known. The legacy sequential 16-bit interpretation is therefore retained only as:

- `source: noah_0103`
- `addressing: unknown`
- `value_index: ...`

Those prefix values are **not** presented as real register numbers.

However, real NOAH packets also contain a standard register block near the end of `0x0103`. The block is accepted only when its encoded start/end/count make it fit exactly before the normal two-byte Growatt trailer. In the currently verified NOAH fixture and live dump this block is:

- start register: `250`
- end register: `374`
- register count: `125`

These confirmed values are additionally logged as:

- `source: noah_0103_modbus`
- `function: 3`
- `block_start: 250`
- `block_end: 374`
- real `register` numbers

This is intentionally **debug-only**. The values are not automatically published as Home Assistant entities. Upstream GroBro previously attempted to publish `0x0103` values and reverted that behavior because incorrect interpretation caused zero/invalid sensor states. This fork therefore keeps discovery separate from reverse engineering until individual new registers are validated.

### R299-R304 watch group

The currently unknown registers `R299-R304` are specially tagged in the JSONL output as a passive watch group. The logger records their initial values and marks later changes with `watch_register` / `watch_group` metadata. No write is performed and these registers remain unavailable as Home Assistant controls until their semantics are independently confirmed.

## Important limitation

`REGISTER_DEBUG_MAX_REGISTER=65535` does **not** actively scan registers. It only allows the logger to retain any correctly addressed register that the device actually transmits anywhere in the 16-bit Modbus address space. If a device only transmits 0-124, GroBro cannot discover higher addresses without additional read requests. Active scanning is intentionally not part of this fork.

## Recommended capture

Leave `REGISTER_DEBUG_CHANGES_ONLY: true` for normal discovery runs. This records the complete initial state and then only changed values, which keeps the file manageable while preserving static register values. Set it to `false` only for short correlation captures where repeated unchanged samples are specifically needed.
