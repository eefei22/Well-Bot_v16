# Fusion Service - Technical Report

## Purpose of the Fusion Service

The Fusion Service is a cloud-based microservice that aggregates emotion predictions from multiple recognition models (Speech Emotion Recognition, SER; Face Emotion Recognition, FER; and Vitals-based emotion recognition) into a single, unified emotion snapshot. It serves as the central aggregation layer in the Well-Bot system, combining multi-modal emotion signals with weighted fusion logic.

**Key Responsibilities:**
- Aggregate emotion predictions from three independent model services (SER, FER, Vitals)
- Apply weighted fusion algorithm to produce unified emotion result
- Persist fused results to `emotional_log` database table
- Provide emotion snapshots for downstream intervention decisions

**Note:** The service does NOT make intervention decisions. It focuses solely on emotion aggregation and persistence. The intervention service reads from `emotional_log` separately.

---

## Architecture Overview

The Fusion Service follows a layered architecture pattern with clear separation of concerns:

### Layer 1: API Layer (`fusion/api.py`)
- FastAPI-based REST endpoints
- Request/response validation using Pydantic models
- Error handling and HTTP status code management
- Endpoints:
  - `POST /emotion/snapshot` - Production endpoint
  - `POST /emotion/snapshot/demo` - Testing/demo endpoint (requires `DEMO_MODE_ENABLED=true`)
  - `GET /emotion/health` - Health check with database connectivity test

### Layer 2: Orchestrator Layer (`fusion/orchestrator.py`)
- Coordinates the 7-step fusion workflow
- Manages parallel model service calls using `asyncio.gather()`
- Handles time window filtering and signal validation
- Orchestrates fusion logic execution and database persistence

### Layer 3: Model Client Layer (`fusion/model_clients.py`)
- HTTP clients for SER, FER, and Vitals services
- Implements retry logic (1 retry per service)
- Graceful error handling with timeout management (default: 1.5s)
- Base class pattern: `BaseModelClient` with specialized `SERClient`, `FERClient`, `VitalsClient`

### Layer 4: Core Logic Layer (`fusion/fusion_logic.py`)
- Weighted aggregation algorithm implementation
- Signal grouping and modality-based averaging
- Weight application and emotion selection
- Confidence score normalization and emotional_score mapping

### Layer 5: Persistence Layer (`utils/database.py`)
- Supabase client integration
- `insert_emotional_log()` function for database writes
- Timezone handling (UTC+8 / Malaysia timezone)

### Configuration (`fusion/config.json`)
- JSON-based configuration with fallback defaults
- Fusion weights per modality (speech: 0.4, face: 0.3, vitals: 0.3)
- Time window and timeout settings
- Model service URLs

---

## Fusion Algorithm Description

The fusion service uses a **weighted aggregation algorithm** with the following steps:

### Step 1: Group Signals by Modality
Signals are grouped into three categories: `speech`, `face`, and `vitals`.

### Step 2: Aggregate Per Modality (Average Confidence Per Emotion)
For each modality, signals with the same emotion label are averaged:
- Example: Speech has 3 "Sad" signals with confidences [0.8, 0.9, 0.7] → average = 0.8

### Step 3: Apply Modality Weights
Default weights (configurable via `config.json`):
- Speech: 0.4 (40%)
- Face: 0.3 (30%)
- Vitals: 0.3 (30%)

### Step 4: Calculate Weighted Score Per Emotion
Formula: `emotion_score = Σ(modality_avg_confidence × modality_weight)`

Example calculation:
```
Sad emotion:
  - Speech: 0.8 × 0.4 = 0.32
  - Face: 0.75 × 0.3 = 0.225
  - Vitals: 0.88 × 0.3 = 0.264
  - Total Sad score: 0.809

Happy emotion:
  - Speech: 0.55 × 0.4 = 0.22
  - Face: 0.0 (no signals)
  - Vitals: 0.0 (no signals)
  - Total Happy score: 0.22
```

### Step 5: Select Emotion with Highest Score
The emotion with the maximum weighted score is selected (e.g., Sad with 0.809 > Happy with 0.22).

