from __future__ import annotations

import threading
import time
from typing import Dict, Optional


class LineCounter:
    """固定した縦線を匿名トラックが横切った回数をセッション内で数える。"""

    def __init__(
        self,
        line_ratio: float = 0.5,
        deadband_ratio: float = 0.06,
        cooldown_seconds: float = 0.75,
        stability_frames: int = 3,
    ) -> None:
        if not 0.0 < line_ratio < 1.0:
            raise ValueError("line_ratio must be between 0 and 1")
        self.line_ratio = line_ratio
        self.deadband_ratio = deadband_ratio
        self.cooldown_seconds = cooldown_seconds
        self.stability_frames = stability_frames
        self._lock = threading.Lock()
        self._sides: Dict[str, int] = {}
        self._candidate_sides: Dict[str, int] = {}
        self._candidate_frames: Dict[str, int] = {}
        self._last_count_at: Dict[str, float] = {}
        self._total = 0
        self._left_to_right = 0
        self._right_to_left = 0

    def update(
        self,
        anonymous_id: str,
        center_x: float,
        frame_width: int,
        now: Optional[float] = None,
    ) -> Optional[str]:
        timestamp = time.monotonic() if now is None else now
        line_x = frame_width * self.line_ratio
        deadband = frame_width * self.deadband_ratio

        if center_x < line_x - deadband:
            current_side = -1
        elif center_x > line_x + deadband:
            current_side = 1
        else:
            with self._lock:
                self._candidate_sides.pop(anonymous_id, None)
                self._candidate_frames.pop(anonymous_id, None)
            return None

        with self._lock:
            if self._candidate_sides.get(anonymous_id) == current_side:
                self._candidate_frames[anonymous_id] = (
                    self._candidate_frames.get(anonymous_id, 0) + 1
                )
            else:
                self._candidate_sides[anonymous_id] = current_side
                self._candidate_frames[anonymous_id] = 1

            if self._candidate_frames[anonymous_id] < self.stability_frames:
                return None

            previous_side = self._sides.get(anonymous_id)
            self._sides[anonymous_id] = current_side
            if previous_side is None or previous_side == current_side:
                return None

            last_count_at = self._last_count_at.get(anonymous_id, float("-inf"))
            if timestamp - last_count_at < self.cooldown_seconds:
                return None

            self._last_count_at[anonymous_id] = timestamp
            self._total += 1
            if previous_side == -1 and current_side == 1:
                self._left_to_right += 1
                return "left_to_right"

            self._right_to_left += 1
            return "right_to_left"

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "passages": self._total,
                "left_to_right": self._left_to_right,
                "right_to_left": self._right_to_left,
                "line_ratio": self.line_ratio,
            }

    def reset(self) -> None:
        with self._lock:
            self._sides.clear()
            self._candidate_sides.clear()
            self._candidate_frames.clear()
            self._last_count_at.clear()
            self._total = 0
            self._left_to_right = 0
            self._right_to_left = 0
