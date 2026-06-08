import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import os
import subprocess
import time
import traceback
import threading

import cv2

import modules.globals
from modules.processors.frame import face_swapper, face_enhancer


def log(msg: str):
    print(f"[rtmp_deeplivecam] {msg}", flush=True)


def setup_deeplivecam(enhancer: bool = False):
    modules.globals.execution_providers = ["CUDAExecutionProvider"]
    modules.globals.execution_threads = 8
    modules.globals.frame_processors = ["face_swapper"]
    modules.globals.many_faces = False
    modules.globals.mouth_mask = False
    modules.globals.map_faces = False

    modules.globals.fp_ui = {
        "face_enhancer": bool(enhancer),
        "face_enhancer_gpen256": False,
        "face_enhancer_gpen512": False,
    }

    log("DeepLiveCam globals configured")
    log(f"execution_providers={modules.globals.execution_providers}")
    log(f"enhancer={enhancer}")

    log("Running face_swapper.pre_check()")
    if not face_swapper.pre_check():
        raise RuntimeError("face_swapper.pre_check() failed")

    log("Running face_swapper.pre_start()")
    if not face_swapper.pre_start():
        raise RuntimeError("face_swapper.pre_start() failed")

    if enhancer:
        log("Running face_enhancer.pre_check()")
        if not face_enhancer.pre_check():
            raise RuntimeError("face_enhancer.pre_check() failed")

        # Realtime RTMP mode has no normal target_path.
        # Original face_enhancer.pre_start() validates target_path and can fail with:
        # "Select an image or video for target path."
        # We skip this validation, but keep enhancer enabled for frame processing.
        log("Skipping face_enhancer.pre_start() in realtime mode; enhancer remains enabled.")


def load_source_face(source_path: str):
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Source image not found: {source_path}")

    source_frame = cv2.imread(source_path)

    if source_frame is None:
        raise RuntimeError(f"Could not read source image: {source_path}")

    source_face = face_swapper.get_one_face(source_frame)

    if source_face is None:
        raise RuntimeError(f"No face found in source image: {source_path}")

    log(f"Source face loaded from: {source_path}")
    return source_face


def open_capture(url: str, retries: int = 60, delay: float = 1.0):
    for attempt in range(1, retries + 1):
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)

        if cap.isOpened():
            ok, frame = cap.read()
            if ok and frame is not None:
                log(f"Input stream opened: {url}")
                return cap, frame

        log(f"Waiting for input stream... attempt {attempt}/{retries}")
        cap.release()
        time.sleep(delay)

    raise RuntimeError(f"Could not open input stream: {url}")

class LatestFrameReader:
    def __init__(self, url: str):
        self.url = url
        self.cap = None
        self.frame = None
        self.lock = threading.Lock()
        self.running = False
        self.thread = None
        self.read_frames = 0
        self.frame_id = 0
        self.reconnects = 0

    def start(self):
        self.running = True
        self.cap, first_frame = open_capture(self.url)

        with self.lock:
            self.frame = first_frame
            self.frame_id = 1

        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        return first_frame

    def _loop(self):
        while self.running:
            try:
                ok, frame = self.cap.read()

                if not ok or frame is None:
                    log("LatestFrameReader: input read failed, reconnecting...")
                    self.reconnects += 1

                    try:
                        self.cap.release()
                    except Exception:
                        pass

                    self.cap, frame = open_capture(self.url)

                with self.lock:
                    self.frame = frame
                    self.frame_id += 1

                self.read_frames += 1

            except Exception as e:
                log(f"LatestFrameReader error: {e}")
                time.sleep(0.2)

    def read(self):
        with self.lock:
            if self.frame is None:
                return None
            return self.frame.copy()

    def read_latest(self):
        with self.lock:
            if self.frame is None:
                return None, self.frame_id
            return self.frame.copy(), self.frame_id

    def stop(self):
        self.running = False

        try:
            if self.thread:
                self.thread.join(timeout=1)
        except Exception:
            pass

        try:
            if self.cap:
                self.cap.release()
        except Exception:
            pass


def start_ffmpeg(width: int, height: int, fps: int, output_url: str, bitrate: str):
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "warning",

        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "-i", "-",

        "-an",

        # Low-latency CPU encode.
        # NVENC is not used because this container reports:
        # OpenEncodeSessionEx failed: unsupported device.
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        "-profile:v", "baseline",

        "-g", str(fps),
        "-keyint_min", str(fps),
        "-sc_threshold", "0",
        "-bf", "0",
        "-refs", "1",

        "-b:v", bitrate,
        "-maxrate", bitrate,
        "-bufsize", bitrate,

        "-x264-params", f"keyint={fps}:min-keyint={fps}:scenecut=0:bframes=0:rc-lookahead=0:sync-lookahead=0",

        "-flags", "+low_delay",
        "-flush_packets", "1",
        "-muxdelay", "0",
        "-muxpreload", "0",
        "-flvflags", "no_duration_filesize",

        "-f", "flv",
        output_url,
    ]

    log("Starting ffmpeg:")
    log(" ".join(cmd))

    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