### Step 6: Normalize Confidence Score
Normalizes raw weighted score to [0, 1] range:
- Formula: `confidence_score = min(raw_score / contributing_weights_sum, 1.0)`
- Accounts for cases where not all modalities contribute

### Step 7: Map to Emotional Score
Converts confidence_score to 0-100 integer scale:
- Formula: `emotional_score = round(confidence_score × 100)`
- Used for UI display and analytics

**Valid Emotions:** Angry, Sad, Happy, Fear

---

## API Endpoints Overview

### Production Endpoint: `POST /emotion/snapshot`

**Request:**
```json
{
  "user_id": "uuid-here",
  "timestamp": "2025-12-03T10:15:30Z",
  "context_id": "optional-session-id",
  "options": {
    "timeout_seconds": 1.5,
    "window_seconds": 60
  }
}
```

**Response (Success):**
```json
{
  "user_id": "uuid-here",
  "timestamp": "2025-12-03T10:15:30Z",
  "emotion_label": "Sad",
  "confidence_score": 0.79,
  "emotional_score": 79,
  "signals_used": [
    {"modality": "speech", "emotion_label": "Sad", "confidence": 0.82},
    {"modality": "face", "emotion_label": "Happy", "confidence": 0.60}
  ]
}
```

**Response (No Signals):**
```json
{
  "status": "no_signals",
  "reason": "no valid modality outputs"
}
```

### Demo Endpoint: `POST /emotion/snapshot/demo`

**Purpose:** Testing/demonstration endpoint that accepts signals directly, bypassing model service calls.

**Requirement:** `DEMO_MODE_ENABLED=true` environment variable must be set.

**Request:**
```json
{
  "user_id": "uuid-here",
  "signals": {
    "speech": "Sad:0.82,Happy:0.60",
    "face": "Sad:0.75",
    "vitals": "Sad:0.88"
  }
}
```

**Response:** Same format as production endpoint.

### Health Check: `GET /emotion/health`

**Response:**
```json
{
  "status": "healthy",
  "service": "fusion",
  "database": "connected"
}
```

---

## Cloud Deployment Setup

### Google Cloud Run Deployment

**Prerequisites:**
- Dockerfile for containerization
- Environment variables configured
- Supabase credentials

**Required Environment Variables:**
```bash
SUPABASE_URL=<supabase-project-url>
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
DEMO_MODE_ENABLED=false  # Set to true only for testing
```

**Deployment Command:**
```bash
gcloud run deploy well-bot-fusion \
  --source . \
  --region asia-south1 \
  --set-env-vars SUPABASE_URL=<url> \
  --set-env-vars SUPABASE_SERVICE_ROLE_KEY=<key> \
  --set-env-vars DEMO_MODE_ENABLED=false \
  --port 8000 \
  --memory 512Mi \
  --cpu 1
```

**Model Service URLs:**
Configure model service URLs via `config.json` or environment variable overrides. In production, these should point to deployed model service endpoints.

**Cold Start Considerations:**
- Cloud Run cold starts can take 10-30 seconds
- Health check endpoint may timeout during cold start
- Consider setting minimum instances > 0 for production

---

## Reliability & Fault Tolerance

### Model Service Failures
- **Individual failures:** Logged as warnings, processing continues with remaining modalities
- **Retry logic:** 1 automatic retry per service on failure
- **Timeout handling:** 1.5s timeout per service (configurable), fails fast to avoid blocking
- **Graceful degradation:** Service continues with partial signals if some models fail

### All Services Fail
- Returns `NoSignalsResponse` with HTTP 200 status
- No database write performed
- Reason field indicates failure cause

### Database Write Failures
- Error logged with full context (user_id, timestamp, fused result)
- Fused result still returned to caller
- Enables potential replay/recovery from logs

### Input Validation
- UUID format validation for `user_id`
- Timestamp format validation (ISO 8601)
- Invalid inputs return HTTP 400 with descriptive error messages

