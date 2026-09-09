"""Application and tray icons, built from the first frame of the warning cat GIF.

The cat is the app's identity, so every icon state starts from that frame. State is
layered on top: a small badge for alerts and errors, and a desaturated, faded cat
while the app is paused. If the GIF is ever missing we fall back to a drawn warning
triangle so the tray is never empty.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QIcon, QImage, QMovie, QPainter, QPainterPath, QPen, QPixmap,
)

from .paths import assets_dir

log = logging.getLogger(__name__)

IDLE = "idle"
ALERT = "alert"
PAUSED = "paused"
ERROR = "error"

ICON_SOURCE = "Warning-Cat.gif"
ICON_SIZES = (16, 20, 24, 32, 48, 64, 128, 256)

# Badge colour per state; None means no badge.
_BADGE = {
    IDLE: None,
    ALERT: "#ffb020",
    PAUSED: None,
    ERROR: "#e0533d",
}

_base_cache: QImage | None = None
_base_loaded = False
_icon_cache: dict[str, QIcon] = {}


# ---------------------------------------------------------------------- #
# the source frame
# ---------------------------------------------------------------------- #

def _load_base_frame() -> QImage | None:
    """First frame of the warning cat, cropped to its opaque bounds."""
    global _base_cache, _base_loaded
    if _base_loaded:
        return _base_cache
    _base_loaded = True

    source = assets_dir() / ICON_SOURCE
    if not source.exists():
        log.warning("icon source %s is missing; falling back to a drawn triangle", source)
        return None

    movie = QMovie(str(source))
    if not movie.isValid():
        log.warning("could not decode %s for icons", source)
        return None
    movie.setCacheMode(QMovie.CacheAll)
    movie.jumpToFrame(0)
    image = movie.currentPixmap().toImage()
    if image.isNull():
        return None

    trimmed = _trim_transparent(image)
    _base_cache = trimmed.convertToFormat(QImage.Format_ARGB32)
    return _base_cache


def _trim_transparent(image: QImage, threshold: int = 12) -> QImage:
    """Crop fully transparent margins so the cat fills the icon square."""
    width, height = image.width(), image.height()
    step = max(1, min(width, height) // 120)
    left, top, right, bottom = width, height, -1, -1

    for y in range(0, height, step):
        for x in range(0, width, step):
            if image.pixelColor(x, y).alpha() > threshold:
                left = min(left, x)
                right = max(right, x)
                top = min(top, y)
                bottom = max(bottom, y)
    if right < 0:
        return image

    pad = step
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(width - 1, right + pad)
    bottom = min(height - 1, bottom + pad)

    # Keep it square so scaling never distorts the cat.
    box_w, box_h = right - left + 1, bottom - top + 1
    side = max(box_w, box_h)
    cx, cy = left + box_w / 2, top + box_h / 2
    sx = int(max(0, min(width - side, cx - side / 2)))
    sy = int(max(0, min(height - side, cy - side / 2)))
    return image.copy(sx, sy, min(side, width - sx), min(side, height - sy))


def _desaturate(image: QImage, keep: float = 0.15, alpha: float = 0.6) -> QImage:
    """Greyscale-ish copy used for the paused state."""
    out = image.convertToFormat(QImage.Format_ARGB32)
    for y in range(out.height()):
        for x in range(out.width()):
            colour = out.pixelColor(x, y)
            if colour.alpha() == 0:
                continue
            grey = int(0.299 * colour.red() + 0.587 * colour.green() + 0.114 * colour.blue())
            out.setPixelColor(x, y, QColor(
                int(grey * (1 - keep) + colour.red() * keep),
                int(grey * (1 - keep) + colour.green() * keep),
                int(grey * (1 - keep) + colour.blue() * keep),
                int(colour.alpha() * alpha),
            ))
    return out


# ---------------------------------------------------------------------- #
# fallback glyph
# ---------------------------------------------------------------------- #

_TRIANGLE_PALETTE = {
    IDLE: ("#3c4250", "#8b93a1"),
    ALERT: ("#ffb020", "#20222a"),
    PAUSED: ("#2b2e36", "#5b6270"),
    ERROR: ("#e0533d", "#ffffff"),
}


def _draw_triangle(state: str, size: int) -> QPixmap:
    fill, glyph = _TRIANGLE_PALETTE.get(state, _TRIANGLE_PALETTE[IDLE])
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    margin = size * 0.06
    path = QPainterPath()
    path.moveTo(QPointF(size / 2, margin))
    path.lineTo(QPointF(size - margin, size - margin * 1.4))
    path.lineTo(QPointF(margin, size - margin * 1.4))
    path.closeSubpath()

    painter.setBrush(QBrush(QColor(fill)))
    painter.setPen(QPen(QColor(0, 0, 0, 90), max(1.0, size * 0.03)))
    painter.drawPath(path)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor(glyph)))
    bar = size * 0.11
    painter.drawRoundedRect(QRectF(size / 2 - bar / 2, size * 0.34, bar, size * 0.30), bar / 2, bar / 2)
    dot = size * 0.12
    painter.drawEllipse(QRectF(size / 2 - dot / 2, size * 0.70, dot, dot))
    painter.end()
    return pixmap


# ---------------------------------------------------------------------- #
# composition
# ---------------------------------------------------------------------- #

def render(state: str, size: int) -> QPixmap:
    """One icon pixmap at one size."""
    base = _load_base_frame()
    if base is None:
        return _draw_triangle(state, size)

    frame = _desaturate(base.scaled(
        max(32, size), max(32, size), Qt.KeepAspectRatio, Qt.SmoothTransformation
    )) if state == PAUSED else base

    scaled = frame.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.drawImage(
        QPointF((size - scaled.width()) / 2, (size - scaled.height()) / 2), scaled
    )

    badge = _BADGE.get(state)
    if badge:
        radius = max(2.5, size * 0.16)
        inset = radius + size * 0.015
        centre = QPointF(size - inset, size - inset)
        painter.setPen(QPen(QColor(20, 22, 28, 225), max(1.0, size * 0.03)))
        painter.setBrush(QBrush(QColor(badge)))
        painter.drawEllipse(centre, radius, radius)
    painter.end()
    return pixmap


def tray_icon(state: str = IDLE) -> QIcon:
    if state not in _icon_cache:
        icon = QIcon()
        for size in ICON_SIZES:
            icon.addPixmap(render(state, size))
        _icon_cache[state] = icon
    return _icon_cache[state]


def app_icon() -> QIcon:
    return tray_icon(IDLE)
