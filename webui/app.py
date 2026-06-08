import ast
import importlib
import json
import os
import re
import secrets
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates


APP_DIR = Path(__file__).resolve().parent


def resolve_project_root() -> Path:
    env_root = os.environ.get("DEEPLIVECAM_ROOT", "").strip()

    candidates = []
    if env_root:
        candidates.append(Path(env_root))

    candidates.extend([
        Path("/workspace/Deep-Live-Cam"),
        APP_DIR.parent,
        APP_DIR,
        Path.cwd(),
        Path.cwd().parent,
    ])

    for candidate in candidates:
        try:
            candidate = candidate.resolve()
        except Exception:
            continue

        if (candidate / "modules").exists() and (candidate / "models").exists():
            return candidate

    # Fallback: keep the old default, but this should normally not be used.
    return Path("/workspace/Deep-Live-Cam").resolve()


PROJECT_ROOT = resolve_project_root()
STREAMING_ROOT = Path(os.environ.get("STREAMING_ROOT", "/workspace/streaming"))

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SOURCE_FACE = PROJECT_ROOT / "realtime" / "source.jpg"
SOURCE_ANNOTATED = PROJECT_ROOT / "realtime" / "source_annotated.jpg"
CONFIG_PATH = PROJECT_ROOT / "webui" / "config.json"

LOG_MEDIAMTX = STREAMING_ROOT / "logs" / "mediamtx.log"
LOG_PROCESSING = PROJECT_ROOT / "logs" / "rtmp_deeplivecam_webui.log"
LOG_FAST_PROCESSING = PROJECT_ROOT / "logs" / "rtmp_deeplivecam_fast.log"
LOG_WEBUI = PROJECT_ROOT / "logs" / "webui.log"

INPUT_RTMP = "rtmp://127.0.0.1:1935/live/test"
OUTPUT_RTMP = "rtmp://127.0.0.1:1935/live/processed"

WEBUI_PASSWORD = os.environ.get("WEBUI_PASSWORD", "deeplivecam")
security = HTTPBasic()


def resolve_webui_root() -> Path:
    candidates = [
        APP_DIR,
        APP_DIR / "webui",
        PROJECT_ROOT / "webui",
    ]
    for candidate in candidates:
        if (candidate / "templates" / "index.html").exists() or (candidate / "index.html").exists():
            return candidate
        if (candidate / "templates").exists():
            return candidate
    return PROJECT_ROOT / "webui"


WEBUI_ROOT = resolve_webui_root()


def resolve_templates_dir() -> Path:
    if (WEBUI_ROOT / "templates" / "index.html").exists():
        return WEBUI_ROOT / "templates"
    if (WEBUI_ROOT / "index.html").exists():
        return WEBUI_ROOT
    if (WEBUI_ROOT / "templates").exists():
        return WEBUI_ROOT / "templates"
    return WEBUI_ROOT / "templates"


TEMPLATES_DIR = resolve_templates_dir()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

BITRATE_RE = re.compile(r"^[1-9][0-9]*[kKmM]$")
SOURCE_CHECK_CACHE: dict[str, Any] = {"key": None, "value": None}

PRESETS = {
    "fast_720p_realtime": {
        "label": "Fast 720p realtime",
        "width": 1280,
        "height": 720,
        "fps": 30,
        "bitrate": "3000k",
        "every_n": 1,
        "detect_every": 3,
        "enhancer_every": 1,
        "enhancer": False,
        "mode": "fast",
    },
    "gfpgan_480p_quality": {
        "label": "GFPGAN 480p quality",
        "width": 854,
        "height": 480,
        "fps": 15,
        "bitrate": "1800k",
        "every_n": 1,
        "detect_every": 5,
        "enhancer_every": 1,
        "enhancer": True,
        "mode": "gfpgan",
    },
    "gfpgan_480p_balanced": {
        "label": "GFPGAN 480p balanced",
        "width": 854,
        "height": 480,
        "fps": 20,
        "bitrate": "2000k",
        "every_n": 1,
        "detect_every": 5,
        "enhancer_every": 2,
        "enhancer": True,
        "mode": "gfpgan",
    },
    "stable_720p": {
        "label": "Stable 720p / 30 FPS",
        "width": 1280,
        "height": 720,
        "fps": 30,
        "bitrate": "3000k",
        "every_n": 1,
        "detect_every": 3,
        "enhancer_every": 1,
        "enhancer": False,
        "mode": "fast",
    },
    "light_480p": {
        "label": "Light 480p / 30 FPS",
        "width": 854,
        "height": 480,
        "fps": 30,
        "bitrate": "1800k",
        "every_n": 1,
        "detect_every": 3,
        "enhancer_every": 1,
        "enhancer": False,
        "mode": "fast",
    },
    "low_latency_safe": {
        "label": "Low latency / safe",
        "width": 854,
        "height": 480,
        "fps": 30,
        "bitrate": "2000k",
        "every_n": 2,
        "detect_every": 3,
        "enhancer_every": 1,
        "enhancer": False,
        "mode": "fast",
    },
    "quality_gfpgan": {
        "label": "Quality / GFPGAN",
        "width": 1280,
        "height": 720,
        "fps": 30,
        "bitrate": "3500k",
        "every_n": 1,
        "detect_every": 5,
        "enhancer_every": 1,
        "enhancer": True,
        "mode": "gfpgan",
    },
}


