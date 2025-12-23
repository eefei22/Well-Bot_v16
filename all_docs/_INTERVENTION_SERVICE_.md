# Intervention Service - Technical Report

## Purpose of the Intervention Service

The Intervention Service is a cloud-based microservice that analyzes emotion logs and user activity history to automatically suggest wellness interventions when negative emotions are detected. It serves as the decision-making layer that determines when and which activities to recommend to users based on their emotional state and engagement patterns.

**Key Responsibilities:**
- Analyze latest emotion logs from the `emotional_log` database table
- Determine if an intervention should be triggered (kick-start decision)
- Generate ranked activity suggestions (1-4) based on emotion, user preferences, and activity frequency
- Provide structured responses to edge devices for intervention presentation

**Note:** The service reads emotion data created by the Fusion Service. It focuses on intervention decision-making and activity recommendation, not emotion detection.

---

## Architecture Overview

The Intervention Service follows a modular architecture with clear separation of concerns:

### Layer 1: API Layer (`main.py`)
- FastAPI-based REST endpoints
- Request/response validation using Pydantic models
- Error handling and HTTP status code management
- Endpoints:
  - `POST /api/intervention/suggest` - Main intervention suggestion endpoint
  - `GET /api/intervention/health` - Health check with database connectivity test

### Layer 2: Orchestrator Layer (`intervention/intervention.py`)
- Coordinates the complete intervention suggestion flow
- Validates input parameters (user_id format, emotion labels)
- Fetches user data from database (emotion logs, preferences, activity counts)
- Calls decision engine and suggestion engine
- Returns structured response with decision and suggestions

### Layer 3: Decision Engine (`intervention/decision_engine.py`)
- Implements kick-start decision algorithm
- Evaluates three conditions:
  1. Negative emotion detected (Sad, Angry, or Fear)
  2. Confidence score >= 0.70
  3. Time since last activity > 60 minutes
- Returns boolean trigger decision with confidence score and reasoning

### Layer 4: Suggestion Engine (`intervention/suggestion_engine.py`)
- Implements activity recommendation algorithm
- Ranks activities (1-4) using multi-factor scoring:
  - Base emotion-activity weights (emotion-specific activity preferences)
  - User preference adjustments (1.2x for preferred, 0.7x for not preferred)
  - Frequency-based multipliers (1.3x for most frequent, down to 1.05x for least frequent)
- Normalizes scores to 0.0-1.0 range
- Returns ranked activities with scores and reasoning

### Layer 5: Data Access Layer (`utils/database.py`)
- Supabase client integration
- Functions:
  - `get_latest_emotion_log()` - Fetch most recent emotion entry
  - `fetch_recent_emotion_logs()` - Fetch emotion logs from last 48 hours
  - `fetch_user_preferences()` - Get user activity preferences
  - `get_time_since_last_activity()` - Calculate minutes since last activity
  - `get_activity_counts()` - Count activity occurrences in last 30 days
- Timezone handling (UTC+8, Malaysia timezone)

### Layer 6: Configuration Layer (`intervention/config_loader.py`)
- Loads configuration from `intervention/config.json`
- Caches configuration after first load
- Provides fallback defaults if config file missing
- Configuration includes:
  - Decision engine thresholds (confidence, time windows)
  - Emotion-activity weight mappings
  - Frequency multipliers
  - Preference multipliers

---

## Intervention Algorithm Description

### Decision Engine Algorithm

The decision engine uses a three-condition AND logic:

```
trigger_intervention = (
    emotion_label in ['Sad', 'Angry', 'Fear'] AND
    confidence_score >= 0.70 AND
    time_since_last_activity_minutes > 60.0
)
```

**Decision Confidence Calculation:**
- If all conditions met: `min(confidence_score, 0.95)`
- If negative emotion but low confidence: `confidence_score * 0.5`
- If recent activity: `0.0`
- If positive emotion: `0.0`

### Suggestion Engine Algorithm

The suggestion engine uses a multi-factor scoring system:

1. **Base Emotion Weights**: Start with emotion-specific activity weights (0.0-1.0)
   - Example: Sad → journal: 0.9, meditation: 0.8, gratitude: 0.7, quote: 0.6

2. **User Preference Adjustment**: Apply multipliers based on user preferences
   - Preferred activity: `score × 1.2`
   - Not preferred activity: `score × 0.7`

