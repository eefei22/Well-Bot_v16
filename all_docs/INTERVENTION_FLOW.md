# Intervention Communication Flow & Strategy

## Overview

This document describes the complete communication pattern, strategy, and flow of events related to interventions between the **Well-Bot_edge** (edge device) and **Well-Bot_cloud** (cloud service). It covers how interventions are decided, updated, triggered, and the full flow including alternative paths.

---

## Architecture Components

### Edge Device (Well-Bot_edge)

1. **InterventionPoller** (`src/utils/intervention_poller.py`)
   - Periodic polling service (default: 15 minutes, configurable)
   - Queries database for new emotion log entries
   - Calls cloud service API when new emotions detected
   - Updates local `intervention_record.json` file

2. **InterventionServiceClient** (`src/utils/intervention_client.py`)
   - HTTP client for cloud service communication
   - Handles POST requests to `/api/intervention/suggest`
   - Manages request/response with error handling and retries

3. **InterventionRecordManager** (`src/utils/intervention_record.py`)
   - Manages `intervention_record.json` file
   - Stores latest emotion entry, decision, and suggestions
   - Tracks timestamps for polling logic

4. **IdleModeActivity** (`src/activities/idle_mode.py`)
   - Monitors wake word detection
   - Checks intervention trigger when intent is "unknown"
   - Routes to ActivitySuggestionActivity if intervention should trigger

5. **ActivitySuggestionActivity** (`src/activities/activity_suggestion.py`)
   - Presents ranked activity suggestions to user
   - Listens for user's activity choice
   - Routes to selected activity or smalltalk

6. **WellBotOrchestrator** (`main.py`)
   - Coordinates intervention poller lifecycle
   - Starts/stops poller based on system state
   - Routes to activities based on intervention triggers

### Cloud Service (Well-Bot_cloud)

1. **Intervention API Endpoint** (`main.py`)
   - `POST /api/intervention/suggest` - Main suggestion endpoint
   - `GET /api/intervention/health` - Health check endpoint

2. **Intervention Orchestrator** (`intervention/intervention.py`)
   - Orchestrates complete intervention flow
   - Fetches user data from database
   - Calls decision and suggestion engines
   - Returns structured response

3. **Decision Engine** (`intervention/decision_engine.py`)
   - Implements kick-start decision algorithm
   - Determines if intervention should trigger
   - Based on: emotion label, confidence score, time since last activity

4. **Suggestion Engine** (`intervention/suggestion_engine.py`)
   - Generates ranked activity recommendations (1-5)
   - Considers: emotion type, user preferences, time of day, recent activities
   - Returns scored and ranked activity list

5. **Database Utilities** (`utils/database.py`)
   - Fetches recent emotion logs (48 hours)
   - Fetches recent activity logs (24 hours)
   - Fetches user preferences
   - Calculates time since last activity

---

## Communication Pattern

### Pattern Type: **Polling with Event-Driven Triggering**

The system uses a **hybrid polling and event-driven approach**:

1. **Polling**: Edge device periodically polls database for new emotion entries
2. **Event-Driven**: When new emotion detected, edge device proactively calls cloud service
3. **State-Based**: Intervention trigger is checked when user interaction occurs (wake word + unknown intent)

### Communication Protocol

- **Protocol**: HTTP REST API
- **Method**: POST requests from edge to cloud
- **Data Format**: JSON
- **Timeout**: 30 seconds (configurable)
- **Polling Interval**: 15 minutes (configurable, default: 5 minutes in code)

---

## Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         PRIMARY INTERVENTION FLOW                       │
└─────────────────────────────────────────────────────────────────────────┘

[1] EMOTION DETECTION (External System)
    ↓
    Emotion logged to Supabase `emotional_log` table
    (emotion_label, confidence_score, timestamp, user_id)
    ↓
[2] INTERVENTION POLLER (Edge Device - Every 15 minutes)
    ↓
    InterventionPoller._check_for_new_emotions()
    ├─ Query database: query_emotional_logs_since(user_id, last_24_hours)
    ├─ Compare with last_processed_timestamp from intervention_record.json
    ├─ If new entry found → proceed to [3]
    └─ If no new entry → update latest_emotion_entry only, schedule next poll
    ↓
[3] PROCESS NEW EMOTION ENTRY (Edge Device)
    ↓
    InterventionPoller._process_new_emotion_entry(entry)
    ├─ Extract: emotion_label, confidence_score, timestamp
    ├─ Record request_time
    └─ Call cloud service API
    ↓
