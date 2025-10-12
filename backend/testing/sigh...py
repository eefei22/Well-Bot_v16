from fastapi import FastAPI
import socketio

# 1. Create the AsyncServer with ASGI mode
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins="*")

# 2. Create your FastAPI app
app = FastAPI()

# 3. Mount the Socket.IO server into the FastAPI app via ASGIApp
#    The second argument allows HTTP (non-socket) requests to be forwarded to FastAPI
asgi_app = socketio.ASGIApp(sio, other_asgi_app=app)

# 4. Then define your socket events on `sio` and define HTTP routes on `app`
@sio.on("connect")
async def connect(sid, environ):
    print("Client connected:", sid)

@sio.on("disconnect")
async def disconnect(sid):
    print("Client disconnected:", sid)

@app.get("/health")
def health():
    return {"status": "ok"}

# 5. At the bottom:
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(asgi_app, host="0.0.0.0", port=8000)
