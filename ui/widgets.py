from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QFontMetrics
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QSlider,
    QStyle,
    QWidget,
    QListWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSizePolicy,
    QFrame,
)
from ..i18n import tr


class ElidedLabel(QLabel):
    def paintEvent(self, event):
        painter = QPainter(self)
        metrics = QFontMetrics(self.font())
        # Use floor to avoid pixel bleed
        width = self.width()
        if width <= 0: return
        
        elided_text = metrics.elidedText(self.text(), Qt.ElideRight, width)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(self.rect(), self.alignment() | Qt.AlignVCenter, elided_text)

    def sizeHint(self):
        hint = super().sizeHint()
        # Set a very small width hint to allow the layout to compress it
        hint.setWidth(10)
        return hint

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update()


class PlaylistItemWidget(QWidget):
    def __init__(self, index: int, name: str, duration: str = "--:--", parent=None):
        super().__init__(parent)
        # REMOVE WA_TransparentForMouseEvents so tooltips work.
        # However, we must ensure clicks still select the item in the list.
        # Qt usually handles this if we don't consume the mouse press.
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(10)

        # Index label
        self.index_label = QLabel(f"{index:02d}")
        self.index_label.setObjectName("ItemIndex")
        self.index_label.setFixedWidth(20)
        self.index_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.index_label)

        # Text container
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        self.title_label = ElidedLabel(name)
        self.title_label.setObjectName("ItemTitle")
        self.title_label.setToolTip(name)
        # Important: Allow the label to shrink to zero so it doesn't push the layout out
        self.title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.title_label.setMinimumWidth(0)
        text_layout.addWidget(self.title_label)

        self.duration_label = QLabel(duration)
        self.duration_label.setObjectName("ItemDuration")
        self.duration_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        text_layout.addWidget(self.duration_label)

        layout.addLayout(text_layout, 1)

    def mousePressEvent(self, event):
        # Forward mouse press to the list widget to ensure selection still works
        # when clicking anywhere on the item widget
        if self.parent() and self.parent().parent():
            # parent().parent() is usually the viewport of the QListWidget
            # but we can just ignore it and let it bubble if we don't accept it.
            super().mousePressEvent(event)
            event.ignore() 

    def sizeHint(self):
        # Provide a reasonable height for two lines of text
        hint = super().sizeHint()
        hint.setHeight(42) # Slightly tighter but enough for 2 lines
        return hint


class ClickableSlider(QSlider):
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Calculate value based on click position
            val = QStyle.sliderValueFromPosition(
                self.minimum(),
                self.maximum(),
                event.position().x(),
                self.width(),
            )
            self.setValue(val)
            self.sliderMoved.emit(val)
        
        # Call super to allow default behavior (like starting a drag)
        # Since we just set the value, the handle will be under the cursor
        # and QSlider will start a drag operation.
        super().mousePressEvent(event)


class RoundedPanel(QWidget):
    def __init__(self, parent=None, radius: int = 16):
        super().__init__(parent)
        self.radius = radius
        self.bg = QColor(18, 18, 18, 150)

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAcceptDrops(True)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect()
        path = QPainterPath()
        if self.objectName() == "PlaylistPanel":
            path.addRect(rect)
        else:
            path.addRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), self.radius, self.radius)

        painter.setClipPath(path)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.bg)
        painter.drawPath(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            curr = self.parent()
            while curr and not hasattr(curr, "owner"):
                curr = curr.parent()
            if curr and hasattr(curr.owner, "dropEvent"):
                curr.owner.dropEvent(event)
                event.acceptProposedAction()
        else:
            super().dropEvent(event)



class OverlayWindow(QWidget):
    def __init__(self, owner: QMainWindow):
        super().__init__(owner)
        self.owner = owner
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setAcceptDrops(True)

        self.panel = RoundedPanel(self, radius=16)
        self.panel.setObjectName("Panel")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            # Propagate to owner manually but accept so it doesn't bubble naturally again
            self.owner.dropEvent(event)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class PlaylistWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)


    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            curr = self.parent()
            while curr and not hasattr(curr, "owner"):
                curr = curr.parent()
            if curr and hasattr(curr.owner, "dropEvent"):
                curr.owner.dropEvent(event)
                event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            # Find the main window to call remove
            curr = self.parent()
            while curr and (not hasattr(curr, "owner")):
                curr = curr.parent()
            if curr and hasattr(curr.owner, "remove_selected_from_playlist"):
                curr.owner.remove_selected_from_playlist()
        else:
            super().keyPressEvent(event)


