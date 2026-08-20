from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple


@dataclass
class PersonBoothState:
    seen_outside: bool = False
    entered_at: Optional[float] = None
    last_seen_at: Optional[float] = None


class BoothTracker:
    """通路側で確認した匿名IDがブースゾーンへ入った来訪と滞在を測る。"""

    def __init__(
        self,
        zone: Tuple[float, float, float, float] = (0.70, 0.08, 0.98, 0.98),
        missing_grace_seconds: float = 0.5,
    ) -> None:
        self.zone = zone
        self.missing_grace_seconds = missing_grace_seconds
        self._lock = threading.Lock()
        self._states: Dict[str, PersonBoothState] = {}
        self._visitor_ids: Set[str] = set()
        self._completed_durations: List[float] = []

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
            state = self._states.setdefault(anonymous_id, PersonBoothState())
            new_visit = False

            if inside:
                if (
                    state.seen_outside
                    and anonymous_id not in self._visitor_ids
                ):
                    self._visitor_ids.add(anonymous_id)
                    state.entered_at = timestamp
                    new_visit = True
                if state.entered_at is not None:
                    state.last_seen_at = timestamp
            else:
                state.seen_outside = True
                self._complete_active_visit(state, timestamp)

            dwell_seconds = (
                max(0.0, timestamp - state.entered_at)
                if state.entered_at is not None
                else 0.0
            )
            return {
                "inside": inside,
                "visitor": anonymous_id in self._visitor_ids,
                "new_visit": new_visit,
                "seconds": dwell_seconds,
            }

    def finish_frame(
        self, visible_ids: Iterable[str], now: Optional[float] = None
    ) -> None:
        timestamp = time.monotonic() if now is None else now
        visible = set(visible_ids)
        with self._lock:
            for anonymous_id, state in self._states.items():
                if (
                    state.entered_at is not None
                    and anonymous_id not in visible
                    and state.last_seen_at is not None
                    and timestamp - state.last_seen_at > self.missing_grace_seconds
                ):
                    self._complete_active_visit(state, state.last_seen_at)

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
            completed = len(self._completed_durations)
            average = (
                sum(self._completed_durations) / completed if completed else 0.0
            )
            active = sum(
                1 for state in self._states.values() if state.entered_at is not None
            )
            return {
                "visitors": len(self._visitor_ids),
                "active_visits": active,
                "completed_visits": completed,
                "average_dwell_seconds": round(average, 1),
                "zone": list(self.zone),
            }

    def reset(self) -> None:
        with self._lock:
            self._states.clear()
            self._visitor_ids.clear()
            self._completed_durations.clear()

    def _complete_active_visit(
        self, state: PersonBoothState, ended_at: float
    ) -> None:
        if state.entered_at is None:
            return
        self._completed_durations.append(max(0.0, ended_at - state.entered_at))
        state.entered_at = None
        state.last_seen_at = None
