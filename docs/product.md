# Hearfolio Cloud

Product-owned spec: what this product does beyond the template. The template's inherited capabilities (sign-in, organizations, users and API tokens, tenant scoping, realtime, background tasks, files, theming, deployment) are in [template-core.md](template-core.md). When the two disagree, **this file wins**.

Agents: do not invent capabilities that are in neither file. Update this file in the same change as the behavior. UI copy is Russian.

---

## Purpose

Self-hosted server for a team that records meetings, calls and voice notes with the Hearfolio app (desktop, Android) and wants them in one shared place. Recordings are uploaded from the app straight to S3, transcribed and titled automatically through OpenRouter, tagged by AI, sorted into projects and summarized with reusable templates. The web app is a light, minimal, Notion-like workspace, fully usable on a phone. Done for a user: "I pressed record in the app, chose the organization and the project, and a minute after stopping, my colleagues see a titled, tagged transcript with a summary."

No public sign-up. Each team deploys its own instance (the app connects to any instance by URL). The release cycle of the server is independent of the app; compatibility is negotiated through `/.well-known/hearfolio`.

## Personas

| Persona | Template model | Goal |
|---|---|---|
| Instance owner | `is_superuser` | Deploys the server, creates the first organization, creates users with passwords, fixes anything |
| Organization owner / admin | `OrganizationUser.role in (owner, admin)` | Configures OpenRouter, models and automation, manages members, invites and private projects, can delete any recording |
| Member | `OrganizationUser.role = member` | Records, reads, edits titles/tags/projects, creates summaries and share links, deletes own recordings |
| Guest with a link | anonymous | Reads exactly what a share link exposes |

## Domain model

All business tables are organization-scoped (`Scope(user=..., organization='organization_id')`) unless noted.

### Roles — `OrganizationUser.role`

`owner | admin | member` (default `member`). The creator of an organization becomes `owner`. Owner and admin are "org admins"; superusers act as org admins everywhere. At least one owner must remain; only an owner can grant/revoke `owner`. Helpers: `OrganizationService.is_admin(user, organization_id)` / `is_owner(...)` (superuser → True); for endpoints of the `Organization-Key` organization the viewset permission `IsOrganizationAdmin` and the dependency `RequireOrgAdmin` (`app/shared/permissions/is_organization_admin.py`).

Membership rules (`/organization-users`, `role` in create/read/PATCH):

- Org admins add and remove members and change roles (admin ↔ member). Granting `owner`, revoking it and removing an owner need an owner (or a superuser).
- Every member can leave (`DELETE` of their own membership). Leaving (or being removed) also drops the user from the organization's private projects.
- The last owner cannot be demoted, removed or leave, not even by a superuser: 409 `details.reason = last_owner`.
- Renaming an organization needs an org admin; deleting it needs an owner. Deleting removes every recording with it; their audio objects (and unfinished multipart uploads) are deleted from S3 by background `library.delete_audio` tasks (batch delete, 1000 keys per task).
- Organizations created before roles existed get their earliest member promoted to `owner` (migration `0009`).
- Role errors are 403 with `details.reason` `not_admin` or `not_owner`.

### Invite (`organization` domain)

`organization, role (admin|member), token_hash, created_by, expires_at (default now+7 days), accepted_by nullable, accepted_at, revoked_at`. Single use. The raw token is returned once on creation; the admin copies the link `{PUBLIC_URL}/invite/{token}`. No email is sent (no SMTP in v1).

