from pathlib import Path
import math
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QBrush, QPainter, QPainterPath, QPixmap, QPen, QIcon, QFont, QPolygonF


def icon_play(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(color))

    path = QPainterPath()
    pad = size * 0.25 # Increased padding for better balance
    # Use floats for the points
    path.moveTo(pad, pad)
    path.lineTo(size - pad, size / 2.0)
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

    w = size * 0.20
    g = size * 0.15
    h = size * 0.60
    # Center the group of two bars
    x_start = (size - (2 * w + g)) / 2.0
    y_start = (size - h) / 2.0
    
    painter.drawRoundedRect(QRectF(x_start, y_start, w, h), 1.5, 1.5)
    painter.drawRoundedRect(QRectF(x_start + w + g, y_start, w, h), 1.5, 1.5)
    painter.end()
    return pm


def icon_prev_track(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(color))

    pad = int(size * 0.25)
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

    pad = int(size * 0.25)
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
    
    # Body
    path = QPainterPath()
    path.addRoundedRect(QRectF(size * 0.1, size * 0.35, size * 0.2, size * 0.3), 1, 1)
    path.moveTo(size * 0.3, size * 0.35)
    path.lineTo(size * 0.55, size * 0.15)
    path.lineTo(size * 0.55, size * 0.85)
    path.lineTo(size * 0.3, size * 0.65)
    painter.fillPath(path, color)

    # Arcs (Rings)
    pen = QPen(color, max(1.2, size * 0.07))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    # Use QRectF for smooth arcs
    painter.drawArc(QRectF(size * 0.4, size * 0.3, size * 0.3, size * 0.4), -45 * 16, 90 * 16)
    painter.drawArc(QRectF(size * 0.35, size * 0.2, size * 0.5, size * 0.6), -45 * 16, 90 * 16)
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
    
    # Using setWidthF for sub-pixel thickness
    pen = QPen(color)
    pen.setWidthF(max(1.6, size * 0.10))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    
    # Use floats for horizontal start/end
    x0 = size * 0.20
    x1 = size * 0.85
    
    # Define vertical positions as floats
    # 0.3, 0.5, 0.7 provides perfectly symmetrical distribution
    for y_percent in (0.25, 0.50, 0.75):
        yy = size * y_percent
        painter.drawLine(QPointF(x0, yy), QPointF(x1, yy))
        
    painter.end()
    return pm

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
    ah = size * 0.12
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
    
    # Use a floating point pen width for precision
    width = max(1.8, size * 0.1)
    pen = QPen(color, width)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    
    # Calculate the exact center using floats
    # For a 18px box, the center is 9.0 - (0.5 if width is odd/even logic) 
    # but simply using size / 2.0 with Antialiasing handles the centering best.
    c = size / 2.0
    margin = size * 0.20
    
    # Horizontal line
    painter.drawLine(QPointF(margin, c), QPointF(size - margin, c))
    # Vertical line
    painter.drawLine(QPointF(c, margin), QPointF(c, size - margin))
    
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
    pen = QPen(color, max(1.4, size * 0.08), Qt.SolidLine, Qt.RoundCap)
    painter.setPen(pen)
    
    # Can
    painter.drawRoundedRect(QRectF(size * 0.25, size * 0.35, size * 0.5, size * 0.5), 1, 1)
    # Lid
    painter.drawLine(QPointF(size * 0.2, size * 0.35), QPointF(size * 0.8, size * 0.35))
    # Handle
    painter.drawPolyline([QPointF(size * 0.4, size * 0.35), 
                          QPointF(size * 0.4, size * 0.25), 
                          QPointF(size * 0.6, size * 0.25), 
                          QPointF(size * 0.6, size * 0.35)])
    painter.end()
    return pm


def icon_stop(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(color))

    pad = int(size * 0.3)
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


def icon_search(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)

    pen = QPen(color)
    pen.setWidthF(max(1.5, size * 0.09))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    radius = size * 0.28
    cx = size * 0.44
    cy = size * 0.44
    painter.drawEllipse(QPointF(cx, cy), radius, radius)
    painter.drawLine(
        QPointF(cx + radius * 0.72, cy + radius * 0.72),
        QPointF(size * 0.84, size * 0.84),
    )
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

