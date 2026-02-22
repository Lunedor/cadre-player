import random
from pathlib import Path
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