- `GET /api/v1/invites/{token}` (public): organization name, role, inviter name, state (`valid | expired | used | revoked`), `expires_at`.
- `POST /api/v1/invites/{token}/accept`: signed-in user → becomes member with the invite role (already a member → 409, invite stays usable). Anonymous with `{name, email, password}` → creates the user (`name` is split into first/last name at the first space; the usual password policy), signs in (sets cookies) and joins. Existing email for an anonymous accept → 409 "Войдите, чтобы принять приглашение". Anonymous without a body → 401. Response: `{user, organization, role}`. A signed-in cookie request follows the template CSRF rule (trusted `Origin`).
- Admin endpoints (`Organization-Key`, `IsOrganizationAdmin`): `GET /organization-invites` (all invites with `state`, newest first, never the token), `POST /organization-invites {role: admin|member, expires_in_days: 1–30 = INVITE_EXPIRE_DAYS}` → the invite plus `token` and `url` (`{PUBLIC_URL}/invite/{token}`, shown once), `POST /organization-invites/{id}/revoke` (idempotent; a used invite → 409).
- Errors carry `details.reason`: 404 `invite_not_found`; 409 `invite_expired | invite_used | invite_revoked | already_member | email_exists`; 401 `registration_required`. Failed lookups and taken emails count per client IP (`PUBLIC_RATE_LIMIT_ATTEMPTS` per `PUBLIC_RATE_LIMIT_WINDOW_SECONDS`, 20 per 15 min) → 429 with `Retry-After`.

Superusers can still create users with passwords in «Настройки → Пользователи» and attach them with a role.

### Organization AI settings — `OrganizationSettings` (1:1 with organization)

| Field | Default | Notes |
|---|---|---|
| `openrouter_base_url` | `https://openrouter.ai/api/v1` | Any OpenAI/OpenRouter-compatible base URL |
| `openrouter_api_key` | empty | Stored encrypted (`CryptoService`). Never returned; read schema exposes `has_api_key` and `api_key_hint` (last 4 chars) |
| `transcription_models` / `transcription_default_model` | `[]` / null | Allowed audio-input models and the default (must be in the list) |
| `summary_models` / `summary_default_model` | `[]` / null | Allowed text models for title, tags, project suggestion and summaries |
| `auto_transcribe` | true | Start transcription when the upload completes |
| `auto_title` | true | Generate a title after transcription unless the user already renamed it |
| `auto_tags` | true | AI assigns tags (may create new org tags, max 5 per recording, reuses existing names case-insensitively) |
| `auto_project` | true | AI **suggests** a project; the user confirms |
| `segment_seconds` | 300 | Audio chunk length for transcription (60–900) |
| `language` | `auto` | Hint passed to the transcription prompt |

Only org admins read/write it (`Organization-Key` selects the organization):

- `GET /ai-settings/current`, `PATCH /ai-settings/current` (partial; `openrouter_api_key`: omitted keeps it, `""`/null removes it). A default model given explicitly must be in its list (400 otherwise); when a list change drops the current default, it falls back to the first allowed model (or null).
- `POST /ai-settings/test {openrouter_base_url?, openrouter_api_key?}` checks the saved key, or unsaved values before saving, against `{base_url}/key` (falls back to `/models` for other compatible APIs) and returns `{ok, message}` with a Russian message.
- The stored key is only ever sent to the stored base URL. A PATCH that changes `openrouter_base_url` while a key is saved must send `openrouter_api_key` too (else 400 «При смене адреса API укажите ключ заново», `details.reason = api_key_required`); `/test` with a different URL and no key answers `{ok: false, message: «Для нового адреса API укажите ключ»}` without calling anyone.
- A base URL whose host is or resolves to a private, loopback, link-local or reserved address is rejected (400, `details.reason = private_base_url`) unless the server sets `AI_ALLOW_PRIVATE_BASE_URLS=true` (self-hosted LLM gateways inside the network). Checked when the URL is saved or tested; best effort against later DNS changes.
- `GET /ai-settings/models?kind=audio|text&search=` proxies the provider catalog (cached 10 min per base URL + key) for a searchable picker. `audio` = `audio` in `input_modalities` (dedicated speech-to-text models come from the `output_modalities=transcription` listing and are called through `/audio/transcriptions`); `text` = text in, text out.

Members get `GET /ai-settings/options`: `configured`, allowed models and defaults only, no secrets. Settings are created with the defaults above on first access, or together with the organization.

### SummaryTemplate

`name, prompt, auto (bool: run automatically after transcription), position, created_by`. Admins manage; everyone uses (`/summary-templates`: members list/retrieve, admins create/update/delete; a new template goes last unless `position` is given). Seeded once together with the organization's AI settings (on org creation; older organizations on first access): «Кратко» (auto), «Решения и договорённости», «Задачи и ответственные». Deleted defaults are not re-created.

### Project