def template_response(request: Request, name: str, context: dict[str, Any] | None = None):
    template_context = {"request": request}
    if context:
        template_context.update(context)

    try:
        return templates.TemplateResponse(name, template_context)
    except TypeError as exc:
        if "unhashable type" not in str(exc):
            raise
        return templates.TemplateResponse(request, name, template_context)


def auth(credentials: HTTPBasicCredentials = Depends(security)):
    good_user = secrets.compare_digest(credentials.username, "admin")
    good_pass = secrets.compare_digest(credentials.password, WEBUI_PASSWORD)
    if not (good_user and good_pass):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )


app = FastAPI(title="DeepLiveCam RunPod WebUI", dependencies=[Depends(auth)])


def run_shell(cmd: str, timeout: int = 15) -> str:
    cwd = PROJECT_ROOT if PROJECT_ROOT.exists() else Path.cwd()
    try:
        result = subprocess.run(
            ["bash", "-lc", cmd],
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return (stdout + stderr + f"\nTimed out after {timeout}s").strip()
    except FileNotFoundError:
        return "bash is not available"
    except Exception as exc:
        return str(exc)


def tail_file(path: Path, lines: int = 100, max_bytes: int = 250_000) -> str:
    if not path.exists():
        return ""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            data = handle.read()
        text = data.decode("utf-8", errors="replace")
        tail = text.splitlines()[-int(lines):]
        return "\n".join(tail)
    except Exception as exc:
        return f"Could not read log: {exc}"


def format_time(epoch: float | None) -> str | None:
    if not epoch:
        return None
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))


def file_mtime(path: Path) -> str | None:
    try:
        return format_time(path.stat().st_mtime)
    except Exception:
        return None


def human_bytes(size: int | None) -> str:
    if size is None:
        return "-"
    value = float(size)
    for suffix in ("B", "KB", "MB", "GB"):
        if value < 1024 or suffix == "GB":
            if suffix == "B":
                return f"{int(value)} {suffix}"
            return f"{value:.1f} {suffix}"
        value /= 1024
    return f"{size} B"


def load_config() -> dict[str, Any]:
    defaults = {
        "external_rtmp_base": "rtmp://EXTERNAL_IP:EXTERNAL_PORT",
        "width": 1280,
        "height": 720,
        "fps": 30,
        "bitrate": "3000k",
        "every_n": 1,
        "detect_every": 3,
        "enhancer_every": 1,
        "profile_stages": False,
        "mode": "fast",
    }
    if CONFIG_PATH.exists():
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            defaults.update(loaded)
        except Exception:
            pass
    return validate_config(defaults, raise_on_error=False)


def validate_config(data: dict[str, Any], raise_on_error: bool = True) -> dict[str, Any]:
    errors: list[str] = []

    def as_int(name: str, fallback: int) -> int:
        try:
            return int(data.get(name, fallback))
        except Exception:
            errors.append(f"{name} must be a number")
            return fallback

    def as_bool(name: str, fallback: bool = False) -> bool:
        value = data.get(name, fallback)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)

    width = as_int("width", 1280)
    height = as_int("height", 720)
    fps = as_int("fps", 30)
    every_n = as_int("every_n", 1)
    detect_every = as_int("detect_every", 3)
    enhancer_every = as_int("enhancer_every", 1)
    profile_stages = as_bool("profile_stages", False)
    bitrate = str(data.get("bitrate", "3000k")).strip()
    mode = str(data.get("mode", "fast")).strip().lower()
    external_rtmp_base = str(data.get("external_rtmp_base", "")).strip().rstrip("/")

    if width <= 0:
        errors.append("width must be greater than 0")
    if height <= 0:
        errors.append("height must be greater than 0")
    if fps < 1 or fps > 60:
        errors.append("fps must be between 1 and 60")
    if every_n < 1:
        errors.append("every_n must be at least 1")
    if detect_every < 1:
        errors.append("detect_every must be at least 1")
    if enhancer_every < 1:
        errors.append("enhancer_every must be at least 1")
    if not BITRATE_RE.match(bitrate):
        errors.append("bitrate must look like 3000k")
    if mode not in ("fast", "gfpgan"):
        errors.append("mode must be fast or gfpgan")

    if errors and raise_on_error:
        raise ValueError("; ".join(errors))

    return {
        "external_rtmp_base": external_rtmp_base,
        "width": max(1, width),
        "height": max(1, height),
        "fps": min(60, max(1, fps)),
        "bitrate": bitrate if BITRATE_RE.match(bitrate) else "3000k",
        "every_n": max(1, every_n),
        "detect_every": max(1, detect_every),
        "enhancer_every": max(1, enhancer_every),
        "profile_stages": profile_stages,
        "enhancer": mode == "gfpgan",
        "mode": mode if mode in ("fast", "gfpgan") else "fast",
    }


def save_config(data: dict[str, Any]):
    config = validate_config(data)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config


