# Well-Bot Edge Application - Architecture Overview

## High-Level System Overview

The Well-Bot Edge application is a voice-activated wellness assistant that runs on edge devices. It provides conversational AI capabilities with multiple wellness activities (journaling, meditation, gratitude, spiritual quotes, and smalltalk). The system uses wake word detection, speech-to-text, intent recognition, and text-to-speech to create a natural voice interaction experience.

### Core System Flow

```
User speaks wake word
    ↓
Wake word detected → Start listening
    ↓
Speech-to-Text processing
    ↓
Intent Recognition (Rhino)
    ↓
Route to Activity (Journal/Meditation/Gratitude/Quote/SmallTalk)
    ↓
Activity execution with conversation
    ↓
Activity completes → Return to wake word listening
```

---

## System Architecture Layers

The application is organized into four main architectural layers:

1. **Orchestration Layer** - Main entry point and system coordination
2. **Activity Layer** - Domain-specific wellness activities
3. **Component Layer** - Reusable core components (STT, TTS, LLM, etc.)
4. **Infrastructure Layer** - Database, configuration, utilities

---

## Layer 1: Orchestration Layer

### 1.1 Main Entry Point (`backend/main.py`)

**Purpose**: Central orchestrator that coordinates the entire voice pipeline and manages system state.

**Key Components**:
- `WellBotOrchestrator` class - Main system coordinator
- System state management (STARTING, LISTENING, PROCESSING, ACTIVITY_ACTIVE, SHUTTING_DOWN)
- Component lifecycle management
- Activity routing and execution
- Intervention polling integration

**Responsibilities**:
- Initialize all system components (STT, TTS, voice pipeline, activities)
- Manage state transitions between wake word listening and activity execution
- Route user intents to appropriate activities
- Handle wake word detection callbacks
- Manage intervention polling service
- Coordinate audio device management (mic muting during playback)
- Handle silence monitoring and timeouts after wake word detection

**Key Methods**:
- `start()` - Initialize and start the entire system
- `_initialize_components()` - Initialize all activities and services
- `_on_wake_detected()` - Callback when wake word is detected
- `_on_transcript_received()` - Callback when speech is transcribed
- `_route_to_activity()` - Route intent to appropriate activity
- `_restart_wakeword_detection()` - Restart wake word listening after activity
- `stop()` - Graceful shutdown

---

## Layer 2: Activity Layer

The Activity Layer contains domain-specific wellness activities. Each activity is a self-contained module that handles its own conversation flow, state management, and completion logic.

### 2.1 SmallTalk Activity (`src/activities/smalltalk.py`)

**Purpose**: General conversational interaction with the user.

**Key Features**:
- Open-ended conversation using LLM (DeepSeek)
- User context injection (persona facts, daily life context)
- Turn-taking using Google STT Voice Activity Detection
- Conversation session management
- Termination phrase detection

**Components Used**:
- `ConversationSession` - Manages conversation state
- `ConversationAudioManager` - Handles audio I/O
- `SmallTalkSession` - LLM conversation pipeline
- `UserContextInjector` - Injects user context into prompts

**Flow**:
1. Initialize conversation session
2. Loop: Capture user speech → Process with LLM → Generate response → Play TTS
3. Detect termination phrase to exit
4. Cleanup and return to orchestrator

### 2.2 Journal Activity (`src/activities/journal.py`)

**Purpose**: Guided journaling session where user speaks their thoughts.

**Key Features**:
- Continuous speech capture
- Real-time transcription display
- Minimum word threshold for saving
- Termination phrase detection
- Auto-save on timeout
- Saves to `wb_journal_entries` table

**Flow**:
1. Start recording session
2. Continuously capture and transcribe speech
3. Accumulate transcript until termination or timeout
4. Save to database if meets word threshold
5. Log activity completion status

### 2.3 Meditation Activity (`src/activities/meditation.py`)

**Purpose**: Play guided meditation audio with interruption support.

