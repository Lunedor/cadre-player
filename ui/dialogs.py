from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QComboBox, QSlider, QPushButton, QGroupBox, QFormLayout, QLineEdit,
    QCheckBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from .styles import DIALOG_STYLE
from ..settings import (
    load_sub_settings, save_sub_settings,
    load_video_settings, save_video_settings,
    load_aspect_ratio, save_aspect_ratio,
    load_equalizer_settings, save_equalizer_settings,
    load_stream_auth_settings, save_stream_auth_settings
)
from ..i18n import tr
from .widgets import ClickableSlider

class SubtitleSettingsDialog(QDialog):
    def __init__(self, player_window, parent=None):
        super().__init__(parent)
        self.player_window = player_window or parent
        self.player = self.player_window.player
        
        self.setWindowTitle(tr("Subtitle Settings"))
        self.setMinimumWidth(380)
        self.setStyleSheet(DIALOG_STYLE)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(24, 24, 24, 24)

        sub_config = load_sub_settings()

        # Appearance Group
        appearance_group = QGroupBox(tr("Appearance"))
        form_layout = QFormLayout(appearance_group)
        form_layout.setContentsMargins(15, 20, 15, 15)
        form_layout.setSpacing(12)

        # Size: [ - ] 45 [ + ]
        size_layout = QHBoxLayout()
        size_layout.setSpacing(8)
        self.minus_btn = QPushButton("-")
        self.minus_btn.setObjectName("AdjustBtn")
        self.minus_btn.clicked.connect(lambda: self.adjust_size(-1))
        
        self.size_val_label = QLabel(str(sub_config["font_size"]))
        self.size_val_label.setObjectName("ValLabel")
        self.size_val_label.setAlignment(Qt.AlignCenter)
        
        self.plus_btn = QPushButton("+")
        self.plus_btn.setObjectName("AdjustBtn")
        self.plus_btn.clicked.connect(lambda: self.adjust_size(1))
        
        size_layout.addWidget(self.minus_btn)
        size_layout.addWidget(self.size_val_label)
        size_layout.addWidget(self.plus_btn)
        size_layout.addStretch()
        form_layout.addRow(tr("Font Size") + ":", size_layout)

        # Color
        self.sub_color_combo = QComboBox()
        self.color_map = {
            tr("White"): "#FFFFFF", tr("Yellow"): "#FFFF00", tr("Cyan"): "#00FFFF", 
            tr("Green"): "#00FF00", tr("Red"): "#FF0000"
        }
        self.sub_color_combo.addItems(list(self.color_map.keys()))
        current_color = sub_config["color"]
        for i, val in enumerate(self.color_map.values()):
            if val.lower() == current_color.lower():
                self.sub_color_combo.setCurrentIndex(i)
                break
        self.sub_color_combo.currentIndexChanged.connect(self.update_subtitles)
        form_layout.addRow(tr("Color") + ":", self.sub_color_combo)

        # Background Style
        self.back_style_combo = QComboBox()
        # MPV sub-back-style mapping: shadow=Shadow, outline=Outline, opaque=Opaque Box, none=None
        self.back_styles = [tr("None"), tr("Shadow"), tr("Outline"), tr("Opaque Box")]
        self.back_style_combo.addItems(self.back_styles)
        
        # Translate the loaded setting text before setting it to ComboBox
        saved_style = sub_config.get("back_style", "Shadow")
        display_style = tr(saved_style) if saved_style in ["None", "Shadow", "Outline", "Opaque Box"] else saved_style
        self.back_style_combo.setCurrentText(display_style)
        self.back_style_combo.currentIndexChanged.connect(self.update_subtitles)
        form_layout.addRow(tr("Background") + ":", self.back_style_combo)

        # Vertical Position (Slider)
        self.pos_slider = QSlider(Qt.Horizontal)
        self.pos_slider.setRange(0, 100)
        self.pos_slider.setValue(sub_config["pos"])
        self.pos_slider.valueChanged.connect(self.update_subtitles)
        form_layout.addRow(tr("Vertical Pos") + ":", self.pos_slider)

        layout.addWidget(appearance_group)

        # Timing Group
        timing_group = QGroupBox(tr("Timing"))
        timing_layout = QFormLayout(timing_group)
        timing_layout.setContentsMargins(15, 20, 15, 15)
        
        # Delay (Slider or Label with buttons? Let's use Label with buttons for consistency if needed, but slider is fine for position. User asked for slider for position.)
        # For simplicity, let's just use a Label + buttons for delay too if they like that style.
        delay_layout = QHBoxLayout()
        self.delay_minus = QPushButton("-")
        self.delay_minus.setObjectName("AdjustBtn")
        self.delay_minus.clicked.connect(lambda: self.adjust_delay(-0.1))
        
        self.delay_label = QLabel(f"{sub_config['delay']:.1f} s")
        self.delay_label.setObjectName("ValLabel")
        self.delay_label.setAlignment(Qt.AlignCenter)
        
        self.delay_plus = QPushButton("+")
        self.delay_plus.setObjectName("AdjustBtn")
        self.delay_plus.clicked.connect(lambda: self.adjust_delay(0.1))
        
        delay_layout.addWidget(self.delay_minus)
        delay_layout.addWidget(self.delay_label)
        delay_layout.addWidget(self.delay_plus)
        delay_layout.addStretch()
        timing_layout.addRow(tr("Sync Delay") + ":", delay_layout)

        layout.addWidget(timing_group)

        # Footer Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        done_btn = QPushButton(tr("Done"))
        done_btn.setObjectName("PrimaryButton")
        done_btn.clicked.connect(self.accept)
        btn_layout.addWidget(done_btn)
        layout.addLayout(btn_layout)

    def adjust_size(self, delta):
        val = int(self.size_val_label.text())
        new_val = max(1, min(120, val + delta))
        self.size_val_label.setText(str(new_val))
        self.update_subtitles()

    def adjust_delay(self, delta):
        # Parse from label to keep state local
        val_str = self.delay_label.text().replace(" s", "")
        val = float(val_str)
        new_val = max(-600.0, min(600.0, val + delta))
        self.delay_label.setText(f"{new_val:.1f} s")
        self.update_subtitles()

    def update_subtitles(self):
        # Reverse map translations to english settings keys
        back_style_display = self.back_style_combo.currentText()
        back_style_en = "Shadow"
        for en_key in ["None", "Shadow", "Outline", "Opaque Box"]:
            if tr(en_key) == back_style_display:
                back_style_en = en_key
                break

        config = {
            "font_size": int(self.size_val_label.text()),
            "color": self.color_map[self.sub_color_combo.currentText()],
            "back_style": back_style_en,
            "pos": self.pos_slider.value(),
            "delay": float(self.delay_label.text().replace(" s", ""))
        }
        save_sub_settings(config)
        self.player_window.apply_subtitle_settings()


