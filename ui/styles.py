COMMON_BUTTON_STYLE = """
QPushButton {
  background: transparent;
  border: 0px;
  color: rgba(255,255,255,230);
  border-radius: 8px;
  qproperty-iconSize: 22px 22px;
  padding: 3px;
  min-width: 20px;
  min-height: 20px;
}
QPushButton:hover { 
  background: rgba(255,255,255,20); 
}
QPushButton:pressed { 
  background: rgba(255,255,255,10); 
}
QPushButton:checked { 
  background: rgba(255,255,255,28); 
  border: 1px solid rgba(255,255,255,20);
}
"""

PANEL_STYLE = COMMON_BUTTON_STYLE + """
QLabel {
  color: rgba(255,255,255,175);
  font-family: "Segoe UI";
  font-size: 14px;
}

QSlider::groove:horizontal {
  background: rgba(255,255,255,22);
  height: 4px;
  border-radius: 2px;
}
QSlider::sub-page:horizontal {
  background: rgba(235,235,235,180);
  height: 4px;
  border-radius: 2px;
}
QSlider::add-page:horizontal {
  background: rgba(255,255,255,12);
  height: 4px;
  border-radius: 2px;
}
QSlider::handle:horizontal {
  background: rgba(255,255,255,230);
  width: 6px;
  height: 16px;
  border-radius: 2px;
  margin: -6px 0px;
}
"""

PLAYLIST_STYLE = COMMON_BUTTON_STYLE + """
QWidget#PlaylistPanel {
  background: rgba(20, 20, 20, 0.98);
  border: 1px solid rgba(255,255,255,25);
  border-radius: 12px;
}

QListView {
  background: transparent;
  border: 1px solid rgba(255,255,255,20);
  border-radius: 8px;
  color: rgba(255,255,255,255);
  font-family: "Segoe UI";
  font-size: 14px;
  outline: none;
  padding-right: 4px;
}

QLineEdit {
  background: rgba(255,255,255,10);
  border: 1px solid rgba(255,255,255,24);
  border-radius: 8px;
  color: rgba(255,255,255,230);
  padding: 4px 8px;
  font-family: "Segoe UI";
  font-size: 12px;
}

QLineEdit:focus {
  border: 1px solid rgba(255,255,255,40);
  background: rgba(255,255,255,14);
}

/* Custom ScrollBar Styling */
QScrollBar:vertical {
  background: transparent;
  width: 8px;
  margin: 0px;
  border-radius: 4px;
}

QScrollBar::handle:vertical {
  background: rgba(255, 255, 255, 40);
  min-height: 30px;
  border-radius: 4px;
  margin: 0px 2px;
}

QScrollBar::handle:vertical:hover {
  background: rgba(255, 255, 255, 45);
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
  background: none;
  height: 0px;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
  background: none;
}
"""


MENU_STYLE = """
QMenu {
    background-color: rgba(25, 25, 25, 0.98);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    padding: 6px 0px;
    color: rgba(255, 255, 255, 210);
    font-family: "Segoe UI";
    font-size: 13px;
}

QMenu::item {
    padding: 6px 24px 6px 20px;
    border-radius: 4px;
    margin: 1px 6px;
}

QMenu::item:selected {
    background-color: rgba(255, 255, 255, 0.08);
    color: white;
}

QMenu::item:disabled {
    color: rgba(255, 255, 255, 0.25);
}

QMenu::separator {
    height: 1px;
    background: rgba(255, 255, 255, 0.08);
    margin: 4px 12px;
}
"""

DIALOG_STYLE = """
QDialog {
    background-color: #121212;
    color: white;
}

QLabel {
    color: rgba(255, 255, 255, 200);
    font-family: "Segoe UI";
    font-size: 13px;
}

QCheckBox {
    color: rgba(255, 255, 255, 220);
    font-family: "Segoe UI";
    font-size: 13px;
    spacing: 6px;
}

QCheckBox::indicator {
    width: 14px;
    height: 14px;
}

QGroupBox {
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
    margin-top: 15px;
    padding-top: 20px;
    color: rgba(255, 255, 255, 220);
    font-weight: 600;
    font-size: 14px;
}

QComboBox {
    background-color: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    padding: 6px 10px;
    color: white;
}

QLineEdit {
    background-color: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 6px;
    padding: 7px 9px;
    color: white;
}

QLineEdit:focus {
    border: 1px solid rgba(255, 255, 255, 0.28);
}

QComboBox:hover {
    background-color: rgba(255, 255, 255, 0.08);
}

QComboBox QAbstractItemView {
    background-color: #1a1a1a;
    color: white;
    selection-background-color: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.1);
}

QSlider::groove:horizontal {
    background: rgba(255, 255, 255, 0.1);
    height: 4px;
    border-radius: 2px;
}

QSlider::groove:vertical {
    background: rgba(255, 255, 255, 0.1);
    width: 4px;
    border-radius: 2px;
}

QSlider::handle:vertical {
    background: rgba(255,255,255,230);
    height: 6px;
    width: 16px;
    margin: 0 -5px;
    border-radius: 7px;
}

QSlider::handle:vertical:hover {
    background: rgba(255,255,255,255);
}

QSlider::handle:horizontal {
    background: rgba(255,255,255,230);
    width: 6px;
    height: 16px;
    margin: -5px 0;
    border-radius: 7px;
}

QPushButton {
    background-color: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    padding: 8px 18px;
    color: white;
    font-weight: 500;
}

QPushButton:hover {
    background-color: rgba(255, 255, 255, 0.1);
}

QPushButton#PrimaryButton {
    background-color: rgba(100, 100, 100, 0.6);
    border: none;
}

QPushButton#PrimaryButton:hover {
    background-color: rgba(100, 100, 100, 0.9);
}

/* Minus/Plus Small Buttons */
QPushButton#AdjustBtn {
    background-color: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.1);
    min-width: 32px;
    max-width: 32px;
    min-height: 28px;
    max-height: 28px;
    border-radius: 4px;
    font-size: 16px;
    padding: 0;
}

QPushButton#AdjustBtn:hover {
    background-color: rgba(255, 255, 255, 0.12);
}

QLabel#ValLabel {
    min-width: 40px;
    alignment: center;
    font-weight: bold;
    color: white;
    font-size: 14px;
}
"""


TITLE_BAR_STYLE = COMMON_BUTTON_STYLE + """
QWidget#TitleBarBg {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(0,0,0,180), stop:1 rgba(0,0,0,0));
}
QPushButton {
    background-color: transparent;
    border: none;
    border-radius: 0px;
    padding: 10px;
    margin: 0px;
    qproperty-iconSize: 18px 18px;
    min-width: 0px;
    min-height: 0px;
}
QPushButton:hover {
    background-color: rgba(255, 255, 255, 0.1);
}
QPushButton#CloseBtn:hover {
    background-color: #e81123;
}

QLabel {
    color: rgba(255, 255, 255, 200);
    font-family: 'Segoe UI', sans-serif;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 1px;
    background: transparent;
}
s
QLabel#AppTitle {
    font-family: "Segoe UI Semibold", "Segoe UI";
    font-weight: 600;
    font-size: 14px;
    color: rgba(255, 255, 255, 245);
    padding-left: 8px;
}

QLabel#AppIcon {
    padding-left: 12px;
}
"""
