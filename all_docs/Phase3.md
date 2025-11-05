Here’s an **implementation outline** meant for a developer who has access only to the small-talk module. It gives the big picture, describes what needs to be done for Phase 3, and defines the tasks clearly.

---

### Overview

The goal of Phase 3 is: *Enable the small-talk module to use knowledge from past conversations (via the Context Updater Service) so that, when a new session starts, our bot “remembers” something relevant about the user.* The developer will modify the small-talk code base so that it **fetches** context at session start and **reports** the end of session, and then **injects** the retrieved context into the prompt.

---

### Big Picture & Data Flow

1. **At session start**:

   * Small-talk module calls `GET /context/{user_id}` on the Context Updater Service.
   * Service returns a JSON “context bundle” (persona_summary, last_session_summary, facts…).
   * Small-talk code receives this bundle, selects relevant data (facts etc), and builds an augmented system/user prompt that includes this context.
   * The prompt is sent to the LLM (via DeepSeek REST) and conversation proceeds.

2. **During session**:

   * The conversation flows as usual (via your existing small-talk activity). The user and bot exchange messages; you record them as you already do (in `wb_messages`, etc).

3. **At session end**:

   * Small-talk module calls `POST /events` on the Context Updater Service with payload indicating `user_id`, `conversation_id`, `event_type: "session_end"`, `timestamp`.
   * The service processes this event (extracts facts etc) and updates its internal tables. That work is happening in the service (not your module).
   * Next time a session starts, the new facts appear in the fetched bundle.

---

### Developer Responsibilities

Here’s what the developer must implement/modify in the small-talk module:

1. **Configuration/Setup**

   * Add new config entries (e.g., `CONTEXT_SERVICE_URL = http://localhost:8000`) in config files.
   * Ensure that `user_id` variable is available (your `get_current_user_id()` returns `DEV_USER_ID` for now).
   * Ensure that the conversation module has access to `conversation_id` at session start and end.

2. **Fetch context at session start**

   * Before sending the first user message to the LLM in a session, call the context service:

     ```python
     response = httpx.get(f"{CONTEXT_SERVICE_URL}/context/{user_id}")
     bundle = response.json()
     ```
   * Validate the response (status, schema).
   * Extract from `bundle`: `persona_summary`, `last_session_summary`, `facts` list.
   * Build a prefix or template for the prompt, such as:

     ```
     You are Well-Bot, a friendly wellness companion.
     Previous info: {persona_summary}
     Last session: {last_session_summary}
     Known facts about you: {fact1}, {fact2}, …
     --- Now continue.
     ```
   * Inject that prefix into your system prompt (or prepend to user message depending on your architecture) before calling the DeepSeek API.

3. **Small talk runs as usual but with context**

4. **Report session end event**

   * When the conversation is finished (according to your logic), call:

     ```python
     httpx.post(f"{CONTEXT_SERVICE_URL}/events", json={
         "user_id": user_id,
         "conversation_id": conversation_id,
         "event_type": "session_end",
         "timestamp": datetime.utcnow().isoformat()
     })
     ```
   * Handle response (202 Accepted expected). Optionally log the `processed_facts_count` or `bundle_version_ts` from the response.

5. **Testing/modification**

   * Add logging around context fetch: log the bundle you receive.
   * Add logging of the prompt sent to DeepSeek (for debugging).
   * Create simple test scenario: conversation ends with a distinctive user message (e.g., “I’m training for a marathon”). Next session you should see that message appear in the fetched facts list and the prompt prefix.
   * Handle edge-cases: if `GET /context/{user_id}` returns empty or no facts (first session), code should still work (skip prefix or include “I look forward to our first conversation…”). If `POST /events` fails, log error but still allow session end gracefully.

6. **Code hygienic tasks**

   * Add config flags so this feature can be toggled (e.g., `ENABLE_CONTEXT_AWARENESS = True/False`) so you can disable quickly if problem arises.
   * Add unit tests to mock `GET /context` and `POST /events` responses to verify correct prompt building and event reporting logic.
   * Write clear comments/documentation in code about where the context is fetched, how it’s injected.

---

### Acceptance Criteria

* On session start, context service is queried and bundle is received.
* The prompt to DeepSeek contains the context prefix with at least one fact (after user has had an earlier session with a distinctive message).
* On session end, event is posted and the service returns 202; next session the new fact shows up.
* Existing conversation flow (without context service) still functions (backwards-compatible).
* Logs show the bundle, prompt, and event call details for debugging.

---


### Dependencies & Assumptions

