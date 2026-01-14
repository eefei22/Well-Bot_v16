import requests
from picamera2 import Picamera2
import time
import cv2
import os
import json
import logging

# Setup basic logging to see errors if it runs as a service
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

USER_PERSONA_PATH = "./config/user_persona.json" 
DEFAULT_USER_ID = "96975f52-5b05-4eb1-bfa5-530485112518"
SERVER_URL = "https://wellbot-fer-backend-520080168829.asia-southeast1.run.app/emotion"

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
        logging.error(f"Error reading {USER_PERSONA_PATH}: {e}")
    
    return os.getenv("DEV_USER_ID", DEFAULT_USER_ID)

# Initialize camera once
try:
    picam2 = Picamera2()
    config = picam2.create_still_configuration(main={"size": (640, 480)}) # Lower res for faster upload
    picam2.configure(config)
    picam2.start()
    logging.info("Camera started successfully.")
except Exception as e:
    logging.critical(f"Camera failed to initialize: {e}")
    exit(1)

while True:
    start_time = time.time()
    
    try:
        # 1. Capture image
        frame = picam2.capture_array()
        filename = "/tmp/frame.jpg"
        success = cv2.imwrite(filename, frame)
        
        if not success or not os.path.exists(filename) or os.path.getsize(filename) == 0:
            logging.warning("Image capture failed or file empty.")
            time.sleep(1) # Short retry
            continue

        # 2. Get the User ID
        current_user_id = get_current_user_id()

        # 3. Send to Server
        with open(filename, "rb") as f:
            files = {"file": f}
            payload = {"user_id": current_user_id}
            
            # Timeout is crucial so the Pi doesn't hang forever if server is slow
            res = requests.post(SERVER_URL, files=files, data=payload, timeout=15)

            if res.status_code == 200:
                logging.info(f"Sent [User: {current_user_id}] - Server Response: {res.json()}")
            else:
                logging.error(f"Server Error ({res.status_code}): {res.text}")

    except requests.exceptions.RequestException as e:
        logging.error(f"Network error: {e}")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")

    # 4. Smart Sleep (Ensure ~10s interval regardless of processing time)
    elapsed = time.time() - start_time
    sleep_time = max(0, 10 - elapsed)
    logging.info(f"Sleeping for {sleep_time:.2f} seconds...")
    time.sleep(sleep_time)