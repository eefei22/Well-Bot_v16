# test_websocket.py
import asyncio
import socketio
import logging
import sys
import os

# Add the backend directory to the path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SERVER_URL = "http://localhost:8000"

class WebSocketTestClient:
    """WebSocket test client for testing the Well-Bot voice pipeline."""
    
    def __init__(self):
        self.sio = socketio.AsyncClient()
        self.connected = False
        self.pipeline_started = False
        self.events_received = []
        
        # Set up event handlers
        self._setup_event_handlers()
    
    def _setup_event_handlers(self):
        """Set up Socket.IO event handlers."""
        
        @self.sio.event
        async def connect():
            logger.info("[Client] Connected to server.")
            self.connected = True
            self.events_received.append("connect")
        
        @self.sio.event
        async def disconnect():
            logger.info("[Client] Disconnected.")
            self.connected = False
            self.events_received.append("disconnect")
        
        @self.sio.event
        async def connected(data):
            logger.info(f"[Client] Server confirmation: {data}")
            self.events_received.append("connected")
        
        @self.sio.event
        async def system_ready(data):
            logger.info(f"[Client] system_ready: {data}")
            self.events_received.append("system_ready")
        
        @self.sio.event
        async def wakeword_detected(data):
            logger.info(f"[Client] wakeword_detected: {data}")
            self.events_received.append("wakeword_detected")
        
        @self.sio.event
        async def stt_final(data):
            logger.info(f"[Client] stt_final: {data}")
            self.events_received.append("stt_final")
        
        @self.sio.event
        async def pipeline_stopped(data):
            logger.info(f"[Client] pipeline_stopped: {data}")
            self.events_received.append("pipeline_stopped")
        
        @self.sio.event
        async def status(data):
            logger.info(f"[Client] status: {data}")
            self.events_received.append("status")
        
        @self.sio.event
        async def error(data):
            logger.error(f"[Client] error: {data}")
            self.events_received.append("error")
    
    async def connect_to_server(self):
        """Connect to the WebSocket server."""
        try:
            await self.sio.connect(SERVER_URL)
            logger.info("[Client] Successfully connected to server")
            return True
        except Exception as e:
            logger.error(f"[Client] Failed to connect: {e}")
            return False
    
    async def disconnect_from_server(self):
        """Disconnect from the WebSocket server."""
        try:
            await self.sio.disconnect()
            logger.info("[Client] Successfully disconnected from server")
        except Exception as e:
            logger.error(f"[Client] Error disconnecting: {e}")
    
    async def start_pipeline(self):
        """Tell the server to start the voice pipeline."""
        try:
            await self.sio.emit("start_pipeline", {})
            logger.info("[Client] Emitted start_pipeline")
            self.pipeline_started = True
            return True
        except Exception as e:
            logger.error(f"[Client] Failed to start pipeline: {e}")
            return False
    
    async def stop_pipeline(self):
        """Tell the server to stop the voice pipeline."""
        try:
            await self.sio.emit("stop_pipeline", {})
            logger.info("[Client] Emitted stop_pipeline")
            self.pipeline_started = False
            return True
        except Exception as e:
            logger.error(f"[Client] Failed to stop pipeline: {e}")
            return False
    
    async def get_status(self):
        """Request current pipeline status."""
        try:
            await self.sio.emit("get_status", {})
            logger.info("[Client] Requested status")
            return True
        except Exception as e:
            logger.error(f"[Client] Failed to get status: {e}")
            return False
    
    def get_events_summary(self):
        """Get a summary of events received."""
        event_counts = {}
        for event in self.events_received:
            event_counts[event] = event_counts.get(event, 0) + 1
        return event_counts

