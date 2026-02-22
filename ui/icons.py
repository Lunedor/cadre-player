from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush, QPainter, QPainterPath, QPixmap, QPen, QIcon


def icon_play(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(color))

    path = QPainterPath()
    pad = int(size * 0.20)
    path.moveTo(pad, pad)
    path.lineTo(size - pad, size // 2)
    path.lineTo(pad, size - pad)
    path.closeSubpath()
    painter.drawPath(path)
    painter.end()
    return pm


def icon_pause(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(color))

    width = int(size * 0.22)
    gap = int(size * 0.12)
    height = int(size * 0.62)
    y = (size - height) // 2
    x1 = (size - (2 * width + gap)) // 2
    painter.drawRoundedRect(x1, y, width, height, 2, 2)
    painter.drawRoundedRect(x1 + width + gap, y, width, height, 2, 2)
    painter.end()
    return pm


def icon_prev_track(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(color))

    pad = int(size * 0.22)
    mid = size // 2

    # Bar on the left
    bar_w = max(2, int(size * 0.10))
    bar_x = pad
    bar_y = pad
    bar_h = size - 2 * pad
    p.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 1.5, 1.5)

    # Triangle pointing left, to the right of the bar
    tri_left = QPainterPath()
    left_x = bar_x + bar_w + int(size * 0.08)
    right_x = size - pad
    tri_left.moveTo(left_x, mid)
    tri_left.lineTo(right_x, pad)
    tri_left.lineTo(right_x, size - pad)
    tri_left.closeSubpath()
    p.drawPath(tri_left)

    p.end()
    return pm


def icon_next_track(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(color))

    pad = int(size * 0.22)
    mid = size // 2

    # Bar on the right
    bar_w = max(2, int(size * 0.10))
    bar_x = size - pad - bar_w
    bar_y = pad
    bar_h = size - 2 * pad
    p.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 1.5, 1.5)

    # Triangle pointing right, to the left of the bar
    tri_right = QPainterPath()
    left_x = pad
    right_x = bar_x - int(size * 0.08)
    tri_right.moveTo(right_x, mid)
    tri_right.lineTo(left_x, pad)
    tri_right.lineTo(left_x, size - pad)
    tri_right.closeSubpath()
    p.drawPath(tri_right)

    p.end()
    return pm


def icon_volume(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(color))

    body = QPainterPath()
    body.addRoundedRect(size * 0.12, size * 0.34, size * 0.20, size * 0.32, 1.5, 1.5)
    body.moveTo(size * 0.32, size * 0.34)
    body.lineTo(size * 0.56, size * 0.18)
    body.lineTo(size * 0.56, size * 0.82)
    body.lineTo(size * 0.32, size * 0.66)
    body.closeSubpath()
    painter.drawPath(body)

    painter.setPen(color)
    painter.setBrush(Qt.NoBrush)
    painter.drawArc(int(size * 0.54), int(size * 0.30), int(size * 0.22), int(size * 0.40), -45 * 16, 90 * 16)
    painter.drawArc(int(size * 0.52), int(size * 0.20), int(size * 0.34), int(size * 0.60), -45 * 16, 90 * 16)
    painter.end()
    return pm


