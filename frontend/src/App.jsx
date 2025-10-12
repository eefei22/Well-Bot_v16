import React, { useState, useEffect, useRef } from 'react';
import io from 'socket.io-client';
import './App.css';

function App() {
  const [socket, setSocket] = useState(null);
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isConnected, setIsConnected] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [transcription, setTranscription] = useState('');
  const [isWakeWordActive, setIsWakeWordActive] = useState(false);
  
  const messagesEndRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const firstChunkRef = useRef(null);  // store first chunk / header
  const seqRef = useRef(0);

  useEffect(() => {
    // Initialize Socket.IO connection
    const newSocket = io('http://localhost:8000');
    setSocket(newSocket);

    // Connection events
    newSocket.on('connect', () => {
      console.log('Connected to server');
      setIsConnected(true);
    });

    newSocket.on('disconnect', () => {
      console.log('Disconnected from server');
      setIsConnected(false);
    });

    newSocket.on('connected', (data) => {
      addMessage('system', data.message);
    });

    // Wake word events
    newSocket.on('wakeword_detected', (data) => {
      console.log('Wake word detected:', data);
      setIsWakeWordActive(true);
      addMessage('system', '🔊 Wake word detected! Starting recording...');
      
      // Auto-start recording when wake word is detected
      startRecording();
    });

    // Recording events
    newSocket.on('recording_started', (data) => {
      console.log('Recording started:', data);
      setIsRecording(true);
      addMessage('system', '🎤 Recording started');
    });

    newSocket.on('recording_stopped', (data) => {
      console.log('Recording stopped:', data);
      setIsRecording(false);
      addMessage('system', '⏹️ Recording stopped');
    });

    // Transcription events
    newSocket.on('transcription_interim', (data) => {
      console.log('Interim transcription:', data);
      setTranscription(data.text);
    });

    newSocket.on('transcription_final', (data) => {
      console.log('Final transcription:', data);
      setTranscription('');
      addMessage('user', data.text);
    });

    newSocket.on('transcription_error', (data) => {
      console.error('Transcription error:', data);
      addMessage('system', `❌ Error: ${data.error}`);
    });

    // Message response events
    newSocket.on('message_response', (data) => {
      console.log('Message response:', data);
      addMessage('system', data.text);
    });

    return () => {
      newSocket.close();
    };
  }, []);

  const addMessage = (sender, text) => {
    const newMessage = {
      id: Date.now(),
      sender,
      text,
      timestamp: new Date().toLocaleTimeString()
    };
    setMessages(prev => [...prev, newMessage]);
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = async (event) => {
        if (event.data.size <= 0) return;

        const blob = event.data;
        const arrayBuffer = await blob.arrayBuffer();

        // Determine if this is the first chunk
        const isFirst = firstChunkRef.current === null;
        if (isFirst) {
          firstChunkRef.current = blob;
        }

        // If not first, optionally prefix the first blob's header
        let sendBuffer;
        if (!isFirst && firstChunkRef.current) {
          // Option B: prefix only header slice, e.g. first 512 bytes
          const headerSlice = await firstChunkRef.current.slice(0, 512).arrayBuffer();
          sendBuffer = new Uint8Array(headerSlice.byteLength + arrayBuffer.byteLength);
          sendBuffer.set(new Uint8Array(headerSlice), 0);
          sendBuffer.set(new Uint8Array(arrayBuffer), headerSlice.byteLength);
        } else {
          sendBuffer = new Uint8Array(arrayBuffer);
        }

        // Emit with metadata
        socket.emit("audio_chunk", {
          seq: seqRef.current++,
          chunk: sendBuffer.buffer,      // ArrayBuffer
          mimeType: blob.type,
          isFirst,
        });
      };

      mediaRecorder.onstop = () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/wav' });
        console.log('Audio recording completed:', audioBlob);
        stream.getTracks().forEach((t) => t.stop());
        // Reset firstChunkRef in case of next recording session
        firstChunkRef.current = null;
        seqRef.current = 0;
      };

      mediaRecorder.start(100);  // chunk every 100ms
      socket.emit("start_recording");
      
    } catch (error) {
      console.error('Error starting recording:', error);
      addMessage('system', '❌ Error accessing microphone');
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      socket.emit('stop_recording');
    }
  };

  const sendMessage = () => {
    if (inputMessage.trim()) {
      addMessage('user', inputMessage);
      socket.emit('message', inputMessage);
      setInputMessage('');
    }
  };

  const simulateWakeWord = () => {
    socket.emit('simulate_wake_word');
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter') {
      sendMessage();
    }
  };

  return (
    <div className="app">
      <div className="header">
        <h1>Well-Bot</h1>
        <div className="status">
          <div className={`status-indicator ${isConnected ? 'connected' : 'disconnected'}`}>
            {isConnected ? '🟢 Connected' : '🔴 Disconnected'}
          </div>
          {isRecording && <div className="recording-indicator">🎤 Recording</div>}
          {isWakeWordActive && <div className="wakeword-indicator">🔊 Wake Word Active</div>}
        </div>
      </div>

      <div className="chat-container">
        <div className="messages">
          {messages.map((message) => (
            <div key={message.id} className={`message ${message.sender}`}>
              <div className="message-content">
                <span className="message-text">{message.text}</span>
                <span className="message-time">{message.timestamp}</span>
              </div>
            </div>
          ))}
          {transcription && (
            <div className="message transcription">
              <div className="message-content">
                <span className="message-text">{transcription}</span>
                <span className="transcription-indicator">(transcribing...)</span>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="input-container">
          <div className="controls">
            <button 
              onClick={simulateWakeWord}
              className="btn btn-secondary"
              disabled={!isConnected}
            >
              🔊 Simulate Wake Word
            </button>
            <button 
              onClick={isRecording ? stopRecording : startRecording}
              className={`btn ${isRecording ? 'btn-danger' : 'btn-primary'}`}
              disabled={!isConnected}
            >
              {isRecording ? '⏹️ Stop Recording' : '🎤 Start Recording'}
            </button>
          </div>
          
          <div className="text-input">
            <input
              type="text"
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="Type a message..."
              disabled={!isConnected}
            />
            <button 
              onClick={sendMessage}
              disabled={!inputMessage.trim() || !isConnected}
              className="btn btn-primary"
            >
              Send
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
