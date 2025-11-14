# Intervention Service Integration

## Overview

The Intervention Service is a cloud-based service that analyzes emotion logs and activity history to automatically suggest wellness interventions when negative emotions are detected. The edge device polls the database for new emotion entries and requests intervention suggestions from the cloud service.

## Architecture

### Components

1. **Cloud Service (Well-Bot_cloud)**
   - REST API endpoint: `POST /api/intervention/suggest`
   - Health check endpoint: `GET /api/intervention/health`
   - Decision engine: Determines if intervention should be triggered
   - Suggestion engine: Ranks activities to suggest (1-5)

2. **Edge Device (Well-Bot_edge)**
   - **InterventionPoller**: Polls database and calls cloud service
   - **InterventionServiceClient**: HTTP client for cloud service
   - **InterventionRecordManager**: Manages intervention_record.json
   - **Database Query**: `query_emotional_logs_since()` for emotion logs

### Data Flow

```
Emotion Detection → emotional_log table
         ↓
InterventionPoller (every 15 minutes)
         ↓
Query new emotion_log entries
         ↓
Call Cloud Service API
         ↓
Receive Decision + Suggestions
         ↓
Save to intervention_record.json
```

## Configuration

### Environment Variables

**Edge Device (.env file):**
- `CLOUD_SERVICE_URL`: Cloud service base URL
  - Example: `https://user-context-well-bot-520080168829.asia-south1.run.app`
  - Default: Uses the same URL as context service if not set

**Cloud Service (.env file):**
- `SUPABASE_URL`: Supabase project URL
- `SUPABASE_SERVICE_ROLE_KEY`: Supabase service role key
- `DEV_USER_ID`: Development user ID (for testing)

### Configuration Files

**Edge Device:**
- `backend/config/intervention_record.json`: Stores latest intervention data
  - Auto-created on first run if missing
  - Structure documented below

## API Endpoints

### Cloud Service Endpoints

#### POST /api/intervention/suggest

Request intervention suggestion based on emotion data.

**Request Body:**
```json
{
  "user_id": "uuid-string",
  "emotion_label": "Sad" | "Angry" | "Happy" | "Fear",
  "confidence_score": 0.0-1.0,
  "timestamp": "ISO 8601 datetime string",
  "context_time_of_day": "morning" | "afternoon" | "evening" | "night" (optional)
}
```

**Response:**
```json
{
  "user_id": "uuid-string",
  "decision": {
    "trigger_intervention": true,
    "confidence_score": 0.85,
    "reasoning": "Negative emotion 'Sad' detected; Confidence 0.85 >= 0.7; Time since last activity: 2233.6 minutes"
  },
  "suggestion": {
    "ranked_activities": [
      {
        "activity_type": "journal",
        "rank": 1,
        "score": 1.000
      },
      {
        "activity_type": "meditation",
        "rank": 2,
        "score": 0.889
      },
      {
        "activity_type": "gratitude",
        "rank": 3,
        "score": 0.605
      },
      {
        "activity_type": "quote",
        "rank": 4,
        "score": 0.593
      }
    ],
    "reasoning": "Emotion: Sad; Time of day: evening; Top suggestion: journal (score: 1.000)"
  }
}
```

**Status Codes:**
- `200`: Success
- `400`: Bad Request (invalid input)
- `500`: Internal Server Error

#### GET /api/intervention/health

Health check endpoint for monitoring service availability.

**Response:**
```json
{
  "status": "healthy",
  "service": "intervention",
  "database": "connected",
  "timestamp": "2025-11-09T10:30:00.000000"
}
```

**Status Codes:**
- `200`: Service is healthy
- `200`: Service is unhealthy (status: "unhealthy" in response)

## Edge Device Components

### InterventionPoller

Polls the database for new emotion log entries and requests intervention suggestions.

**Location:** `backend/src/utils/intervention_poller.py`

**Initialization:**
```python
poller = InterventionPoller(
    user_id="uuid-string",
    record_file_path=Path("config/intervention_record.json"),
    poll_interval_minutes=15,
    service_url="https://cloud-service-url.com"  # Optional, uses CLOUD_SERVICE_URL from .env
)
```

**Methods:**
- `start()`: Start polling service (runs initial check + periodic checks)
- `stop()`: Stop polling service gracefully

**Polling Behavior:**
- Runs immediately on startup
- Checks database for new emotion entries since last processed timestamp
- If new entries found, calls cloud service for each new entry
- Polls every 15 minutes (configurable)
- Updates `intervention_record.json` with latest results

### InterventionServiceClient

HTTP client for communicating with the cloud intervention service.

**Location:** `backend/src/utils/intervention_client.py`

**Initialization:**
```python
client = InterventionServiceClient(service_url=None)  # Uses CLOUD_SERVICE_URL from .env if None
```

**Methods:**
- `get_suggestion(user_id, emotion_label, confidence_score, timestamp, context_time_of_day=None) -> Dict | None`
  - Requests intervention suggestion from cloud service
  - Returns response dict or None on failure
