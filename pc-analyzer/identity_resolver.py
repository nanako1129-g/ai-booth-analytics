from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple


Box = Tuple[int, int, int, int]


@dataclass
class RawTrackState:
    anonymous_id: str
    box: Box
    last_seen_at: float


class IdentityResolver:
    """短時間・近距離のByteTrack ID切替を同じ匿名IDへ引き継ぐ。"""

    def __init__(
        self,
        handoff_seconds: float = 1.25,
        max_distance_ratio: float = 0.18,
    ) -> None:
        self.handoff_seconds = handoff_seconds
        self.max_distance_ratio = max_distance_ratio
        self._lock = threading.Lock()
        self._raw_tracks: Dict[int, RawTrackState] = {}
        self._next_number = 1

    def resolve(
        self,
        raw_id: int,
        box: Box,
        frame_width: int,
        frame_height: int,
        current_raw_ids: Iterable[int],
        now: Optional[float] = None,
    ) -> str:
        timestamp = time.monotonic() if now is None else now
        current_ids = set(current_raw_ids)

        with self._lock:
            existing = self._raw_tracks.get(raw_id)
            if existing is not None:
                existing.box = box
                existing.last_seen_at = timestamp
                return existing.anonymous_id

            diagonal = math.hypot(frame_width, frame_height)
            max_distance = diagonal * self.max_distance_ratio
            center = self._center(box)
            best_state: Optional[RawTrackState] = None
            best_distance = float("inf")

            for candidate_raw_id, candidate in self._raw_tracks.items():
                if candidate_raw_id in current_ids:
                    continue
                if timestamp - candidate.last_seen_at > self.handoff_seconds:
                    continue
                distance = math.dist(center, self._center(candidate.box))
                if distance <= max_distance and distance < best_distance:
                    best_state = candidate
                    best_distance = distance

            if best_state is None:
                anonymous_id = f"person_{self._next_number:03d}"
                self._next_number += 1
            else:
                anonymous_id = best_state.anonymous_id

            self._raw_tracks[raw_id] = RawTrackState(
                anonymous_id=anonymous_id,
                box=box,
                last_seen_at=timestamp,
            )
            return anonymous_id

    @staticmethod
    def _center(box: Box) -> Tuple[float, float]:
        x1, y1, x2, y2 = box
        return (x1 + x2) / 2, (y1 + y2) / 2
