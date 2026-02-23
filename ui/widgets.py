from urllib.parse import parse_qs, unquote

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QRect,
    QSize,
    Signal,
    QSortFilterProxyModel,
    Qt,
    QMimeData,
    QByteArray,
    QDataStream,
    QIODevice,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QAbstractItemView,
    QStyle,
    QStyledItemDelegate,
    QLabel,
    QListView,
    QMainWindow,
    QSlider,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
)


PLAYLIST_PATH_ROLE = Qt.UserRole + 1
PLAYLIST_NAME_ROLE = Qt.UserRole + 2
PLAYLIST_DURATION_ROLE = Qt.UserRole + 3


def _playlist_item_name(path_value: str) -> str:
    def _basename(value: str) -> str:
        token = str(value or "").rstrip("/\\")
        if not token:
            return ""
        token = token.rsplit("/", 1)[-1]
        token = token.rsplit("\\", 1)[-1]
        return token

    text = str(path_value or "")
    lowered = text.lower()
    if lowered.startswith(("http://", "https://")):
        tail = text.split("://", 1)[1]
        host = tail.split("/", 1)[0].split("@")[-1]
        host_lower = host.lower()
        path_q = tail[len(tail.split("/", 1)[0]):] if "/" in tail else ""
        path, _, query = path_q.partition("?")
        if "youtube.com" in host_lower and path == "/watch":
            vid = parse_qs(query).get("v", [""])[0]
            return f"YouTube {vid}" if vid else "YouTube"
        if "youtu.be" in host_lower:
            vid = path.strip("/")
            return f"YouTube {vid}" if vid else "YouTube"
        raw_name = _basename(path)
        if raw_name:
            return unquote(raw_name)
        return host or text
    return _basename(text) or text


