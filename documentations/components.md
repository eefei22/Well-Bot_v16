# Well-Bot v16 Component Documentation

## Overview

Well-Bot is a voice-activated conversational AI system that enables natural language interactions through a comprehensive pipeline of speech processing, intent recognition, and activity management. The system follows a modular, component-based architecture with clear separation of concerns across backend processing, frontend user interface, and real-time communication layers.

## System Architecture

The system consists of three main layers:

1. **Backend Layer** - Python-based voice processing pipeline and business logic
2. **Frontend Layer** - React-based user interface
3. **Communication Layer** - Socket.IO for real-time bidirectional communication

---

## Backend Components

The backend is organized into four primary modules:

### 1. Activities Module (`backend/src/activities/`)

**Purpose**: Contains high-level activity implementations that orchestrate multiple components to deliver specific user experiences.

#### SmallTalk Activity
- **File**: `smalltalk.py`
- **Description**: Manages conversational interactions with users, coordinating speech recognition, natural language processing, and speech synthesis to enable fluid conversations.
- **Functionality**:
  - Initializes and manages conversation lifecycle
  - Coordinates microphone input, speech-to-text processing, and text-to-speech output
  - Handles conversation state management (active, inactive, terminating)
  - Provides re-initialization capabilities for repeated use
  - Integrates with SmallTalkManager for LLM-based conversation handling

### 2. Components Module (`backend/src/components/`)

**Purpose**: Provides reusable, low-level building blocks for voice processing and AI capabilities.

#### Wake Word Detection (`wakeword.py`)
- **Description**: Implements continuous listening for custom wake words using Picovoice's Porcupine engine.
- **Functionality**:
  - Monitors audio input for wake word detection
  - Supports custom wake word models (.ppn files)
  - Manages audio stream lifecycle
  - Triggers callbacks when wake words are detected
  - Handles Porcupine engine initialization and cleanup

#### Speech-to-Text Service (`stt.py`)
- **Description**: Converts spoken audio to text using Google Cloud Speech API.
- **Functionality**:
  - Provides streaming speech recognition with interim and final results
  - Supports multiple languages and sample rates
  - Handles audio streaming from microphone or audio generators
  - Configurable recognition parameters (punctuation, profanity filtering, etc.)
  - Provides both streaming and file-based recognition

#### Text-to-Speech Service (`tts.py`)
- **Description**: Converts text to natural-sounding speech using Google Cloud Text-to-Speech API.
- **Functionality**:
  - Supports streaming and batch synthesis
  - Configurable voice selection and audio parameters
  - Outputs PCM audio format
  - Handles audio chunk generation for real-time playback
  - Provides WAV file generation from PCM chunks

#### Intent Recognition (`intent.py`)
- **Description**: Classifies user utterances into predefined intent categories using spaCy NLP models.
- **Functionality**:
  - Loads trained spaCy text classification models
  - Predicts user intent from transcribed speech
  - Returns confidence scores for each intent category
  - Supports multiple intent types (small_talk, todo_add, journal_write)

#### LLM Client (`llm.py`)
- **Description**: Provides interface to DeepSeek language model for generating conversational responses.
- **Functionality**:
  - Supports streaming and non-streaming chat completions
  - Handles OpenAI-compatible API communication
  - Manages conversation context with message history
  - Provides token-by-token streaming for responsive interactions

#### Microphone Stream (`mic_stream.py`)
- **Description**: Manages audio input from system microphone.
- **Functionality**:
  - Captures audio from default microphone device
  - Provides audio chunks in configurable formats
  - Manages PyAudio stream lifecycle
  - Supports configurable sample rates and buffer sizes

#### Voice Pipeline - Wake Word (`_pipeline_wakeword.py`)
- **Description**: Orchestrates the complete wake word detection and post-wake processing pipeline.
- **Functionality**:
  - Combines wake word detection with STT and intent recognition
  - Manages state transitions (listening → processing → complete)
  - Coordinates callbacks for wake detection and transcript results
  - Handles pipeline lifecycle and cleanup

#### Voice Pipeline - SmallTalk (`_pipeline_smalltalk.py`)
- **Description**: Implements the conversation session management for SmallTalk activity.
- **Functionality**:
  - Manages turn-based conversation flow
  - Integrates STT, LLM, and TTS for complete conversation loop
  - Handles termination phrase detection
  - Manages silence timeouts and inactivity nudges
  - Controls conversation database logging

### 3. Managers Module (`backend/src/managers/`)

**Purpose**: Provides high-level business logic coordinators that orchestrate multiple components.