def pgrep(pattern: str) -> str:
    return run_shell(f"pgrep -af {shlex.quote(pattern)} || true")


def parse_processes(raw: str) -> list[dict[str, Any]]:
    processes: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        pid_text, _, command = line.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if "pgrep -af" in command:
            continue
        processes.append({"pid": pid, "command": command})
    return processes


def get_mediamtx_processes() -> list[dict[str, Any]]:
    return parse_processes(pgrep("[m]ediamtx"))


def get_processing_processes() -> list[dict[str, Any]]:
    return parse_processes(pgrep("[r]tmp_deeplivecam.py"))


def is_mediamtx_running() -> bool:
    return bool(get_mediamtx_processes())


def is_processing_running() -> bool:
    return bool(get_processing_processes())


def is_port_open(host: str = "127.0.0.1", port: int = 1935, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def has_listener_1935() -> bool:
    raw = run_shell(
        "if command -v ss >/dev/null 2>&1; then "
        "ss -lntp | grep -E '(:1935\\s|:1935$)' || true; "
        "elif command -v netstat >/dev/null 2>&1; then "
        "netstat -lntp 2>/dev/null | grep -E '(:1935\\s|:1935$)' || true; "
        "fi",
        timeout=4,
    )
    clean = raw.replace("\x00", "")
    lower = clean.lower()
    if "bash is not available" in lower or "accessdenied" in lower or "access denied" in lower:
        return is_port_open()
    return ":1935" in clean


def get_gpu_info() -> dict[str, Any]:
    raw = run_shell(
        "nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu "
        "--format=csv,noheader,nounits || true",
        timeout=8,
    )
    clean = raw.replace("\x00", "")
    lower = clean.lower()
    if (
        not clean
        or "not found" in lower
        or "failed" in lower
        or "accessdenied" in lower
        or "access denied" in lower
        or "no devices were found" in lower
    ):
        return {"ok": False, "status": "Problem", "raw": clean}

    first_line = clean.splitlines()[0]
    parts = [part.strip() for part in first_line.split(",")]
    if len(parts) >= 5:
        return {
            "ok": True,
            "status": "OK",
            "name": parts[0],
            "util": parts[1],
            "memory_used": parts[2],
            "memory_total": parts[3],
            "temperature": parts[4],
            "raw": clean,
        }
    return {"ok": True, "status": "OK", "raw": clean}


def build_obs_urls(config: dict[str, Any]) -> dict[str, str]:
    base = str(config.get("external_rtmp_base", "")).rstrip("/")
    if not base or "EXTERNAL" in base:
        return {
            "server": "rtmp://EXTERNAL_IP:EXTERNAL_PORT/live",
            "stream_key": "test",
            "processed": "rtmp://EXTERNAL_IP:EXTERNAL_PORT/live/processed",
            "input_local": INPUT_RTMP,
            "output_local": OUTPUT_RTMP,
        }

    return {
        "server": f"{base}/live",
        "stream_key": "test",
        "processed": f"{base}/live/processed",
        "input_local": INPUT_RTMP,
        "output_local": OUTPUT_RTMP,
    }


def get_source_key() -> tuple[int, int] | None:
    if not SOURCE_FACE.exists():
        return None
    stat = SOURCE_FACE.stat()
    return (stat.st_mtime_ns, stat.st_size)


def extract_bbox(face: Any) -> tuple[int, int, int, int] | None:
    bbox = None

    # Do not use "or" with numpy arrays here.
    # numpy.ndarray cannot be evaluated as True/False.
    if isinstance(face, dict):
        value = face.get("bbox")
        if value is not None:
            bbox = value
        else:
            value = face.get("bounding_box")
            if value is not None:
                bbox = value

    elif hasattr(face, "bbox"):
        bbox = getattr(face, "bbox")

    elif isinstance(face, (list, tuple)) and len(face) >= 4:
        bbox = face[:4]

    if bbox is None:
        return None

    if hasattr(bbox, "tolist"):
        bbox = bbox.tolist()

    try:
        values = list(bbox)[:4]
        x1, y1, x2, y2 = [int(round(float(value))) for value in values]
    except Exception:
        return None

    if x2 <= x1 or y2 <= y1:
        x2 = x1 + abs(x2)
        y2 = y1 + abs(y2)

    return x1, y1, x2, y2


def normalize_faces(value: Any) -> list[Any]:
    if value is None:
        return []

    if isinstance(value, (list, tuple)):
        return [item for item in value if item is not None]

    # Some libs may return array-like containers.
    # Avoid "if value" for numpy arrays.
    try:
        if hasattr(value, "__len__") and not hasattr(value, "bbox") and not isinstance(value, dict):
            return [item for item in list(value) if item is not None]
    except Exception:
        pass

    return [value]


def detect_faces(image: Any) -> tuple[list[Any], list[str]]:
    errors: list[str] = []

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    try:
        face_analyser = importlib.import_module("modules.face_analyser")
        get_many_faces = getattr(face_analyser, "get_many_faces", None)
        if callable(get_many_faces):
            faces = normalize_faces(get_many_faces(image))
            if len(faces) > 0:
                return faces, errors
    except Exception as exc:
        errors.append(f"modules.face_analyser.get_many_faces: {exc}")

    try:
        face_swapper = importlib.import_module("modules.processors.frame.face_swapper")

        get_many_faces = getattr(face_swapper, "get_many_faces", None)
        if callable(get_many_faces):
            faces = normalize_faces(get_many_faces(image))
            if len(faces) > 0:
                return faces, errors

        get_one_face = getattr(face_swapper, "get_one_face", None)
        if callable(get_one_face):
            face = get_one_face(image)
            return ([face] if face is not None else []), errors

    except Exception as exc:
        errors.append(f"face_swapper: {exc}")

    return [], errors


def remove_annotated_preview():
    try:
        if SOURCE_ANNOTATED.exists():
            SOURCE_ANNOTATED.unlink()
    except Exception:
        pass


def get_source_status(force: bool = False) -> dict[str, Any]:
    key = get_source_key()
    if key is None:
        remove_annotated_preview()
        SOURCE_CHECK_CACHE["key"] = None
        SOURCE_CHECK_CACHE["value"] = None
        return {
            "exists": False,
            "ready": False,
            "face_found": False,
            "face_count": 0,
            "status": "Missing",
            "message": "source.jpg не загружен",
            "advice": "Загрузите фото лица перед стартом обработки.",
            "annotated_exists": False,
        }

    if not force and SOURCE_CHECK_CACHE.get("key") == key and SOURCE_CHECK_CACHE.get("value"):
        return dict(SOURCE_CHECK_CACHE["value"])

    stat = SOURCE_FACE.stat()
    base: dict[str, Any] = {
        "exists": True,
        "ready": False,
        "face_found": False,
        "face_count": 0,
        "status": "Invalid",
        "message": "Лицо не найдено",
        "advice": "Лицо не найдено. Используйте фото крупнее, лучше свет, фронтальный ракурс.",
        "mtime": int(stat.st_mtime),
        "mtime_label": format_time(stat.st_mtime),
        "size": stat.st_size,
        "size_label": human_bytes(stat.st_size),
        "cache_key": f"{stat.st_mtime_ns}-{stat.st_size}",
        "annotated_exists": False,
    }

    try:
        import cv2

        image = cv2.imread(str(SOURCE_FACE))
        if image is None:
            remove_annotated_preview()
            base.update(
                {
                    "message": "Файл есть, но изображение не читается",
                    "advice": "Загрузите JPG или PNG файл с хорошо видимым лицом.",
                }
            )
            SOURCE_CHECK_CACHE.update({"key": key, "value": dict(base)})
            return base

        height, width = image.shape[:2]
        base.update(
            {
                "image_width": width,
                "image_height": height,
                "image_size": f"{width}x{height}",
                "shape": list(image.shape),
            }
        )

        faces, detector_errors = detect_faces(image)
        face_count = len(faces)
        bboxes = [bbox for bbox in (extract_bbox(face) for face in faces) if bbox is not None]

        if face_count > 0:
            base.update(
                {
                    "ready": True,
                    "face_found": True,
                    "face_count": face_count,
                    "status": "Ready",
                    "message": "Лицо найдено",
                    "advice": "",
                    "detector_errors": detector_errors[-2:],
                }
            )
            if bboxes:
                annotated = image.copy()
                for index, (x1, y1, x2, y2) in enumerate(bboxes, start=1):
                    x1 = max(0, min(width - 1, x1))
                    y1 = max(0, min(height - 1, y1))
                    x2 = max(0, min(width - 1, x2))
                    y2 = max(0, min(height - 1, y2))
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 220, 90), 3)
                    cv2.putText(
                        annotated,
                        f"Face {index}",
                        (x1, max(20, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.65,
                        (0, 220, 90),
                        2,
                    )
                SOURCE_ANNOTATED.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(SOURCE_ANNOTATED), annotated)
                base["annotated_exists"] = SOURCE_ANNOTATED.exists()
            else:
                remove_annotated_preview()
        else:
            remove_annotated_preview()
            base["detector_errors"] = detector_errors[-2:]

    except Exception as exc:
        remove_annotated_preview()
        base.update(
            {
                "status": "Invalid",
                "message": f"Ошибка проверки: {exc}",
                "advice": "Проверьте зависимости DeepLiveCam и попробуйте еще раз.",
            }
        )

    SOURCE_CHECK_CACHE.update({"key": key, "value": dict(base)})
    return base


def check_source_face() -> dict[str, Any]:
    return get_source_status(force=True)


def parse_processing_log(text: str | None = None) -> dict[str, Any]:
    log_text = text if text is not None else tail_file(LOG_PROCESSING, 700)
    fps_matches = re.findall(r"avg_out_fps=([0-9]+(?:\.[0-9]+)?)", log_text)
    proc_matches = re.findall(r"proc_fps=([0-9]+(?:\.[0-9]+)?)", log_text)
    error_matches = re.findall(r"errors=([0-9]+)", log_text)
    detect_every_matches = re.findall(r"detect_every=([0-9]+)", log_text)
    enhancer_every_matches = re.findall(r"enhancer_every=([0-9]+)", log_text)
    detections_matches = re.findall(r"detections_count=([0-9]+)", log_text)
    enhancer_matches = re.findall(r"enhancer_count=([0-9]+)", log_text)
    provider_matches = re.findall(r"Applied providers:\s*(\[[^\]]+\])", log_text)

    providers: list[str] = []
    if provider_matches:
        try:
            parsed = ast.literal_eval(provider_matches[-1])
            if isinstance(parsed, list):
                providers = [str(provider) for provider in parsed]
        except Exception:
            providers = []

    error_lines = [
        line
        for line in log_text.splitlines()
        if re.search(r"\b(error|traceback|failed)\b", line, flags=re.IGNORECASE)
    ]

    last_fps = float(fps_matches[-1]) if fps_matches else None
    proc_fps = float(proc_matches[-1]) if proc_matches else None
    errors = int(error_matches[-1]) if error_matches else len(error_lines)
    detect_every = int(detect_every_matches[-1]) if detect_every_matches else None
    enhancer_every = int(enhancer_every_matches[-1]) if enhancer_every_matches else None
    detections_count = int(detections_matches[-1]) if detections_matches else None
    enhancer_count = int(enhancer_matches[-1]) if enhancer_matches else None

    return {
        "last_fps": last_fps,
        "proc_fps": proc_fps,
        "errors": errors,
        "detect_every": detect_every,
        "enhancer_every": enhancer_every,
        "detections_count": detections_count,
        "enhancer_count": enhancer_count,
        "error_lines": len(error_lines),
        "providers": providers,
        "active_provider": providers[0] if providers else None,
        "cuda_provider": "CUDAExecutionProvider" in providers,
        "last_update": file_mtime(LOG_PROCESSING),
    }


def parse_mediamtx_log(text: str | None = None) -> dict[str, Any]:
    log_text = text if text is not None else tail_file(LOG_MEDIAMTX, 1000)
    publishing_by_conn: dict[str, str] = {}
    reading_by_conn: dict[str, str] = {}
    seen_publish: set[str] = set()
    seen_read: set[str] = set()

    for line in log_text.splitlines():
        conn_match = re.search(r"\[(conn [^\]]+)\]", line)
        conn = conn_match.group(1) if conn_match else None

        publish_match = re.search(r"is publishing to path '([^']+)'", line)
        if publish_match:
            path = publish_match.group(1)
            seen_publish.add(path)
            if conn:
                publishing_by_conn[conn] = path

        read_match = re.search(r"is reading from path '([^']+)'", line)
        if read_match:
            path = read_match.group(1)
            seen_read.add(path)
            if conn:
                reading_by_conn[conn] = path

        if conn and ("closed:" in line or "destroyed" in line):
            publishing_by_conn.pop(conn, None)
            reading_by_conn.pop(conn, None)

    active_publish = set(publishing_by_conn.values())
    active_read = set(reading_by_conn.values())

    def online(path: str, active: set[str], seen: set[str]) -> bool:
        return path in active or (path in seen and not active)

    return {
        "publish_paths": sorted(active_publish or seen_publish),
        "read_paths": sorted(active_read or seen_read),
        "publish_test": online("live/test", active_publish, seen_publish),
        "publish_processed": online("live/processed", active_publish, seen_publish),
        "read_processed": online("live/processed", active_read, seen_read),
        "last_update": file_mtime(LOG_MEDIAMTX),
    }


def get_runtime_status() -> dict[str, Any]:
    config = load_config()
    mediamtx_processes = get_mediamtx_processes()
    processing_processes = get_processing_processes()
    mediamtx_state = parse_mediamtx_log()
    processing_metrics = parse_processing_log()
    source = get_source_status(force=False)
    gpu = get_gpu_info()

    return {
        "pids": {
            "mediamtx": [process["pid"] for process in mediamtx_processes],
            "processing": [process["pid"] for process in processing_processes],
        },
        "processes": {
            "mediamtx": mediamtx_processes,
            "processing": processing_processes,
        },
        "mediamtx_running": bool(mediamtx_processes),
        "processing_running": bool(processing_processes),
        "listener_1935": has_listener_1935(),
        "mediamtx_publish_test": mediamtx_state["publish_test"],
        "mediamtx_publish_processed": mediamtx_state["publish_processed"],
        "mediamtx_read_processed": mediamtx_state["read_processed"],
        "obs_input_online": mediamtx_state["publish_test"],
        "processed_output_online": mediamtx_state["publish_processed"],
        "processed_viewer_online": mediamtx_state["read_processed"],
        "last_fps": processing_metrics["last_fps"],
        "proc_fps": processing_metrics["proc_fps"],
        "errors": processing_metrics["errors"],
        "detect_every": processing_metrics["detect_every"],
        "enhancer_every": processing_metrics["enhancer_every"],
        "detections_count": processing_metrics["detections_count"],
        "enhancer_count": processing_metrics["enhancer_count"],
        "providers": processing_metrics["providers"],
        "active_provider": processing_metrics["active_provider"],
        "cuda_provider": processing_metrics["cuda_provider"],
        "gpu": gpu,
        "gpu_ok": gpu.get("ok", False),
        "source": source,
        "source_face_status": source.get("status", "Missing"),
        "config": config,
        "presets": PRESETS,
        "obs": build_obs_urls(config),
        "logs": {
            "processing_last_update": processing_metrics["last_update"],
            "mediamtx_last_update": mediamtx_state["last_update"],
            "webui_last_update": file_mtime(LOG_WEBUI),
        },
    }


def diagnostic_item(key: str, label: str, ok: bool, detail: str = "", raw: str = "") -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": "OK" if ok else "Problem",
        "ok": ok,
        "detail": detail,
        "raw": raw,
    }


