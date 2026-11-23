# Growatt 0x0103 payload investigation (2026-11-23)

## Evidence and scope

Source: privately supplied Better GroBro raw MQTT JSONL (captured 2026-11-23); sample counts from the supplied dump. Do not commit the actual JSONL, unredacted serials, credentials, or payloads.

- **Two** type `0x0103` messages were present: one 1093-byte NOAH packet and one 585-byte NEO packet.
- Both had the standard Growatt 8-byte prefix and a 30-byte, NUL-padded outer serial in offsets **8:38**.
- In both packets, offsets **38:54** held a NUL-padded identifier. NOAH used the full 16-character identity; NEO used the **last ten** characters of the outer identity.
- Offsets **54:70** were 16 zero bytes in both observed packets.
- Type `0x0103` appears at offsets **6:8** (same bytes that generic Modbus code interprets as address/function = 1/3).
- These are observed offsets, **not** a formal device-independent specification. The source GroBro DEVELOPMENT.md describes a related wrapper layout that does not match this sample exactly.

## Observed type-specific content

| Byte range | NEO 585 bytes | NOAH 1093 bytes | Confidence |
|---|---|---|---|
| 0:8 | Standard packet prefix, type 0x0103 at 6:8 | Same | Observed |
| 8:38 | Outer device serial, NUL padded | Same | Observed |
| 38:54 | Suffix-only serial, NUL padded | Full serial | Observed |
| 54:70 | All zero | All zero | Observed |
| 70 onward | Binary fields intermixed with printable ASCII | Binary fields, mostly zeros in early section | Observed |
| trailing two bytes | Opaque trailer | Opaque trailer | Observed; CRC not verified |

Additional NEO text strings found in its decoded type-0x0103 packet include `GJ1.0`, `GJAA`, and `PV Inverter`. Their **semantics are unconfirmed**. Some small values (including 100, 413 and 124) are present, but treating them as a percentage, power limit, firmware version or holding-register ID without a field map is not justified.

## Comparison with type 0x0104

The same capture contains multiple 585-byte NEO messages with type `0x0104`, all carrying the suffix identifier at offsets 38:54 as well. Bytes at offset 70 onward vary across successive type-0x0104 reports; the single NEO type-0x0103 packet contains a markedly different text/binary layout. It is **not** safe to treat the entire `0x0103` body as the same sequential register map used by `0x0104`.

## Existing code and decisions

- `grobro/grobro/parser.py::parse_noah_0103` returns the embedded identifier and interprets bytes starting at 54 as generic 16-bit words. These words have **no validated per-field mapping**.
- `grobro/grobro/client.py` intentionally intercepts valid `0x0103` wrappers, including NEO's matching suffix-only identifier (fix in 3.3.21), to avoid treating serial ASCII such as `BZP4` as an impossible Modbus start/end range.
- The pre-existing NEO holding-register definitions (`inverter_power` at register 0 and `output_power_limit` at register 3) are **not** sufficient to establish where these fields would appear inside the captured `0x0103` packet.
- Preserve normal `0x0104` telemetry and current MQTT handling. **Do not publish any new Home Assistant entities from `0x0103`** pending validated field offsets, unit conversions, version compatibility and tests.

## What would establish field meanings

1. Compare repeat `0x0103` packets for the **same** device at known operating states.
2. Cross-check stable text areas with device/version information from confirmed config responses.
3. Confirm each candidate numeric field against an independent known register or device observation across multiple values, and verify byte order/scaling.
4. Only then implement explicit per-field parsing with fixtures; keep unsupported values opaque and private.
