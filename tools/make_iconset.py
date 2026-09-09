r"""Generate the .iconset that `iconutil` turns into ZendeskWarningLight.icns.

Runs on any platform - it only needs Qt to draw - so the icon can be produced and
inspected without a Mac. `build.sh` then calls macOS's own `iconutil` to pack the
folder into a .icns, which avoids hand-rolling that container format.

    python tools/make_iconset.py [output.iconset]

Note the source art (the first frame of Warning-Cat.gif) is 480x480, so the 512@2x
(1024px) slice is upscaled and will look slightly soft in Finder's largest preview.
Every size macOS actually uses in the menu bar, Dock and Finder lists is at or below
the native resolution.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from zwl import icons  # noqa: E402
from zwl.paths import APP_NAME  # noqa: E402

# (points, scale) -> macOS wants both the 1x and 2x slice of each size.
SLICES = ((16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2),
          (256, 1), (256, 2), (512, 1), (512, 2))

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "build" / "{}.iconset".format(APP_NAME)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)

    QApplication([])
    written = []
    for points, scale in SLICES:
        pixels = points * scale
        name = "icon_{0}x{0}{1}.png".format(points, "@2x" if scale == 2 else "")
        pixmap = icons.render(icons.IDLE, pixels)
        target = out / name
        if not pixmap.save(str(target), "PNG"):
            raise SystemExit("could not write {}".format(target))
        written.append((name, pixels))

    print("wrote {} slices to {}".format(len(written), out))
    for name, pixels in written:
        print("   {:<24} {}px".format(name, pixels))
    print("\nOn a Mac, pack it with:")
    print("   iconutil -c icns {}".format(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