**Key Features**:
- Plays pre-recorded meditation audio files
- Supports termination phrase during playback
- Tracks completion status (completed vs. interrupted)
- Language-specific audio files (EN, CN, BM)

**Flow**:
1. Load meditation audio file for user's language
2. Start audio playback
3. Monitor for termination phrase
4. Mark as completed if audio finishes, incomplete if interrupted
5. Log activity status

### 2.4 Gratitude Activity (`src/activities/gratitude.py`)

**Purpose**: User records gratitude items via voice.

**Key Features**:
- Single gratitude item capture
- Speech-to-text transcription
- Saves to `wb_gratitude_items` table
- Completion tracking

**Flow**:
1. Prompt user to speak gratitude
2. Capture and transcribe speech
3. Save to database
4. Log activity completion

### 2.5 Spiritual Quote Activity (`src/activities/spiritual_quote.py`)

**Purpose**: Deliver spiritual quotes to the user.

**Key Features**:
- Fetches quotes from `wb_spiritual_quotes` table
- TTS delivery of quote
- Marks quote as seen
- Tracks completion

**Flow**:
1. Fetch next unseen quote from database
2. Generate TTS audio
3. Play quote to user
4. Mark quote as seen
5. Log activity completion

### 2.6 Activity Suggestion Activity (`src/activities/activity_suggestion.py`)

**Purpose**: Suggests activities when intent is unclear or intervention is triggered.

**Key Features**:
- Uses LLM to understand user intent
- Suggests appropriate activities from available set
- Can route to selected activity or fallback to smalltalk
- Handles intervention-triggered suggestions

**Flow**:
1. Receive user transcript with unclear intent
2. Use LLM to analyze and suggest activity
3. Present suggestion to user
4. Route to selected activity or smalltalk
5. Track conversation context

---

## Layer 3: Component Layer

The Component Layer provides reusable building blocks used by activities and the orchestrator.

### 3.1 Voice Pipeline Components

#### 3.1.1 Wake Word Detection (`src/components/wakeword.py`)

**Purpose**: Detects wake word using Picovoice Porcupine.

**Key Features**:
- Continuous audio monitoring
- Custom wake word model support (`.ppn` files)
- Low-latency detection
- Thread-safe operation

**Integration**: Used by `VoicePipeline` for initial activation

#### 3.1.2 Voice Pipeline (`src/components/_pipeline_wakeword.py`)

**Purpose**: Orchestrates wake word → STT → Intent recognition flow.

**Key Components**:
- `VoicePipeline` class - Main pipeline orchestrator
- Manages wake word detector, STT service, and intent recognition
- Handles callbacks for wake detection and transcript completion
- Manages microphone streaming during STT session

**Flow**:
1. Continuously monitor for wake word
2. On wake word: Start STT session
3. Stream audio to STT service
4. Process audio through intent recognition (Rhino)
5. Return final transcript + intent to orchestrator

**Key Methods**:
- `start()` - Begin wake word monitoring
- `stop()` - Stop pipeline and cleanup
- `is_active()` - Check if wake word detection is active
- `is_stt_active()` - Check if STT session is running

### 3.2 Speech Processing Components

#### 3.2.1 Speech-to-Text (`src/components/stt.py`)

**Purpose**: Converts speech audio to text using Google Cloud Speech-to-Text.

**Key Features**:
- Streaming recognition support
- Language-specific models
- Voice Activity Detection (VAD) for turn-taking
- Real-time transcription with interim results
- Final transcript callback

**Configuration**: Language code from user's language preference

#### 3.2.2 Text-to-Speech (`src/components/tts.py`)

**Purpose**: Converts text to speech audio using Google Cloud Text-to-Speech.

**Key Features**:
- Streaming synthesis support
- Language-specific voices
- Configurable audio encoding (LINEAR16, MP3, etc.)
- Sample rate and channel configuration

**Usage**: Used by activities to speak responses to users