async def run_basic_test():
    """Run a basic WebSocket connection test."""
    logger.info("=== Starting Basic WebSocket Test ===")
    
    client = WebSocketTestClient()
    
    try:
        # Connect to server
        if not await client.connect_to_server():
            logger.error("Failed to connect to server")
            return False
        
        # Wait a moment for connection to stabilize
        await asyncio.sleep(1)
        
        # Start the pipeline
        if not await client.start_pipeline():
            logger.error("Failed to start pipeline")
            return False
        
        # Wait for system_ready event
        await asyncio.sleep(2)
        
        # Get status
        await client.get_status()
        await asyncio.sleep(1)
        
        # Stop the pipeline
        await client.stop_pipeline()
        await asyncio.sleep(1)
        
        # Disconnect
        await client.disconnect_from_server()
        
        # Print summary
        logger.info("=== Test Summary ===")
        events = client.get_events_summary()
        for event, count in events.items():
            logger.info(f"Event '{event}': {count} times")
        
        return True
        
    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        return False

async def run_listening_test(duration=30):
    """Run a test that listens for wake word detection and STT results."""
    logger.info(f"=== Starting Listening Test ({duration}s) ===")
    
    client = WebSocketTestClient()
    
    try:
        # Connect to server
        if not await client.connect_to_server():
            logger.error("Failed to connect to server")
            return False
        
        # Wait a moment for connection to stabilize
        await asyncio.sleep(1)
        
        # Start the pipeline
        if not await client.start_pipeline():
            logger.error("Failed to start pipeline")
            return False
        
        logger.info(f"[Client] Listening for wake word and STT for {duration} seconds...")
        logger.info("[Client] Say the wake word to test the pipeline!")
        
        # Let it run for the specified duration
        await asyncio.sleep(duration)
        
        # Stop the pipeline
        await client.stop_pipeline()
        await asyncio.sleep(1)
        
        # Disconnect
        await client.disconnect_from_server()
        
        # Print summary
        logger.info("=== Listening Test Summary ===")
        events = client.get_events_summary()
        for event, count in events.items():
            logger.info(f"Event '{event}': {count} times")
        
        return True
        
    except Exception as e:
        logger.error(f"Listening test failed with error: {e}")
        return False

async def run_interactive_test():
    """Run an interactive test where user can control the pipeline."""
    logger.info("=== Starting Interactive Test ===")
    logger.info("Commands: 'start', 'stop', 'status', 'quit'")
    
    client = WebSocketTestClient()
    
    try:
        # Connect to server
        if not await client.connect_to_server():
            logger.error("Failed to connect to server")
            return False
        
        await asyncio.sleep(1)
        
        while True:
            try:
                command = input("\nEnter command (start/stop/status/quit): ").strip().lower()
                
                if command == "quit":
                    break
                elif command == "start":
                    await client.start_pipeline()
                elif command == "stop":
                    await client.stop_pipeline()
                elif command == "status":
                    await client.get_status()
                else:
                    print("Invalid command. Use: start, stop, status, or quit")
                
                # Small delay to see responses
                await asyncio.sleep(0.5)
                
            except KeyboardInterrupt:
                break
        
        # Cleanup
        await client.stop_pipeline()
        await client.disconnect_from_server()
        
        # Print summary
        logger.info("=== Interactive Test Summary ===")
        events = client.get_events_summary()
        for event, count in events.items():
            logger.info(f"Event '{event}': {count} times")
        
        return True
        
    except Exception as e:
        logger.error(f"Interactive test failed with error: {e}")
        return False

async def main():
    """Main test runner."""
    print("Well-Bot WebSocket Test Client")
    print("==============================")
    print("1. Basic connection test")
    print("2. Listening test (30 seconds)")
    print("3. Interactive test")
    print("4. Custom listening duration")
    
    try:
        choice = input("\nSelect test (1-4): ").strip()
        
        if choice == "1":
            await run_basic_test()
        elif choice == "2":
            await run_listening_test(30)
        elif choice == "3":
            await run_interactive_test()
        elif choice == "4":
            duration = int(input("Enter duration in seconds: "))
            await run_listening_test(duration)
        else:
            print("Invalid choice")
            return
        
        print("\nTest completed!")
        
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
    except Exception as e:
        logger.error(f"Test runner error: {e}")

if __name__ == "__main__":
    # Check if server is running
    print("Make sure the Well-Bot server is running on http://localhost:8000")
    print("You can start it with: python backend/main.py")
    print()
    
    asyncio.run(main())
