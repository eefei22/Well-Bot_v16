# Well-Bot Edge Application Features

This document provides a comprehensive overview of all features available in the Well-Bot edge application, organized by individual activities and components.

## Table of Contents
1. [Activities](#activities)
2. [Components](#components)
3. [System Features](#system-features)
4. [Database Integration](#database-integration)
5. [Configuration & Localization](#configuration--localization)

---

## Activities

### SmallTalk Activity
- **Conversational AI**: Natural language conversation using DeepSeek LLM
- **User Context Injection**: Personalized conversations using user persona and facts
- **Turn Management**: Configurable maximum turn limits with automatic session termination
- **Termination Phrases**: Detection of user termination phrases to end conversations
- **Silence Monitoring**: 
  - Nudge prompts after silence timeout
  - Final timeout with termination
- **Context Processor Integration**: Automatic notification to context processor service after conversations (when turn count >= 4)
- **Multi-language Support**: Conversations in user's preferred language (English, Chinese, Bahasa Malay)
- **Audio Feedback**: Optional audio file playback for start/end/nudge prompts
- **Database Logging**: All conversations and messages saved to database
- **Context Seeding**: Supports system message injection for conversation context

### Journal Activity
- **Voice Journaling**: Speech-to-text journal entry recording
- **Paragraph Detection**: Automatic paragraph finalization after pause thresholds
- **Termination Phrases**: User can say termination phrases to end journaling
- **Auto-save**: Automatic saving of journal entries to database
- **Content Validation**: Minimum word/character threshold validation
- **Title Generation**: Automatic timestamp-based title generation
- **Mood Tracking**: Default mood assignment for journal entries
- **Topic Extraction**: Placeholder for future topic extraction
- **Silence Monitoring**:
  - Nudge prompts during recording
  - Timeout with auto-save
- **Multi-language Support**: Supports Chinese character counting and English word counting
- **Audio Feedback**: Optional audio file playback for prompts

### Gratitude Activity
- **Voice Gratitude Recording**: Speech-to-text gratitude note capture
- **Termination Phrases**: Detection of completion phrases
- **Database Storage**: Saves gratitude items to database
- **SmallTalk Handoff**: Seamless transition to SmallTalk with gratitude context
- **Context Seeding**: Injects gratitude note into SmallTalk conversation context
- **Silence Monitoring**:
  - Nudge prompts during recording
  - Timeout handling
- **Audio Feedback**: Optional audio file playback for prompts

### Meditation Activity
- **Guided Meditation Playback**: Plays meditation audio files based on user language
- **Interruptible Playback**: Can be stopped mid-playback using termination phrases
- **Rhino Intent Detection**: Uses Rhino for termination intent recognition during playback
- **Parallel Processing**: Simultaneous audio playback and termination listening
- **Completion Detection**: Tracks whether meditation completed or was interrupted
- **Contextual SmallTalk**: Different prompts based on completion status
- **Language-specific Audio**: Automatically selects meditation file based on user language
- **SmallTalk Handoff**: Transitions to SmallTalk with meditation context

### Spiritual Quote Activity
- **Religion-aware Quotes**: Fetches quotes matching user's spiritual beliefs
- **Quote Rotation**: Tracks seen quotes to avoid repetition
- **TTS Delivery**: Speaks quotes via text-to-speech
- **Database Integration**: Marks quotes as seen in database
- **SmallTalk Handoff**: Transitions to SmallTalk with quote context
- **Context Seeding**: Injects quote into SmallTalk conversation

### Activity Suggestion Activity
- **Ranked Suggestions**: Presents activities ranked by cloud service recommendations
- **Cold Start Support**: Falls back to default activity list when no rankings available
- **Keyword Intent Matching**: Matches user speech to activity keywords
- **Activity Routing**: Routes user to selected activity or SmallTalk
- **Conversation Context**: Preserves conversation context for SmallTalk seeding
- **Silence Monitoring**:
  - Nudge prompts
  - Timeout handling
- **Multi-language Support**: Localized activity names and descriptions
- **Audio Feedback**: Optional audio file playback

### Idle Mode Activity
- **Wake Word Detection**: Continuous listening for wake word using Porcupine
- **Intent Recognition**: Keyword-based intent matching after wake word detection
- **STT Processing**: Speech-to-text transcription for intent recognition
- **Silence Monitoring**:
  - Nudge timeout after wake word
  - Final silence timeout
- **Audio Feedback**: Optional audio file playback for wake word detection and prompts
- **TTS Responses**: Text-to-speech responses for prompts
- **Intervention Triggering**: Checks intervention record for unknown intents
- **Activity Routing**: Exits when intent detected to allow main orchestrator routing

---

## Components

### Wake Word Detector (Porcupine)
- **Custom Wake Word**: Well-Bot custom wake word model support
- **Continuous Listening**: Background wake word detection
- **Audio Stream Management**: PyAudio-based microphone streaming
- **Callback System**: Triggers callbacks on wake word detection
- **Resource Management**: Proper cleanup of Porcupine and audio resources
- **Frame Processing**: Processes audio frames for wake word detection

### Speech-to-Text Service (Google Cloud Speech)
- **Streaming Recognition**: Real-time speech transcription
- **Interim Results**: Provides partial transcription during speech
- **Final Results**: Returns complete transcription
- **Multi-language Support**: Configurable language codes
- **Timeout Handling**: Configurable STT timeout
- **Single/Multi-utterance**: Configurable utterance modes

### Text-to-Speech Client (Google Cloud TTS)
- **Streaming Synthesis**: Real-time TTS audio generation
- **Multi-language Voices**: Language-specific voice selection
- **Audio Format Configuration**: Configurable sample rate, channels, encoding
- **PCM Stream Playback**: Direct PCM audio stream playback

### Intent Recognition (Rhino)
- **Rhino Integration**: Audio-based intent recognition (bypasses STT)
- **Context-based Intents**: Uses Rhino context files for intent classification
- **Frame Processing**: Processes audio frames directly
- **Inference Management**: Handles inference results and resets
- **Confidence Scores**: Intent confidence reporting

### Keyword Intent Matcher
- **Language-specific Intents**: Loads intents based on user language
- **Normalized Matching**: Text normalization for robust keyword matching
- **Multiple Matching Strategies**: Various matching approaches for reliability
- **Confidence Reporting**: Returns intent with confidence scores

### Conversation Audio Manager
- **Microphone Management**: Centralized microphone stream coordination
- **Audio Playback**: Unified audio file and TTS stream playback
- **Microphone Muting**: Automatic mic muting during audio playback
- **Silence Monitoring**:
  - Configurable nudge timeout
  - Configurable silence timeout
  - Pre/post delay for nudge audio to prevent STT pickup
- **State Management**: Tracks audio playback and microphone states
- **Resource Cleanup**: Proper PyAudio resource management

### Conversation Session
- **Session Lifecycle**: Start/stop conversation sessions
- **Turn Counting**: Tracks conversation turns with configurable limits
- **Database Integration**: Creates and manages conversation records
- **Message Storage**: Saves user and assistant messages to database
- **Emoji Stripping**: Removes emojis from assistant responses
- **Language Support**: Language code tracking for messages

### SmallTalk Session
- **LLM Integration**: DeepSeek LLM streaming chat
- **Message History**: Maintains conversation context
- **System Prompts**: Configurable system prompts
- **Termination Detection**: Checks for termination phrases
- **STT Integration**: Captures user speech via STT
- **TTS Integration**: Streams LLM responses to TTS

### LLM Client (DeepSeek)
- **Streaming Chat**: Real-time token streaming from LLM
- **Non-streaming Chat**: Standard chat completion
- **Message History**: Maintains conversation context
- **Error Handling**: Robust error handling and recovery

### User Context Injector
- **Database Context Fetching**: Retrieves user persona and facts from database
- **Local File Fallback**: Falls back to local file if database unavailable
- **Context Caching**: Saves context to local file for offline use
- **System Message Injection**: Injects persona and facts as system messages
- **Graceful Degradation**: Continues without context if unavailable

### Termination Phrase Detector
- **Normalized Matching**: Robust text normalization for phrase matching
- **Multiple Matching Strategies**: Exact match, prefix match, substring match
- **Active State Checking**: Optional active state requirement
- **Exception-based**: Raises exceptions for termination detection

### Microphone Stream
- **Audio Capture**: Continuous microphone audio streaming
- **Buffered Streaming**: Queue-based audio chunk buffering
- **Mute/Unmute**: Microphone muting capability
- **Threading**: Background thread for audio capture
- **Resource Management**: Proper PyAudio cleanup
- **Configurable Parameters**: Sample rate and chunk size configuration

### Activity Logger
- **Time-of-day Context**: Derives time-of-day context (morning/afternoon/evening/night)
- **Malaysian Timezone**: Uses Asia/Kuala_Lumpur timezone
- **Query Logic**: Provides query parameters for activity log queries

### Intervention Poller
- **Periodic Polling**: Configurable polling interval (default: 15 minutes)
- **Emotion Log Monitoring**: Checks for new emotion log entries
- **Cloud Service Integration**: Requests intervention suggestions from cloud service
- **Record Management**: Updates intervention_record.json with decisions and suggestions
- **Timestamp Tracking**: Tracks last processed entries to avoid duplicates
- **Automatic Start/Stop**: Starts when system enters LISTENING state, stops during activities

---

## System Features

### Orchestration
- **State Management**: System states (STARTING, LISTENING, PROCESSING, ACTIVITY_ACTIVE, SHUTTING_DOWN)
- **Activity Routing**: Routes intents to appropriate activities
- **Pipeline Management**: Manages wake word pipeline lifecycle
- **Resource Cleanup**: Ensures proper cleanup between activities
- **Error Handling**: Comprehensive error handling and recovery

### Wake Word Pipeline
- **Wake Word Detection**: Continuous listening for wake word
- **STT Session**: Starts STT session after wake word detection
- **Intent Classification**: Classifies user intent from transcript
- **Silence Monitoring**:
  - Nudge timeout after wake word
  - Final silence timeout
- **Audio Feedback**: Optional audio file playback for prompts
- **TTS Responses**: Text-to-speech responses for prompts

### Configuration Management
- **User-specific Config**: Loads configuration based on user ID
- **Language Resolution**: Resolves user language preference
- **Config Caching**: Caches configuration for performance
- **Multi-language Configs**: Separate config files per language (en, cn, bm)
- **Global Config**: Shared numerical and system settings

### Audio System
- **Multi-format Playback**: Supports WAV audio file playback
- **Platform-specific**: Windows PowerShell fallback for audio playback
- **PyAudio Integration**: Native PyAudio for TTS stream playback
- **Microphone Coordination**: Automatic mic muting during playback
- **Delay Management**: Pre/post delays for nudge audio to prevent STT pickup

### Multi-language Support
- **Language Detection**: Automatic language resolution from user preferences
- **Localized Prompts**: Language-specific prompts and messages
- **Localized Audio**: Language-specific audio file paths
- **TTS Language Selection**: Language-specific TTS voice selection
- **STT Language Selection**: Language-specific STT language codes

---

## Database Integration

### User Management
- **User Authentication**: Supabase authentication integration
- **User Profile**: User information retrieval
- **Language Preferences**: User language preference storage
- **Religion Preferences**: User spiritual belief tracking

### Conversation Management
- **Conversation Creation**: Creates conversation records
- **Message Storage**: Saves user and assistant messages
- **Conversation Ending**: Marks conversations as ended
- **Turn Tracking**: Tracks conversation turns

### Activity Logging
- **Activity Start Logging**: Logs activity start events
- **Intervention Logs**: Tracks intervention-triggered activities
- **Emotion Logs**: Tracks emotion-triggered activities
- **Duration Tracking**: Optional activity duration tracking

### Journal Management
- **Journal Entry Storage**: Saves journal entries with title, body, mood
- **Journal Retrieval**: Queries journal entries
- **Draft Support**: Draft journal entry support
- **Topic Tracking**: Topic array storage

### Gratitude Management
- **Gratitude Item Storage**: Saves gratitude notes
- **Gratitude Retrieval**: Queries gratitude items

### Quote Management
- **Quote Fetching**: Fetches religion-aware quotes
- **Quote Tracking**: Tracks seen quotes per user
- **Quote Rotation**: Ensures quote variety

### Context Bundle
- **Persona Summary**: Stores user persona summaries
- **Facts Storage**: Stores user facts
- **Version Tracking**: Tracks context bundle versions
- **Local Caching**: Local file caching for offline access

### Emotional Logs
- **Emotion Entry Querying**: Queries emotional log entries
- **Timestamp Filtering**: Filters by timestamp ranges
- **Emotion Label Tracking**: Tracks emotion labels and confidence scores

---

## Configuration & Localization

### Configuration Files
- **Global Config**: System-wide numerical settings (global.json)
- **Language Configs**: Per-language configuration files (en.json, cn.json, bm.json)
- **Intent Configs**: Language-specific intent keyword files (intents_en.json, intents_cn.json, intents_bm.json)
- **Intervention Record**: Intervention decision and suggestion storage (intervention_record.json)
- **User Persona**: Local user persona fallback (user_persona.json)

### Configurable Features
- **Timeouts**: Configurable silence, nudge, and STT timeouts
- **Audio Settings**: Configurable sample rates, channels, encoding
- **Turn Limits**: Configurable maximum conversation turns
- **Language Codes**: Configurable STT and TTS language codes
- **Audio File Paths**: Configurable audio file paths per language
- **Prompts**: Localized prompts for all activities
- **Termination Phrases**: Configurable termination phrases per activity

### Localization Support
- **Three Languages**: English, Chinese (Mandarin), Bahasa Malay
- **Localized Audio**: Language-specific audio files
- **Localized Prompts**: Language-specific text prompts
- **Localized Activity Names**: Translated activity names and descriptions
- **Cultural Adaptation**: Religion-aware content (quotes)

---

## Summary

The Well-Bot edge application provides a comprehensive voice-based wellness assistant with:

- **7 Core Activities**: SmallTalk, Journal, Gratitude, Meditation, Spiritual Quote, Activity Suggestion, Idle Mode
- **14+ Core Components**: Wake word, STT, TTS, Intent recognition, Audio management, Session management, LLM integration, Context injection, Microphone stream, and more
- **Multi-language Support**: English, Chinese, Bahasa Malay
- **Database Integration**: Comprehensive Supabase integration for all data storage
- **Cloud Integration**: Intervention polling and cloud service communication
- **Robust Audio System**: Coordinated microphone and audio playback management
- **Silence Monitoring**: Nudge and timeout features across activities
- **Context Awareness**: User persona and facts injection for personalized conversations

All features are designed to work together seamlessly, with proper resource management, error handling, and graceful degradation when services are unavailable.