### 3.3 Intent Recognition (`src/components/intent_recognition.py`)

**Purpose**: Classifies user intent from audio using Picovoice Rhino.

**Key Features**:
- Audio-based intent classification (no text required)
- Custom context files (`.rhn` files)
- Configurable sensitivity
- Endpoint detection (silence after command)

**Intents Supported**:
- `smalltalk` - General conversation
- `journaling` - Start journal activity
- `meditation` - Start meditation activity
- `quote` - Get spiritual quote
- `gratitude` - Record gratitude
- `termination` - End session

### 3.4 Conversation Components

#### 3.4.1 Conversation Session (`src/components/conversation_session.py`)

**Purpose**: Manages conversation state and history.

**Key Features**:
- Message history tracking
- System prompt management
- Context window management
- Conversation reset capability

**Usage**: Used by SmallTalk and Activity Suggestion activities

#### 3.4.2 Conversation Audio Manager (`src/components/conversation_audio_manager.py`)

**Purpose**: Manages audio I/O for conversation activities.

**Key Features**:
- Microphone streaming
- STT integration
- TTS playback
- Audio device management
- Turn-taking coordination

**Key Methods**:
- `capture_user_speech()` - Blocking call to capture user speech
- `play_tts_response()` - Play TTS audio
- `cleanup()` - Release audio resources

#### 3.4.3 SmallTalk Session (`src/components/_pipeline_smalltalk.py`)

**Purpose**: LLM conversation pipeline for SmallTalk activity.

**Key Features**:
- DeepSeek API integration
- Streaming response generation
- System prompt customization
- Message formatting

**Integration**: Used by `SmallTalkActivity`

### 3.5 Context & Personalization

#### 3.5.1 User Context Injector (`src/components/user_context_injector.py`)

**Purpose**: Injects user-specific context into LLM prompts.

**Key Features**:
- Fetches persona facts from database
- Fetches daily life context from database
- Formats context for LLM prompts
- Caching for performance

**Data Sources**:
- `users_context_bundle` table (persona_facts, persona_summary)

### 3.6 Audio Components

#### 3.6.1 Microphone Stream (`src/components/mic_stream.py`)

**Purpose**: Handles microphone audio input streaming.

**Key Features**:
- PyAudio-based audio capture
- Configurable sample rate and format
- Thread-safe streaming
- Audio device selection

**Usage**: Used by voice pipeline and conversation activities

### 3.7 Activity Logging (`src/components/activity_logger.py`)

**Purpose**: Logs activity start and completion to database.

**Key Features**:
- Activity start logging
- Completion status tracking
- Time-of-day context (Malaysian timezone)
- Trigger type tracking (direct_command vs. suggestion_flow)

**Database**: `wb_activity_logs` table

### 3.8 Termination Detection (`src/components/termination_phrase.py`)

**Purpose**: Detects termination phrases in user speech.

**Key Features**:
- Language-specific termination phrases
- Text normalization for matching
- Integration with STT transcripts

**Usage**: Activities use this to detect when user wants to exit

---

## Layer 4: Infrastructure Layer

### 4.1 Database Integration (`src/supabase/`)

#### 4.1.1 Supabase Client (`src/supabase/client.py`)

**Purpose**: Manages Supabase client connection.

**Key Features**:
- Service role key support
- Client initialization
- Connection pooling

#### 4.1.2 Authentication (`src/supabase/auth.py`)

**Purpose**: Handles user authentication and user ID resolution.

**Key Functions**:
- `get_current_user_id()` - Get current authenticated user ID
- User session management

#### 4.1.3 Database Operations (`src/supabase/database.py`)

**Purpose**: Database query and mutation operations.

**Key Functions**:
- `get_user_language()` - Fetch user language preference
- `log_activity_start()` - Log activity initiation
- `log_activity_completion()` - Log activity completion
- `save_journal_entry()` - Save journal entries
- `save_gratitude_item()` - Save gratitude items
- `fetch_next_quote()` - Get spiritual quotes
- `mark_quote_seen()` - Mark quotes as viewed
- `query_emotional_logs_since()` - Query emotion logs for intervention service

