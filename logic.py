import random
import logging

from .i18n import tr
from .utils import REPEAT_OFF, REPEAT_ONE, REPEAT_ALL

class PlayerLogic:
    def __init__(self):
        self.playlist = []
        self.current_index = -1
        self.shuffle_enabled = False
        self.shuffle_order = []
        self.shuffle_pos = 0
        self.repeat_mode = REPEAT_OFF

    def rebuild_shuffle_order(self, keep_current: bool):
        size = len(self.playlist)
        self.shuffle_order = list(range(size))
        if size == 0:
            self.shuffle_pos = 0
            return
        random.shuffle(self.shuffle_order)
        if keep_current and 0 <= self.current_index < size:
            if self.current_index in self.shuffle_order:
                self.shuffle_order.remove(self.current_index)
            self.shuffle_order.insert(0, self.current_index)
        if 0 <= self.current_index < size and self.current_index in self.shuffle_order:
            self.shuffle_pos = self.shuffle_order.index(self.current_index)
        else:
            self.shuffle_pos = 0

    def sync_shuffle_pos_to_current(self):
        if not self.shuffle_enabled:
            return
        if self.current_index in self.shuffle_order:
            self.shuffle_pos = self.shuffle_order.index(self.current_index)

    def get_adjacent_index(self, forward: bool):
        size = len(self.playlist)
        if size == 0:
            return None
        if self.current_index < 0:
            return 0
        if self.repeat_mode == REPEAT_ONE:
            return self.current_index

        if self.shuffle_enabled:
            if not self.shuffle_order:
                self.rebuild_shuffle_order(keep_current=True)
            self.sync_shuffle_pos_to_current()
            next_pos = self.shuffle_pos + (1 if forward else -1)
            if 0 <= next_pos < len(self.shuffle_order):
                self.shuffle_pos = next_pos
                return self.shuffle_order[self.shuffle_pos]
            if self.repeat_mode == REPEAT_ALL:
                self.shuffle_pos = 0 if forward else len(self.shuffle_order) - 1
                return self.shuffle_order[self.shuffle_pos]
            return None

        next_index = self.current_index + (1 if forward else -1)
        if 0 <= next_index < size:
            return next_index
        if self.repeat_mode == REPEAT_ALL:
            return 0 if forward else size - 1
        return None

    def _advance_after_end(self):
        return self.next_video(manual=False)

    def prev_video(self, manual: bool = True):
        if self._full_duration_scan_active:
            self.show_status_overlay(tr("Duration scan is running (F4 to cancel)"))
            return
        if not self._can_switch_track_now(manual=manual):
            return
        next_index = self.get_adjacent_index(forward=False)
        if next_index is None:
            return
        self.save_current_resume_info()
        self._user_paused = False
        self.current_index = next_index
        self._schedule_play_current(self._manual_switch_delay_ms if manual else 0)
        self.show_status_overlay(tr("Previous"))
        logging.info("Prev video: current_index=%d playlist=%d", self.current_index, len(self.playlist))

    def next_video(self, manual: bool = True):
        if self._full_duration_scan_active:
            self.show_status_overlay(tr("Duration scan is running (F4 to cancel)"))
            return False
        if not self._can_switch_track_now(manual=manual):
            return False
        next_index = self.get_adjacent_index(forward=True)
        if next_index is None:
            return False
        self.save_current_resume_info()
        self._user_paused = False
        self.current_index = next_index
        self._schedule_play_current(self._manual_switch_delay_ms if manual else 0)
        self.show_status_overlay(tr("Next"))
        logging.info("Next video: current_index=%d playlist=%d", self.current_index, len(self.playlist))
        return True
