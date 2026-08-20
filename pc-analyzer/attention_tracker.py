from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Set, Tuple


@dataclass
class ActiveVisit:
    entered_at: float
    last_seen_at: float


class AttentionTracker:
    """注目ゾーン内の連続滞在を測り、匿名IDごとに一度だけ停止判定する。"""

    def __init__(
        self,
        threshold_seconds: float = 2.0,
        zone: Tuple[float, float, float, float] = (0.15, 0.12, 0.85, 0.95),
        missing_grace_seconds: float = 0.5,
    ) -> None:
        self.threshold_seconds = threshold_seconds
        self.zone = zone
        self.missing_grace_seconds = missing_grace_seconds
        self._lock = threading.Lock()
        self._active: Dict[str, ActiveVisit] = {}
        self._qualified_ids: Set[str] = set()

    def update(
        self,
        anonymous_id: str,
        center_x: float,
        center_y: float,
        frame_width: int,
        frame_height: int,
        now: Optional[float] = None,
    ) -> dict:
        timestamp = time.monotonic() if now is None else now
        inside = self.contains(center_x, center_y, frame_width, frame_height)

        with self._lock:
            if not inside:
                self._active.pop(anonymous_id, None)
                return {
                    "inside": False,
                    "seconds": 0.0,
                    "stopped": anonymous_id in self._qualified_ids,
                    "new_stop": False,
                }

            active = self._active.get(anonymous_id)
            if active is None:
                active = ActiveVisit(entered_at=timestamp, last_seen_at=timestamp)
                self._active[anonymous_id] = active
            else:
                active.last_seen_at = timestamp

            dwell_seconds = max(0.0, timestamp - active.entered_at)
            new_stop = (
                dwell_seconds >= self.threshold_seconds
                and anonymous_id not in self._qualified_ids
            )
            if new_stop:
                self._qualified_ids.add(anonymous_id)

            return {
                "inside": True,
                "seconds": dwell_seconds,
                "stopped": anonymous_id in self._qualified_ids,
                "new_stop": new_stop,
            }

    def finish_frame(
        self, visible_ids: Iterable[str], now: Optional[float] = None
    ) -> None:
        timestamp = time.monotonic() if now is None else now
        visible = set(visible_ids)
        with self._lock:
            expired = [
                anonymous_id
                for anonymous_id, visit in self._active.items()
                if anonymous_id not in visible
                and timestamp - visit.last_seen_at > self.missing_grace_seconds
            ]
            for anonymous_id in expired:
                self._active.pop(anonymous_id, None)

    def contains(
        self,
        center_x: float,
        center_y: float,
        frame_width: int,
        frame_height: int,
    ) -> bool:
        x_min, y_min, x_max, y_max = self.zone
        return (
            frame_width * x_min <= center_x <= frame_width * x_max
            and frame_height * y_min <= center_y <= frame_height * y_max
        )

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "stops": len(self._qualified_ids),
                "threshold_seconds": self.threshold_seconds,
                "zone": list(self.zone),
            }

    def reset(self) -> None:
        with self._lock:
            self._active.clear()
            self._qualified_ids.clear()