**Tables Used**:
- `users` - User information and preferences
- `wb_activity_logs` - Activity tracking
- `wb_journal_entries` - Journal entries
- `wb_gratitude_items` - Gratitude items
- `wb_spiritual_quotes` - Spiritual quotes
- `wb_conversation` - Conversation records
- `wb_message` - Individual messages
- `users_context_bundle` - User context (persona facts, daily life context)
- `emotional_log` - Emotion logs for intervention service

### 4.2 Configuration Management

#### 4.2.1 Config Loader (`src/utils/config_loader.py`)

**Purpose**: Loads configuration files from disk.

**Key Features**:
- Global configuration loading (`global.json`)
- Language-specific configuration loading (`en.json`, `cn.json`, `bm.json`)
- Access key management (Porcupine, Rhino)
- DeepSeek API configuration

#### 4.2.2 Config Resolver (`src/utils/config_resolver.py`)

**Purpose**: Resolves user-specific configurations with caching.

**Key Features**:
- User language resolution from database
- Configuration caching (TTL-based)
- Language code mapping (en, cn, bm)
- Global and language config aggregation

**Key Functions**:
- `resolve_language()` - Get user's language preference
- `get_global_config_for_user()` - Get global config
- `get_language_config()` - Get language-specific config

**Configuration Files**:
- `config/global.json` - Global settings (audio, wakeword, smalltalk)
- `config/en.json` - English-specific settings
- `config/cn.json` - Chinese-specific settings
- `config/bm.json` - Bahasa Malay-specific settings

### 4.3 Intervention Service Integration

#### 4.3.1 Intervention Poller (`src/utils/intervention_poller.py`)

**Purpose**: Polls database for emotion logs and requests intervention suggestions.

**Key Features**:
- Periodic polling (default: 5 minutes)
- Queries new emotion logs since last check
- Calls cloud intervention service API
- Updates `intervention_record.json` with decisions
- Thread-safe operation with start/stop control

**Integration**: Used by orchestrator to check for intervention triggers

#### 4.3.2 Intervention Client (`src/utils/intervention_client.py`)

**Purpose**: HTTP client for cloud intervention service.

**Key Features**:
- POST requests to `/api/intervention/suggest`
- Request/response handling
- Error handling and retries

#### 4.3.3 Intervention Record Manager (`src/utils/intervention_record.py`)

**Purpose**: Manages intervention record JSON file.

**Key Features**:
- Load/save intervention record
- Tracks latest decision and suggestions
- File-based persistence

**File**: `config/intervention_record.json`

---

## Data Flow Diagrams

### Main System Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    WellBotOrchestrator                      │
│  (State: LISTENING → PROCESSING → ACTIVITY_ACTIVE)          │
└─────────────────────────────────────────────────────────────┘
                            │
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                    VoicePipeline                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │ WakeWord      │→ │ STT Service  │→ │ Intent     │        │
│  │ Detector      │  │ (Google STT) │  │ Recognition│        │
│  │ (Porcupine)   │  │              │  │ (Rhino)    │        │
│  └──────────────┘  └──────────────┘  └──────────────┘        │
└─────────────────────────────────────────────────────────────┘
                            │
                            ↓ (transcript + intent)
┌─────────────────────────────────────────────────────────────┐
│                    Activity Router                          │
│  Routes to: Journal/Meditation/Gratitude/Quote/SmallTalk    │
└─────────────────────────────────────────────────────────────┘
                            │
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                    Activity Execution                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Conversation │  │ Audio        │  │ LLM          │      │
│  │ Session      │  │ Manager      │  │ (DeepSeek)   │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ↓ (activity completes)
┌─────────────────────────────────────────────────────────────┐
│                    Return to Wake Word Listening            │
└─────────────────────────────────────────────────────────────┘
```

### Activity Execution Flow (Example: SmallTalk)

```
SmallTalkActivity.run()
    ↓