- `check_health() -> bool`
  - Checks if cloud service is healthy
  - Returns True if healthy, False otherwise

**Error Handling:**
- Handles timeouts (30 second default)
- Handles connection errors
- Handles HTTP errors
- Returns None on any failure (logged)

### InterventionRecordManager

Manages the `intervention_record.json` file.

**Location:** `backend/src/utils/intervention_record.py`

**Initialization:**
```python
manager = InterventionRecordManager(
    record_file_path=Path("config/intervention_record.json")
)
```

**Methods:**
- `load_record() -> Dict`: Load current record from JSON file
- `save_record(record: Dict) -> bool`: Save record to JSON file
- `get_latest_emotion_timestamp() -> datetime | None`: Get timestamp of last processed emotion entry
- `update_record(emotion_entry, decision, suggestion, request_time, response_time) -> bool`: Update record with new data

**Auto-Creation:**
- Creates file with initial empty structure if missing
- Ensures parent directory exists

### Database Query Function

**Location:** `backend/src/supabase/database.py`

**Function:**
```python
query_emotional_logs_since(user_id: str, since_timestamp: datetime) -> List[Dict]
```

**Parameters:**
- `user_id`: User UUID
- `since_timestamp`: Datetime object (timezone-naive). Only entries with timestamp > since_timestamp are returned

**Returns:**
- List of emotion log dictionaries, ordered by timestamp ascending
- Each entry contains: `id`, `user_id`, `timestamp`, `emotion_label`, `confidence_score`, `emotional_score`

## intervention_record.json Structure

**Location:** `backend/config/intervention_record.json`

**Structure:**
```json
{
  "latest_emotion_entry": {
    "id": 123,
    "user_id": "uuid-string",
    "timestamp": "2025-11-09T10:30:00",
    "emotion_label": "Sad",
    "confidence_score": 0.85,
    "emotional_score": 65
  },
  "latest_decision": {
    "trigger_intervention": true,
    "confidence_score": 0.85,
    "reasoning": "Negative emotion 'Sad' detected; Confidence 0.85 >= 0.7; Time since last activity: 2233.6 minutes"
  },
  "latest_suggestion": {
    "ranked_activities": [
      {
        "activity_type": "journal",
        "rank": 1,
        "score": 1.000
      },
      {
        "activity_type": "meditation",
        "rank": 2,
        "score": 0.889
      },
      {
        "activity_type": "gratitude",
        "rank": 3,
        "score": 0.605
      },
      {
        "activity_type": "quote",
        "rank": 4,
        "score": 0.593
      }
    ],
    "reasoning": "Emotion: Sad; Time of day: evening; Top suggestion: journal (score: 1.000)"
  },
  "last_request_time": "2025-11-09T10:30:15.123456",
  "last_response_time": "2025-11-09T10:30:16.456789"
}
```

**Initial State:**
```json
{
  "latest_emotion_entry": null,
  "latest_decision": null,
  "latest_suggestion": null,
  "last_request_time": null,
  "last_response_time": null
}
```

**Update Behavior:**
- File is overwritten each time a new response is received from cloud service
- Only the latest emotion entry, decision, and suggestion are stored
- Request and response timestamps are updated with each call

## Integration with Main Orchestrator

The intervention polling service is integrated into `WellBotOrchestrator`:

**Initialization:**
- Poller is initialized in `start()` method after component initialization
- Uses `CLOUD_SERVICE_URL` from environment variables
- Poll interval: 15 minutes (configurable)

**Shutdown:**
- Poller is stopped gracefully in `stop()` method
- Ensures no polling continues after orchestrator shutdown

**Error Handling:**
- If polling service fails to start, orchestrator continues without it (logs warning)
- Polling errors are logged but don't crash the orchestrator

## Decision Engine Logic

### Kick-Start Decision

Intervention is triggered if **all** of the following conditions are met:
1. Emotion is negative: `emotion_label` in `['Sad', 'Angry', 'Fear']`
2. Confidence threshold: `confidence_score >= 0.70`
3. Time since last activity: `> 60 minutes`

**Output:**
- `trigger_intervention`: boolean
- `confidence_score`: float (0.0 to 1.0)
- `reasoning`: string (explains which conditions were met/failed)

### Activity Suggestion

Activities are ranked 1-5 based on:
1. **Base emotion mapping**: Each emotion has base weights for activities
   - Sad → journal (0.9), meditation (0.8), gratitude (0.7), quote (0.6)
   - Angry → meditation (0.9), journal (0.7), quote (0.6), gratitude (0.5)
   - Fear → gratitude (0.8), journal (0.7), meditation (0.7), quote (0.6)
   - Happy → gratitude (0.8), journal (0.7), quote (0.6), meditation (0.5)

2. **User preferences**: Adjusted by `users.prefer_intervention` JSONB field
   - Preferred activities: +20% boost
   - Non-preferred activities: -30% reduction

