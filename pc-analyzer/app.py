from __future__ import annotations

import argparse
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = PROJECT_ROOT / ".runtime"
(RUNTIME_ROOT / "ultralytics").mkdir(parents=True, exist_ok=True)
(RUNTIME_ROOT / "matplotlib").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("YOLO_CONFIG_DIR", str(RUNTIME_ROOT / "ultralytics"))
os.environ.setdefault("MPLCONFIGDIR", str(RUNTIME_ROOT / "matplotlib"))

import cv2
from flask import Flask, Response, jsonify, render_template
from ultralytics import YOLO

from attention_tracker import AttentionTracker
from booth_tracker import BoothTracker
from identity_resolver import IdentityResolver
from line_counter import LineCounter


DEFAULT_STREAM_URL = os.environ.get(
    "STACK_CHAN_STREAM_URL", "http://stackchan-camera.local/stream"
)
BOUNDARY = b"--frame\r\n"


@dataclass(frozen=True)
class VisibleTrack:
    anonymous_id: str
    confidence: float
    box: tuple[int, int, int, int]
    in_attention_zone: bool = False
    attention_seconds: float = 0.0
    stopped: bool = False
    in_booth_zone: bool = False
    booth_seconds: float = 0.0
    visitor: bool = False


class CameraAnalyzer:
    def __init__(
        self,
        stream_url: str,
        model_name: str,
        confidence: float,
        image_size: int,
        device: str,
    ) -> None:
        self.stream_url = stream_url
        self.confidence = confidence
        self.image_size = image_size
        self.device = device
        self.identities = IdentityResolver()
        self.line_counter = LineCounter()
        self.attention_tracker = AttentionTracker()
        self.booth_tracker = BoothTracker()

        self._condition = threading.Condition()
        self._latest_jpeg: Optional[bytes] = None
        self._running = False
        self._connected = False
        self._model_ready = False
        self._error: Optional[str] = None
        self._fps = 0.0
        self._processed_frames = 0
        self._tracks: List[VisibleTrack] = []

        model_path = Path(model_name)
        if not model_path.is_absolute() and model_path.parent == Path("."):
            model_path = PROJECT_ROOT / "models" / model_path
        model_path.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
        self.model = YOLO(str(model_path))
        self._model_ready = True

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        threading.Thread(target=self._run, name="camera-analyzer", daemon=True).start()

    def status(self) -> dict:
        with self._condition:
            return {
                "connected": self._connected,
                "model_ready": self._model_ready,
                "error": self._error,
                "fps": round(self._fps, 1),
                "processed_frames": self._processed_frames,
                "people_visible": len(self._tracks),
                "tracks": [
                    {
                        "id": track.anonymous_id,
                        "confidence": round(track.confidence, 2),
                        "attention_seconds": round(track.attention_seconds, 1),
                        "in_attention_zone": track.in_attention_zone,
                        "stopped": track.stopped,
                        "in_booth_zone": track.in_booth_zone,
                        "booth_seconds": round(track.booth_seconds, 1),
                        "visitor": track.visitor,
                    }
                    for track in self._tracks
                ],
                "line_counter": self.line_counter.snapshot(),
                "attention": self.attention_tracker.snapshot(),
                "booth": self.booth_tracker.snapshot(),
                "privacy": {
                    "video_recording": False,
                    "face_recognition": False,
                    "demographic_inference": False,
                },
            }

    def mjpeg_frames(self) -> Iterator[bytes]:
        previous_frame: Optional[bytes] = None
        while True:
            with self._condition:
                self._condition.wait_for(
                    lambda: self._latest_jpeg is not None and self._latest_jpeg is not previous_frame,
                    timeout=2.0,
                )
                jpeg = self._latest_jpeg
            if jpeg is None or jpeg is previous_frame:
                continue
            previous_frame = jpeg
            yield (
                BOUNDARY
                + b"Content-Type: image/jpeg\r\n"
                + f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii")
                + jpeg
                + b"\r\n"
            )

    def _run(self) -> None:
        while self._running:
            capture = cv2.VideoCapture(self.stream_url)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not capture.isOpened():
                self._set_connection_error("CoreS3の映像へ接続できません")
                capture.release()
                time.sleep(2)
                continue

            with self._condition:
                self._connected = True
                self._error = None

            last_frame_at = time.perf_counter()
            smoothed_fps = 0.0

            while self._running:
                success, frame = capture.read()
                if not success or frame is None:
                    self._set_connection_error("映像が途切れました。再接続しています")
                    break

                now = time.perf_counter()
                elapsed = max(now - last_frame_at, 1e-6)
                instant_fps = 1.0 / elapsed
                smoothed_fps = instant_fps if smoothed_fps == 0 else smoothed_fps * 0.9 + instant_fps * 0.1
                last_frame_at = now

                try:
                    result = self.model.track(
                        frame,
                        persist=True,
                        tracker="bytetrack.yaml",
                        classes=[0],
                        conf=self.confidence,
                        iou=0.5,
                        imgsz=self.image_size,
                        device=self.device,
                        verbose=False,
                    )[0]
                    tracks = self._extract_tracks(
                        result,
                        frame_width=frame.shape[1],
                        frame_height=frame.shape[0],
                        now=now,
                    )
                    annotated = self._draw(frame, tracks, smoothed_fps)
                except Exception as exc:  # 推論失敗時も接続を維持し、画面へ原因を出す。
                    with self._condition:
                        self._error = f"推論エラー: {type(exc).__name__}"
                    annotated = frame
                    tracks = []

                encoded, jpeg = cv2.imencode(
                    ".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 78]
                )
                if not encoded:
                    continue

                with self._condition:
                    self._latest_jpeg = jpeg.tobytes()
                    self._fps = smoothed_fps
                    self._processed_frames += 1
                    self._tracks = tracks
                    self._condition.notify_all()

            capture.release()
            time.sleep(1)

    def _extract_tracks(
        self,
        result,
        frame_width: int,
        frame_height: int,
        now: float,
    ) -> List[VisibleTrack]:
        boxes = result.boxes
        if boxes is None or boxes.id is None:
            self.attention_tracker.finish_frame([], now=now)
            self.booth_tracker.finish_frame([], now=now)
            return []

        raw_ids = boxes.id.int().cpu().tolist()
        visible: List[VisibleTrack] = []
        visible_ids = []
        for coordinates, raw_id, confidence in zip(
            boxes.xyxy.cpu().tolist(),
            raw_ids,
            boxes.conf.cpu().tolist(),
        ):
            x1, y1, x2, y2 = (int(value) for value in coordinates)
            box = (x1, y1, x2, y2)
            anonymous_id = self.identities.resolve(
                raw_id=int(raw_id),
                box=box,
                frame_width=frame_width,
                frame_height=frame_height,
                current_raw_ids=raw_ids,
                now=now,
            )
            center_x = (x1 + x2) / 2
            center_y = (y1 + y2) / 2
            attention = self.attention_tracker.update(
                anonymous_id=anonymous_id,
                center_x=center_x,
                center_y=center_y,
                frame_width=frame_width,
                frame_height=frame_height,
                now=now,
            )
            booth = self.booth_tracker.update(
                anonymous_id=anonymous_id,
                center_x=center_x,
                center_y=center_y,
                frame_width=frame_width,
                frame_height=frame_height,
                now=now,
            )
            visible_track = VisibleTrack(
                anonymous_id=anonymous_id,
                confidence=float(confidence),
                box=box,
                in_attention_zone=attention["inside"],
                attention_seconds=float(attention["seconds"]),
                stopped=bool(attention["stopped"]),
                in_booth_zone=bool(booth["inside"]),
                booth_seconds=float(booth["seconds"]),
                visitor=bool(booth["visitor"]),
            )
            visible.append(visible_track)
            visible_ids.append(anonymous_id)
            self.line_counter.update(
                anonymous_id=anonymous_id,
                center_x=center_x,
                frame_width=frame_width,
                now=now,
            )
        self.attention_tracker.finish_frame(visible_ids, now=now)
        self.booth_tracker.finish_frame(visible_ids, now=now)
        return visible

    def _draw(self, frame, tracks: List[VisibleTrack], fps: float):
        output = frame.copy()
        counter = self.line_counter.snapshot()
        attention = self.attention_tracker.snapshot()
        booth = self.booth_tracker.snapshot()
        line_x = int(output.shape[1] * counter["line_ratio"])
        zone_x1 = int(output.shape[1] * attention["zone"][0])
        zone_y1 = int(output.shape[0] * attention["zone"][1])
        zone_x2 = int(output.shape[1] * attention["zone"][2])
        zone_y2 = int(output.shape[0] * attention["zone"][3])
        booth_x1 = int(output.shape[1] * booth["zone"][0])
        booth_y1 = int(output.shape[0] * booth["zone"][1])
        booth_x2 = int(output.shape[1] * booth["zone"][2])
        booth_y2 = int(output.shape[0] * booth["zone"][3])
        cv2.rectangle(
            output,
            (zone_x1, zone_y1),
            (zone_x2, zone_y2),
            (255, 180, 40),
            2,
        )
        cv2.putText(
            output,
            f"ATTENTION {attention['threshold_seconds']:.0f}s",
            (zone_x1 + 4, min(zone_y1 + 14, output.shape[0] - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            (255, 180, 40),
            1,
            cv2.LINE_AA,
        )
        cv2.rectangle(
            output,
            (booth_x1, booth_y1),
            (booth_x2, booth_y2),
            (215, 90, 225),
            2,
        )
        cv2.putText(
            output,
            "BOOTH",
            (booth_x1 + 4, min(booth_y1 + 30, output.shape[0] - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            (215, 90, 225),
            1,
            cv2.LINE_AA,
        )
        cv2.line(output, (line_x, 0), (line_x, output.shape[0]), (0, 220, 255), 2)
        cv2.putText(
            output,
            "PASS LINE",
            (min(line_x + 5, output.shape[1] - 82), output.shape[0] - 9),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (0, 220, 255),
            1,
            cv2.LINE_AA,
        )
        for track in tracks:
            x1, y1, x2, y2 = track.box
            cv2.rectangle(output, (x1, y1), (x2, y2), (45, 220, 140), 2)
            stop_label = " STOP" if track.stopped else ""
            dwell_label = (
                f" {track.attention_seconds:.1f}s" if track.in_attention_zone else ""
            )
            booth_label = (
                f" BOOTH {track.booth_seconds:.1f}s" if track.in_booth_zone and track.visitor else ""
            )
            label = (
                f"{track.anonymous_id} {track.confidence:.0%}"
                f"{dwell_label}{stop_label}{booth_label}"
            )
            (text_width, text_height), _ = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1
            )
            label_top = max(0, y1 - text_height - 8)
            cv2.rectangle(
                output,
                (x1, label_top),
                (x1 + text_width + 8, y1),
                (45, 220, 140),
                -1,
            )
            cv2.putText(
                output,
                label,
                (x1 + 4, y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                (5, 20, 16),
                1,
                cv2.LINE_AA,
            )

        cv2.putText(
            output,
            f"people: {len(tracks)}  analysis: {fps:.1f} FPS",
            (8, 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            output,
            f"passages: {counter['passages']}",
            (8, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (0, 220, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            output,
            f"stops: {attention['stops']}",
            (8, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (255, 180, 40),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            output,
            f"visitors: {booth['visitors']}  avg: {booth['average_dwell_seconds']:.1f}s",
            (8, 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (215, 90, 225),
            1,
            cv2.LINE_AA,
        )
        return output

    def _set_connection_error(self, message: str) -> None:
        with self._condition:
            self._connected = False
            self._error = message
            self._tracks = []
            self._condition.notify_all()

    def reset_counts(self) -> None:
        self.line_counter.reset()
        self.attention_tracker.reset()
        self.booth_tracker.reset()


def create_app(analyzer: CameraAnalyzer) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/health")
    def health():
        status = analyzer.status()
        code = 200 if status["connected"] and status["model_ready"] else 503
        return jsonify(status), code

    @app.get("/api/status")
    def api_status():
        return jsonify(analyzer.status())

    @app.post("/api/reset-counts")
    def reset_counts():
        analyzer.reset_counts()
        return jsonify(analyzer.status())

    @app.get("/stream")
    def stream():
        return Response(
            analyzer.mjpeg_frames(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "X-Privacy": "no-recording-no-face-recognition",
            },
        )

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stack-chan anonymous person tracker")
    parser.add_argument("--stream-url", default=DEFAULT_STREAM_URL)
    parser.add_argument("--model", default="yolo11n.pt")
    parser.add_argument("--confidence", type=float, default=0.30)
    parser.add_argument("--image-size", type=int, default=320)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    analyzer = CameraAnalyzer(
        stream_url=args.stream_url,
        model_name=args.model,
        confidence=args.confidence,
        image_size=args.image_size,
        device=args.device,
    )
    analyzer.start()
    app = create_app(analyzer)
    app.run(host=args.host, port=args.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
