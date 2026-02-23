from PySide6.QtWidgets import QMenu
from PySide6.QtCore import Qt
from ..ui.styles import MENU_STYLE
from ..settings import load_aspect_ratio, load_language_setting
from ..i18n import tr, get_supported_languages

def create_main_context_menu(player, pos):
    menu = QMenu(player)
    menu.setStyleSheet(MENU_STYLE)

    # Playback Controls
    play_action = menu.addAction(tr("Play / Pause") + "\tSpace")
    play_action.triggered.connect(player.toggle_play)

    stop_action = menu.addAction(tr("Stop"))
    stop_action.triggered.connect(player.stop_playback)

    prev_action = menu.addAction(tr("Previous") + "\tPgUp")
    prev_action.triggered.connect(player.prev_video)

    next_action = menu.addAction(tr("Next") + "\tPgDn")
    next_action.triggered.connect(player.next_video)

    menu.addSeparator()

    # Standalone: Playback Speed
    speed_menu = menu.addMenu(tr("Playback Speed"))
    current_speed = float(player.player.speed or 1.0)
    for speed in [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]:
        if speed == 1.0:
            label = tr("{}x (Normal)").format(speed)
        else:
            label = tr("{}x").format(speed)
        action = speed_menu.addAction(label)
        action.setCheckable(True)
        if abs(current_speed - speed) < 0.01:
            action.setChecked(True)
        action.triggered.connect(lambda checked, s=speed: setattr(player.player, "speed", s))

    # Audio Options
    audio_options_menu = menu.addMenu(tr("Audio Options"))
    mute_action = audio_options_menu.addAction(tr("Mute / Unmute") + "\tM")
    mute_action.triggered.connect(player.toggle_mute)
    audio_options_menu.addSeparator()

    # Audio Tracks
    tracks = []
    try:
        tracks = player.player.track_list
    except:
        pass
    
    audio_tracks = [t for t in tracks if t['type'] == 'audio']
    audio_menu = audio_options_menu.addMenu(tr("Audio Tracks"))
    if len(audio_tracks) <= 1:
        audio_menu.setEnabled(False)
    else:
        for t in audio_tracks:
            title = t.get('title') or t.get('lang') or f"Track {t['id']}"
            action = audio_menu.addAction(title)
            action.setCheckable(True)
            if t['selected']: action.setChecked(True)
            action.triggered.connect(lambda checked, tid=t['id']: setattr(player.player, "aid", tid))

    eq_action = audio_options_menu.addAction(tr("Equalizer") + "...")
    eq_action.triggered.connect(player.open_equalizer_dialog)

    # Video Options
    video_options_menu = menu.addMenu(tr("Video Options"))
    quality_menu = video_options_menu.addMenu(tr("Video Quality"))
    quality_options = player.get_stream_quality_menu_options()
    if not quality_options:
        quality_menu.setEnabled(False)
    else:
        for value, label, is_current in quality_options:
            q_act = quality_menu.addAction(label)
            q_act.setCheckable(True)
            q_act.setChecked(is_current)
            q_act.triggered.connect(lambda checked, q=value: player.set_stream_quality(q))

    # Aspect Ratio
    aspect_menu = video_options_menu.addMenu(tr("Aspect Ratio"))
    current_ar = load_aspect_ratio()
    ratios = ["auto", "16:9", "4:3", "16:10", "2.35:1", "2.39:1"]
    for r in ratios:
        label = tr("Auto (Original)") if r == "auto" else r
        act = aspect_menu.addAction(label)
        act.setCheckable(True)
        if current_ar == r: act.setChecked(True)
        act.triggered.connect(lambda checked, ar=r: player.set_aspect_ratio(ar))

    video_settings_action = video_options_menu.addAction(tr("Video Settings")+"...")
    video_settings_action.triggered.connect(player.open_video_settings)

    ss_action = video_options_menu.addAction(tr("Screenshot") + "\tS")
    ss_action.triggered.connect(player.screenshot_save_as)

    # Subtitle Options
    subtitle_options_menu = menu.addMenu(tr("Subtitle Options"))
    sub_tracks = [t for t in tracks if t['type'] == 'sub']
    sub_menu = subtitle_options_menu.addMenu(tr("Subtitle Tracks"))
    if not sub_tracks:
        sub_menu.setEnabled(False)
    else:
        none_action = sub_menu.addAction(tr("No Subtitles"))
        none_action.setCheckable(True)
        if not any(t['selected'] for t in sub_tracks):
            none_action.setChecked(True)
        none_action.triggered.connect(lambda: setattr(player.player, "sid", "no"))
        
        for t in sub_tracks:
            title = t.get('title') or t.get('lang') or f"Track {t['id']}"
            action = sub_menu.addAction(title)
            action.setCheckable(True)
            if t['selected']: action.setChecked(True)
            action.triggered.connect(lambda checked, tid=t['id']: setattr(player.player, "sid", tid))

    add_sub_action = subtitle_options_menu.addAction(tr("Add Subtitle File")+"...")
    add_sub_action.triggered.connect(player.add_subtitle_file)
    
    sub_settings_action = subtitle_options_menu.addAction(tr("Subtitle Settings")+"...")
    sub_settings_action.triggered.connect(player.open_subtitle_settings)

    menu.addSeparator()

    # Standalone
    playlist_action = menu.addAction(tr("Toggle Playlist") + "\tP")
    playlist_action.triggered.connect(player.toggle_playlist_panel)

    del_action = menu.addAction(tr("Delete File") + "\tDel")
    del_action.triggered.connect(player.delete_selected_file_to_trash)

    menu.addSeparator()

    # View Interface
    view_menu = menu.addMenu(tr("View Interface"))
    pin_controls = view_menu.addAction(tr("Pin Controls"))
    pin_controls.setCheckable(True)
    pin_controls.setChecked(player.pinned_controls)
    pin_controls.triggered.connect(player.toggle_pin_controls)

    pin_playlist = view_menu.addAction(tr("Pin Playlist"))
    pin_playlist.setCheckable(True)
    pin_playlist.setChecked(player.pinned_playlist)
    pin_playlist.triggered.connect(player.toggle_pin_playlist)

    fs_action = view_menu.addAction(tr("Fullscreen") + "\tF")
    fs_action.triggered.connect(player.toggle_fullscreen)

    ontop_action = view_menu.addAction(tr("Always On Top"))
    ontop_action.setCheckable(True)
    ontop_action.setChecked(player.always_on_top)
    ontop_action.triggered.connect(player.toggle_always_on_top)

    menu.addSeparator()

    # Standalone: Language
    lang_menu = menu.addMenu(tr("Language"))
    supported_langs = get_supported_languages()
    current_lang = load_language_setting("")
    
    # Auto option
    auto_action = lang_menu.addAction(tr("Auto (System)"))
    auto_action.setCheckable(True)
    if not current_lang: auto_action.setChecked(True)
    auto_action.triggered.connect(lambda: player.change_language(""))
    
    lang_menu.addSeparator()
    
    for code, name in supported_langs:
        action = lang_menu.addAction(name)
        action.setCheckable(True)
        if current_lang == code: action.setChecked(True)
        action.triggered.connect(lambda checked, c=code: player.change_language(c))
    
    menu.addSeparator()

    # Standalone: About
    about_action = menu.addAction(tr("About"))
    about_action.triggered.connect(player.open_about_dialog)

    menu.addSeparator()

    return menu

def create_playlist_context_menu(player, pos):
    indices = player.get_selected_playlist_indices()
    num_selected = len(indices)
    if num_selected == 0:
        return None

    menu = QMenu(player)
    menu.setStyleSheet(MENU_STYLE)
    
    if num_selected == 1:
        play_action = menu.addAction(tr("Play"))
        remove_action = menu.addAction(tr("Remove"))
        delete_action = menu.addAction(tr("Delete file"))
        reveal_action = menu.addAction(tr("Reveal in Explorer"))
        copy_action = menu.addAction(tr("Copy path"))
        path = player.playlist[indices[0]]
    else:
        play_action = None
        remove_action = menu.addAction(tr("Remove {} items").format(num_selected))
        delete_action = menu.addAction(tr("Delete {} files from disk").format(num_selected))
        reveal_action = None
        copy_action = menu.addAction(tr("Copy paths"))
        path = None
    
    return menu, indices, path, play_action, remove_action, delete_action, reveal_action, copy_action