3. **Time of day**: Adjustments based on time period
   - Morning: gratitude (+10%), journal (-20%), meditation (-30%)
   - Afternoon: quote (+10%), meditation (-20%), journal (-30%)
   - Evening: journal (+10%), meditation (+10%), gratitude (-30%)
   - Night: journal (+10%), meditation (-20%), gratitude (-40%)

4. **Recent activity penalty**: Activities used in last 5 entries get -20% reduction

**Output:**
- `ranked_activities`: List of all activities ranked 1-5
- Each activity has: `activity_type`, `rank` (1-5), `score` (0.0-1.0)
- `reasoning`: string (explains top suggestion)

## Polling Behavior

### Startup Behavior

1. On orchestrator startup, poller initializes
2. Checks for latest emotion entry in last 24 hours to establish baseline timestamp
3. If found, uses that timestamp as "last processed"
4. If not found, starts checking from 1 minute ago
5. Runs initial check immediately

### Periodic Polling

1. Every 15 minutes (configurable), poller checks database
2. Queries for entries with `timestamp > last_processed_timestamp`
3. If new entries found:
   - Processes the most recent entry (last in list)
   - Calls cloud service with emotion data
   - Updates `intervention_record.json` with response
   - Updates `last_processed_timestamp` to the processed entry's timestamp
4. If no new entries, logs debug message and continues

### Error Handling

- Database query errors: Logged, polling continues
- Cloud service errors: Logged, record not updated
- File write errors: Logged, polling continues
- Network errors: Logged, polling continues

All errors are non-fatal - the polling service continues running even if individual operations fail.

## Testing

### Test Script

**Location:** `backend/testing/test_intervention.py`

**Tests:**
1. Database query for emotion logs
2. Cloud service request and response
3. Record saving to intervention_record.json

**Run:**
```bash
cd backend
python testing/test_intervention.py
```

**Requirements:**
- `DEV_USER_ID` set in `.env`
- `CLOUD_SERVICE_URL` set in `.env`
- Database connection configured
- Cloud service accessible

### Manual Testing

1. **Test Database Query:**
   ```python
   from src.supabase.database import query_emotional_logs_since
   from datetime import datetime, timedelta
   
   entries = query_emotional_logs_since(user_id, datetime.now() - timedelta(hours=24))
   print(f"Found {len(entries)} entries")
   ```

2. **Test Cloud Service:**
   ```python
   from src.utils.intervention_client import InterventionServiceClient
   
   client = InterventionServiceClient()
   response = client.get_suggestion(user_id, "Sad", 0.85, datetime.now())
   print(response)
   ```

3. **Test Record Manager:**
   ```python
   from src.utils.intervention_record import InterventionRecordManager
   from pathlib import Path
   
   manager = InterventionRecordManager(Path("config/intervention_record.json"))
   record = manager.load_record()
   print(record)
   ```

## Troubleshooting

### Polling Service Not Starting

**Symptoms:** No logs about intervention polling service starting

**Possible Causes:**
- `CLOUD_SERVICE_URL` not set in `.env`
- `global_config` not loaded
- Exception during initialization

**Solution:**
- Check `.env` file for `CLOUD_SERVICE_URL`
- Check logs for initialization errors
- Service continues without polling if initialization fails

### No New Entries Detected

**Symptoms:** Polling runs but no new entries found

**Possible Causes:**
- No new emotion entries in database
- Timestamp tracking issue
- Database query failing silently

**Solution:**
- Check database for new `emotional_log` entries
- Check `intervention_record.json` for `latest_emotion_entry.timestamp`
- Check logs for database query errors

### Cloud Service Calls Failing

**Symptoms:** Polling runs but cloud service calls fail

**Possible Causes:**
- Network connectivity issues
- Cloud service URL incorrect
- Cloud service down
- Timeout (30 seconds)

**Solution:**
- Verify `CLOUD_SERVICE_URL` is correct
- Test cloud service health: `GET /api/intervention/health`
- Check network connectivity
- Check cloud service logs

### Record Not Updating

**Symptoms:** Cloud service responds but `intervention_record.json` not updated

**Possible Causes:**
- File write permissions
- Disk space issues
- JSON serialization errors

**Solution:**
- Check file permissions on `config/intervention_record.json`
- Check disk space
- Check logs for write errors

## Future Enhancements

### Phase 3 (Planned)

- Activity logging integration: Log suggested activities with `trigger_type = "suggestion_flow"`
- User interaction flow: Conversation prompts for suggested activities
- Preference learning: Update user preferences based on activity completion

### Phase 4 (Planned)

- Cool-down periods: Avoid continuous suggestions when user repeatedly negative
- Outcome emotion tracking: Measure effectiveness by tracking post-intervention emotions
- Fallback behavior: Handle missing/low-confidence emotion inputs

## Related Documentation

- [Activity Logging](./ACTIVITY_LOGGING.md): How activities are logged
- [Context Management Service](../Well-Bot_cloud/.docs/context_management_service.md): Cloud service documentation