def icon_volume_muted(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = icon_volume(size=size, color=color)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = painter.pen()
    pen.setColor(color)
    pen.setWidthF(max(1.6, size * 0.1))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.drawLine(int(size * 0.64), int(size * 0.30), int(size * 0.86), int(size * 0.70))
    painter.drawLine(int(size * 0.86), int(size * 0.30), int(size * 0.64), int(size * 0.70))
    painter.end()
    return pm


def icon_playlist(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = painter.pen()
    pen.setColor(color)
    pen.setWidthF(max(1.6, size * 0.10))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    x0 = int(size * 0.18)
    x1 = int(size * 0.82)
    for y in (0.24, 0.50, 0.76):
        yy = int(size * y)
        painter.drawLine(x0, yy, x1, yy)
    painter.end()
    return pm

from typing import Literal
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
)

def icon_shuffle(size: int = 18, color: QColor = QColor(235, 235, 235), off: bool = False) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    draw_color = QColor(color)
    if off: draw_color.setAlpha(int(draw_color.alpha() * 0.35))
    pen = QPen(draw_color)
    pen.setWidthF(max(1.5, size * 0.09))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    
    p1 = QPainterPath()
    p1.moveTo(size * 0.16, size * 0.26)
    p1.cubicTo(size * 0.36, size * 0.26, size * 0.46, size * 0.76, size * 0.78, size * 0.76)
    painter.drawPath(p1)
    p2 = QPainterPath()
    p2.moveTo(size * 0.16, size * 0.76)
    p2.cubicTo(size * 0.36, size * 0.76, size * 0.46, size * 0.26, size * 0.78, size * 0.26)
    painter.drawPath(p2)
    # Arrowheads
    ah = size * 0.08
    painter.drawLine(size * 0.70, size * 0.18, size * 0.84, size * 0.26)
    painter.drawLine(size * 0.70, size * 0.34, size * 0.84, size * 0.26)
    painter.drawLine(size * 0.70, size * 0.68, size * 0.84, size * 0.76)
    painter.drawLine(size * 0.70, size * 0.84, size * 0.84, size * 0.76)
    painter.end()
    return pm

def icon_repeat(size: int = 18, color: QColor = QColor(235, 235, 235), one: bool = False, off: bool = False) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    draw_color = QColor(color)
    if off: draw_color.setAlpha(int(draw_color.alpha() * 0.35))
    pen = QPen(draw_color)
    pen.setWidthF(max(1.5, size * 0.09))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    
    ty, by, ah = size * 0.30, size * 0.70, size * 0.08
    painter.drawLine(size * 0.20, ty, size * 0.80, ty)
    painter.drawLine(size * 0.80, by, size * 0.20, by)
    # Arrows
    painter.drawLine(size * 0.70, ty - ah, size * 0.82, ty)
    painter.drawLine(size * 0.70, ty + ah, size * 0.82, ty)
    painter.drawLine(size * 0.30, by - ah, size * 0.18, by)
    painter.drawLine(size * 0.30, by + ah, size * 0.18, by)
    
    if one:
        f = QFont("Arial", max(7, int(size * 0.4)))
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, "1")
    painter.end()
    return pm

