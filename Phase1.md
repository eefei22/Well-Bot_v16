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
│   ├── src/                          # Core source modules
│   │   ├── speech.py                 # Google Cloud Speech-to-Text service
│   │   └── wakeword/                 # Wake word detection module
│   │       ├── __init__.py           # Package initialization
│   │       ├── wakeword.py           # WakeWordDetector class implementation
│   │       ├── unit_test.py          # Real-time wake word testing
│   │       └── _manual.md            # Wake word service documentation
│   ├── testing/                      # Test files
│   │   └── STT.py                    # Speech-to-text testing
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
├── porcupine/                        # Picovoice Porcupine SDK
│   └── binding/python/               # Python bindings for wake word detection
├── start_backend.bat                 # Backend startup script
├── start_frontend.bat                # Frontend startup script
└── Phase1.md                         # This file
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

## 🎯 **NEW FEATURE: Wake Word Detection System**

### **🚀 Implementation Overview**
The Well-Bot now features a complete wake word detection system using Picovoice's Porcupine engine. This allows the bot to activate only when specific wake words are spoken, providing hands-free interaction.

### **🔧 Core Components**

#### **WakeWordDetector Class** (`backend/src/wakeword/wakeword.py`)
- **Custom Wake Word Support**: Uses your custom `WellBot_WakeWordModel.ppn` file
- **Built-in Keywords**: Can detect built-in keywords like 'picovoice', 'bumblebee', etc.
- **Real-time Processing**: Processes audio frames in real-time with 16kHz sample rate
- **Error Handling**: Comprehensive error handling and logging
- **Resource Management**: Proper cleanup of resources

#### **Key Features:**
- ✅ **Frame-based Processing**: Processes 512-sample audio frames
- ✅ **Multi-keyword Support**: Can detect multiple wake words simultaneously
- ✅ **Factory Pattern**: Easy instantiation with `create_wake_word_detector()`
- ✅ **Configuration Management**: Reads access keys and model files from Config directory
- ✅ **Thread-safe**: Safe for use in multi-threaded environments

### **🧪 Testing & Validation**

#### **Unit Test System** (`backend/src/wakeword/unit_test.py`)
The comprehensive unit test provides:

- **Real-time Audio Capture**: Uses PyAudio to capture live microphone input
- **Interactive Testing**: Provides clear feedback when wake words are detected
- **Performance Metrics**: Tracks frame processing and detection counts
- **Error Simulation**: Tests various error conditions and edge cases
- **Resource Cleanup**: Ensures proper cleanup of audio resources

#### **Test Capabilities:**
- 🎤 **Live Microphone Testing**: Real-time audio capture and processing
- 📊 **Detection Statistics**: Counts total detections and frames processed
- ⏱️ **Performance Monitoring**: Tracks processing speed and accuracy
- 🔄 **Continuous Operation**: Runs until manually stopped (Ctrl+C)
- ✅ **Success Validation**: Confirms wake word detection is working correctly

### **📋 Usage Example**
```python
from wakeword import create_wake_word_detector

# Create detector with custom wake word
detector = create_wake_word_detector(
    access_key_file="Config/WakeWord/PorcupineAccessKey.txt",
    custom_keyword_file="Config/WakeWord/WellBot_WakeWordModel.ppn"
)

# Initialize the detector
if detector.initialize():
    # Process audio frames continuously
    audio_frame = get_audio_frame()  # Your audio input
    keyword_index = detector.process_audio_frame(audio_frame)
    
    if keyword_index >= 0:
        print("🎯 Wake word detected!")
    
    # Cleanup when done
    detector.cleanup()
```

### **⚙️ Technical Specifications**
- **Sample Rate**: 16,000 Hz
- **Audio Format**: 16-bit PCM
- **Channels**: Mono (single channel)
- **Frame Length**: 512 samples per frame
- **Processing Latency**: < 100ms per frame
- **Memory Usage**: Minimal footprint with efficient resource management