#### SmallTalk Manager
- **File**: `smalltalk_manager.py`
- **Description**: Central coordinator for SmallTalk conversation sessions, managing the complete conversation lifecycle.
- **Functionality**:
  - Creates and manages conversation sessions
  - Coordinates microphone input, speech recognition, LLM processing, and speech output
  - Handles timeout management (silence and nudge timeouts)
  - Manages audio playback for system notifications (nudges, termination, start/end sounds)
  - Configures TTS voice and language settings
  - Integrates with Supabase for conversation persistence
  - Supports multiple languages through configuration

### 4. Supabase Module (`backend/src/supabase/`)

**Purpose**: Provides database connectivity and data persistence for user conversations and messages.

#### Database Client (`client.py`)
- **Description**: Initializes and manages connections to Supabase backend.
- **Functionality**:
  - Provides service role and authenticated client access
  - Loads credentials from environment configuration
  - Manages connection lifecycle

#### Authentication (`auth.py`)
- **Description**: Placeholder for future authentication functionality.
- **Current State**: Empty file - authentication features not yet implemented
- **Planned Functionality**:
  - User login and session management
  - Authentication state handling
  - User identity management for database operations

#### Database Operations (`database.py`)
- **Description**: Provides high-level database operations for conversations and messages.
- **Functionality**:
  - Creates and manages conversation records
  - Stores and retrieves user messages
  - Tracks conversation metadata and timestamps
  - Associates messages with conversations and users
  - Provides conversation history retrieval

### 5. Orchestration (`backend/main.py`)

**Purpose**: Main entry point that coordinates the entire system workflow.

#### WellBotOrchestrator
- **Description**: Central coordinator that manages system state and component lifecycle.
- **Functionality**:
  - Initializes all system components (STT, wake word detection, activities)
  - Manages system state machine (starting, listening, processing, activity_active, shutting_down)
  - Coordinates workflow: Wake Word → Speech Recognition → Intent Classification → Activity Execution
  - Routes user intents to appropriate activities
  - Handles activity lifecycle (start, run, cleanup, re-initialization)
  - Manages component cleanup and resource release
  - Provides graceful shutdown and error handling

---

## Frontend Components

The frontend is built with React and TypeScript, providing a web-based user interface.

### Location: `frontend/src/`

#### Main Application (`App.jsx`)
- **Description**: Root React component that manages the user interface and Socket.IO communication.
- **Functionality**:
  - Establishes Socket.IO connection to backend server
  - Manages UI state (connection status, recording state, transcription)
  - Handles user interactions (text input, voice recording controls)
  - Displays real-time messages and transcriptions
  - Provides visual feedback for system states
  - Manages audio recording and streaming to backend

#### UI Components
- **Chat Interface**: Displays conversation history with message bubbles
- **Control Panel**: Provides buttons for recording, wake word simulation, and text input
- **Status Indicators**: Shows connection status, recording state, and wake word activation
- **Transcription Display**: Shows real-time interim and final transcriptions

#### Entry Point (`main.tsx`)
- **Description**: Application entry point that renders the React app.
- **Functionality**:
  - Initializes React application
  - Mounts root component to DOM
  - Sets up global styles and configurations

---

## Communication Layer

### Socket.IO Integration

**Purpose**: Enables real-time bidirectional communication between frontend and backend.

#### Backend Socket.IO Server
- **Technology**: Python Socket.IO with FastAPI/ASGI integration
- **Functionality**:
  - Listens for client connections
  - Receives audio chunks from frontend
  - Emits wake word detection events
  - Streams transcription results (interim and final)
  - Sends system status updates
  - Provides event-based architecture for asynchronous operations

#### Frontend Socket.IO Client
- **Technology**: socket.io-client JavaScript library
- **Functionality**:
  - Connects to backend server
  - Sends audio data for processing
  - Receives real-time transcription updates
  - Handles system notifications and events
  - Manages connection lifecycle and reconnection

#### Event Types
- `connect` / `disconnect`: Connection state events
- `wakeword_detected`: Wake word detection notification
- `start_recording` / `stop_recording`: Recording control
- `audio_chunk`: Audio data streaming
- `transcription_interim` / `transcription_final`: STT results
- `message_response`: System responses
- `simulate_wake_word`: Testing utility

---

## Configuration and Assets

### Configuration Files
- **Location**: `backend/config/` (implied from code references)
- **Purpose**: Stores system configuration and credentials
- **Components**:
  - Wake Word models and API keys (`WakeWord/`)
  - STT credentials (`STT/GoogleCloud.json`)
  - Intent classifier models (`intent_classifier/`)
  - LLM configuration (`LLM/deepseek.json`, `smalltalk_instructions.json`)
  - User preferences (`user_preference/preference.json`)

### Assets
- **Location**: `backend/assets/`
- **Purpose**: Stores audio files for system notifications and multi-language support
- **Structure**:
  - `ENGLISH/`: English language audio notifications
  - `BAHASA/`: Bahasa language audio notifications
  - `MANDARIN/`: Mandarin language audio notifications
  - Audio files for nudges, termination, start/end notifications