def run_diagnostics(check: str = "all") -> dict[str, Any]:
    check = (check or "all").strip().lower()
    items: list[dict[str, Any]] = []
    raw_blocks: dict[str, str] = {}

    def include(*names: str) -> bool:
        return check == "all" or check in names

    if include("gpu"):
        raw = run_shell("nvidia-smi || true", timeout=12)
        clean = raw.replace("\x00", "")
        lower = clean.lower()
        ok = (
            bool(clean.strip())
            and "not found" not in lower
            and "failed" not in lower
            and "accessdenied" not in lower
            and "access denied" not in lower
            and "no devices were found" not in lower
        )
        first = clean.splitlines()[0] if clean.splitlines() else "nvidia-smi did not return data"
        items.append(diagnostic_item("gpu", "GPU", ok, first, clean))
        raw_blocks["nvidia-smi"] = clean

    if include("deps", "python", "python_deps"):
        packages = [
            ("cv2", "cv2"),
            ("insightface", "insightface"),
            ("onnxruntime", "onnxruntime"),
            ("torch", "torch"),
            ("PySide6.QtCore", "PySide6"),
            ("modules.processors.frame.face_swapper", "DeepLiveCam face_swapper"),
        ]
        package_results: list[str] = []
        deps_ok = True
        providers: list[str] = []
        torch_cuda: str | None = None

        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))

        for module_name, label in packages:
            try:
                module = importlib.import_module(module_name)
                version = getattr(module, "__version__", "")
                if module_name == "onnxruntime":
                    providers = list(module.get_available_providers())
                if module_name == "torch":
                    torch_cuda = str(module.cuda.is_available())
                if module_name == "PySide6.QtCore":
                    getattr(module, "Qt")
                package_results.append(f"{label}: OK {version}".strip())
            except Exception as exc:
                deps_ok = False
                package_results.append(f"{label}: Problem - {exc}")

        cuda_ok = "CUDAExecutionProvider" in providers
        items.append(diagnostic_item("python_deps", "Python deps", deps_ok, "; ".join(package_results)))
        items.append(
            diagnostic_item(
                "cuda_provider",
                "CUDAExecutionProvider",
                cuda_ok,
                f"providers: {providers or 'unknown'}; torch cuda: {torch_cuda}",
            )
        )

    if include("models"):
        models_dir = PROJECT_ROOT / "models"
        raw = run_shell(f"ls -lh {shlex.quote(str(models_dir))} 2>/dev/null || true", timeout=8)
        ok = models_dir.exists() and any(models_dir.iterdir())
        items.append(diagnostic_item("models", "Models", ok, str(models_dir), raw))
        raw_blocks["models"] = raw

    if include("source", "source_face"):
        source = get_source_status(force=True)
        detail = source.get("message", "")
        if source.get("image_size"):
            detail += f"; {source['image_size']}; {source.get('size_label', '')}"
        items.append(diagnostic_item("source_face", "Source face", bool(source.get("ready")), detail))

    if include("mediamtx", "port"):
        mediamtx_raw = pgrep("[m]ediamtx")
        mediamtx_processes = parse_processes(mediamtx_raw)
        items.append(
            diagnostic_item(
                "mediamtx_process",
                "MediaMTX process",
                bool(mediamtx_processes),
                ", ".join(str(process["pid"]) for process in mediamtx_processes) or "not running",
                mediamtx_raw,
            )
        )
        port_raw = run_shell("ss -lntp 2>/dev/null | grep 1935 || true", timeout=8)
        port_ok = ":1935" in port_raw or is_port_open()
        items.append(diagnostic_item("port_1935", "Port 1935", port_ok, port_raw or "no listener found", port_raw))
        raw_blocks["ss_1935"] = port_raw

    if include("processing"):
        processing_raw = pgrep("[r]tmp_deeplivecam.py")
        processing_processes = parse_processes(processing_raw)
        items.append(
            diagnostic_item(
                "processing_process",
                "Processing process",
                bool(processing_processes),
                ", ".join(str(process["pid"]) for process in processing_processes) or "not running",
                processing_raw,
            )
        )

    if include("obs", "obs_input", "streams", "processed", "processed_output"):
        mediamtx_state = parse_mediamtx_log()
        if include("obs", "obs_input", "streams"):
            items.append(
                diagnostic_item(
                    "obs_input",
                    "OBS input live/test",
                    bool(mediamtx_state["publish_test"]),
                    "ONLINE" if mediamtx_state["publish_test"] else "OFFLINE",
                )
            )
        if include("processed", "processed_output", "streams"):
            items.append(
                diagnostic_item(
                    "processed_output",
                    "Processed output live/processed",
                    bool(mediamtx_state["publish_processed"]),
                    "ONLINE" if mediamtx_state["publish_processed"] else "OFFLINE",
                )
            )
            items.append(
                diagnostic_item(
                    "processed_viewer",
                    "Processed viewer",
                    bool(mediamtx_state["read_processed"]),
                    "ONLINE" if mediamtx_state["read_processed"] else "OFFLINE",
                )
            )

    if check == "all":
        raw_blocks["mediamtx_tail"] = tail_file(LOG_MEDIAMTX, 80)
        raw_blocks["processing_tail"] = tail_file(LOG_PROCESSING, 80)
        raw_blocks["fast_processing_tail"] = tail_file(LOG_FAST_PROCESSING, 40)
        raw_blocks["webui_tail"] = tail_file(LOG_WEBUI, 60)

    return {
        "ok": all(item["ok"] for item in items) if items else False,
        "check": check,
        "items": items,
        "raw": raw_blocks,
        "updated_at": format_time(time.time()),
    }