`name, emoji (nullable), description, is_private, created_by, archived_at`. `ProjectMember(project, user)` for private projects.

- Public project: visible to every member.
- Private project: visible (and its recordings) only to its members. Org admins see private projects in the settings list and manage members, but do not see the recordings unless they are members (Notion-like teamspace). The creator becomes a member. Decided: an org admin may add themselves to any private project (like a workspace owner joining a teamspace); this is allowed on purpose and not journaled (no project event log in v1), the member list shows it.
- Create/rename: any member for public; private projects are created by any member (creator becomes member) and managed by its members and org admins.
- Making a project private/public and deleting it: the project's creator or an org admin (the actor becomes a member when it turns private). Deleting a project keeps its recordings (they lose the project). `archived` (PATCH) sets `archived_at`; archived projects stay usable.
- API (`domains/library`): `GET /projects` — visible ones (public + member of), for pickers and the sidebar; filters `name`, `is_private`, `archived`. `GET /projects/manage` — the settings list: visible ones, plus every private project for org admins. `POST/PATCH/DELETE /projects/{id}`, members of private projects: `GET/POST /projects/{id}/members {user_id}`, `DELETE /projects/{id}/members/{user_id}` (project members and org admins; the user must be in the organization).

### Tag

`name` (unique per org, case-insensitive, whitespace collapsed, ≤ 64 chars), `color`: `gray | brown | orange | yellow | green | blue | purple | pink | red` (Notion-like tag palette; a tag created without a color, e.g. by AI, gets a stable one from its name). Any member creates tags (`POST /tags`, 409 on a duplicate name); renaming, recoloring, deleting and merging (`POST /tags/{id}/merge {target_id}`: every recording of the tag gets the target, the tag is deleted) are for org admins.

### Recording

| Field | Notes |
|---|---|
| `client_id` UUID | Idempotency key from the app; unique per organization. Re-POST with the same id returns the existing recording |
| `created_by` | Author |
| `visibility` | `organization` (default) or `personal` (only the author) |
| `project` nullable | Must be visible to the author. Recording in a private project is visible to project members only |
| `suggested_project` nullable, `project_suggestion_state` | `none | pending | accepted | dismissed`. Shown per viewer: a suggested project the viewer cannot see comes back as `suggested_project(_id) = null`, state `none` |
| `tags` M2M | |
| `title`, `title_source` | `auto | user`. AI never overwrites `user` |
| `recorded_at`, `duration_ms`, `source` | `source`: `desktop | android | web | import` |
| `audio_key`, `audio_size`, `audio_mime`, `original_filename` | S3 object under `hearfolio/YYYY/MM/DD/<uuid>.<ext>` |
| `upload_state` | `pending | uploading | uploaded | failed` |
| `status` | `awaiting_upload | queued | transcribing | transcribed | failed` |
| `progress` | 0–100 during transcription; `segments_done`, `segments_total` |
| `transcript_text`, `transcript_segments` | Segments JSON: `[{start_ms, end_ms, text}]`, enough for highlighting in the player |
| `transcription_model`, `language`, `error_code`, `error_message` | `error_message` is human-readable Russian, never raw provider JSON |
| `deleted_at` | Soft delete: tombstone for app sync; purged (and S3 object deleted) after `RECORDING_PURGE_AFTER_DAYS` (30) by the daily task `library.purge_deleted_recordings` (03:17 UTC); a recording whose audio cannot be deleted waits for the next run |

Visibility rule (one queryset helper used everywhere, tested): a user sees a recording if it is in their organization, not deleted, and (`created_by = user`) or (`visibility = organization` and (`project` is null or project is public or user is a project member)).

Permissions: everyone who sees a recording can rename, move between visible projects, edit tags, create summaries and share links. Delete: author or org admin. Changing `visibility` (either way): author only. Restore (`POST /recordings/{id}/restore`, within the 30 days): author or org admin; `GET /recordings?deleted=true` lists the caller's visible deleted recordings.

Settled details (`domains/library`):

