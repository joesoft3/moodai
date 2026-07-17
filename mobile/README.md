# Mood AI — Flutter mobile client

Native Android/iOS client for the Mood API (`backend/`, `/api/v1`): email login,
conversation drawer, **streaming** chat with live-search toggle and markdown rendering,
voice messages (STT + TTS playback), file attachments, agent-mode with live step view,
and **team workspaces** — switch between personal and team chats in the drawer, per-author
bubble labels, and joining a team by pasting an invite link/code.

> ⚠️ Written without a local Flutter SDK in this environment — the code is dependency-light
> and standard; run `flutter pub get` + `flutter analyze` on your machine first.

## Setup

```bash
cd mobile
flutter pub get

# Run against your backend (Android emulator → host machine loopback is 10.0.2.2):
flutter run --dart-define=API_URL=http://10.0.2.2:8000/api/v1

# Physical phone on the same Wi-Fi as the backend machine:
flutter run --dart-define=API_URL=http://192.168.x.x:8000/api/v1

# Release builds
flutter build apk --dart-define=API_URL=https://api.yourdomain.com/api/v1
flutter build ipa --dart-define=API_URL=https://api.yourdomain.com/api/v1
```

The backend's `CORS_ORIGINS` does not apply to mobile (no browser CORS) — just make sure the
host/port is reachable. Streaming uses raw `POST` + incremental line parsing (`data: {...}\n\n`),
matching the web client's protocol, so no SDK upgrade is needed when events are added server-side.

## Structure

```
lib/
├── main.dart          # theme (matches web palette), token gate
├── api.dart           # REST + SSE streaming client (http pkg), token storage
├── login_screen.dart  # login / register
└── chat_screen.dart   # drawer (conversations), message list, streaming composer
```

## Roadmap (parity with web)

Voice (record → `/voice/chat`), document upload, agent/deepsearch progress views, plugin
approval cards, settings (memory/custom instructions), share links.