3. **Frequency-Based Multipliers**: Boost activities based on relative usage frequency (last 30 days)
   - Activities grouped by frequency count (same count = same multiplier)
   - Most frequent group: `score × 1.3`
   - Second most frequent: `score × 1.2`
   - Third most frequent: `score × 1.1`
   - Least frequent: `score × 1.05`

4. **Score Normalization**: Normalize all scores to 0.0-1.0 range
   - `normalized_score = score / max_score`

5. **Ranking**: Sort activities by normalized score (descending)
   - Rank 1 = highest score (best recommendation)
   - Rank 4 = lowest score

**Algorithm Flow:**
```
Base Emotion Weights
    ↓
Apply User Preferences (×1.2 or ×0.7)
    ↓
Apply Frequency Multipliers (×1.3 to ×1.05)
    ↓
Normalize to 0.0-1.0
    ↓
Sort and Rank (1-4)
```

---

## API Endpoints Overview

### POST /api/intervention/suggest

**Purpose:** Request intervention suggestion for a user.

**Request Body:**
```json
{
  "user_id": "uuid-string"
}
```

**Response:**
```json
{
  "user_id": "uuid-string",
  "decision": {
    "trigger_intervention": true,
    "confidence_score": 0.85,
    "reasoning": "Negative emotion 'Sad' detected; Confidence 0.85 >= 0.70; Time since last activity: 120.0 minutes"
  },
  "suggestion": {
    "ranked_activities": [
      {
        "activity_type": "journal",
        "rank": 1,
        "score": 0.923
      },
      {
        "activity_type": "meditation",
        "rank": 2,
        "score": 0.821
      },
      {
        "activity_type": "gratitude",
        "rank": 3,
        "score": 0.712
      },
      {
        "activity_type": "quote",
        "rank": 4,
        "score": 0.654
      }
    ],
    "reasoning": "Emotion: Sad; Top suggestion: journal (score: 0.923)"
  }
}
```

**Error Responses:**
- `400 Bad Request`: Invalid user_id format or missing emotion logs
- `500 Internal Server Error`: Database errors or processing failures

### GET /api/intervention/health

**Purpose:** Health check endpoint for service monitoring.

**Response:**
```json
{
  "status": "healthy",
  "service": "intervention",
  "database": "connected",
  "timestamp": "2024-01-01T12:00:00"
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
```

**Deployment Command:**
```bash
gcloud run deploy well-bot-intervention \
  --source . \
  --region asia-south1 \
  --set-env-vars SUPABASE_URL=<url> \
  --set-env-vars SUPABASE_SERVICE_ROLE_KEY=<key> \
  --port 8080 \
  --memory 512Mi \
  --cpu 1 \
  --timeout 60 \
  --max-instances 10
```

**Dockerfile Configuration:**
- Base image: `python:3.12-slim`
- Port: 8080 (Cloud Run maps to HTTPS on 443)
- Command: `uvicorn main:app --host 0.0.0.0 --port 8080`

**Cloud Run Configuration:**
- **Platform**: Managed (fully serverless)
- **Region**: asia-south1 (configurable)
- **Memory**: 512Mi (sufficient for database queries and scoring)
- **CPU**: 1 vCPU
- **Timeout**: 60 seconds
- **Max Instances**: 10 (auto-scales based on load)
- **Min Instances**: 0 (scales to zero when idle)

**Service Characteristics:**
- Auto-scaling based on request volume
- Cold start: ~5-10 seconds (container initialization)
- Warm instances: Faster response times
- Health checks: `/api/intervention/health` endpoint
- Logging: Integrated with Google Cloud Logging

---

## Reliability & Fault Tolerance

### Input Validation
- **UUID format validation** for `user_id` (returns HTTP 400 if invalid)
- **Emotion label validation** (must be one of: Sad, Angry, Happy, Fear)
- **Missing data handling**: Returns HTTP 400 if no emotion logs found for user

### Database Failures
- **Connection errors**: Logged with full context, returns HTTP 500
- **Query failures**: Exception handling with detailed error messages
- **Missing data**: Graceful handling with clear error messages

### Configuration Failures
- **Missing config file**: Falls back to hardcoded defaults
- **Invalid JSON**: Logs error and uses fallback defaults
- **Missing config keys**: Uses fallback values per key