---

## Component Dependencies and Relationships

### Primary Data Flow

```
User Speech Input
    ↓
Microphone Stream (mic_stream.py)
    ↓
Wake Word Detection (wakeword.py) → Orchestrator (main.py)
    ↓
Speech-to-Text (stt.py)
    ↓
Intent Recognition (intent.py)
    ↓
Activity Routing (orchestrator)
    ↓
SmallTalk Activity (smalltalk.py) → SmallTalk Manager (smalltalk_manager.py)
    ↓
LLM Processing (llm.py) → DeepSeek API
    ↓
Text-to-Speech (tts.py)
    ↓
Audio Output to User
```

### Database Integration Flow

```
Conversation Start
    ↓
Database (database.py) → Supabase (wb_conversation table)
    ↓
User Messages & System Responses
    ↓
Database (database.py) → Supabase (wb_message table)
    ↓
Conversation End (timestamp update)
```

### Frontend-Backend Communication Flow

```
Frontend (App.jsx)
    ↓ Socket.IO
Backend Server
    ↓
Audio Processing Pipeline
    ↓ Socket.IO events
Frontend (real-time updates)
```

---

## Technology Stack

### Backend
- **Language**: Python 3.12
- **Core Libraries**:
  - `picovoice` (Porcupine) - Wake word detection
  - `google-cloud-speech` - Speech-to-Text
  - `google-cloud-texttospeech` - Text-to-Speech
  - `spacy` - Intent classification
  - `httpx` - HTTP client for LLM API
  - `pyaudio` - Audio I/O
  - `supabase` - Database client
  - `python-socketio` - Real-time communication
  - `fastapi` / `uvicorn` - Web server framework

### Frontend
- **Framework**: React 19.2.0
- **Language**: TypeScript / JavaScript
- **Build Tool**: Vite 7.1.7
- **Libraries**:
  - `socket.io-client` - Real-time communication
  - `react-dom` - React rendering

### External Services
- **Picovoice**: Wake word detection service
- **Google Cloud Speech API**: Speech recognition
- **Google Cloud Text-to-Speech API**: Speech synthesis
- **DeepSeek API**: Large language model
- **Supabase**: PostgreSQL database and authentication

---

## Deployment and Execution

### Backend
- **Entry Point**: `backend/main.py`
- **Execution**: `python backend/main.py`
- **Script**: `start_backend.bat` (Windows)

### Frontend
- **Entry Point**: `frontend/src/main.tsx`
- **Development**: `npm run dev` (Vite dev server)
- **Script**: `start_frontend.bat` (Windows)
- **Port**: Default HTTP port (typically 5173 for Vite)

### System Requirements
- Python 3.12+ with virtual environment
- Node.js for frontend build
- Microphone and audio output devices
- Internet connectivity for cloud services
- Valid API credentials for Google Cloud and DeepSeek

---

## System States and Lifecycle

### Orchestrator States
1. **STARTING**: System initialization in progress
2. **LISTENING**: Actively listening for wake word
3. **PROCESSING**: Processing speech after wake word detection
4. **ACTIVITY_ACTIVE**: Running a user activity (e.g., SmallTalk)
5. **SHUTTING_DOWN**: Graceful shutdown in progress

### Activity Lifecycle
1. **Initialize**: Load configurations and create component instances
2. **Start**: Begin activity execution (e.g., start conversation)
3. **Run**: Execute activity logic (conversation loop, turns, etc.)
4. **Cleanup**: Release resources (close audio streams, save data)
5. **Re-initialize**: Prepare for next execution (reset state, recreate components)

---

## Extension Points

### Adding New Activities
1. Create new activity class in `backend/src/activities/`
2. Implement required lifecycle methods (initialize, start, run, cleanup)
3. Register activity in orchestrator's routing logic
4. Add corresponding intent to intent classifier training data

### Adding New Intents
1. Update spaCy model training data with new intent examples
2. Retrain intent classifier model
3. Add intent handling logic in orchestrator
4. Create or route to appropriate activity

### Multi-language Support
1. Add language-specific audio files to `backend/assets/[LANGUAGE]/`
2. Update configuration files with language-specific settings
3. Configure TTS voice and STT language codes
4. Update LLM system prompts for target language

---

## Summary

Well-Bot v16 is a sophisticated voice-activated AI system built on a modular, component-based architecture. The system separates concerns across distinct layers:

- **Backend components** handle low-level voice processing, AI inference, and data persistence
- **Activities and managers** coordinate components to deliver high-level user experiences
- **Frontend interface** provides visual feedback and alternative input methods
- **Communication layer** enables real-time interaction between UI and processing pipeline

The architecture supports extensibility through clearly defined interfaces, configuration-driven behavior, and separation of concerns. New activities, intents, and language support can be added without modifying core components, making the system maintainable and scalable.