[4] CLOUD SERVICE API CALL (Edge → Cloud)
    ↓
    POST /api/intervention/suggest
    Payload: {
        user_id: str,
        emotion_label: str,
        confidence_score: float,
        timestamp: ISO datetime,
        context_time_of_day: Optional[str]
    }
    ↓
[5] CLOUD SERVICE PROCESSING (Cloud)
    ↓
    intervention.process_suggestion_request(request)
    ├─ [5a] Fetch user data from database
    │   ├─ fetch_recent_emotion_logs(user_id, hours=48)
    │   ├─ fetch_recent_activity_logs(user_id, hours=24)
    │   ├─ fetch_user_preferences(user_id)
    │   └─ get_time_since_last_activity(user_id)
    │
    ├─ [5b] Determine time of day context
    │   └─ get_time_of_day_context(timestamp) → 'morning'|'afternoon'|'evening'|'night'
    │
    ├─ [5c] Decision Engine
    │   └─ decide_trigger_intervention(emotion_label, confidence_score, time_since_last_activity)
    │       Decision Logic:
    │       ├─ is_negative_emotion? (Sad, Angry, Fear)
    │       ├─ confidence_score >= 0.70?
    │       ├─ time_since_last_activity > 60 minutes?
    │       └─ trigger_intervention = all conditions met
    │
    └─ [5d] Suggestion Engine
        └─ suggest_activities(emotion_label, user_preferences, recent_activity_logs, time_of_day)
            Scoring Factors:
            ├─ Base emotion-to-activity weights
            ├─ User preference adjustments (±20% boost/reduction)
            ├─ Time-of-day adjustments (multipliers)
            └─ Recent activity penalty (-20% if used recently)
    ↓
[6] CLOUD SERVICE RESPONSE (Cloud → Edge)
    ↓
    Response: {
        user_id: str,
        decision: {
            trigger_intervention: bool,
            confidence_score: float,
            reasoning: str
        },
        suggestion: {
            ranked_activities: [
                {activity_type: str, rank: int, score: float},
                ...
            ],
            reasoning: str
        }
    }
    ↓
[7] UPDATE INTERVENTION RECORD (Edge Device)
    ↓
    InterventionRecordManager.update_record(
        emotion_entry, decision, suggestion, request_time, response_time
    )
    ├─ Save to: backend/config/intervention_record.json
    └─ Preserves: last_database_query_time
    ↓
[8] INTERVENTION TRIGGER CHECK (Edge Device - On User Interaction)
    ↓
    User says wake word → IdleModeActivity detects
    ├─ User speaks → STT transcript
    ├─ KeywordIntentMatcher matches intent
    └─ If intent == "unknown":
        ├─ Load intervention_record.json
        ├─ Check decision.trigger_intervention
        └─ If true → Route to ActivitySuggestionActivity
    ↓
[9] ACTIVITY SUGGESTION ACTIVITY (Edge Device)
    ↓
    ActivitySuggestionActivity.run()
    ├─ Load ranked activities from intervention_record.json
    ├─ Format and speak suggestions via TTS
    ├─ Listen for user's activity choice (keyword matching)
    ├─ Route to selected activity OR smalltalk if no match
    └─ Log activity start to database (if activity selected)
    ↓
[10] ACTIVITY EXECUTION (Edge Device)
    ↓
    Selected activity runs (journal, meditation, gratitude, quote, smalltalk)
    ├─ Activity logs start to database
    ├─ User completes activity
    └─ Activity ends → Return to idle mode
    ↓
[11] RETURN TO IDLE MODE (Edge Device)
    ↓
    WellBotOrchestrator._restart_idle_mode()
    ├─ Restart InterventionPoller (if in LISTENING state)
    └─ Resume wake word detection
```

---

## Decision Logic Details

### Decision Engine Criteria

The decision engine (`decision_engine.py`) uses three criteria to determine if an intervention should trigger:

1. **Negative Emotion Detection**
   - Emotion must be in: `['Sad', 'Angry', 'Fear']`
   - Positive emotions ('Happy') do not trigger interventions

2. **Confidence Threshold**
   - `confidence_score >= 0.70` (70% confidence)
   - Lower confidence reduces decision confidence but doesn't prevent trigger if other conditions met

3. **Activity Gap**
   - `time_since_last_activity > 60 minutes`
   - Prevents intervention spam if user recently engaged

**Decision Formula:**
```
trigger_intervention = is_negative_emotion AND 
                      meets_confidence_threshold AND 
                      enough_time_passed
