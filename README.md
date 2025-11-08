## Running the Project with Docker

This project provides Docker and Docker Compose configurations to run the Python backend in a reproducible environment.

### Project-Specific Docker Requirements
- **Python Version:** 3.13 (as specified in the Dockerfile)
- **Dependencies:** Installed from `backend/requirements.txt` inside a Python virtual environment (`venv`).

### Environment Variables
- No environment variables are strictly required by default. If you use a `.env` file for configuration, uncomment the `env_file` line in the `docker-compose.yml` and place your `.env` file in the `backend/` directory.

### Build and Run Instructions
1. **Build and start the backend service:**
   ```sh
   docker compose up --build
   ```
   This will build the image using the provided Dockerfile and start the backend service.

2. **Stopping the service:**
   ```sh
   docker compose down
   ```

### Special Configuration
- The backend runs as a non-root user (`backenduser`) for improved security.
- All Python dependencies are installed in a virtual environment, isolated from the system Python.
- If you need to connect to external services (e.g., Postgres, Redis), uncomment and configure the relevant sections in `docker-compose.yml`.

### Ports
- **No ports are exposed by default.**
  - If your backend listens on a port (e.g., 8000), uncomment and configure the `ports` section in `docker-compose.yml` and the `EXPOSE` line in the Dockerfile.

### Additional Notes
- If you add database or cache services, also uncomment the `depends_on` and `networks` sections as needed.
- For environment-specific configuration, use a `.env` file and reference it in the compose file.

---
```

Well-Bot_v16/
├── 📄 compose.yaml                    # Docker Compose configuration
├── 📄 Dockerfile                     # Multi-stage Docker build
├── 📄 README.md                      # Project documentation
├── 📄 start_backend.bat              # Windows backend startup script
├── 📄 start_frontend.bat             # Windows frontend startup script
├──📁 venv/                          # Python virtual environment
└── backend/
	├── 📄 main.py                        # Main application entry point (624 lines)
	├── 📄 requirements.txt               # Python dependencies
	├── 📄 .env                           # Environment variables 
	├── 📁 assets/                        # Multi-language audio assets
	│   ├── 📁 BAHASA/                    # Malay audio files (7 files)
	│   ├── 📁 ENGLISH/                   # English audio files (11 files)
	│   └── 📁 MANDARIN/                  # Chinese audio files (7 files)
	├── 📁 config/                        # Configuration files
   │   ├── 📄 intents.json               # Intent recognition config
   │   ├── 📄 preference.json            # User preferences
   │   ├── 📄 smalltalk_instructions.json # Smalltalk behavior config
   │   ├── 📁 WakeWord/
   │   │   └── 📄 WellBot_WakeWordModel.ppn # Porcupine wake word model
   │   └── 📄 wakeword_config.json       # Wake word configuration
   ├── 📁 src/                           # Source code modules
   │   ├── 📁 activities/                # Activity implementations
   │   │   └── 📄 smalltalk.py           # Smalltalk activity handler
   │   ├── 📁 components/                # Core system components
   │   │   ├── 📄 conversation_audio_manager.py # Audio session management
   │   │   ├── 📄 conversation_session.py # Conversation state management
   │   │   ├── 📄 intent_detection.py    # Intent classification
   │   │   ├── 📄 llm.py                 # Large Language Model integration
   │   │   ├── 📄 mic_stream.py          # Microphone input handling
   │   │   ├── 📄 stt.py                 # Speech-to-Text processing
   │   │   ├── 📄 tts.py                 # Text-to-Speech synthesis
   │   │   └── 📄 wakeword.py            # Wake word detection
   │   ├── 📄 config_loader.py           # Configuration management
   │   └── 📁 supabase/                  # Database integration
   │       ├── 📄 auth.py                # Authentication handling
   │       ├── 📄 client.py              # Supabase client setup
   │       ├── 📄 database.py            # Database operations
   │       └── 📄 schemas.sql            # Database schema
   └── 📁 testing/                       # Test suite
       ├── 📄 debug_audio_playback.py    # Audio debugging
       ├── 📄 smalltalk_manager.py       # Smalltalk testing
       ├── 📄 test_activity_reinit.py    # Activity reinitialization tests
       ├── 📄 test_audio_fix.py          # Audio system tests
       ├── 📄 test_complete_fixes.py     # Comprehensive tests
       ├── 📄 test_tts.py                # TTS testing
       └── 📄 websocket.py               # WebSocket testing

```