@app.get("/")
def index(request: Request):
    return template_response(request, "index.html")


@app.get("/api/health")
def api_health():
    return {"ok": True, "service": "DeepLiveCam WebUI"}


@app.get("/static/app.css")
def static_app_css():
    css_path = WEBUI_ROOT / "static" / "app.css"
    if not css_path.exists():
        raise HTTPException(status_code=404, detail="app.css not found")
    return FileResponse(str(css_path), media_type="text/css")


@app.get("/api/status")
def api_status():
    return JSONResponse(get_runtime_status())


@app.get("/api/source-image")
def api_source_image():
    if not SOURCE_FACE.exists():
        return JSONResponse({"exists": False, "message": "source.jpg не найден"})
    return FileResponse(
        str(SOURCE_FACE),
        media_type="image/jpeg",
        filename=SOURCE_FACE.name,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Expires": "0"},
    )


@app.get("/api/source-annotated-image")
def api_source_annotated_image():
    if not SOURCE_ANNOTATED.exists():
        return JSONResponse({"exists": False, "message": "annotated preview is not available"})
    return FileResponse(
        str(SOURCE_ANNOTATED),
        media_type="image/jpeg",
        filename=SOURCE_ANNOTATED.name,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Expires": "0"},
    )


@app.post("/api/delete-source")
def api_delete_source():
    try:
        if SOURCE_FACE.exists():
            SOURCE_FACE.unlink()
        remove_annotated_preview()
        SOURCE_CHECK_CACHE.update({"key": None, "value": None})
        return {"ok": True, "source": get_source_status(force=True)}
    except Exception as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=500)