```

### Decision Confidence Calculation

- **If trigger = true**: `decision_confidence = min(confidence_score, 0.95)`
- **If trigger = false**:
  - Not negative emotion → `confidence = 0.0`
  - Low confidence → `confidence = confidence_score * 0.5`
  - Recent activity → `confidence = 0.0`

---

## Suggestion Engine Details

### Activity Ranking Algorithm

The suggestion engine (`suggestion_engine.py`) ranks activities using a multi-factor scoring system:

1. **Base Emotion Weights** (0.0-1.0)
   - Each emotion has preferred activities
   - Example: 'Sad' → journal (0.9), meditation (0.8), gratitude (0.7), quote (0.6)

2. **User Preference Adjustments**
   - If user prefers activity: `score *= 1.2` (+20% boost)
   - If user doesn't prefer: `score *= 0.7` (-30% reduction)

3. **Time-of-Day Adjustments** (multipliers)
   - Morning: gratitude (0.9), journal (0.8)
   - Afternoon: quote (0.9), meditation (0.8)
   - Evening: journal (0.9), meditation (0.9)
   - Night: journal (0.9), meditation (0.8)

4. **Recent Activity Penalty**
   - If activity used in last 5 activities: `score *= 0.8` (-20% reduction)

5. **Normalization**
   - Scores normalized to 0.0-1.0 range
   - Sorted by score (descending)
   - Ranked 1-5 (1 = highest score)

---

## Alternative Flows

### Flow A: No New Emotion Entry

```
[1] InterventionPoller._check_for_new_emotions()
    ├─ Query database for latest entry
    ├─ Compare with last_processed_timestamp
    └─ Latest entry timestamp <= last_processed_timestamp
        ↓
    [2] Update latest_emotion_entry only (no cloud call)
        └─ InterventionRecordManager.update_emotion_entry_only()
            ├─ Preserves existing decision and suggestion
            └─ Updates last_database_query_time
        ↓
    [3] Schedule next poll (15 minutes)
```

**Key Point**: Cloud service is only called when a **new** emotion entry is detected (timestamp comparison).

---

### Flow B: Cloud Service Unavailable

```
[1] InterventionPoller._process_new_emotion_entry()
    └─ InterventionServiceClient.get_suggestion()
        ├─ HTTP request fails (timeout, connection error, etc.)
        └─ Returns None
        ↓
    [2] Log error, skip record update
        └─ Latest emotion entry still updated (from polling)
        └─ Decision and suggestion remain unchanged
        ↓
    [3] Schedule next poll (will retry on next new emotion)
```

**Key Point**: System is resilient - continues polling even if cloud service is temporarily unavailable. Previous decision/suggestion remains cached.

---

### Flow C: User Explicitly Requests Activity (Bypasses Intervention)

```
[1] User says wake word
    ↓
[2] User speaks: "start journaling" (or other explicit command)
    ↓
[3] KeywordIntentMatcher matches intent: "journaling"
    ↓
[4] WellBotOrchestrator._route_to_activity()
    ├─ Intent != "unknown" → Skip intervention check
    └─ Route directly to JournalActivity
    ↓
[5] Activity executes (no intervention trigger needed)
```

**Key Point**: Explicit user commands bypass intervention logic. Intervention only triggers when intent is "unknown" (user didn't specify activity).

---

### Flow D: Intervention Triggered but User Doesn't Select Activity

```
[1] ActivitySuggestionActivity.run()
    ├─ Speaks ranked activity suggestions
    ├─ Listens for user choice
    └─ No activity matched (timeout or no keyword match)
        ↓
    [2] Route to SmallTalkActivity
        ├─ Conversation context seeded with activity suggestions
        └─ User can discuss or request activity naturally
        ↓
    [3] SmallTalkActivity completes
        └─ Return to idle mode
```

**Key Point**: If user doesn't explicitly select an activity, system gracefully falls back to smalltalk with context.

---

### Flow E: Multiple Emotions Detected Between Polls

```
[1] InterventionPoller polls every 15 minutes
    ├─ Query returns multiple new emotion entries
    └─ Gets latest entry (last in list, ordered ascending)
        ↓
    [2] Process only latest entry
        └─ Cloud service called with latest emotion
        ↓
    [3] Decision and suggestion based on latest emotion
        └─ Previous emotions in same poll window are not processed separately
```

**Key Point**: Only the **latest** emotion entry is processed per poll cycle. Multiple emotions between polls are handled by processing the most recent one.

---

### Flow F: Intervention Poller Lifecycle Management

```
[1] System starts → LISTENING state
    └─ InterventionPoller.start()
        ├─ Run initial check immediately
        └─ Schedule periodic polls
        ↓