* The Context Updater Service is running at `localhost:8000` with endpoints `/context/{user_id}` and `/events`.
* The database for the service is populated by previous conversations (so that facts exist).
* The small-talk module can access `conversation_id` (or whichever ID tracks the session).
* No authentication required for prototype (as defined).
* The developer has access to modify the small-talk module code base and test on local machine.

--- 

# How to call this service from a separate application:

## Communication Protocol

**HTTP/REST** over FastAPI. Default base URL: `http://localhost:8000` (configurable via `SERVICE_PORT`).

CORS is enabled for all origins (adjust in production).

## Available Endpoints

### 1. Health Check
```http
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "service": "context-updater-service",
  "version": "1.0.0"
}
```

### 2. Get Context Bundle (Publisher Endpoint)
```http
GET /context/{user_id}
```

**Path Parameters:**
- `user_id` (required): User UUID (e.g., `"51435f38-0f05-4478-9293-d8d9aa70d455"`)

**Response:** `ContextBundleResponse`
```json
{
  "user_id": "51435f38-0f05-4478-9293-d8d9aa70d455",
  "version_ts": "2024-01-15T10:30:00Z",
  "persona_summary": "User prefers...",
  "last_session_summary": "Last session about...",
  "facts": [
    {
      "fact_id": 1,
      "user_id": "51435f38-0f05-4478-9293-d8d9aa70d455",
      "text": "User likes coffee",
      "tags": ["preference"],
      "confidence": 0.95,
      "recency_days": 2.5,
      "created_ts": "2024-01-13T08:00:00Z",
      "updated_ts": "2024-01-15T10:00:00Z"
    }
  ]
}
```

**Status Codes:**
- `200` - Success
- `400` - Invalid UUID format
- `404` - User context not found (returns empty bundle)
- `503` - Database error

### 3. Post Events (Subscriber Endpoint)
```http
POST /events
```

**Request Body:** `EventPayload`
```json
{
  "user_id": "51435f38-0f05-4478-9293-d8d9aa70d455",
  "conversation_id": "123e4567-e89b-12d3-a456-426614174000",
  "event_type": "session_end",
  "timestamp": "2024-01-15T10:30:00Z",
  "metadata": {
    "additional": "data"
  }
}
```

**Field Details:**
- `user_id` (required): Valid UUID string
- `conversation_id` (optional): Valid UUID string or null
- `event_type` (required): One of:
  - `"session_start"`
  - `"session_end"`
  - `"turn_complete"`
  - `"conversation_end"`
- `timestamp` (optional): ISO 8601 datetime (defaults to current time if not provided)
- `metadata` (optional): Additional key-value pairs

**Response:** `EventResponse`
```json
{
  "status": "accepted",
  "message": "Event session_end processed successfully",
  "processed_facts_count": 3,
  "bundle_version_ts": "2024-01-15T10:30:00Z"
}
```

**Status Codes:**
- `202` - Accepted and processing
- `400` - Missing required fields
- `422` - Invalid event payload (e.g., invalid UUID format)
- `404` - Conversation not found
- `503` - Database error

## Example Usage

### Python Example
```python
import requests
import json

BASE_URL = "http://localhost:8000"

# Get context for a user
user_id = "51435f38-0f05-4478-9293-d8d9aa70d455"
response = requests.get(f"{BASE_URL}/context/{user_id}")
context_bundle = response.json()

# Post an event
event = {
    "user_id": user_id,
    "conversation_id": "123e4567-e89b-12d3-a456-426614174000",
    "event_type": "session_end",
    "metadata": {"session_duration": 300}
}
response = requests.post(
    f"{BASE_URL}/events",
    json=event,
    headers={"Content-Type": "application/json"}
)
result = response.json()
```

### JavaScript/TypeScript Example
```javascript
const BASE_URL = "http://localhost:8000";

// Get context for a user
const userId = "51435f38-0f05-4478-9293-d8d9aa70d455";
const contextResponse = await fetch(`${BASE_URL}/context/${userId}`);
const contextBundle = await contextResponse.json();

// Post an event
const event = {
  user_id: userId,
  conversation_id: "123e4567-e89b-12d3-a456-426614174000",
  event_type: "session_end",
  metadata: { session_duration: 300 }
};

const eventResponse = await fetch(`${BASE_URL}/events`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json"
  },
  body: JSON.stringify(event)
});

const result = await eventResponse.json();
```

## API Documentation

When running, view interactive docs:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

These show request/response schemas and allow testing directly in the browser.

## Error Response Format

All errors return:
```json
{
  "error_code": "ERROR_CODE",
  "message": "Human-readable error message",
  "details": {}
}
```

The service uses FastAPI with automatic request validation, so invalid payloads return `422` with validation details.