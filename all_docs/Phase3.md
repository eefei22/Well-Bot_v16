# 1) Goals & constraints

* **Goal:** Resolve the **active language** per user from your DB, then load the matching `en.json | cn.json | bm.json` and expose it across the pipeline (wake word → smalltalk → journal).
* **Today:** No full auth; use a **fixed dev user UUID** to simulate user differentiation.
* **Soon:** Switch to real auth without refactoring the pipeline.

# 2) Key decisions

* **User identity handle:** Use a **UUID** (`users.id`) as the canonical foreign key across tables (conversations, messages, logs). This keeps things stable whether or not auth is enabled.
* **Language source of truth:** `users.language` (enum-like: `en|cn|bm`).
* **Config selection:** A single **ConfigResolver** that:

  1. fetches `language` for a given `user_id`
  2. returns the correct language JSON
  3. falls back to `en` if anything fails or value is unknown
* **Snapshotting:** Store the **resolved language at message time** (e.g., `lang_snapshot`) so historical records aren’t affected by later preference changes.

# 3) Minimal data model extensions

Add (or confirm) these tables to support user-differentiated state:

**conversations**

* `id uuid pk default gen_random_uuid()`
* `user_id uuid not null references users(id)`
* `started_at timestamptz not null default now()`
* `ended_at timestamptz null`
* `topic text null`
* `lang_snapshot text not null default 'en'`  ← language used when the conversation started

**messages**

* `id uuid pk default gen_random_uuid()`
* `conversation_id uuid not null references conversations(id)`
* `sender text not null check (sender in ('user','bot','system'))`
* `content text not null`
* `created_at timestamptz not null default now()`
* `lang_snapshot text not null default 'en'`

*(Optional later: indexes on `user_id`, `conversation_id`, and time for analytics.)*

# 4) Where `config_fetch.py` fits

Create a **small, single-purpose module** that your pipeline can import:

* **Responsibilities**

  * Fetch `language` from `public.users` given `user_id`.
  * Validate/normalize to `{en, cn, bm}`; else default to `en`.
  * Provide a **pure function**: `resolve_language(user_id) -> 'en'|'cn'|'bm'`
  * Provide a **higher-level helper**: `get_language_config(user_id) -> dict` that returns the loaded language JSON.
  * Provide a **simple cache** (in-memory dict keyed by `user_id`) with short TTL (e.g., 60–300s) to avoid excess queries.

* **Inputs**

  * `SUPABASE_URL`
  * `SUPABASE_SERVICE_ROLE_KEY` (or anon key if you’ve opened read for `users.language`; service role is simplest now but protect it!)
  * `DEV_USER_ID` (for your current hardcoded tests)

* **Outputs**

  * normalized language code
  * loaded language config object

# 5) Runtime flow (today, with fixed UUID)

1. **Startup**: `GLOBAL_CONFIG` loads once.
2. **Session start (or on first need)**:

   * `current_user_id = ENV['DEV_USER_ID']` (or a CLI arg/process flag).
   * `lang = resolve_language(current_user_id)` via Supabase REST (httpx).
   * `LANGUAGE_CONFIG = load_language_config(lang)` (your existing loader).
3. **Pass LANGUAGE_CONFIG** by dependency injection (preferred) into:

   * `_pipeline_wakeword.py`
   * `_pipeline_smalltalk.py`
   * `activities/smalltalk.py`
   * `activities/journal.py`
4. **Conversation open**:

   * Create a `conversations` row (user_id, `lang_snapshot = lang`).
5. **Each message**:

   * Create a `messages` row with `lang_snapshot = lang`.

# 6) Runtime flow (future, with real auth)

* You’ll have a **Supabase Auth JWT** in the request context.
* Resolve **auth user id → app user id**:

  * Easiest path: make `users.id` **the same** as `auth.users.id` (store app profile fields in `public.users`, keyed by the auth UUID).
  * If you must keep two IDs, add a **mapping** table `auth_user_map(auth_user_id uuid pk, user_id uuid fk)` and resolve once per session.
* After you have `user_id`, reuse the **exact same** `resolve_language(user_id)` and downstream behavior. No pipeline refactor needed.

# 7) Supabase REST call shape (via httpx)

* Endpoint: `GET {SUPABASE_URL}/rest/v1/users?select=language&id=eq.{user_id}&limit=1`
* Headers:

  * `apikey: <service or anon key>`
  * `Authorization: Bearer <service or anon key>`
  * `Accept: application/json`
* Parse: if 200 with `[{"language":"cn"}]`, normalize to `'cn'`; else `'en'`.

**Security note:** Avoid shipping the service role key to untrusted clients. For server-side only (your backend), it’s fine. Later, if you query from the client, use **RLS** with anon key and policies permitting `select language where id = auth.uid()`.

# 8) Config resolution policy

* **Accepted values:** `en`, `cn`, `bm` (lowercase).
* **Fallbacks:**

  * Missing user row → `'en'`
  * Missing or invalid `language` → `'en'`
  * Language file missing a field → fallback to **English** for that specific field (optional “partial fallback” layer if you want).
* **Caching:**

  * Per-user result cached for ~60–300s.
  * Manual invalidation path (e.g., call `ConfigResolver.invalidate(user_id)` after a profile edit).

# 9) Injection strategy in your codebase

Prefer **dependency injection** over globals so multi-user concurrency is clean:

* **Create** a `ConfigManager`:

  * `resolve_language(user_id)`
  * `get_language_config(user_id)` (loads JSON once per language; caches per language, not per user)
  * `get_global_config()`
* **At activity/pipeline start**, pass `{global_config, language_config}` explicitly.
* **Avoid** module-level hardcoded `LANGUAGE_CONFIG` for anything user-specific.

# 10) Failure modes & handling

* **Supabase down / timeout** → log warning, use `'en'`.
* **HTTP 401/403** → configuration error; log ERROR, use `'en'`.
* **Unknown language** → warn, use `'en'`.
* **JSON missing key** → either:

  * strict: raise and abort activity; or
  * lenient: log and fall back to English field.
* **Race conditions** (multi-thread): protect in-memory caches with a simple lock (only around writes).

# 11) Testing checklist (now)

* Set `DEV_USER_ID` to a user with `language = 'bm'`; confirm Malay prompts/audio paths flow through smalltalk & journal.
* Toggle `language` in DB; confirm cache TTL behavior.
* Turn off network; confirm English fallback.
* Start two conversations under the same `user_id`; confirm consistent `lang_snapshot`.

# 12) Later: switching to real auth

* Align `users.id` with Supabase `auth.users.id`.
* Add RLS policy on `users`: `select language using (id = auth.uid())`.
* Replace `DEV_USER_ID` with `ctx.user_id` resolved from the JWT.
* Everything else remains the same.

# 13) Light pseudo-API (no code, just contracts)

**ConfigResolver**

* `resolve_language(user_id: UUID) -> Literal['en','cn','bm']`
* `get_language_config(user_id: UUID) -> dict`
* `get_global_config() -> dict`
* `invalidate(user_id: UUID) -> None`

**Usage pattern**

* At session start:

  * `lang = resolve_language(user_id)`
  * `global_cfg = get_global_config()`
  * `lang_cfg = get_language_config(user_id)`
  * Pass `{global_cfg, lang_cfg}` to pipeline/activity constructors.