### Edge Device Integration
- **HTTP timeout**: 30 seconds (configurable in client)
- **Connection errors**: Logged, returns None (edge device handles gracefully)
- **Retry logic**: Not implemented at service level (edge device can retry)

### Error Handling Strategy
- **Validation errors**: HTTP 400 with descriptive messages
- **Processing errors**: HTTP 500 with error details
- **Database errors**: Logged with full context, HTTP 500 returned
- **All exceptions**: Caught, logged with stack trace, appropriate HTTP status returned

---

## Data Flow

### Complete Intervention Flow

```
1. Fusion Service
   ↓
   Creates emotion_log entry in database
   ↓
2. Edge Device (InterventionPoller)
   ↓
   Polls every 15 minutes (configurable)
   ↓
   Calls POST /api/intervention/suggest
   ↓
3. Cloud Intervention Service
   ↓
   [Orchestrator] Validates user_id
   ↓
   [Database] Fetches latest emotion_log
   ↓
   [Database] Fetches recent emotion_logs (48h)
   ↓
   [Database] Fetches user preferences
   ↓
   [Database] Calculates time since last activity
   ↓
   [Database] Gets activity counts (30 days)
   ↓
   [Decision Engine] Evaluates trigger conditions
   ↓
   [Suggestion Engine] Ranks activities (1-4)
   ↓
   Returns decision + suggestions
   ↓
4. Edge Device
   ↓
   Saves to intervention_record.json
   ↓
   On next wake word:
   ↓
   Checks intervention_record.json
   ↓
   If trigger_intervention=true:
   ↓
   Routes to ActivitySuggestionActivity
   ↓
   Presents ranked activities to user
```

### Database Tables Used

- **emotional_log**: Source of emotion data (created by Fusion Service)
  - Fields: `user_id`, `emotion_label`, `confidence_score`, `timestamp`
  
- **intervention_log**: Activity history (read for frequency calculation)
  - Fields: `user_id`, `intervention_type`, `timestamp`
  
- **users**: User preferences
  - Fields: `id`, `prefer_intervention` (JSONB field)

### Data Dependencies

- **Latest emotion**: Required (service fails if missing)
- **Recent emotions**: Optional (used for context, not critical)
- **User preferences**: Optional (defaults to empty dict if missing)
- **Activity counts**: Optional (defaults to 0 for all activities if missing)
- **Time since last activity**: Optional (defaults to infinity if no activities)

---

## Limitations

### Algorithm Limitations
- **Fixed thresholds**: Confidence threshold (0.70) and time window (60 minutes) are hardcoded in config
- **Emotion mapping**: Only supports 4 emotions (Sad, Angry, Happy, Fear)
- **Activity types**: Limited to 4 activities (journal, gratitude, meditation, quote)
- **Frequency window**: Activity counts only consider last 30 days (fixed window)
- **No learning**: Algorithm does not adapt based on user response or effectiveness

### Scalability Limitations
- **No caching**: Each request queries database (no result caching)
- **Synchronous processing**: All database queries are sequential (not parallelized)
- **Single instance**: No distributed processing or load balancing considerations
- **Database load**: Multiple queries per request (5+ queries per suggestion)

### Data Limitations
- **Timezone assumption**: Assumes all timestamps are in UTC+8 (Malaysia timezone)
- **No historical analysis**: Only considers latest emotion, not emotion trends
- **No activity effectiveness**: Does not consider whether past activities were effective
- **Binary preferences**: User preferences are boolean (preferred/not preferred), no granularity

### Integration Limitations
- **Polling-based**: Edge device must poll (not push-based or event-driven)
- **No real-time**: 15-minute polling interval means up to 15-minute delay
- **Single user per request**: Cannot batch process multiple users
- **No webhooks**: Cannot notify edge device when intervention should trigger

### Error Recovery Limitations
- **No retry logic**: Service does not retry failed database queries
- **No circuit breaker**: No protection against cascading failures
- **No rate limiting**: No protection against request flooding
- **Limited monitoring**: Health check only tests database connectivity

### Configuration Limitations
- **Static config**: Configuration loaded once at startup (requires restart to change)
- **No A/B testing**: Cannot test different algorithm parameters
- **No per-user customization**: All users use same algorithm parameters

---