@app.get("/api/logs")
def api_logs():
    processing = tail_file(LOG_PROCESSING, 220)
    mediamtx = tail_file(LOG_MEDIAMTX, 180)
    webui = tail_file(LOG_WEBUI, 140)
    diagnostics_summary = run_diagnostics("streams")
    processing_summary = parse_processing_log(processing)

    return JSONResponse(
        {
            "mediamtx": mediamtx,
            "processing": processing,
            "webui": webui,
            "diagnostics": diagnostics_summary,
            "summary": {
                "fps": processing_summary["last_fps"],
                "proc_fps": processing_summary["proc_fps"],
                "errors": processing_summary["errors"],
                "detect_every": processing_summary["detect_every"],
                "enhancer_every": processing_summary["enhancer_every"],
                "detections_count": processing_summary["detections_count"],
                "enhancer_count": processing_summary["enhancer_count"],
                "active_provider": processing_summary["active_provider"],
                "providers": processing_summary["providers"],
                "last_update": processing_summary["last_update"],
                "mediamtx_last_update": file_mtime(LOG_MEDIAMTX),
                "webui_last_update": file_mtime(LOG_WEBUI),
            },
        }
    )


@app.get("/api/diagnostics")
def api_diagnostics():
    return JSONResponse(run_diagnostics("all"))