def icon_close(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = painter.pen()
    pen.setColor(color)
    pen.setWidthF(max(1.8, size * 0.1))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    pad = int(size * 0.25)
    painter.drawLine(pad, pad, size - pad, size - pad)
    painter.drawLine(size - pad, pad, pad, size - pad)
    painter.end()
    return pm


def icon_plus(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(color, max(1.8, size * 0.1))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    c = size // 2
    painter.drawLine(size * 0.25, c, size * 0.75, c)
    painter.drawLine(c, size * 0.25, c, size * 0.75)
    painter.end()
    return pm


def icon_folder(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(color))
    path = QPainterPath()
    path.addRoundedRect(size * 0.12, size * 0.30, size * 0.76, size * 0.48, 2, 2)
    tab = QPainterPath()
    tab.addRoundedRect(size * 0.18, size * 0.20, size * 0.26, size * 0.16, 2, 2)
    painter.drawPath(path)
    painter.drawPath(tab)
    painter.end()
    return pm


def icon_minus(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = painter.pen()
    pen.setColor(color)
    pen.setWidthF(max(1.8, size * 0.1))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    c = size // 2
    painter.drawLine(int(size * 0.22), c, int(size * 0.78), c)
    painter.end()
    return pm


def icon_trash(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = painter.pen()
    pen.setColor(color)
    pen.setWidthF(max(1.4, size * 0.08))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.drawRoundedRect(size * 0.28, size * 0.30, size * 0.44, size * 0.48, 2, 2)
    painter.drawLine(int(size * 0.24), int(size * 0.30), int(size * 0.76), int(size * 0.30))
    painter.drawLine(int(size * 0.36), int(size * 0.22), int(size * 0.64), int(size * 0.22))
    painter.end()
    return pm


def icon_stop(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(color))

    pad = int(size * 0.28)
    side = size - 2 * pad
    painter.drawRoundedRect(pad, pad, side, side, 2, 2)
    painter.end()
    return pm


def icon_sort(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(color)
    pen.setWidthF(max(1.6, size * 0.10))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    
    x0 = int(size * 0.22)
    x1 = int(size * 0.78)
    
    # Draw three horizontal lines of different lengths
    painter.drawLine(x0, int(size * 0.28), x1, int(size * 0.28))
    painter.drawLine(int(size * 0.35), int(size * 0.50), x1 - int(size * 0.13), int(size * 0.50))
    painter.drawLine(int(size * 0.48), int(size * 0.72), x1 - int(size * 0.26), int(size * 0.72))
    
    painter.end()
    return pm


def icon_save(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(color)
    pen.setWidthF(max(1.6, size * 0.09))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    
    # Simple floppy disk or download arrow style
    # Disk base
    pad = size * 0.22
    painter.drawRoundedRect(pad, pad, size-pad*2, size-pad*2, 2, 2)
    # Inner rectangle
    painter.drawRect(size*0.35, pad, size*0.3, size*0.25)
    # Bottom stripe
    painter.drawLine(size*0.32, size*0.65, size*0.68, size*0.65)
    
    painter.end()
    return pm


def icon_open_folder(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    
    pen = QPen(color)
    line_width = max(1.5, size * 0.08)
    pen.setWidthF(line_width)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    
    # Coordinates for the 3 parallel lines (List)
    margin = size * 0.2
    right_margin = size * 0.45  # Leave space on the right for the plus sign
    
    # Line 1 (Top)
    painter.drawLine(margin, size * 0.3, size - margin, size * 0.3)
    # Line 2 (Middle)
    painter.drawLine(margin, size * 0.5, size - right_margin, size * 0.5)
    # Line 3 (Bottom)
    painter.drawLine(margin, size * 0.7, size - right_margin, size * 0.7)
    
    # Draw the Plus Sign (+) at the bottom right
    plus_size = size * 0.25
    cx = size - margin - (plus_size / 2) + 3
    cy = size * 0.65 - 1
    
    # Vertical bar
    painter.drawLine(cx, cy - plus_size/2, cx, cy + plus_size/2)
    # Horizontal bar
    painter.drawLine(cx - plus_size/2, cy, cx + plus_size/2, cy)
    
    painter.end()
    return pm


def icon_maximize(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(color)
    pen.setWidthF(max(1.2, size * 0.08))
    painter.setPen(pen)
    pad = int(size * 0.3)
    painter.drawRect(pad, pad, size - 2 * pad, size - 2 * pad)
    painter.end()
    return pm


def icon_restore(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(color)
    pen.setWidthF(max(1.2, size * 0.08))
    painter.setPen(pen)
    
    pad = int(size * 0.3)
    s = size - 2 * pad - 2
    
    # Back square
    painter.drawRect(pad + 2, pad - 2, s, s)
    # Fore square
    painter.setBrush(Qt.transparent)
    painter.drawRect(pad, pad, s, s)
    painter.end()
    return pm


def icon_fullscreen(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(color)
    pen.setWidthF(max(1.5, size * 0.08))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    
    pad = int(size * 0.25)
    len_line = int(size * 0.15)
    
    # Top Left
    painter.drawLine(pad, pad + len_line, pad, pad)
    painter.drawLine(pad, pad, pad + len_line, pad)
    
    # Top Right
    painter.drawLine(size - pad - len_line, pad, size - pad, pad)
    painter.drawLine(size - pad, pad, size - pad, pad + len_line)
    
    # Bottom Left
    painter.drawLine(pad, size - pad - len_line, pad, size - pad)
    painter.drawLine(pad, size - pad, pad + len_line, size - pad)
    
    # Bottom Right
    painter.drawLine(size - pad - len_line, size - pad, size - pad, size - pad)
    painter.drawLine(size - pad, size - pad, size - pad, size - pad - len_line)
    
    painter.end()
    return pm


def icon_exit_fullscreen(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(color)
    pen.setWidthF(max(1.5, size * 0.08))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    
    pad = int(size * 0.20)
    center = size // 2
    len_line = int(size * 0.15)
    
    # Arrorws pointing inward
    # Top Left
    painter.drawLine(pad, pad, center - 2, center - 2)
    # Top Right
    painter.drawLine(size - pad, pad, center + 2, center - 2)
    # Bottom Left
    painter.drawLine(pad, size - pad, center - 2, center + 2)
    # Bottom Right
    painter.drawLine(size - pad, size - pad, center + 2, center + 2)
    
    painter.end()
    return pm


def get_app_icon() -> QIcon:


    icon = QIcon()
    base_path = Path(__file__).parent.parent / "icons"
    for size in [16, 32, 64, 128, 256]:
        icon_path = base_path / f"icon-{size}.png"
        if icon_path.exists():
            icon.addFile(str(icon_path))
    return icon
