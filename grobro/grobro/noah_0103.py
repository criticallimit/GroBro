"""Helpers for the partially reverse-engineered NOAH/NEXA 0x0103 message.

A 0x0103 packet contains additional opaque/preamble data, followed by a standard
Growatt register block and the usual two-byte packet trailer. We keep the opaque
part untouched and only expose a register block when its start/end/count make the
block fit *exactly* before the two-byte trailer. This avoids assigning addresses
to the unrelated prefix bytes.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddedRegisterBlock:
    offset: int
    start: int
    end: int
    values: tuple[int, ...]

    @property
    def registers(self) -> dict[int, int]:
        return {
            self.start + index: value
            for index, value in enumerate(self.values)
        }


def find_embedded_register_block(
    decoded_packet: bytes,
) -> EmbeddedRegisterBlock | None:
    """Find an embedded register block that ends exactly before the 2-byte tail."""
    if len(decoded_packet) < 24 + 30 + 6 + 2:
        return None

    payload = decoded_packet[24:]
    if len(payload) < 30:
        return None

    # Keep the same post-device-serial region used by the existing 0x0103 parser.
    data = payload[30:]
    trailer_size = 2
    data_end = len(data) - trailer_size
    if data_end < 6:
        return None

    candidates: list[EmbeddedRegisterBlock] = []
    for offset in range(0, data_end - 5):
        start, end = struct.unpack_from(">HH", data, offset)
        if end < start:
            continue
        count = end - start + 1
        # Defensive upper bound; Growatt blocks observed here are small enough
        # that a huge accidental range should not be treated as a candidate.
        if count <= 0 or count > 2048:
            continue
        block_size = 4 + count * 2
        if offset + block_size != data_end:
            continue

        values_raw = data[offset + 4 : offset + block_size]
        if len(values_raw) != count * 2:
            continue
        values = tuple(
            struct.unpack_from(">H", values_raw, index * 2)[0]
            for index in range(count)
        )
        candidates.append(
            EmbeddedRegisterBlock(
                offset=offset,
                start=start,
                end=end,
                values=values,
            )
        )

    if not candidates:
        return None

    # Prefer the candidate with the largest register range. A valid embedded
    # Growatt block contains many registers; tiny accidental suffix matches are
    # much more likely to be false positives.
    return max(candidates, key=lambda candidate: len(candidate.values))