Initialize ConversationSession
    ↓
Loop:
    ├─→ ConversationAudioManager.capture_user_speech()
    │       ├─→ MicStream.start()
    │       ├─→ STT Service.streaming_recognize()
    │       └─→ Wait for final transcript
    │
    ├─→ UserContextInjector.inject_context()
    │       └─→ Fetch from users_context_bundle table
    │
    ├─→ SmallTalkSession.generate_response()
    │       ├─→ Format messages with context
    │       ├─→ Call DeepSeek API
    │       └─→ Stream response
    │
    ├─→ ConversationAudioManager.play_tts_response()
    │       ├─→ TTS Service.synthesize()
    │       └─→ Play audio
    │
    └─→ Check termination phrase → Exit if detected
```

### Intervention Service Flow

```
InterventionPoller (runs every 5 minutes)
    ↓
Query emotional_log table (new entries since last check)
    ↓
If new entries found:
    ├─→ Call Cloud Service API (/api/intervention/suggest)
    │       └─→ Send emotion logs + activity history
    │
    ├─→ Receive decision + activity suggestions
    │
    └─→ Save to intervention_record.json
            └─→ {trigger_intervention: true/false, suggestions: [...]}
    ↓
On next wake word detection:
    ├─→ Check intervention_record.json
    │
    └─→ If trigger_intervention=true:
            └─→ Route to ActivitySuggestionActivity