- The rule lives in `LibraryVisibility.recordings(user, organization_id, deleted=False|True|None)`; list, detail, search, sync, audio, events, share management and every write start from it, so an invisible recording is a 404. Projects: `LibraryVisibility.projects` (public or member of); "visible to the author" for `project_id` means this set.
- `PATCH /recordings/{id} {title?, project_id? (null removes), tag_ids?, visibility?}`: a title from a user sets `title_source=user`. Moving answers a pending project suggestion (accepted if it is the suggested project, dismissed otherwise). Banner buttons: `POST /recordings/{id}/project-suggestion/accept|dismiss`.
- List filters: `project_id, tag_id, created_by_id, status, personal (true: my personal ones; false: shared ones), recorded_from, recorded_to (dates, inclusive), search, deleted`; newest `recorded_at` first, paginated like every list. `search` is PostgreSQL full-text (`simple` config, no stemming, so it works the same for Russian and English) over title + transcript on a generated, GIN-indexed `search_vector`; each hit carries `snippet: [{text, highlight}] | null` — a transcript fragment split into plain and highlighted parts (null when only the title matched), never HTML.
- `GET /recordings/{id}/events`: the journal, newest first; `actor` null means AI/system.
- `GET /recordings/{id}/audio?download=true` adds a `Content-Disposition` with the title as file name; without it the presigned GET answers `Content-Disposition: inline`, and always `Content-Type` = the stored `audio_mime`.
- Project names never leak (`RecordingPresenter`, used by detail, list, search, sync and every write response): a project the viewer cannot see is never named. The author still sees their own recording in a private project they left; for them it shows `project_id = project = null`.

### RecordingResult (summaries)

