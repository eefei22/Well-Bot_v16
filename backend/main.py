# backend/main.py

from fastapi import FastAPI
import socketio
import os
import logging
from src.scripts._pipeline_wakeword import create_voice_pipeline
import uvicorn

# Configure clean logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins="*")
app = FastAPI()
asgi_app = socketio.ASGIApp(sio, other_asgi_app=app)

def safe_on_wake():
    import threading
    logger.info(f"safe_on_wake wrapper running on thread {threading.current_thread().name}")
    try:
        sio.start_background_task(sio.emit, "wakeword_detected", {"status": "triggered"})
        logger.info("safe_on_wake: scheduled emit")
    except Exception as e:
        logger.error("safe_on_wake: error scheduling emit", exc_info=e)

def safe_on_transcript(text: str):
    import threading
    logger.info(f"safe_on_transcript wrapper running on thread {threading.current_thread().name}, text: {text}")
    try:
        sio.start_background_task(sio.emit, "stt_final", {"text": text})
        logger.info("safe_on_transcript: scheduled emit")
    except Exception as e:
        logger.error("safe_on_transcript: error scheduling emit", exc_info=e)

def create_pipeline():
    backend_dir = os.path.dirname(__file__)
    access_key_path = os.path.join(backend_dir, 'Config', 'WakeWord', 'PorcupineAccessKey.txt')
    custom_keyword_path = os.path.join(backend_dir, 'Config', 'WakeWord', 'WellBot_WakeWordModel.ppn')
    return create_voice_pipeline(
        access_key_file=access_key_path,
        custom_keyword_file=custom_keyword_path,
        language="en-US",
        on_wake_callback=safe_on_wake,
        on_final_transcript=safe_on_transcript
    )

pipeline = create_pipeline()

@sio.on("connect")
async def connect(sid, environ):
    logger.info(f"Client connected: {sid}")
    await sio.emit("connected", {"message": "Connected to Well-Bot"}, to=sid)

@sio.on("start_pipeline")
async def start_pipeline(sid, data):
    try:
        pipeline.start()
        logger.info(f"Pipeline started for client: {sid}")
        await sio.emit("system_ready", {"message": "Listening for wake word..."}, to=sid)
    except Exception as e:
        logger.error(f"Failed to start pipeline: {e}", exc_info=e)
        await sio.emit("error", {"message": str(e)}, to=sid)

@sio.on("stop_pipeline")
async def stop_pipeline(sid, data):
    pipeline.stop()
    await sio.emit("pipeline_stopped", {"message": "Pipeline stopped"}, to=sid)

@app.get("/health")
async def health():
    return {"status": "healthy", "pipeline_active": pipeline.is_active()}

if __name__ == "__main__":
    uvicorn.run(asgi_app, host="0.0.0.0", port=8000)