class PillOverlayWindow(QWidget):
    def __init__(self, owner: QMainWindow):
        super().__init__(owner)
        self.owner = owner
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setAcceptDrops(True)

        self.panel = RoundedPanel(self, radius=21)
        self.panel.bg = QColor(18, 18, 18, 175)
        self.label = QLabel("", self.panel)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setAcceptDrops(False) # Let it pass through to panel
        self.label.setStyleSheet(
            """
            QLabel {
              color: rgba(255,255,255,235);
              font-family: "Segoe UI";
              font-size: 16px;
              font-weight: 600;
              letter-spacing: 0.3px;
            }
            """
        )

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.owner.dropEvent(event)
        else:
            super().dropEvent(event)


class TitleBarOverlay(QWidget):
    def __init__(self, owner: QMainWindow):
        super().__init__(owner)
        self.owner = owner
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)

        # Background gradient
        self.bg_panel = QWidget(self)
        self.bg_panel.setObjectName("TitleBarBg")

        # Interactive row: [info_label | stretch | min | max | close]
        self._row = QWidget(self)
        row_layout = QHBoxLayout(self._row)
        row_layout.setContentsMargins(15, 0, 0, 0)
        row_layout.setSpacing(0)

        self.info_label = QLabel("", self._row)
        self.info_label.setStyleSheet(
            "color: rgba(255,255,255,100); font-family: 'Segoe UI'; font-size: 11px;"
        )
        self.info_label.setMaximumWidth(250)
        row_layout.addWidget(self.info_label)
        row_layout.addStretch()

        self.min_btn = IconButton(parent=self._row)
        self.min_btn.setFixedSize(32, 32)
        row_layout.addWidget(self.min_btn)

        self.max_btn = IconButton(parent=self._row)
        self.max_btn.setFixedSize(32, 32)
        row_layout.addWidget(self.max_btn)

        self.close_btn = IconButton(parent=self._row)
        self.close_btn.setObjectName("CloseBtn")
        self.close_btn.setFixedSize(32, 32)
        row_layout.addWidget(self.close_btn)

        self.close_btn.clicked.connect(self.owner.close)
        self.min_btn.clicked.connect(self.owner.showMinimized)
        self.max_btn.clicked.connect(self.owner.toggle_window_maximize)

        # Centered brand label — full-width overlay, mouse-transparent
        # Created LAST so it can be raised above everything else
        self.brand_container = QWidget(self)
        self.brand_container.setAttribute(Qt.WA_TransparentForMouseEvents)
        
        brand_layout = QHBoxLayout(self.brand_container)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(1)  # Gap between icon and text
        brand_layout.setAlignment(Qt.AlignCenter)

        # Add the icon
        from .icons import get_app_icon
        self.brand_icon = QLabel()
        self.brand_icon.setPixmap(get_app_icon().pixmap(32, 32))
        
        # Add the text
        self.brand_label = QLabel("Cadre Player")
        
        brand_layout.addWidget(self.brand_icon)
        brand_layout.addWidget(self.brand_label)
        # Stacking: bg → _row (buttons) → brand_container
        self.bg_panel.lower()
        self._row.raise_()
        self.brand_container.raise_()  # On top but invisible to mouse


    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.owner._drag_pos = event.globalPosition().toPoint() - self.owner.frameGeometry().topLeft()
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if hasattr(self.owner, "_drag_pos") and self.owner._drag_pos is not None:
            self.owner.move(event.globalPosition().toPoint() - self.owner._drag_pos)
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.owner._drag_pos = None
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        rect = self.rect()
        self.bg_panel.setGeometry(rect)
        self._row.setGeometry(rect)
        self.brand_container.setGeometry(rect)
        self.brand_container.raise_()  # Keep it on top after layout updates


class DragHandle(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def mousePressEvent(self, event):
        p = self.parent()
        while p and not hasattr(p, "_drag_pos"):
            p = p.parent()
        if p:
            p.mousePressEvent(event)
        else:
            super().mousePressEvent(event)
            
    def mouseMoveEvent(self, event):
        p = self.parent()
        while p and not hasattr(p, "_drag_pos"):
            p = p.parent()
        if p:
            p.mouseMoveEvent(event)
        else:
            super().mouseMoveEvent(event)
            
    def mouseReleaseEvent(self, event):
        p = self.parent()
        while p and not hasattr(p, "_drag_pos"):
            p = p.parent()
        if p:
            p.mouseReleaseEvent(event)
        else:
            super().mouseReleaseEvent(event)


from PySide6.QtWidgets import QPushButton
from PySide6.QtGui import QIcon

class IconButton(QPushButton):
    def __init__(self, tooltip=None, icon=None, parent=None, checkable=False):
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)
        if tooltip:
            self.setToolTip(tooltip)
        if icon:
            self.setIcon(icon)
        if checkable:
            self.setCheckable(True)


