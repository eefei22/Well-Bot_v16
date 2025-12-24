
import requests
from picamera2 import Picamera2
import time
import cv2
import os
import json

USER_PERSONA_PATH = "./config/user_persona.json" 
DEFAULT_USER_ID = "96975f52-5b05-4eb1-bfa5-530485112518"

def get_current_user_id():
    """Reads user_id from JSON with fallbacks."""
    try:
        if os.path.exists(USER_PERSONA_PATH):
            with open(USER_PERSONA_PATH, "r") as f:
                data = json.load(f)
                user_id = data.get("user_id")
                if user_id:
                    return user_id
    except Exception as e:
        print(f"Error reading {USER_PERSONA_PATH}: {e}")
    
    # Fallback to Environment Variable or Default
    return os.getenv("DEV_USER_ID", DEFAULT_USER_ID)

# Initialize camera
picam2 = Picamera2()
picam2.configure(picam2.create_still_configuration())
picam2.start()

while True:
    # 1. Capture image
    frame = picam2.capture_array()
    filename = "/tmp/frame.jpg"
    success = cv2.imwrite(filename, frame)
    
    if not success or not os.path.exists(filename) or os.path.getsize(filename) == 0:
        print("Image capture failed.")
        continue

    # 2. Get the User ID
    current_user_id = get_current_user_id()
    print(f"Captured image for user: {current_user_id}")

    # 3. Send image AND user_id to FastAPI server
    with open(filename, "rb") as f:
        try:
            url = "https://wellbot-fer-backend-520080168829.asia-southeast1.run.app/emotion"
            
            # files handles the 'file' field, data handles the 'user_id' Form field
            files = {"file": f}
            payload = {"user_id": current_user_id}

            res = requests.post(url, files=files, data=payload)

            if res.status_code == 200:
                print("Success:", res.json())
            else:
                print(f"Server Error ({res.status_code}):", res.text)

        except requests.exceptions.RequestException as e:
            print("Network error:", e)

    print("Waiting for 8 seconds...")
    time.sleep(8)