@app.post("/api/run-check")
async def api_run_check(request: Request):
    check = "all"
    content_type = request.headers.get("content-type", "")
    try:
        if "application/json" in content_type:
            payload = await request.json()
            if isinstance(payload, dict) and payload.get("check"):
                check = str(payload["check"])
        elif "form" in content_type:
            form = await request.form()
            if form.get("check"):
                check = str(form["check"])
    except Exception:
        check = "all"
    return JSONResponse(run_diagnostics(check))


@app.post("/api/config")
def api_config(
    external_rtmp_base: str = Form(...),
    width: int = Form(...),
    height: int = Form(...),
    fps: int = Form(...),
    bitrate: str = Form(...),
    every_n: int = Form(...),
    detect_every: int = Form(3),
    enhancer_every: int = Form(1),
    profile_stages: bool = Form(False),
    mode: str = Form(...),
):
    try:
        config = save_config(
            {
                "external_rtmp_base": external_rtmp_base,
                "width": width,
                "height": height,
                "fps": fps,
                "bitrate": bitrate,
                "every_n": every_n,
                "detect_every": detect_every,
                "enhancer_every": enhancer_every,
                "profile_stages": profile_stages,
                "mode": mode,
            }
        )
    except ValueError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
    return {"ok": True, "config": config, "obs": build_obs_urls(config)}


