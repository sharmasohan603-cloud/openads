# TelePulse Ad Engine — PRD

## Original Problem Statement
Build a platform to run ads using a Telegram account in Telegram groups using Telethon string sessions.

## User Choices
- Connect accounts via **Telethon string session** (session string + api_id + api_hash).
- Ad sending: **auto-repeat / schedule ads at intervals** to many groups.
- Ad content: **text + image/media** AND **forward an existing channel message**.
- **Multiple** Telegram accounts/sessions.
- User provides their own api_id & api_hash (from my.telegram.org).

## Architecture
- **Frontend**: React 19 + Tailwind + shadcn/ui + framer-motion + sonner. Dark "Tactical Obsidian" dashboard (`/app/frontend/src/pages/Dashboard.jsx` + components). Polls backend every 8s.
- **Backend**: FastAPI (`/app/backend/server.py`) + Telethon 1.44 (`telegram_service.py`). MongoDB via motor. Async campaign scheduler using asyncio tasks in the app event loop.
- **Storage**: Emergent object storage (`storage.py`) for uploaded ad media; served via `/api/uploads/{path}`.
- **Integrations**: Telethon (StringSession), Emergent object storage (EMERGENT_LLM_KEY).

## User Personas
- Telegram marketer/operator broadcasting promotional messages across many groups from one or more accounts.

## Core Requirements (static)
1. Add/validate/remove multiple Telegram accounts via string session.
2. Fetch groups/supergroups/channels per account.
3. Create ad campaigns (text / text+media / forward), pick target groups, set repeat interval.
4. Start/stop campaigns; auto-broadcast on interval.
5. Activity logs (success/failure per group) + stats overview.
6. Session tester to verify a session quickly.

## Implemented (2026-06)
- [x] Account CRUD with live Telethon session validation (own profile fetched on add).
- [x] Fetch dialogs (groups/supergroups/channels) per account.
- [x] Campaign builder: text, text+media (object-storage upload), forward via t.me link parsing.
- [x] Interval scheduler (asyncio loop) with per-group send + 4s spacing; auto-stop after 3 consecutive client errors; resumes running campaigns on startup.
- [x] Start/stop/delete campaigns; sent counters.
- [x] Activity logs table with success/failed filters + clear.
- [x] Stats: total accounts, active campaigns, messages sent, success rate.
- [x] Session tester widget.
- [x] Dark dashboard UI with sidebar nav (Overview/Accounts/Campaigns/Logs/Tester), data-testids, toasts.
- [x] Tested: 100% backend + frontend (iteration_1). Live Telegram send/fetch verified to fail gracefully without real creds.

## Update 2026-06 — Account Pool + Group List engine (per user pivot)
- Removed per-campaign account picker. All loaded accounts form a **pool**; the scheduler auto-rotates accounts across groups (round-robin) and, if the picked account can't deliver (not a member/error), automatically tries the next account (capped at 10 attempts per group).
- Campaign now takes a **pasted list of groups** (one per line: @username, t.me link, or numeric id) instead of fetching+checkbox selection.
- Interval is now in **seconds** (default 60) between each send.
- `.session`/`.zip` upload of many real sessions verified working (156 live accounts connected in the user's env).
- Logs record which pooled account actually delivered each group.
- Backend interval display is backward compatible (old interval_minutes campaigns show *60s).

## Notes / Limitations
- No authentication (single-user dashboard).
- Live sending/group-fetch require a REAL valid Telethon session + api_id/api_hash — only verifiable by the end user.
- Orphaned media files are not auto-cleaned on campaign delete (soft concern).

## Backlog
- P1: Per-campaign randomized send delay & flood-wait handling / retry backoff.
- P1: Campaign edit (currently create/delete only).
- P2: Media cleanup on campaign delete.
- P2: Per-account dashboard filtering & analytics charts (recharts).
- P2: Schedule start/end windows (quiet hours).

## Next Tasks
- Await user's real credentials to validate live broadcasting end-to-end.