[2] User starts activity → ACTIVITY_ACTIVE state
    └─ InterventionPoller.stop()
        └─ Polling paused during activity
        ↓
[3] Activity ends → Return to LISTENING state
    └─ InterventionPoller.start()
        └─ Resume polling
```

**Key Point**: Poller is **stopped during activities** to avoid unnecessary database queries and cloud calls. Resumes when system returns to idle/listening state.

---

## Data Flow & State Management

### Intervention Record Structure

The `intervention_record.json` file maintains:

```json
{
  "latest_emotion_entry": {
    "id": int,
    "emotion_label": str,
    "confidence_score": float,
    "timestamp": ISO datetime string
  },
  "latest_decision": {
    "trigger_intervention": bool,
    "confidence_score": float,
    "reasoning": str
  },
  "latest_suggestion": {
    "ranked_activities": [
      {
        "activity_type": str,
        "rank": int,
        "score": float
      }
    ],
    "reasoning": str
  },
  "last_request_time": ISO datetime string,
  "last_response_time": ISO datetime string,
  "last_database_query_time": ISO datetime string
}
```

### State Transitions

```
STARTING
  ↓
LISTENING (InterventionPoller active)
  ↓
PROCESSING (Wake word detected, processing intent)
  ↓
ACTIVITY_ACTIVE (InterventionPoller stopped, activity running)
  ↓
LISTENING (Activity ends, InterventionPoller resumed)
  ↓
[Loop continues...]
```

---

## Configuration

### Edge Device Configuration

**Environment Variables** (`.env`):
- `CLOUD_SERVICE_URL`: Cloud service base URL
  - Default: `https://user-context-well-bot-520080168829.asia-south1.run.app`

**Code Configuration** (`InterventionPoller.__init__`):
- `poll_interval_minutes`: Default 15 minutes (configurable)

### Cloud Service Configuration

**Decision Engine Constants** (`decision_engine.py`):
- `NEGATIVE_EMOTIONS = ['Sad', 'Angry', 'Fear']`
- `CONFIDENCE_THRESHOLD = 0.70`
- `MIN_TIME_SINCE_LAST_ACTIVITY_MINUTES = 60.0`

**Suggestion Engine Constants** (`suggestion_engine.py`):
- `ACTIVITY_TYPES = ['journal', 'gratitude', 'meditation', 'quote']`
- Emotion-to-activity weight mappings
- Time-of-day adjustment multipliers
- User preference boost/reduction factors

---

## Error Handling & Resilience

### Edge Device Error Handling

1. **Database Query Failures**
   - Logs error, continues polling
   - Preserves existing intervention record

2. **Cloud Service Failures**
   - HTTP errors logged, returns None
   - Previous decision/suggestion cached
   - Retries on next poll cycle

3. **File I/O Failures**
   - InterventionRecordManager handles file read/write errors
   - Returns default empty record on read failure
   - Logs errors but doesn't crash system

### Cloud Service Error Handling

1. **Database Connection Failures**
   - Raises HTTPException (500)
   - Edge device handles gracefully (Flow B)

2. **Invalid Request Data**
   - Raises HTTPException (400)
   - Edge device logs error, continues polling

3. **Processing Errors**
   - Logs error with full traceback
   - Raises HTTPException (500)
   - Edge device handles gracefully

---

## Performance Considerations

1. **Polling Interval**: 15 minutes balances responsiveness vs. resource usage
2. **Database Queries**: Only queries last 24 hours of emotion logs (efficient)
3. **Cloud Service Calls**: Only on new emotion entries (not every poll)
4. **Caching**: Intervention record cached locally, reduces file I/O
5. **Poller Lifecycle**: Stopped during activities (reduces unnecessary work)

---

## Summary

The intervention system uses a **polling-based discovery** pattern with **event-driven processing**:

- **Polling**: Edge device periodically checks for new emotions (15 min intervals)
- **Event-Driven**: New emotions trigger immediate cloud service calls
- **State-Based**: Intervention triggers checked on user interaction (unknown intent)
- **Resilient**: System continues operating even if cloud service unavailable
- **Efficient**: Only processes new emotions, stops polling during activities

The flow ensures interventions are:
- **Timely**: Detected within 15 minutes of emotion logging
- **Contextual**: Based on user history, preferences, and time of day
- **Non-Intrusive**: Only triggers when user interaction occurs and intent is unknown
- **Personalized**: Activity suggestions ranked by emotion, preferences, and recent activity

