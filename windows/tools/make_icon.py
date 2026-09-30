"""Generate assets/app.ico from the runtime-drawn tray icon.

Writes a multi-resolution ICO with PNG payloads, which Windows has understood
since Vista and which keeps the file small.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QBuffer, QByteArray  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from zwl import icons  # noqa: E402

SIZES = icons.ICON_SIZES


def png_bytes(size: int) -> bytes:
    pixmap = icons.render(icons.IDLE, size)
    store = QByteArray()          # must outlive the buffer
    buffer = QBuffer(store)
    buffer.open(QBuffer.WriteOnly)
    pixmap.save(buffer, "PNG")
    buffer.close()
    return bytes(store)


def build_ico(path: Path) -> None:
    images = [(size, png_bytes(size)) for size in SIZES]

    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)

    entries, payloads = b"", b""
    for size, data in images:
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,   # width  (0 means 256)
            0 if size >= 256 else size,   # height
            0,                            # palette size
            0,                            # reserved
            1,                            # colour planes
            32,                           # bits per pixel
            len(data),
            offset,
        )
        payloads += data
        offset += len(data)

    path.write_bytes(header + entries + payloads)


if __name__ == "__main__":
    QApplication([])
    target = Path(__file__).resolve().parent.parent / "assets" / "app.ico"
    build_ico(target)
    print("wrote {} ({:,} bytes)".format(target, target.stat().st_size))