### Parallel Processing
- All model service calls execute concurrently using `asyncio.gather()`
- Exception handling prevents one failure from blocking others
- `return_exceptions=True` ensures all results are collected

### Health Monitoring
- Health endpoint checks database connectivity
- Returns HTTP 503 if database unavailable
- Can be extended to check model service health

---

## Data Flow

### Request Flow

```
Edge Device / Backend Service
    ↓
POST /emotion/snapshot
    ↓
Orchestrator (validate request, determine timestamp)
    ↓
Parallel HTTP Calls (asyncio.gather)
    ├─→ SER Service /predict
    ├─→ FER Service /predict
    └─→ Vitals Service /predict
    ↓
Time Window Filtering (60s default)
    ↓
Fusion Logic (weighted aggregation)
    ↓
Database Write (emotional_log table)
    ↓
Response (FusedEmotionResponse)
```

### Model Service Contract

**Request to Model Service:**
```json
{
  "user_id": "uuid",
  "snapshot_timestamp": "2025-12-03T10:15:30Z",
  "window_seconds": 60
}
```

**Response from Model Service:**
```json
{
  "signals": [
    {
      "user_id": "uuid",
      "timestamp": "2025-12-03T10:15:30Z",
      "modality": "speech",
      "emotion_label": "Sad",
      "confidence": 0.82
    }
  ]
}
```

### Database Schema

**Table:** `emotional_log`

| Column | Type | Description |
|--------|------|-------------|
| id | integer | Primary key (auto-generated) |
| user_id | uuid | User identifier |
| timestamp | timestamp | Snapshot timestamp (UTC+8) |
| emotion_label | varchar | Fused emotion (Angry/Sad/Happy/Fear) |
| confidence_score | double | Normalized confidence (0.0-1.0) |
| emotional_score | integer | Emotional score (0-100) |

### Downstream Consumption

- **Intervention Service:** Reads from `emotional_log` table to make intervention decisions
- **Analytics/Dashboard:** Queries `emotional_log` for emotion trends and patterns
- **Reporting:** Uses `emotional_score` for UI display and analytics

---

## Limitations

### Temporal Constraints
- **Time Window:** Only considers signals within 60-second window (configurable)
- **Stale Data:** Signals outside time window are discarded, may result in `no_signals` if all data is stale

### Modality Dependencies
- **Partial Failures:** If all three model services fail, no fusion can occur
- **Single Modality:** Fusion works with partial signals, but results may be less reliable with fewer modalities

### Algorithm Limitations
- **Fixed Weights:** Modality weights are static (configurable but not adaptive)
- **No Signal Quality Metrics:** Does not consider signal recency or quality beyond time window
- **Simple Averaging:** Uses arithmetic mean for confidence aggregation within modalities

### Performance Constraints
- **Synchronous Database Writes:** Database writes are blocking (could be optimized to async)
- **No Caching:** Each request triggers full fusion calculation (no result caching)
- **Timeout Sensitivity:** Strict 1.5s timeout may cause failures on slow networks

### Deployment Constraints
- **Cold Starts:** Cloud Run cold starts can cause 10-30 second delays
- **Single Region:** Service deployed to single region (no multi-region redundancy)
- **No Load Balancing:** Relies on Cloud Run's built-in load balancing

### Data Limitations
- **Emotion Set:** Limited to 4 emotions (Angry, Sad, Happy, Fear)
- **No Emotion Intensity:** Does not distinguish between mild and intense emotions
- **No Context Awareness:** Does not consider user history or conversation context

### Security Considerations
- **Demo Endpoint:** Demo endpoint requires environment variable flag (not authentication)
- **No Rate Limiting:** No built-in rate limiting on endpoints
- **Database Credentials:** Requires service role key with write permissions

---

## Future Enhancements

- Adaptive modality weights based on signal quality
- Signal quality metrics and recency scoring
- Caching layer for recent fusion results
- Asynchronous database writes for improved performance
- Multi-region deployment for redundancy
- Rate limiting and authentication for demo endpoint
- Extended emotion set and intensity levels
- Context-aware fusion using user history
```
