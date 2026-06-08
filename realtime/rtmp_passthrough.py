import argparse
import subprocess
import sys
import time

import cv2


def log(msg: str):
    print(f"[rtmp_passthrough] {msg}", flush=True)


def open_capture(url: str, retries: int = 30, delay: float = 1.0):
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
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        "-profile:v", "baseline",
        "-g", str(fps),
        "-keyint_min", str(fps),
        "-bf", "0",
        "-b:v", bitrate,
        "-f", "flv",
        output_url,
    ]

    log("Starting ffmpeg:")
    log(" ".join(cmd))

    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="rtmp://127.0.0.1:1935/live/test")
    parser.add_argument("--output", default="rtmp://127.0.0.1:1935/live/processed")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--bitrate", default="3000k")
    args = parser.parse_args()

    cap, first_frame = open_capture(args.input)

    frame = cv2.resize(first_frame, (args.width, args.height))
    ffmpeg = start_ffmpeg(args.width, args.height, args.fps, args.output, args.bitrate)

    frame_count = 0
    started = time.time()

    try:
        while True:
            if frame_count > 0:
                ok, frame = cap.read()
                if not ok or frame is None:
                    log("Input frame read failed, reconnecting...")
                    cap.release()
                    cap, frame = open_capture(args.input)

            frame = cv2.resize(frame, (args.width, args.height))

            try:
                ffmpeg.stdin.write(frame.tobytes())
            except BrokenPipeError:
                log("ffmpeg pipe broken")
                break

            frame_count += 1

            if frame_count % args.fps == 0:
                elapsed = time.time() - started
                real_fps = frame_count / max(elapsed, 0.001)
                log(f"frames={frame_count}, avg_fps={real_fps:.2f}")

    except KeyboardInterrupt:
        log("Interrupted")

    finally:
        cap.release()
        if ffmpeg.stdin:
            try:
                ffmpeg.stdin.close()
            except Exception:
                pass
        ffmpeg.terminate()
        log("Stopped")


if __name__ == "__main__":
    main()
