# Antigravity Rules - Sal0 Karaokê Architecture & Storage Standards

## 📁 Storage Architecture & Data Mapping (`/data`)
All persistent server data MUST strictly adhere to the following volume path structure mapped to `/data`:

1. **Volume Mount**: `/data` (mapped via Docker Compose `-v /sua/pasta/data:/data`).
2. **Library Directory (`/data/library`)**:
   - `videos/`: Original audio/video files (`/data/library/videos/`).
   - `photos/`: Background images & background videos (`/data/library/photos/`).
   - `history/`: Final rendered Karaoke videos (`/data/library/history/`).
3. **Output Directory (`/data/output`)**:
   - `models/whisper/`: AI Whisper Models (`/data/output/models/whisper/`).
   - `profiles.json`: Saved subtitle & pipeline profiles (`/data/output/profiles.json`).
   - `telegram.json`: Global Telegram Bot Token & Chat ID (`/data/output/telegram.json`).
   - `external_url.json`: Remote IP / External Access URL (`/data/output/external_url.json`).
   - `state.json`: Global pipeline status & progress (`/data/output/state.json`).
   - `app_diagnostic.log`: System logs (`/data/output/app_diagnostic.log`).
4. **Cache Directory (`/data/cache`)**:
   - `cache_meta.json`, `original_input.*`, `original_bg.*`, `vocals.wav`, `instrumental.wav`, `transcribed_segments.json`.
5. **Users & Sessions (`/data`)**:
   - `users.json`: `/data/users.json`
   - `sessions.json`: `/data/sessions.json`

## 🔐 Authentication Standard
- Backend `get_current_user` MUST accept `x-session-token` header, `Authorization: Bearer <token>` header, AND `?token=<token>` query string.
- Frontend `authFetch` MUST send both `x-session-token` AND `Authorization: Bearer <token>`.

## 🤖 AI Model Detection Standard
- `is_model_downloaded()` MUST check `/data/output/models/whisper/` and `/root/.cache/huggingface/hub/` for folders matching model keywords (`medium`, `turbo`, `large-v3`, `large-v2`, `small`, `base`) and verify model binary/config presence.