@app.post("/api/upload-source")
async def api_upload_source(file: UploadFile = File(...)):
    SOURCE_FACE.parent.mkdir(parents=True, exist_ok=True)
    data = await file.read()
    if not data:
        return JSONResponse({"ok": False, "message": "Файл пустой"}, status_code=400)
    SOURCE_FACE.write_bytes(data)
    SOURCE_CHECK_CACHE.update({"key": None, "value": None})
    return {"ok": True, "source": get_source_status(force=True)}


@app.post("/api/check-source")
def api_check_source():
    return get_source_status(force=True)


@app.post("/api/start-mediamtx")
def api_start_mediamtx():
    STREAMING_ROOT.joinpath("logs").mkdir(parents=True, exist_ok=True)

    run_shell('pkill -f "/workspace/streaming/mediamtx" || true')
    run_shell('pkill -f "./mediamtx" || true')

    try:
        log = open(LOG_MEDIAMTX, "w", buffering=1, encoding="utf-8", errors="replace")
        subprocess.Popen(
            [str(STREAMING_ROOT / "mediamtx"), str(STREAMING_ROOT / "mediamtx.yml")],
            cwd=str(STREAMING_ROOT),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    except Exception as exc:
        return JSONResponse({"ok": False, "message": f"MediaMTX не запущен: {exc}"}, status_code=500)

    return {"ok": True, "message": "MediaMTX запущен"}


@app.post("/api/stop-mediamtx")
def api_stop_mediamtx():
    run_shell('pkill -f "/workspace/streaming/mediamtx" || true')
    run_shell('pkill -f "./mediamtx" || true')
    return {"ok": True, "message": "MediaMTX остановлен"}


@app.post("/api/start-processing")
def api_start_processing():
    config = load_config()
    source = get_source_status(force=True)

    if not source.get("exists"):
        return JSONResponse({"ok": False, "message": "Сначала загрузите source.jpg"}, status_code=400)

    if not source.get("face_found"):
        return JSONResponse({"ok": False, "message": "На source.jpg не найдено лицо"}, status_code=400)

    if not is_mediamtx_running():
        return JSONResponse({"ok": False, "message": "Сначала запустите MediaMTX"}, status_code=400)

    PROJECT_ROOT.joinpath("logs").mkdir(parents=True, exist_ok=True)

    run_shell('pkill -f "rtmp_deeplivecam.py" || true')
    run_shell('pkill -f "ffmpeg.*live/processed" || true')

    # cmd = [
    #     sys.executable,
    #     str(PROJECT_ROOT / "realtime" / "rtmp_deeplivecam.py"),
    #     "--source",
    #     str(SOURCE_FACE),
    #     "--input",
    #     INPUT_RTMP,
    #     "--output",
    #     OUTPUT_RTMP,
    #     "--width",
    #     str(config.get("width", 1280)),
    #     "--height",
    #     str(config.get("height", 720)),
    #     "--fps",
    #     str(config.get("fps", 30)),
    #     "--bitrate",
    #     str(config.get("bitrate", "3000k")),
    #     "--every-n",
    #     str(config.get("every_n", 1)),
    #     "--detect-every",
    #     str(config.get("detect_every", 1)),
    #     "--enhancer-every",
    #     str(config.get("enhancer_every", 1)),
    # ]

    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "realtime" / "rtmp_deeplivecam.py"),
        "--source", str(SOURCE_FACE),
        "--input", INPUT_RTMP,
        "--output", OUTPUT_RTMP,
        "--width", str(config.get("width", 1280)),
        "--height", str(config.get("height", 720)),
        "--fps", str(config.get("fps", 30)),
        "--bitrate", str(config.get("bitrate", "3000k")),
        "--every-n", str(config.get("every_n", 1)),
        "--detect-every", str(config.get("detect_every", 1)),
        "--enhancer-every", str(config.get("enhancer_every", 1)),
        "--flush-every", str(config.get("flush_every", 1)),
    ]

    # if config.get("mode") == "gfpgan":
    #     cmd.append("--enhancer")

    # if config.get("profile_stages"):
    #     cmd.append("--profile-stages")

    if config.get("mode") == "gfpgan":
        cmd.append("--enhancer")
    
    if config.get("profile_stages"):
        cmd.append("--profile-stages")

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{PROJECT_ROOT}:{env.get('PYTHONPATH', '')}"

    try:
        log = open(LOG_PROCESSING, "w", buffering=1, encoding="utf-8", errors="replace")
        subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    except Exception as exc:
        return JSONResponse({"ok": False, "message": f"Обработка не запущена: {exc}"}, status_code=500)

    return {"ok": True, "message": "Обработка запущена", "cmd": cmd}


@app.post("/api/stop-processing")
def api_stop_processing():
    run_shell('pkill -f "rtmp_deeplivecam.py" || true')
    run_shell('pkill -f "ffmpeg.*live/processed" || true')
    return {"ok": True, "message": "Обработка остановлена"}


@app.post("/api/restart-processing")
def api_restart_processing():
    api_stop_processing()
    return api_start_processing()
