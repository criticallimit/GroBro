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

    # Search directly in the post-serial region without copying the packet.
    data = memoryview(decoded_packet)[54:]
    trailer_size = 2
    data_end = len(data) - trailer_size
    best = None
    best_count = 0
    # Exact fit requires an even number of value bytes. Skip offsets with
    # incompatible parity and prefixes too long for the 2048-register limit.
    search_start = max(0, data_end - 4 - 2048 * 2)
    search_start += (data_end - search_start) % 2
    for offset in range(search_start, data_end - 5, 2):
        start, end = struct.unpack_from(">HH", data, offset)
        if end < start:
            continue
        count = end - start + 1
        # Keep the observed-block bound and exact trailer fit unchanged.
        if count > 2048 or offset + 4 + count * 2 != data_end:
            continue
        # Decode only the largest candidate. Equal counts retain the first
        # candidate, matching the previous max() selection.
        if count > best_count:
            best = (offset, start, end)
            best_count = count

    if best is None:
        return None

    offset, start, end = best
    values = tuple(value for (value,) in struct.iter_unpack(">H", data[offset + 4:data_end]))
    return EmbeddedRegisterBlock(offset=offset, start=start, end=end, values=values)