`recording, template nullable, title, prompt (snapshot), model, status (queued|running|done|failed), content (markdown), error_code (stable, see below), error_message, created_by` (null for automatic ones). Only after the recording is transcribed. Several can be requested in one call: `POST /recordings/{id}/results {template_ids: [...], custom_prompt?: str, model?: str}` (one result per template, plus «Свой запрос» for `custom_prompt`; `model` must be an allowed summary model, default the organization's); each is an independent task (`ai.generate_result`). Regenerate = new result with the same prompt snapshot (`POST /recording-results/{id}/regenerate`); delete (`DELETE /recording-results/{id}`) own results, automatic ones also by the recording's author, anything as org admin.

Reading results (decided on the ai side so the library schema stays free of ai types): `GET /recordings/{id}/results` for one recording, `GET /recording-results?recording_id=&status=&updated_after=` across every recording the caller sees. Recording detail and sync items carry no `results` field; every result change bumps the recording's `updated_at` (so `/recordings/sync` reports it) and sends `result.updated` `{id, recording_id, status, deleted, updated_at}`; clients then refetch the recording's results (the app: `updated_after` with its last sync time).

### ShareLink

`recording, token (random, url-safe), include_audio, include_transcript, result_ids (list), expires_at nullable, revoked_at, created_by, views`. One active link per recording (editing settings keeps the token). Public SSR page `/s/{token}` shows title, date, duration and exactly what is included; audio through a short-lived presigned URL. Revoking makes the page 404.

- Management (anyone who sees the recording): `GET /recordings/{id}/share` (the active link or null), `PUT /recordings/{id}/share {include_audio, include_transcript, result_ids, expires_at?}` creates or edits it, `DELETE` revokes it (a later share gets a new token). `result_ids` must be results of this recording (else 400, `details.reason = unknown_result_ids`). Two first shares at once end with one link (the later request edits it). The read schema carries `url` = `{PUBLIC_URL}/s/{token}` (null without `PUBLIC_URL`; the web app then builds it from its origin). A database index enforces one active link.
- Public: `GET /api/v1/public/share/{token}` (no auth) → `{title, recorded_at, duration_ms, language, audio: {url, expires_at} | null, transcript_text | null, transcript_segments | null, results}`; audio URLs live `SHARE_AUDIO_PRESIGN_EXPIRE_SECONDS` (10 min); every open increments `views`. Unknown, revoked, expired links and deleted recordings are 404. `results` come from the ai domain through `RecordingPipeline.register_share_results_provider` (only the ids in `result_ids`), see [pipeline-seam.md](pipeline-seam.md).

### RecordingEvent (short journal, not an audit log)

`recording, actor nullable (AI/system), kind (created, uploaded, transcribed, failed, renamed, moved, tagged, shared, unshared, result_created, restored, deleted), data JSON, created_at`. Shown as a compact «История» list on the recording page.

## API contract for the apps (stable, versioned)

Breaking changes only in a new `/api/v2`. The desktop/Android app depends on these.

- `GET /.well-known/hearfolio` (public JSON): `{product: "hearfolio", name, server_version, api_version: 1, min_app_version, oauth: {authorize_url, token_url, revoke_url}, upload: {multipart_threshold_bytes, part_size_bytes}}`. `name` = `INSTANCE_NAME` (`Hearfolio`), `server_version` = `APP_VERSION` (from `version.json` at build), `min_app_version` = `MIN_APP_VERSION` (`0.10.0`), upload sizes = `UPLOAD_MULTIPART_THRESHOLD_BYTES` (16 MiB) / `UPLOAD_PART_SIZE_BYTES` (8 MiB). URLs are built from `PUBLIC_URL` (fallback: the request origin): `authorize_url` is the web consent page `/oauth/authorize`, `token_url`/`revoke_url` the API endpoints. Caddy routes this path to the API.
- **OAuth 2.0 authorization code + PKCE (S256) for native apps.** Public client `hearfolio-app`. Allowed redirect URIs: `hearfolio://oauth/callback` and loopback `http://127.0.0.1:{port}/callback`. Flow: app opens `{server}/oauth/authorize?client_id&redirect_uri&code_challenge&code_challenge_method=S256&state&device_name` in the system browser → Nuxt page (requires sign-in, returns after `/auth`) shows «Подключить Hearfolio на {device_name}?» with the account → `POST /api/v1/oauth/authorize` returns a single-use code (60 s, stored hashed) → redirect to `redirect_uri?code&state`. Standard extras are tolerated on both authorize endpoints: `response_type` (must be `code` if present) and `scope` (ignored: the token has the user's access). `POST /api/v1/oauth/token` (`grant_type=authorization_code`, `code`, `code_verifier`, `redirect_uri`, `client_id`) → `{access_token, token_type: "Token", user, organizations}`. The token is a regular named API token («Hearfolio · {device_name}», no expiry) so it appears in Профиль → Токены and can be revoked there; `POST /api/v1/oauth/revoke` revokes it from the app.
  - `GET /api/v1/oauth/authorize?<same params>` validates the request for the consent page → `{client_id, client_name, redirect_uri, device_name}`. `POST /api/v1/oauth/authorize {client_id, redirect_uri, code_challenge, code_challenge_method, state?, device_name}` → `{code, state, redirect_to}`. Both need a signed-in web session (an API token cannot authorize, 403) and answer bad requests with the API envelope, 400 `details.error` = `invalid_client | invalid_request`. Loopback redirects: `http://127.0.0.1:{1–65535}/callback` exactly (no `localhost`, no IPv6, no query). `device_name` 1–64 chars, trimmed.
  - Token endpoint: form or JSON, public, `Cache-Control: no-store`. Errors in RFC 6749 form `{error, error_description}`: 400 `invalid_request | invalid_client | invalid_grant | unsupported_grant_type`, 429 `rate_limited` (failed exchanges per client IP, same limit as invites). A code is claimed before it is checked, so a wrong verifier burns it; presenting a used code again deletes the token issued for it (claim and token issue are one transaction with the code row locked, so a reuse racing the first exchange still revokes). Codes expired over a day ago are deleted daily (`oauth.purge_expired_codes`); unused invites expired or revoked over 30 days ago too (`organization.purge_stale_invites`; used ones stay).
  - Revoke: `Authorization: Token …` only (otherwise 400 `invalid_request`), 204.
- `GET /api/v1/me/organizations`: organizations with the caller's role (no `Organization-Key` needed), `[{id, name, key, role, created_at, updated_at}]`. `GET /auth/me` and the login response carry the same `role` per organization.
- Recordings (`Organization-Key` header): `POST /recordings` (create with `client_id`, metadata, optional `title` + `title_source` (`user` by default when a title is given, so AI never renames it; `auto` for a generated name like «Запись 13.11 10:05» that the AI title may replace), `project_id`, `visibility`, optional `transcript_text`/`transcript_segments` when copying an already transcribed local recording → no transcription), returns the recording and an upload plan: single presigned PUT below the threshold, otherwise S3 multipart (`upload_id`, presigned part URLs). `POST /recordings/{id}/upload/complete {parts?}` → verifies the object, sets `uploaded`, enqueues the pipeline per settings. `POST /recordings/{id}/upload/parts` refreshes expired part URLs (resume after app restart).
  - Upload details: `audio_size` is required (> 0, ≤ `UPLOAD_MAX_BYTES`, 10 GiB) and must match the uploaded object. `audio_mime` must be `audio/*` or `video/*` (optional parameters such as `;codecs=opus`), else 400 `details.reason = unsupported_media_type`; playback URLs serve it as the `Content-Type`. Single: `{method: "single", url, headers: {Content-Type}, expires_at}`; the URL is signed for exactly `audio_size` bytes (`Content-Length` is part of the signature: send the body with a known length, not chunked). Multipart: `{method: "multipart", upload_id, part_size, parts_count, parts: [{part_number, url}], expires_at}`; the app keeps each part's `ETag` and sends `{parts: [{part_number, etag}]}` to `complete` (omitted → the server lists the uploaded parts itself). Part URLs live `UPLOAD_PRESIGN_EXPIRE_SECONDS` (6 h); `upload/parts {part_numbers?}` returns fresh ones. Only the author uploads. `complete` is idempotent (a repeated or concurrent `complete` of an uploaded recording returns it; it is journaled and enqueued once). Rejections are 400 `VALIDATION_ERROR` with `details.reason`:
    - `upload_incomplete`: the object is not in S3 yet (or S3 could not assemble it); nothing changed, upload and call `complete` again.
    - `upload_parts_missing`: multipart; `details.missing_parts` lists the part numbers S3 does not have (first 1000). Upload them (fresh URLs from `upload/parts {part_numbers}`) and retry. Also for part numbers outside the plan.
    - `upload_size_mismatch`: the object (or a part) has the wrong size. The object is deleted / the multipart upload aborted, `upload_state=failed`, `error_code = upload_size_mismatch`; call `upload/parts` to start over.
    - `upload_failed`: `complete` after such a rejection; call `upload/parts` first.
    - `upload_expired`: the multipart upload no longer exists in S3 (aborted or expired by a lifecycle rule); a new one was started, fetch its URLs with `upload/parts` and upload every part again.
    - S3 unreachable: 503 `APP_ERROR`, `details.reason = storage_unavailable`; retry later.
    - A deleted (or invisible) recording: `complete` and `upload/parts` answer 404 `NOT_FOUND`; stop uploading it.
  - Multipart parts are checked before assembly (all of `1..parts_count`, each exactly `part_size` bytes, the last one the rest), so nothing larger than `audio_size` is kept. `upload/parts` notices a multipart upload S3 no longer knows (`NoSuchUpload`, e.g. after an `AbortIncompleteMultipartUpload` lifecycle rule) and transparently starts a new one: the response carries the new `upload_id` and URLs for every part, whatever `upload_state` was. Configure such a lifecycle rule on the bucket (e.g. 7 days) for uploads abandoned by apps. A re-POST with a known `client_id` by the same author returns the recording and a fresh plan (`upload: null` once uploaded); another user's `client_id` is 409.
  - `upload_state`: `pending` (single PUT expected), `uploading` (multipart started), `uploaded`, `failed`. `status`: `awaiting_upload` until `complete`, then `queued` (or stays `transcribed` when the transcript came with the recording); the pipeline takes it from there.
- `GET /recordings/sync?cursor=&limit=` (limit 1–500, default 100) → `{items, deleted_ids, next_cursor, has_more}` ordered by `(updated_at, id)`; the cursor is opaque (pass `next_cursor` back; with no changes it comes back unchanged).
  - **Guarantee for app developers**: every change is delivered at least once, possibly more than once. `updated_at` is set before a transaction commits, so a slow write can land just behind a cursor; the last page's `next_cursor` therefore trails the present by 5 seconds when its newest row is that recent, and the next sync repeats changes from that window. Apply items idempotently: upsert by `id`, ignore an item whose `updated_at` is not newer than the stored one, treat a `deleted_ids` entry for an unknown id as a no-op. Paging (`has_more = true`) always moves forward.
  - Items are the recording detail (list fields + `transcript_text`, `transcript_segments`); results metadata is added by the ai domain. `deleted_ids` lists every recording of the organization changed in the window that the caller cannot see now — deleted, made personal by its author, moved into a private project, its project made private or the caller removed from it — so the client drops it if it has it (ids of recordings it never had may appear; ignore them). Bulk changes (project access, tag rename/merge/delete) bump `updated_at` of the affected recordings.
- Realtime on `/ws/organizations/{organization_id}`: `recording.updated` / `recording.deleted` with `{id, updated_at}` only. Every member of the organization receives them, also for recordings they cannot see: the websocket service fans out per organization channel and has no cheap per-user filter, so payloads carry nothing but the id and the time. Clients refetch the detail (404 when invisible) or run sync, which applies visibility; a bulk change of more than 50 recordings sends one `recordings.resync {updated_at}` instead.
- `GET /recordings/{id}/audio` → `{url, expires_at}` presigned GET for streaming/caching.
- `error_code` on recordings and results is a stable machine code; clients localize by it and fall back to the Russian `error_message`. Recording codes: `upload_size_mismatch` (library) and the pipeline's `not_configured`, `auth`, `payment`, `forbidden`, `rate_limited`, `bad_request`, `model_unavailable`, `too_large`, `server`, `network`, `timeout`, `invalid_response`, `incomplete`, `empty`, `content_filter`, `storage` (audio could not be read from S3), `audio` (ffmpeg could not read or cut it), `internal`. `RecordingResult.error_code` uses the pipeline codes. New codes may appear; unknown ones fall back to the message.
- Projects, tags, ai-options: plain list endpoints the app uses for pickers.

## Processing pipeline (Taskiq)

`recording.process(recording_id)` after upload: 

1. **Transcribe** (if `auto_transcribe` and no transcript provided): download audio from S3 to a temp dir, split with `ffmpeg` into `segment_seconds` chunks (mono 16 kHz mp3 at 32 kbit/s; plain cuts, a tail under 15 s joins the previous chunk; silent chunks are not sent), send each chunk to the transcription model via `chat/completions` with `input_audio`, a strict "verbatim transcript only" prompt and a `max_tokens` large enough for the chunk. Treat `finish_reason=length` / empty text as a retryable segment failure (retry that segment only, exponential backoff, up to 3 times; on a final failure retry once with half-length sub-chunks). Save each finished segment immediately (progress + websocket event) so a worker crash resumes from the last finished segment. Idempotent: a second run continues, it never duplicates.
2. **Title** (`auto_title`, `title_source=auto`): short Russian/English title in the transcript language, ≤ 80 chars.
3. **Tags** (`auto_tags`) and **project suggestion** (`auto_project`): one JSON-mode call to the summary model with existing tag and visible project names; unknown project names are ignored; suggestion only if confidence is reasonable.
4. **Auto summaries**: one `RecordingResult` per template with `auto=true`.

Failures set `status=failed` with a Russian `error_message` and keep finished segments; «Повторить» (`POST /recordings/{id}/retry`, for `failed` or `queued`) resumes after the last saved chunk, also when `auto_transcribe` is off. Re-transcribe (`POST /recordings/{id}/retranscribe {model?}`, an allowed transcription model) collects the new chunks aside and keeps the old transcript until the new one is complete; a failed re-transcription keeps the old text and resumes on «Повторить». After it succeeds the title is regenerated (unless renamed by a user); tags, project suggestion and summaries are not repeated. Both are open to everyone who sees the recording.

Steps 2–4 run once per recording (a re-delivered or retried task repeats nothing). A failed title/tags/summary step does not fail the recording: it is logged and retried on the next run. One run per recording at a time (Redis lock). A request that finds a run in progress (a «Повторить» or re-transcription during post-processing) is not lost: it leaves a pending marker and the running worker runs again before it lets go. Without Redis nothing runs (fail closed): the task is rescheduled after 30 s, 60 s, … up to 5 times. Silent chunks become empty segments, not errors. Every state change publishes `recording.updated` (and `result.updated`) on the organization channel (id-only payloads, see Realtime above). Automatic summaries are created once per template even if a run crashes right after creating them. A summary stuck in `running` for 15 minutes (its worker died) is taken over by a redelivered task and requeued by `ai.requeue_stale_results` (every 5 minutes).

ffmpeg/ffprobe read uploads with `-protocol_whitelist file`, an allowlist of plain audio/video demuxers (no HLS/concat playlists that could reference other files) and bounded probing.

The Docker image must contain `ffmpeg`.

## Web app (Nuxt) — scenarios

Look and feel: Notion-like — calm neutral surfaces, generous whitespace, one accent, inline editing instead of forms where natural, keyboard friendly (⌘K search), instant optimistic updates, skeletons instead of spinners, everything reachable on a 360 px phone (sidebar becomes a sheet, sticky bottom player). Russian copy.

- **Shell**: left sidebar — organization switcher, «Поиск» (⌘K), «Все записи», «Личные», «Проекты» (list, lock icon on private, «+»), «Настройки» at the bottom. Collapsible on desktop, a sheet on mobile.
- **Записи** (`/recordings`, also `/projects/{id}`, `/recordings?personal=1`): list grouped by day (Сегодня, Вчера, дата), each row: title, status (processing progress inline), duration, author avatar, project, tags, time. Filters: project, tag, author, status; search by title and transcript (Postgres full-text, highlights the matching snippet). «Загрузить» imports audio files from the browser (drag & drop onto the list) using the same upload API. Realtime updates.
- **Запись** (`/recordings/{id}`): inline-editable title; a property block like Notion page properties (Проект, Теги, Автор, Создано, Длительность, Доступ, Модель); project suggestion banner «Похоже на проект X» [Перенести] [Нет]; sticky audio player (speed 1–2×, ±15 s) with the transcript below, current segment highlighted, click a segment to seek; tabs «Расшифровка», «Саммари» (list of results, «Создать саммари» with multi-select of templates, optional own prompt and model), «История». Menu: копировать текст, скачать аудио, скачать .txt/.md, расшифровать заново (model picker), сделать личной/общей, удалить (confirm). «Поделиться» popover: toggle public link, checkboxes «Аудио», «Расшифровка», chosen summaries, copy link.
- **Публичная ссылка** (`/s/{token}`): SSR, read-only, clean, no app chrome.
- **Приглашение** (`/invite/{token}`): accept when signed in, or create an account (имя, email, пароль) and join; clear states for expired/used/revoked.
- **Подключение приложения** (`/oauth/authorize`): consent screen described above; errors for bad client/redirect.
- **Настройки**: Организация (name), Участники (roles, remove, invite links with copy/revoke), AI (OpenRouter URL and key with «Проверить», searchable model pickers for allowed + default, automation toggles, segment length, language), Шаблоны саммари, Проекты (incl. private ones and their members), Теги (rename, color, merge, delete), Профиль/Токены (connected devices appear as tokens).

## Non-goals (v1)

Email delivery, public sign-up, billing/quotas, guests limited to projects, comments, manual transcript editing, speaker diarization, a full audit log, on-device or self-hosted transcription models on the server (OpenRouter-compatible API only).

## Changes to template behavior

- Organization memberships get roles (`owner | admin | member`); the template had none.
- Invite links let users join (and register) without a superuser.
- Only org admins manage members and rename the organization; only owners delete it (the template let every member do it).
- An OAuth authorization-code + PKCE endpoint issues API tokens to the Hearfolio app (`domains/oauth`).
- Template-owned files touched for this: `core/auth.py` (`PUBLIC_PATHS` takes `{param}` templates and lists the invite, OAuth token and well-known paths; `AuthState.api_token_id`), `domains/auth` (`Authentication.api_token_id`; `MeSchema.organizations` carry `role`), `core/settings.py` (Hearfolio settings), `core/services/rate_limiter.py` (invite/OAuth limiters), `core/utils/request_utils.py`, `main.py` (well-known router, `OAuthError` handler), `Caddyfile` and `frontend/modules/dev-proxy.ts` (`/.well-known/hearfolio`).
- The Docker image includes `ffmpeg`.