```

---

## Configuration Structure

### Global Configuration (`config/global.json`)

```json
{
  "language_codes": {
    "stt_language_code": "en-US",
    "tts_language_code": "en-US",
    "tts_voice_name": "en-US-Chirp3-HD-Charon"
  },
  "audio_settings": {
    "stt_sample_rate": 16000,
    "tts_sample_rate": 24000
  },
  "wakeword": {
    "stt_timeout_s": 8.0,
    "nudge_timeout_seconds": 3.0,
    "silence_timeout_seconds": 8.0,
    "use_audio_files": false
  },
  "smalltalk": {
    "max_turns": 20,
    "timeout_seconds": 300
  }
}
```

### Language Configuration (`config/en.json`, `config/cn.json`, `config/bm.json`)

```json
{
  "audio_paths": {
    "wokeword_audio_path": "assets/ENGLISH/wokeword_EN_male.wav",
    "nudge_audio_path": "assets/ENGLISH/inactivity_nudge_EN_male.wav",
    "termination_audio_path": "assets/ENGLISH/termination_EN_male.wav"
  },
  "wakeword_responses": {
    "prompts": {
      "nudge": "I'm listening. What would you like to do?",
      "timeout": "I'll be here when you need me."
    }
  },
  "smalltalk": {
    "system_prompt": "...",
    "termination_phrases": ["goodbye", "see you later"]
  },
  "intents": {
    "context_path": "config/Intent/WellBot_Intent_en.rhn"
  }
}
```

---

## Key Integrations

### External Services

1. **Google Cloud Speech-to-Text**
   - Streaming recognition
   - Language-specific models
   - Voice Activity Detection

2. **Google Cloud Text-to-Speech**
   - Neural voice synthesis
   - Language-specific voices
   - Streaming support

3. **Picovoice Porcupine**
   - Wake word detection
   - Custom wake word models

4. **Picovoice Rhino**
   - Intent recognition
   - Custom context files

5. **DeepSeek API**
   - LLM for conversation
   - Reasoning model support
   - Streaming responses

6. **Supabase**
   - PostgreSQL database
   - User authentication
   - Real-time capabilities

7. **Cloud Intervention Service**
   - REST API for intervention suggestions
   - Emotion analysis
   - Activity ranking

---

## Threading Model

The application uses multiple threads for concurrent operations:

1. **Main Thread**: Orchestrator and activity coordination
2. **Wake Word Thread**: Continuous wake word monitoring (VoicePipeline)
3. **STT Thread**: Speech recognition during wake word processing
4. **Activity Thread**: Activity execution (separate thread per activity)
5. **Intervention Poller Thread**: Background polling for interventions
6. **Audio Playback Threads**: TTS playback (managed by PyAudio)

**Thread Safety**: Uses locks (`threading.Lock`) for state management and resource coordination.

---

## Error Handling & Recovery

### Component Initialization
- Validation of config files and model files
- Graceful degradation if optional components fail
- Logging of initialization failures

### Activity Execution
- Try-except blocks around activity execution
- Cleanup on failure (audio device release, resource cleanup)
- Re-initialization of activities after completion

### Audio Device Management
- Guard delays for Windows USB audio device release
- Timeout-based teardown waiting
- Force stop mechanisms with timeouts

### Database Operations
- Exception handling with fallback values
- Logging of database errors
- Graceful degradation (e.g., default language on failure)

---

## State Management

### System States (WellBotOrchestrator)

- `STARTING` - Initial system startup
- `LISTENING` - Waiting for wake word
- `PROCESSING` - Wake word detected, processing speech
- `ACTIVITY_ACTIVE` - Activity is running
- `SHUTTING_DOWN` - System shutdown in progress

### Activity States

Each activity manages its own internal state:
- `_active` - Boolean flag for activity execution
- `_initialized` - Boolean flag for component initialization
- Activity-specific state (e.g., journal transcript accumulation)

---

## Performance Considerations

### Caching
- User language preference caching (5-minute TTL)
- Configuration caching in memory
- User context caching (fetched once per activity)

### Resource Management
- Audio device release between activities
- Pipeline cleanup and recreation for wake word restart
- Thread cleanup on activity completion

### Timeouts
- STT timeout after wake word (8 seconds default)
- Silence monitoring (nudge after 3s, timeout after 8s)
- Activity-specific timeouts (e.g., smalltalk 300s)

---

## Security Considerations

### Authentication
- Supabase user authentication
- Service role keys for database access
- User ID validation

### API Keys
- Environment variable storage for sensitive keys
- No hardcoded credentials
- Secure key management

### Data Privacy
- User-specific data isolation (user_id filtering)
- Secure database connections
- No logging of sensitive user data

---

## Testing

Test files are located in `backend/testing/`:
- `test_context_processor.py` - Context processing tests
- `test_intent_recognition.py` - Intent recognition tests
- `test_intervention.py` - Intervention service tests
- `test_llm_converse.py` - LLM conversation tests
- `test_micstream_stt.py` - Microphone and STT tests
- `test_tts.py` - Text-to-speech tests
- `test_wakeword.py` - Wake word detection tests

---

## Deployment

### Docker Support
- `Dockerfile` - Multi-stage build for production
- `compose.yaml` - Docker Compose configuration
- Non-root user execution for security

### Environment Variables
Required variables (set in `.env`):
- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_SERVICE_ROLE_KEY` - Service role key
- `PORCUPINE_ACCESS_KEY` - Picovoice Porcupine access key
- `RHINO_ACCESS_KEY` - Picovoice Rhino access key
- `DEEPSEEK_API_KEY` - DeepSeek API key
- `GOOGLE_APPLICATION_CREDENTIALS` - Path to Google Cloud credentials JSON
- `CLOUD_SERVICE_URL` - Cloud intervention service URL (optional)

---

## Summary

The Well-Bot Edge application is a sophisticated voice-activated wellness assistant with a modular architecture:

- **Orchestration Layer** manages system-wide coordination and state
- **Activity Layer** provides domain-specific wellness activities
- **Component Layer** offers reusable building blocks (STT, TTS, LLM, etc.)
- **Infrastructure Layer** handles database, configuration, and utilities

The system supports multiple languages (English, Chinese, Bahasa Malay), integrates with cloud services for context and interventions, and provides a natural voice interaction experience through wake word detection, speech recognition, and conversational AI.