def icon_restore_playlist(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    
    pen = QPen(color)
    pen_width = max(1.2, size * 0.08)
    pen.setWidthF(pen_width)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    
    # Calculate center and radius for the circular arrow
    cx = size / 2.0
    cy = size / 2.0
    r = size * 0.3
    
    # Draw a 270-degree counter-clockwise arc
    # Qt angles: 0 is 3 o'clock, 90 is 12 o'clock.
    # Start at -180 (9 o'clock) and span 270 degrees to end exactly at 90 (12 o'clock).
    rect = QRectF(cx - r, cy - r, r * 2, r * 2)
    start_angle = -180 * 16
    span_angle = 270 * 16
    painter.drawArc(rect, start_angle, span_angle)
    
    # Draw the arrowhead at the 12 o'clock position, pointing left
    arrow_size = pen_width * 2.8
    tip_x = cx - pen_width * 0.5
    tip_y = cy - r
    
    # Define the triangle coordinates for the arrowhead
    p1 = QPointF(tip_x - arrow_size * 0.5, tip_y)
    p2 = QPointF(tip_x + arrow_size * 0.5, tip_y - arrow_size * 0.6)
    p3 = QPointF(tip_x + arrow_size * 0.5, tip_y + arrow_size * 0.6)
    
    # Switch to a solid brush to fill the arrowhead
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawPolygon(QPolygonF([p1, p2, p3]))
    
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
    # Square caps and miter joins ensure the elbows of the brackets form sharp 90-degree angles
    pen.setCapStyle(Qt.SquareCap)
    pen.setJoinStyle(Qt.MiterJoin)
    painter.setPen(pen)
    
    c = size / 2.0
    gap = size * 0.12  # Distance from the center to the bracket vertex
    arm = size * 0.25  # Length of the bracket arms
    
    # Top-Left inward bracket
    painter.drawPolyline([
        QPointF(c - gap - arm, c - gap),
        QPointF(c - gap, c - gap),
        QPointF(c - gap, c - gap - arm)
    ])
    
    # Top-Right inward bracket
    painter.drawPolyline([
        QPointF(c + gap + arm, c - gap),
        QPointF(c + gap, c - gap),
        QPointF(c + gap, c - gap - arm)
    ])
    
    # Bottom-Left inward bracket
    painter.drawPolyline([
        QPointF(c - gap - arm, c + gap),
        QPointF(c - gap, c + gap),
        QPointF(c - gap, c + gap + arm)
    ])
    
    # Bottom-Right inward bracket
    painter.drawPolyline([
        QPointF(c + gap + arm, c + gap),
        QPointF(c + gap, c + gap),
        QPointF(c + gap, c + gap + arm)
    ])
    
    painter.end()
    return pm

def icon_settings(size: int = 18, color: QColor = QColor(235, 235, 235)) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(color))
    
    cx, cy = size / 2, size / 2
    outer_r = size * 0.45  # Peak of the tooth
    inner_r = size * 0.32  # Base of the tooth
    hole_r = size * 0.18   # Center hole
    
    path = QPainterPath()
    num_teeth = 8
    
    for i in range(num_teeth):
        # Calculate angles for the 4 corners of each trapezoidal tooth
        angle_deg = i * (360 / num_teeth)
        
        # Point 1: Inner base start
        a1 = math.radians(angle_deg - 12)
        # Point 2: Outer peak start
        a2 = math.radians(angle_deg - 8)
        # Point 3: Outer peak end
        a3 = math.radians(angle_deg + 8)
        # Point 4: Inner base end
        a4 = math.radians(angle_deg + 12)
        
        if i == 0:
            path.moveTo(cx + inner_r * math.cos(a1), cy + inner_r * math.sin(a1))
        else:
            path.lineTo(cx + inner_r * math.cos(a1), cy + inner_r * math.sin(a1))
            
        path.lineTo(cx + outer_r * math.cos(a2), cy + outer_r * math.sin(a2))
        path.lineTo(cx + outer_r * math.cos(a3), cy + outer_r * math.sin(a3))
        path.lineTo(cx + inner_r * math.cos(a4), cy + inner_r * math.sin(a4))

    path.closeSubpath()

    # Subtract the center hole
    hole_path = QPainterPath()
    hole_path.addEllipse(cx - hole_r, cy - hole_r, hole_r * 2, hole_r * 2)
    
    final_gear = path.subtracted(hole_path)
    
    painter.drawPath(final_gear)
    painter.end()
    
    return pm

def get_app_icon() -> QIcon:
    """
    Returns a QIcon object using the multi-resolution ICO file.
    The ICO container holds 16px to 256px layers internally.
    """
    # Assuming icon.ico is in the 'icons' folder relative to this script
    icon_path = Path(__file__).parent.parent / "icons" / "icon.ico"
    
    if icon_path.exists():
        # Loading the .ico file directly handles all internal sizes (16, 32, 64, etc.)
        return QIcon(str(icon_path))
    
    # Return an empty QIcon if the file is missing to avoid crashes
    return QIcon()