### **🔗 Integration Points**
- **Speech Service**: Ready for integration with `speech.py`
- **Socket.IO**: Can trigger real-time events when wake words are detected
- **Frontend**: Can provide visual feedback when wake word is detected
- **Main Application**: Seamlessly integrates with FastAPI backend

---

## 📦 **Dependencies**

### **Backend Dependencies (Python)**
```
fastapi==0.104.1
uvicorn[standard]==0.24.0
python-socketio==5.10.0
google-cloud-speech==2.21.0
picovoice==3.0.1              # Wake word detection engine
pvporcupine                    # Porcupine wake word detection
pyaudio==0.2.14               # Audio I/O for microphone capture
python-multipart==0.0.6
numpy                          # Numerical computing
soundfile                      # Audio file I/O
librosa                        # Audio analysis
pydub                          # Audio manipulation
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

---

## 🧪 **Wake Word Test Results & Capabilities**

### **Test Execution**
To run the wake word detection test:
```powershell
cd backend\src\wakeword
python unit_test.py
```

### **Expected Test Output**
```
============================================================
🧪 WAKE WORD DETECTION UNIT TEST
============================================================
This test will:
✅ Initialize the wake word detector
✅ Start microphone capture
✅ Listen for your custom wake word
✅ Provide feedback when wake word is detected
✅ Ignore other speech (no feedback)
============================================================

🔧 Test 1: Creating wake word detector...
✅ Wake word detector created successfully

🔧 Test 2: Initializing wake word detector...
✅ Wake word detector initialized successfully
   📊 Frame length: 512
   📊 Sample rate: 16000

🔧 Test 3: Starting microphone capture...
🎤 Microphone started - listening for wake word...
✅ Microphone started successfully

🔧 Test 4: Real-time wake word detection
========================================
🎤 LISTENING FOR WAKE WORD...
📢 Say your wake word to test detection
📢 Say other words to test rejection
⏹️  Press Ctrl+C to stop the test
========================================

🔄 Listening... (50 frames processed)
🔄 Listening... (100 frames processed)

🎯 WAKE WORD DETECTED! (Detection #1)
   📍 Keyword index: 0
   ⏰ Time: 14:32:15
   ✅ Test PASSED - Wake word correctly identified
========================================

⏹️  Test stopped by user
📊 Total frames processed: 1250
🎯 Total detections: 3
✅ Test PASSED - Wake word detection working correctly

🧹 Cleaning up resources...
🎤 Microphone stopped
✅ Cleanup completed

============================================================
🎉 WAKE WORD DETECTION TEST COMPLETED
============================================================
```

### **Test Validation Points**
- ✅ **Initialization**: Wake word detector creates and initializes successfully
- ✅ **Audio Capture**: Microphone starts and captures audio frames correctly
- ✅ **Frame Processing**: Processes 512-sample frames at 16kHz sample rate
- ✅ **Wake Word Detection**: Correctly identifies custom wake word
- ✅ **False Positive Rejection**: Ignores non-wake word speech
- ✅ **Resource Management**: Properly cleans up audio resources
- ✅ **Performance**: Maintains real-time processing without lag

### **Performance Metrics**
- **Frame Rate**: ~31.25 frames per second (512 samples @ 16kHz)
- **Detection Latency**: < 100ms from wake word spoken to detection
- **CPU Usage**: Minimal impact on system resources
- **Memory Usage**: Efficient memory management with proper cleanup
- **Accuracy**: High precision with custom wake word model

### **Troubleshooting**
If tests fail, check:
- ✅ Picovoice access key is valid in `Config/WakeWord/PorcupineAccessKey.txt`
- ✅ Custom wake word model exists at `Config/WakeWord/WellBot_WakeWordModel.ppn`
- ✅ Microphone permissions are granted
- ✅ Audio drivers are working correctly
- ✅ No other applications are using the microphone