class VideoSettingsDialog(QDialog):
    def __init__(self, player_window, parent=None):
        super().__init__(parent)
        self.player_window = player_window or parent
        
        self.setWindowTitle(tr("Video Settings"))
        self.setMinimumWidth(420)
        self.setStyleSheet(DIALOG_STYLE)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(24, 24, 24, 24)

        config = load_video_settings()

        # Engine Group
        engine_group = QGroupBox(tr("Performance"))
        engine_layout = QFormLayout(engine_group)
        engine_layout.setContentsMargins(15, 20, 15, 15)
        
        self.hwdec_combo = QComboBox()
        self.hwdec_combo.addItems(["no", "auto", "auto-safe", "d3d11va", "nvdec"])
        self.hwdec_combo.setCurrentText(config.get("hwdec", "auto-safe"))
        self.hwdec_combo.currentIndexChanged.connect(self.update_video)
        engine_layout.addRow(tr("Hardware Decoding") + ":", self.hwdec_combo)

        self.renderer_combo = QComboBox()
        self.renderer_combo.addItem(tr("GPU (Legacy)"), "gpu")
        self.renderer_combo.addItem(tr("GPU Next (Recommended for DV)"), "gpu-next")
        current_renderer = config.get("renderer", "gpu")
        for i in range(self.renderer_combo.count()):
            if self.renderer_combo.itemData(i) == current_renderer:
                self.renderer_combo.setCurrentIndex(i)
                break
        self.renderer_combo.currentIndexChanged.connect(self.update_video)
        engine_layout.addRow(tr("Renderer") + ":", self.renderer_combo)

        self.gpu_api_combo = QComboBox()
        self.gpu_api_combo.addItem(tr("Auto (Default)"), "auto")
        self.gpu_api_combo.addItem("Vulkan", "vulkan")
        self.gpu_api_combo.addItem("D3D11", "d3d11")
        self.gpu_api_combo.addItem("OpenGL", "opengl")
        current_gpu_api = config.get("gpu_api", "auto")
        for i in range(self.gpu_api_combo.count()):
            if self.gpu_api_combo.itemData(i) == current_gpu_api:
                self.gpu_api_combo.setCurrentIndex(i)
                break
        self.gpu_api_combo.currentIndexChanged.connect(self.update_video)
        engine_layout.addRow(tr("GPU API") + ":", self.gpu_api_combo)
        layout.addWidget(engine_group)

        # Image Adjust Group
        adjust_group = QGroupBox(tr("Image Adjustments"))
        adjust_layout = QFormLayout(adjust_group)
        adjust_layout.setContentsMargins(15, 20, 15, 15)
        
        self.bright_slider = QSlider(Qt.Horizontal)
        self.bright_slider.setRange(-100, 100)
        self.bright_slider.setValue(config["brightness"])
        self.bright_slider.valueChanged.connect(self.update_video)
        adjust_layout.addRow(tr("Brightness") + ":", self.bright_slider)

        self.contrast_slider = QSlider(Qt.Horizontal)
        self.contrast_slider.setRange(-100, 100)
        self.contrast_slider.setValue(config["contrast"])
        self.contrast_slider.valueChanged.connect(self.update_video)
        adjust_layout.addRow(tr("Contrast") + ":", self.contrast_slider)

        self.sat_slider = QSlider(Qt.Horizontal)
        self.sat_slider.setRange(-100, 100)
        self.sat_slider.setValue(config["saturation"])
        self.sat_slider.valueChanged.connect(self.update_video)
        adjust_layout.addRow(tr("Saturation") + ":", self.sat_slider)

        self.gamma_slider = QSlider(Qt.Horizontal)
        self.gamma_slider.setRange(-100, 100)
        self.gamma_slider.setValue(config["gamma"])
        self.gamma_slider.valueChanged.connect(self.update_video)
        adjust_layout.addRow(tr("Gamma") + ":", self.gamma_slider)

        layout.addWidget(adjust_group)

        # Geometry Group
        geo_group = QGroupBox(tr("Geometry"))
        geo_layout = QFormLayout(geo_group)
        geo_layout.setContentsMargins(15, 20, 15, 15)

        # Zoom
        zoom_layout = QHBoxLayout()
        self.zoom_minus = QPushButton("-")
        self.zoom_minus.setObjectName("AdjustBtn")
        self.zoom_minus.clicked.connect(lambda: self.adjust_zoom(-0.1))
        
        self.zoom_label = QLabel(f"{config['zoom']:.1f}")
        self.zoom_label.setObjectName("ValLabel")
        self.zoom_label.setAlignment(Qt.AlignCenter)
        
        self.zoom_plus = QPushButton("+")
        self.zoom_plus.setObjectName("AdjustBtn")
        self.zoom_plus.clicked.connect(lambda: self.adjust_zoom(0.1))
        
        zoom_layout.addWidget(self.zoom_minus)
        zoom_layout.addWidget(self.zoom_label)
        zoom_layout.addWidget(self.zoom_plus)
        zoom_layout.addStretch()
        geo_layout.addRow(tr("Video Zoom") + ":", zoom_layout)

        # Aspect Ratio
        self.aspect_combo = QComboBox()
        self.aspect_combo.addItems([tr("auto"), "16:9", "4:3", "16:10", "2.35:1", "2.39:1"])
        saved_aspect = load_aspect_ratio()
        display_aspect = tr("auto") if saved_aspect == "auto" else saved_aspect
        self.aspect_combo.setCurrentText(display_aspect)
        self.aspect_combo.currentIndexChanged.connect(self.update_video)
        geo_layout.addRow(tr("Aspect Ratio") + ":", self.aspect_combo)

        # Rotation
        self.rotate_combo = QComboBox()
        self.rotate_combo.addItems(["0°", "90°", "180°", "270°"])
        rotate_val = config["rotate"]
        self.rotate_combo.setCurrentIndex(max(0, min(3, rotate_val // 90)))
        self.rotate_combo.currentIndexChanged.connect(self.update_video)
        geo_layout.addRow(tr("Rotation") + ":", self.rotate_combo)

        self.mirror_h_check = QCheckBox(tr("Mirror Horizontal"))
        self.mirror_h_check.setChecked(bool(config.get("mirror_horizontal", False)))
        self.mirror_h_check.toggled.connect(self.update_video)
        geo_layout.addRow(self.mirror_h_check)

        self.mirror_v_check = QCheckBox(tr("Mirror Vertical"))
        self.mirror_v_check.setChecked(bool(config.get("mirror_vertical", False)))
        self.mirror_v_check.toggled.connect(self.update_video)
        geo_layout.addRow(self.mirror_v_check)

        self.seek_thumb_check = QCheckBox(tr("Seek Thumbnail Preview"))
        self.seek_thumb_check.setChecked(bool(config.get("seek_thumbnail_preview", False)))
        self.seek_thumb_check.toggled.connect(self.update_video)
        geo_layout.addRow(self.seek_thumb_check)

        layout.addWidget(geo_group)

        # Footer Buttons
        btn_layout = QHBoxLayout()
        
        reset_btn = QPushButton(tr("Reset All"))
        reset_btn.clicked.connect(self.reset_to_defaults)
        btn_layout.addWidget(reset_btn)
        
        btn_layout.addStretch()
        
        done_btn = QPushButton(tr("Done"))
        done_btn.setObjectName("PrimaryButton")
        done_btn.clicked.connect(self.accept)
        btn_layout.addWidget(done_btn)
        
        layout.addLayout(btn_layout)

    def adjust_zoom(self, delta):
        val = float(self.zoom_label.text())
        # Range from -2.0 (shrunk) to 10.0 (extreme close-up)
        new_val = max(-2.0, min(10.0, val + delta))
        self.zoom_label.setText(f"{new_val:.1f}")
        self.update_video()

    def reset_to_defaults(self):
        self.bright_slider.setValue(0)
        self.contrast_slider.setValue(0)
        self.sat_slider.setValue(0)
        self.gamma_slider.setValue(0)
        self.zoom_label.setText("0.0")
        self.rotate_combo.setCurrentIndex(0)
        self.mirror_h_check.setChecked(False)
        self.mirror_v_check.setChecked(False)
        self.seek_thumb_check.setChecked(False)
        self.aspect_combo.setCurrentText("auto")
        self.hwdec_combo.setCurrentText("auto-safe")
        self.renderer_combo.setCurrentIndex(0)
        self.gpu_api_combo.setCurrentIndex(0)
        self.update_video()

    def update_video(self):
        rotate_idx = self.rotate_combo.currentIndex()
        
        aspect_val = self.aspect_combo.currentText()
        if aspect_val == tr("auto"):
            aspect_val = "auto"
            
        config = {
            "brightness": self.bright_slider.value(),
            "contrast": self.contrast_slider.value(),
            "saturation": self.sat_slider.value(),
            "gamma": self.gamma_slider.value(),
            "zoom": float(self.zoom_label.text()),
            "rotate": rotate_idx * 90,
            "mirror_horizontal": self.mirror_h_check.isChecked(),
            "mirror_vertical": self.mirror_v_check.isChecked(),
            "seek_thumbnail_preview": self.seek_thumb_check.isChecked(),
            "hwdec": self.hwdec_combo.currentText(),
            "renderer": self.renderer_combo.currentData(),
            "gpu_api": self.gpu_api_combo.currentData(),
        }
        save_video_settings(config)
        save_aspect_ratio(aspect_val)

        self.player_window.apply_video_settings()
        self.player_window.set_aspect_ratio(aspect_val)


class URLInputDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Open URL"))
        self.setMinimumWidth(400)
        self.setStyleSheet(DIALOG_STYLE)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(24, 24, 24, 24)
        
        layout.addWidget(QLabel(tr("Enter URL:")))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://...")
        layout.addWidget(self.url_edit)

        net_row = QHBoxLayout()
        self.ssl_check = QCheckBox(tr("Use SSL"))
        self.ssl_check.setChecked(False)
        net_row.addWidget(self.ssl_check)
        net_row.addStretch()
        net_row.addWidget(QLabel(tr("Port") + ":"))
        self.port_edit = QLineEdit("443")
        self.port_edit.setValidator(QIntValidator(1, 65535, self))
        self.port_edit.setFixedWidth(80)
        net_row.addWidget(self.port_edit)
        layout.addLayout(net_row)

        auth_row = QHBoxLayout()
        self.auth_check = QCheckBox(tr("Use authentication"))
        auth_row.addWidget(self.auth_check)
        auth_row.addStretch()
        layout.addLayout(auth_row)

        user_row = QHBoxLayout()
        user_row.addWidget(QLabel(tr("Username") + ":"))
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText(tr("Username"))
        user_row.addWidget(self.username_edit, 1)
        layout.addLayout(user_row)

        pass_row = QHBoxLayout()
        pass_row.addWidget(QLabel(tr("Password") + ":"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText(tr("Password"))
        pass_row.addWidget(self.password_edit, 1)
        layout.addLayout(pass_row)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setAutoDefault(False)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        self.open_btn = QPushButton(tr("Open"))
        self.open_btn.setObjectName("PrimaryButton")
        self.open_btn.setAutoDefault(True)
        self.open_btn.setDefault(True)
        self.open_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.open_btn)
        
        layout.addLayout(btn_layout)

        self.auth_check.setChecked(False)
        # Intentionally do not prefill credentials to avoid exposing secrets in UI.
        self.username_edit.setText("")
        self.password_edit.setText("")
        self._toggle_auth_fields(self.auth_check.isChecked())
        self._toggle_ssl_fields(self.ssl_check.isChecked())
        self.auth_check.toggled.connect(self._toggle_auth_fields)
        self.ssl_check.toggled.connect(self._toggle_ssl_fields)
        self.url_edit.returnPressed.connect(self.open_btn.click)

    def _toggle_auth_fields(self, enabled: bool):
        self.username_edit.setEnabled(enabled)
        self.password_edit.setEnabled(enabled)

    def _toggle_ssl_fields(self, enabled: bool):
        self.port_edit.setEnabled(enabled)
        
    def get_url(self):
        url = self.url_edit.text().strip()
        if not url:
            return ""
        if "://" not in url:
            scheme = "https" if self.ssl_check.isChecked() else "http"
            url = f"{scheme}://{url}"
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if not parsed.netloc:
                return url

            port = self.port_edit.text().strip() if self.ssl_check.isChecked() else ""
            if port:
                host_only = parsed.netloc.split("@")[-1].split(":")[0]
                userinfo = ""
                if "@" in parsed.netloc:
                    userinfo = parsed.netloc.split("@")[0] + "@"
                parsed = parsed._replace(netloc=f"{userinfo}{host_only}:{port}")
            return parsed.geturl()
        except Exception:
            return url

    def get_auth(self):
        enabled = self.auth_check.isChecked()
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        if enabled and username:
            save_stream_auth_settings(True, username, password)
            return {
                "enabled": True,
                "username": username,
                "password": password,
            }

        saved = load_stream_auth_settings()
        if enabled and saved["enabled"] and saved["username"]:
            return saved

        save_stream_auth_settings(False, "", "")
        return {
            "enabled": False,
            "username": "",
            "password": "",
        }


class EqualizerDialog(QDialog):
    def __init__(self, player_window, parent=None):
        super().__init__(parent)
        self.player_window = player_window
        self.setWindowTitle(tr("Equalizer"))
        self.setMinimumWidth(500)
        self.setMinimumHeight(350)
        self.setStyleSheet(DIALOG_STYLE)

        self.settings = load_equalizer_settings()
        self.gains = self.settings["gains"]
        self.enabled = self.settings["enabled"]

        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)

        # Top: Enable Checkbox
        top_layout = QHBoxLayout()
        self.enable_cb = QCheckBox(tr("Enable Equalizer"))
        self.enable_cb.setStyleSheet("QCheckBox { color: white; font-size: 14px; font-weight: 600; spacing: 8px; }")
        self.enable_cb.setChecked(self.enabled)
        self.enable_cb.toggled.connect(self.on_toggle)
        top_layout.addWidget(self.enable_cb)
        top_layout.addStretch()
        layout.addLayout(top_layout)

        # Middle: Sliders
        sliders_layout = QHBoxLayout()
        sliders_layout.setSpacing(10)
        
        self.sliders = []
        # Standard 10-band ISO frequencies
        freqs = ["31", "62", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"]
        
        for i, freq in enumerate(freqs):
            band_layout = QVBoxLayout()
            band_layout.setSpacing(8)
            
            slider = ClickableSlider(Qt.Vertical)
            slider.setRange(-12, 12)
            slider.setValue(self.gains[i])
            slider.setTickPosition(QSlider.TicksBothSides)
            slider.setTickInterval(6)
            slider.valueChanged.connect(self.on_change)
            self.sliders.append(slider)
            
            label = QLabel(freq)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("color: rgba(255,255,255,150); font-size: 11px;")
            
            band_layout.addWidget(slider, 1, Qt.AlignHCenter)
            band_layout.addWidget(label, 0, Qt.AlignHCenter)
            sliders_layout.addLayout(band_layout)
            
        layout.addLayout(sliders_layout)

        # Bottom: Buttons
        btn_layout = QHBoxLayout()
        reset_btn = QPushButton(tr("Reset"))
        reset_btn.clicked.connect(self.reset_values)
        btn_layout.addWidget(reset_btn)
        
        btn_layout.addStretch()
        
        ok_btn = QPushButton(tr("Done"))
        ok_btn.setObjectName("PrimaryButton")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        
        layout.addLayout(btn_layout)

    def on_toggle(self, checked):
        self.enabled = checked
        current_gains = [s.value() for s in self.sliders]
        save_equalizer_settings(self.enabled, current_gains)
        self.player_window.apply_equalizer_settings()


    def reset_values(self):
        for slider in self.sliders:
            slider.setValue(0)

    def on_change(self):
        current_gains = [s.value() for s in self.sliders]
        save_equalizer_settings(self.enabled, current_gains)
        if self.enabled:
            self.player_window.update_equalizer_gains(current_gains)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("About"))
        self.setMinimumWidth(420)
        self.setStyleSheet(DIALOG_STYLE)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Cadre Player")
        title.setStyleSheet("font-size: 20px; font-weight: 700; color: white;")
        layout.addWidget(title)

        subtitle = QLabel(tr("Modern desktop media player powered by MPV."))
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: rgba(255,255,255,185); font-size: 13px;")
        layout.addWidget(subtitle)

        details = QLabel(tr("• MPV backend\n• Playlist and stream support\n• Subtitle, video and equalizer controls"))
        
        details.setStyleSheet("color: rgba(255,255,255,165); font-size: 12px;")
        layout.addWidget(details)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton(tr("Close"))
        close_btn.setObjectName("PrimaryButton")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
