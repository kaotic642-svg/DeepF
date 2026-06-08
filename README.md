# DeepLiveCam RunPod WebUI


## Схема работы

OBS → RTMP `live/test` → MediaMTX → Python/CUDA обработчик → RTMP `live/processed` → OBS Media Source.

## Основной стабильный режим

- Fast mode
- 1280x720
- 30 FPS
- bitrate 3000k
- every_n=1
- detect_every=8
- enhancer_every=1
- flush_every=3
- GFPGAN OFF

## Запуск на новом сервере

```bash
cd /workspace/Deep-Live-Cam
WEBUI_PASSWORD='123456789' ./START_WEBUI_AUTO.sh