class PlaylistListModel(QAbstractListModel):
    orderChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._paths: list[str] = []
        self._durations: dict[str, str] = {}
        self._titles: dict[str, str] = {}
        self._resolved_titles: dict[str, str] = {}

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._paths)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._paths):
            return None
        path = self._paths[row]
        if role == Qt.DisplayRole:
            return path
        if role == Qt.ToolTipRole:
            return path
        if role == PLAYLIST_PATH_ROLE:
            return path
        if role == PLAYLIST_NAME_ROLE:
            return self._titles.get(path, self._resolved_titles.get(path, path))
        if role == PLAYLIST_DURATION_ROLE:
            return self._durations.get(path, "--:--")
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemIsDropEnabled
        return (
            Qt.ItemIsEnabled
            | Qt.ItemIsSelectable
            | Qt.ItemIsDragEnabled
            | Qt.ItemIsDropEnabled
        )

    def mimeTypes(self):
        return ["application/x-cadre-playlist-rows"]

    def mimeData(self, indexes):
        mime = QMimeData()
        encoded_data = QByteArray()
        stream = QDataStream(encoded_data, QIODevice.WriteOnly)
        
        rows = sorted({index.row() for index in indexes})
        for row in rows:
            stream.writeInt32(row)
            
        mime.setData("application/x-cadre-playlist-rows", encoded_data)
        return mime

    def dropMimeData(self, data, action, row, column, parent):
        if action == Qt.IgnoreAction:
            return True
        if not data.hasFormat("application/x-cadre-playlist-rows"):
            return False
        
        if row != -1:
            begin_row = row
        elif parent.isValid():
            begin_row = parent.row()
        else:
            begin_row = self.rowCount()
            
        encoded_data = data.data("application/x-cadre-playlist-rows")
        stream = QDataStream(encoded_data, QIODevice.ReadOnly)
        source_rows = []
        while not stream.atEnd():
            source_rows.append(stream.readInt32())

        source_rows = sorted(
            {
                int(r)
                for r in source_rows
                if isinstance(r, int) and 0 <= int(r) < len(self._paths)
            }
        )
        if not source_rows:
            return False

        original = list(self._paths)
        moving = [original[r] for r in source_rows]
        source_set = set(source_rows)
        remaining = [value for i, value in enumerate(original) if i not in source_set]

        insert_row = begin_row
        for r in source_rows:
            if r < begin_row:
                insert_row -= 1
        insert_row = max(0, min(insert_row, len(remaining)))

        reordered = remaining[:insert_row] + moving + remaining[insert_row:]
        if reordered == original:
            return False

        self.beginResetModel()
        self._paths = reordered
        self.endResetModel()
        self.orderChanged.emit()
        return True

    def supportedDropActions(self):
        return Qt.MoveAction

    def moveRows(self, sourceParent, sourceRow, count, destinationParent, destinationChild):
        if sourceParent.isValid() or destinationParent.isValid():
            return False
        if count <= 0:
            return False
        if sourceRow < 0 or (sourceRow + count) > len(self._paths):
            return False
        if destinationChild < 0 or destinationChild > len(self._paths):
            return False
        if destinationChild >= sourceRow and destinationChild <= (sourceRow + count):
            return False

        self.beginMoveRows(
            sourceParent, sourceRow, sourceRow + count - 1, destinationParent, destinationChild
        )
        moved = self._paths[sourceRow : sourceRow + count]
        del self._paths[sourceRow : sourceRow + count]
        if destinationChild > sourceRow:
            destinationChild -= count
        for i, value in enumerate(moved):
            self._paths.insert(destinationChild + i, value)
        self.endMoveRows()
        return True

    def set_paths(self, paths: list[str], durations: dict[str, str], titles: dict[str, str] = None):
        self.beginResetModel()
        self._paths = list(paths)
        self._durations = dict(durations)
        self._titles = dict(titles or {})
        self._resolved_titles = {p: _playlist_item_name(p) for p in self._paths}
        self.endResetModel()

    def append_paths(self, paths: list[str], durations: dict[str, str], titles: dict[str, str] = None):
        if not paths:
            return
        start = len(self._paths)
        end = start + len(paths) - 1
        self.beginInsertRows(QModelIndex(), start, end)
        self._paths.extend(paths)
        self._durations = dict(durations)
        if titles is not None:
            self._titles = dict(titles)
        for p in paths:
            self._resolved_titles[p] = _playlist_item_name(p)
        self.endInsertRows()

    def update_duration(self, path: str, duration_text: str):
        self._durations[path] = duration_text
        changed = False
        for row, item_path in enumerate(self._paths):
            if item_path == path:
                idx = self.index(row, 0)
                self.dataChanged.emit(idx, idx, [PLAYLIST_DURATION_ROLE])
                changed = True
        return changed

    def update_title(self, path: str, title: str):
        self._titles[path] = title
        if path not in self._resolved_titles:
            self._resolved_titles[path] = _playlist_item_name(path)
        for row, item_path in enumerate(self._paths):
            if item_path == path:
                idx = self.index(row, 0)
                self.dataChanged.emit(idx, idx, [PLAYLIST_NAME_ROLE])

    def paths(self):
        return list(self._paths)


class PlaylistFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._query = ""
        self.setDynamicSortFilter(False)

    def set_query(self, query: str):
        new_query = (query or "").strip().casefold()
        if new_query == self._query:
            return
        self._query = new_query
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if not self._query:
            return True
        model = self.sourceModel()
        idx = model.index(source_row, 0, source_parent)
        name = str(model.data(idx, PLAYLIST_NAME_ROLE) or "")
        return self._query in name.casefold()


class PlaylistItemDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = option.rect.adjusted(1, 1, -1, -1)
        is_selected = bool(option.state & QStyle.State_Selected)
        is_hovered = bool(option.state & QStyle.State_MouseOver)

        source_row = index.row()
        model = index.model()
        if hasattr(model, "mapToSource"):
            source_row = model.mapToSource(index).row()

        view = option.widget
        current_row = view.property("current_playlist_index") if view else -1
        is_current = source_row == current_row

        if is_selected:
            bg = QColor(255, 255, 255, 36)
            border = QColor(255, 255, 255, 58)
        elif is_current:
            bg = QColor(255, 255, 255, 24)
            border = QColor(255, 255, 255, 46)
        elif is_hovered:
            bg = QColor(255, 255, 255, 18)
            border = QColor(255, 255, 255, 20)
        else:
            bg = QColor(255, 255, 255, 10)
            border = QColor(255, 255, 255, 14)

        painter.setPen(border)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 8, 8)

        index_text = f"{source_row + 1:02d}"
        title = str(index.data(PLAYLIST_NAME_ROLE) or "")
        duration = str(index.data(PLAYLIST_DURATION_ROLE) or "--:--")

        content = rect.adjusted(8, 4, -8, -4)
        index_rect = QRect(content.left(), content.top(), 24, content.height())
        text_rect = QRect(content.left() + 32, content.top(), content.width() - 32, content.height())
        title_rect = QRect(text_rect.left(), text_rect.top(), text_rect.width(), 19)
        dur_rect = QRect(text_rect.left(), text_rect.top() + 20, text_rect.width(), 16)

        f_index = QFont("Cascadia Code", 9)
        f_index.setBold(True)
        painter.setFont(f_index)
        painter.setPen(QColor(255, 255, 255, 120))
        painter.drawText(index_rect, Qt.AlignVCenter | Qt.AlignLeft, index_text)

        f_title = QFont("Segoe UI", 10)
        f_title.setWeight(QFont.DemiBold)
        painter.setFont(f_title)
        painter.setPen(QColor(255, 255, 255, 244))
        title_elided = painter.fontMetrics().elidedText(title, Qt.ElideRight, title_rect.width())
        painter.drawText(title_rect, Qt.AlignVCenter | Qt.AlignLeft, title_elided)

        f_dur = QFont("Segoe UI", 8)
        painter.setFont(f_dur)
        painter.setPen(QColor(255, 255, 255, 150))
        painter.drawText(dur_rect, Qt.AlignVCenter | Qt.AlignLeft, duration)
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 42)


class ClickableSlider(QSlider):
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.orientation() == Qt.Vertical:
                # Vertical: usually Bottom=Min, Top=Max
                y = event.position().y()
                h = self.height()
                if self.invertedAppearance():
                    pos_ratio = y / h
                else:
                    pos_ratio = 1.0 - (y / h)
            else:
                # Horizontal: usually Left=Min, Right=Max
                x = event.position().x()
                w = self.width()
                if self.invertedAppearance():
                    pos_ratio = 1.0 - (x / w)
                else:
                    pos_ratio = x / w
            
            val_range = self.maximum() - self.minimum()
            new_val = self.minimum() + (val_range * pos_ratio)
            self.setValue(int(round(new_val)))
            self.sliderMoved.emit(self.value())
        
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


class PlaylistWidget(QListView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setUniformItemSizes(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setMouseTracking(True)


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
        if event.key() in (Qt.Key_Enter, Qt.Key_Return):
            curr = self.parent()
            while curr and (not hasattr(curr, "owner")):
                curr = curr.parent()
            if curr and hasattr(curr.owner, "play_selected_item"):
                curr.owner.play_selected_item()
        elif event.key() == Qt.Key_Delete:
            # Find the main window to call remove
            curr = self.parent()
            while curr and (not hasattr(curr, "owner")):
                curr = curr.parent()
            if curr:
                if event.modifiers() & Qt.ShiftModifier and hasattr(curr.owner, "delete_to_trash"):
                    curr.owner.delete_to_trash()
                elif hasattr(curr.owner, "remove_selected_from_playlist"):
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
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
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
        brand_layout.setSpacing(4)  # Gap between icon and text
        brand_layout.setAlignment(Qt.AlignCenter)

        # Add the icon
        from .icons import get_app_icon
        self.brand_icon = QLabel()
        self.brand_icon.setPixmap(get_app_icon().pixmap(26, 26))
        
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
