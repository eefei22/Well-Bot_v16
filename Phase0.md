# Well-Bot v16 - Project Status & Structure

## 🎯 **Project Overview**
**Well-Bot Speech Processing MVP** - A real-time speech processing system with wake word detection, speech-to-text, and chat interface.

---

## 📁 **Project Structure**

```
Well-Bot_v16/
├── backend/                          # Python FastAPI Backend
│   ├── Config/                       # Configuration files
│   │   ├── STT/
│   │   │   └── GoogleCloud.json      # Google Cloud credentials
│   │   └── WakeWord/
│   │       ├── PorcupineAccessKey.txt # Porcupine access key
│   │       └── WellBot_WakeWordModel.ppn # Custom wake word model
│   ├── services/                     # Core service modules
│   │   ├── speech_service.py         # Google Cloud Speech-to-Text service
│   │   └── wakeword_listener.py      # Porcupine wake word detection
│   ├── sockets/                      # Socket.IO related files
│   ├── testing/                      # Test files
│   │   └── STT.py                    # Speech-to-text testing
│   ├── utils/                        # Utility modules
│   ├── main.py                       # Main application entry point
│   └── requirements.txt              # Python dependencies
├── frontend/                         # React Frontend
│   ├── src/
│   │   ├── App.jsx                   # Main React component
│   │   ├── App.css                   # Chat interface styles
│   │   ├── main.tsx                  # Application entry point
│   │   ├── style.css                 # Global styles
│   │   ├── counter.ts                # TypeScript counter component
│   │   └── typescript.svg            # TypeScript logo
│   ├── public/
│   │   └── vite.svg                  # Vite logo
│   ├── index.html                    # HTML template
│   ├── package.json                  # Node.js dependencies
│   ├── package-lock.json             # Dependency lock file
│   ├── tsconfig.json                 # TypeScript configuration
│   └── vite.config.js                # Vite build configuration
├── start_backend.bat                 # Backend startup script
├── start_frontend.bat                # Frontend startup script
└── CurrentStatus.md                  # This file
```

---

## 🛠️ **Frameworks & Technologies**

### **Backend Stack**
- **FastAPI** - Modern Python web framework for APIs
- **Uvicorn** - ASGI server for FastAPI
- **Socket.IO** - Real-time bidirectional communication
- **Google Cloud Speech-to-Text** - Speech recognition service
- **Porcupine** - Wake word detection engine
- **PyAudio** - Audio I/O library

### **Frontend Stack**
- **React 19** - JavaScript UI library
- **TypeScript** - Typed JavaScript
- **Vite** - Build tool and dev server
- **Socket.IO Client** - Real-time communication client

### **Audio Processing**
- **PyDub** - Audio manipulation library
- **SoundFile** - Audio file I/O
- **Librosa** - Audio analysis library
- **NumPy** - Numerical computing

---

## 📦 **Dependencies**

### **Backend Dependencies (Python)**
```
fastapi==0.104.1
uvicorn[standard]==0.24.0
python-socketio==5.10.0
google-cloud-speech==2.21.0
picovoice==3.0.1
pyaudio==0.2.14
python-multipart==0.0.6
numpy
soundfile
librosa
pydub
```

### **Frontend Dependencies (Node.js)**
```json
{
  "dependencies": {
    "@types/react": "^19.2.2",
    "@types/react-dom": "^19.2.1",
    "@vitejs/plugin-react": "^5.0.4",
    "react": "^19.2.0",
    "react-dom": "^19.2.0",
    "socket.io-client": "^4.8.1"
  },
  "devDependencies": {
    "typescript": "~5.9.3",
    "vite": "^7.1.7"
  }
}
```