class StageProfiler:
    STAGES = ("read", "resize", "detect", "swap", "enhance", "write", "sleep", "total")

    def __init__(self, window: int):
        self.window = max(1, int(window))
        self.reset()

    def reset(self):
        self.count = 0
        self.totals = {stage: 0.0 for stage in self.STAGES}

    def add(self, stages: dict[str, float]):
        self.count += 1
        for stage in self.STAGES:
            self.totals[stage] += stages.get(stage, 0.0)

        if self.count < self.window:
            return

        averages = {stage: self.totals[stage] / self.count for stage in self.STAGES}
        log(
            "stage_avg_ms "
            f"window={self.count} "
            f"read={averages['read']:.1f} "
            f"resize={averages['resize']:.1f} "
            f"detect={averages['detect']:.1f} "
            f"swap={averages['swap']:.1f} "
            f"enhance={averages['enhance']:.1f} "
            f"write={averages['write']:.1f} "
            f"sleep={averages['sleep']:.1f} "
            f"total={averages['total']:.1f}"
        )
        self.reset()


def elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="/workspace/Deep-Live-Cam/realtime/source.jpg")
    parser.add_argument("--input", default="rtmp://127.0.0.1:1935/live/test")
    parser.add_argument("--output", default="rtmp://127.0.0.1:1935/live/processed")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--bitrate", default="3000k")
    parser.add_argument("--enhancer", action="store_true")
    parser.add_argument("--every-n", type=int, default=1, help="Process every Nth frame. 1 = every frame")
    parser.add_argument("--detect-every", type=int, default=1, help="Run face detection every N frames after the first target face is found. 1 = every frame")
    parser.add_argument("--enhancer-every", type=int, default=1, help="Run face enhancer every N frames. 1 = every frame")
    parser.add_argument("--profile-stages", action="store_true", help="Log average per-stage timings from inside the RTMP loop")
    parser.add_argument("--profile-window", type=int, default=30, help="Number of output frames per stage profiling window")
    parser.add_argument(
        "--flush-every",
        type=int,
        default=int(os.environ.get("DLC_FLUSH_EVERY", "1")),
        help="Flush ffmpeg stdin every N frames. 1 = flush every frame."
    )
    args = parser.parse_args()

    args.every_n = max(1, args.every_n)
    args.detect_every = max(1, args.detect_every)
    args.enhancer_every = max(1, args.enhancer_every)
    args.profile_window = max(1, args.profile_window)

    setup_deeplivecam(enhancer=args.enhancer)
    source_face = load_source_face(args.source)
    log(f"detect_every={args.detect_every}, enhancer_every={args.enhancer_every}, flush_every={args.flush_every}")
    if args.profile_stages:
        log(f"profile_stages=True, profile_window={args.profile_window}")

    reader = LatestFrameReader(args.input)
    first_frame = reader.start()
    last_reader_frame_id = None

    ffmpeg = start_ffmpeg(
        width=args.width,
        height=args.height,
        fps=args.fps,
        output_url=args.output,
        bitrate=args.bitrate,
    )

    frame_count = 0
    processed_count = 0
    error_count = 0
    detections_count = 0
    enhancer_count = 0
    started = time.time()
    cached_target_face = None
    frame = first_frame
    profiler = StageProfiler(args.profile_window) if args.profile_stages else None
    pending_profile_read_ms = 0.0
    pending_profile_sleep_ms = 0.0
    pending_profile_total_ms = 0.0

    try:
        while True:
            loop_started = time.perf_counter() if profiler else 0.0
            read_ms = 0.0
            resize_ms = 0.0
            detect_ms = 0.0
            swap_ms = 0.0
            enhance_ms = 0.0
            write_ms = 0.0

            if frame_count > 0:
                stage_started = time.perf_counter() if profiler else 0.0
                frame, current_reader_frame_id = reader.read_latest()
                if profiler:
                    read_ms = elapsed_ms(stage_started)

                if frame is None:
                    log("No latest frame available, waiting...")
                    stage_started = time.perf_counter() if profiler else 0.0
                    time.sleep(0.005)
                    if profiler:
                        pending_profile_read_ms += read_ms + elapsed_ms(stage_started)
                        pending_profile_total_ms += elapsed_ms(loop_started)
                    continue

                # Do not process/output the same input frame multiple times.
                # This prevents pushing 38-50 FPS into a 30 FPS RTMP stream.
                if current_reader_frame_id == last_reader_frame_id:
                    stage_started = time.perf_counter() if profiler else 0.0
                    time.sleep(0.002)
                    if profiler:
                        pending_profile_read_ms += read_ms
                        pending_profile_sleep_ms += elapsed_ms(stage_started)
                        pending_profile_total_ms += elapsed_ms(loop_started)
                    continue

                last_reader_frame_id = current_reader_frame_id

            stage_started = time.perf_counter() if profiler else 0.0
            frame = cv2.resize(frame, (args.width, args.height))
            if profiler:
                resize_ms = elapsed_ms(stage_started)

            should_process = args.every_n <= 1 or frame_count % args.every_n == 0
            should_detect = (
                cached_target_face is None
                or args.detect_every <= 1
                or frame_count % args.detect_every == 0
            )

            if should_detect:
                stage_started = 0.0
                try:
                    detections_count += 1
                    stage_started = time.perf_counter() if profiler else 0.0
                    detected_target_face = face_swapper.get_one_face(frame)
                    if profiler:
                        detect_ms = elapsed_ms(stage_started)

                    if detected_target_face is not None:
                        cached_target_face = detected_target_face

                except Exception as e:
                    if profiler and stage_started:
                        detect_ms = elapsed_ms(stage_started)
                    error_count += 1
                    log(f"Face detection error #{error_count}: {e}")
                    if error_count <= 3:
                        traceback.print_exc()

            if should_process:
                try:
                    if cached_target_face is None:
                        result = frame
                    else:
                        stage_started = time.perf_counter() if profiler else 0.0
                        result = face_swapper.process_frame(source_face, frame, cached_target_face)
                        if profiler:
                            swap_ms = elapsed_ms(stage_started)
                        processed_count += 1

                        should_enhance = (
                            args.enhancer
                            and (args.enhancer_every <= 1 or frame_count % args.enhancer_every == 0)
                        )

                        if should_enhance:
                            stage_started = 0.0
                            try:
                                enhancer_count += 1
                                stage_started = time.perf_counter() if profiler else 0.0
                                result = face_enhancer.process_frame(source_face, result)
                                if profiler:
                                    enhance_ms = elapsed_ms(stage_started)
                            except Exception as enhancer_error:
                                if profiler and stage_started:
                                    enhance_ms = elapsed_ms(stage_started)
                                error_count += 1
                                log(f"GFPGAN/enhancer error #{error_count}: {enhancer_error}; using swapped frame without enhancement")

                except Exception as e:
                    if profiler and cached_target_face is not None and swap_ms == 0.0:
                        swap_ms = elapsed_ms(stage_started)
                    error_count += 1
                    log(f"Frame processing error #{error_count}: {e}")
                    if error_count <= 3:
                        traceback.print_exc()

                    result = frame
            else:
                result = frame

            try:
                if profiler:
                    stage_started = time.perf_counter()
                    ffmpeg.stdin.write(result.tobytes())
                    if args.flush_every <= 1 or frame_count % args.flush_every == 0:
                        ffmpeg.stdin.flush()
                    write_ms = elapsed_ms(stage_started)
                else:
                    ffmpeg.stdin.write(result.tobytes())
            except BrokenPipeError:
                log("ffmpeg pipe broken")
                break

            frame_count += 1
            profile_sample = None
            if profiler:
                profile_sample = {
                    "read": pending_profile_read_ms + read_ms,
                    "resize": resize_ms,
                    "detect": detect_ms,
                    "swap": swap_ms,
                    "enhance": enhance_ms,
                    "write": write_ms,
                    "sleep": pending_profile_sleep_ms,
                    "total": pending_profile_total_ms + elapsed_ms(loop_started),
                }
                pending_profile_read_ms = 0.0
                pending_profile_sleep_ms = 0.0
                pending_profile_total_ms = 0.0

            if frame_count % args.fps == 0:
                elapsed = time.time() - started
                avg_fps = frame_count / max(elapsed, 0.001)
                proc_fps = processed_count / max(elapsed, 0.001)
                log(
                    f"frames={frame_count}, processed={processed_count}, "
                    f"errors={error_count}, avg_out_fps={avg_fps:.2f}, proc_fps={proc_fps:.2f}, "
                    f"reader_frames={reader.read_frames}, reconnects={reader.reconnects}, "
                    f"detect_every={args.detect_every}, enhancer_every={args.enhancer_every}, "
                    f"detections_count={detections_count}, enhancer_count={enhancer_count}"
                )

            if profiler:
                profiler.add(profile_sample)

    except KeyboardInterrupt:
        log("Interrupted")

    finally:
        try:
            reader.stop()
        except Exception:
            pass

        if ffmpeg.stdin:
            try:
                ffmpeg.stdin.close()
            except Exception:
                pass

        ffmpeg.terminate()
        log("Stopped")


if __name__ == "__main__":
    main()
