# Activity Logging - Completion Logic Documentation

## Overview

The activity logging system tracks when activities are initiated and whether they complete successfully. This document explains the completion logic for each activity type.

## Timezone Handling

All time-of-day context (`context_time_of_day`) is derived using **Malaysian timezone (UTC+8)**. The system uses `Asia/Kuala_Lumpur` timezone to ensure accurate time-of-day classification regardless of where the server is located.

## Completion Logic by Activity Type

### 1. Journal Activity (`journal`)

**Completed = True** when:
- Journal entry is successfully saved to database (`_save()` returns `True`)
- This occurs when:
  - User finishes speaking and content meets minimum word threshold
  - User says termination phrase and content is saved
  - User presses Ctrl+C and content is saved
  - Timeout occurs and accumulated content is saved

**Completed = False** when:
- No content was recorded (below word threshold)
- User skipped/terminated without saving
- Save operation failed
- Activity was interrupted before any content could be saved

**Implementation**: `backend/src/activities/journal.py` - `start()` method tracks `completed` based on `_save()` return value.

---

### 2. Gratitude Activity (`gratitude`)

**Completed = True** when:
- Gratitude item is successfully saved to database (`save_gratitude_item()` succeeds)
- User recorded gratitude text and it was persisted

**Completed = False** when:
- No gratitude text was recorded (empty or whitespace only)
- Recording failed (exception during `_record_gratitude()`)
- Save operation failed (exception during `save_gratitude_item()`)

**Implementation**: `backend/src/activities/gratitude.py` - `run()` method sets `completed = True` only after successful save.

---

### 3. Meditation Activity (`meditation`)

**Completed = True** when:
- Meditation audio playback completed fully (`_meditation_completed = True`)
- User did NOT terminate the meditation early (`_termination_detected` is not set)
- Both conditions: `was_completed = self._meditation_completed and not self._termination_detected.is_set()`

**Completed = False** when:
- User terminated meditation early (said termination phrase during playback)
- Meditation file was not found
- Activity failed to initialize or run
- Any exception occurred during meditation session

**Implementation**: `backend/src/activities/meditation.py` - `run()` method determines completion based on whether meditation finished or was stopped.

---

### 4. Spiritual Quote Activity (`quote`)

**Completed = True** when:
- Quote was successfully fetched from database
- Quote was spoken to the user via TTS
- Quote was marked as seen in database (`mark_quote_seen()` called)

**Completed = False** when:
- No quote available (`fetch_next_quote()` returns `None`)
- Activity failed to initialize
- Exception occurred during quote delivery

**Implementation**: `backend/src/activities/spiritual_quote.py` - `run()` method sets `completed = True` after quote is delivered and marked seen.

---

### 5. SmallTalk Activity (`smalltalk`)

**Note**: SmallTalk is **NOT logged** as an activity. It is considered a conversation mode, not a trackable wellness activity. Only the five activities above (journal, gratitude, todo, meditation, quote) are logged.

---

## Summary Table

| Activity | Completed = True | Completed = False |
|----------|------------------|-------------------|
| **journal** | Entry saved to DB | No content, save failed, skipped |
| **gratitude** | Item saved to DB | No text, recording failed, save failed |
| **meditation** | Audio completed fully | Terminated early, file not found, error |
| **quote** | Quote delivered & marked seen | No quote available, error |
| **todo** | (Not yet implemented) | (Not yet implemented) |

## Time-of-Day Context

The `context_time_of_day` field is derived using Malaysian timezone (UTC+8):

- **morning**: 5:00 - 11:59 (Malaysian time)
- **afternoon**: 12:00 - 16:59 (Malaysian time)
- **evening**: 17:00 - 20:59 (Malaysian time)
- **night**: 21:00 - 4:59 (Malaysian time)

This ensures consistent time-of-day classification regardless of server location.

## Database Schema

The `wb_activity_logs` table stores:
- `id`: UUID (primary key)
- `user_id`: UUID (foreign key to users)
- `type`: Activity type ('journal', 'gratitude', 'todo', 'meditation', 'quote')
- `created_at`: Timestamp with timezone (UTC)
- `trigger_type`: 'direct_command' or 'suggestion_flow'
- `completed`: Boolean (True = completed, False = skipped/terminated)
- `context_time_of_day`: 'morning', 'afternoon', 'evening', or 'night' (derived from Malaysian timezone)

