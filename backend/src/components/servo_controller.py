# backend/src/components/servo_controller.py

try:
    import RPi.GPIO as GPIO
except ModuleNotFoundError:
    GPIO = None
import time
import threading
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

class ServoController:
    def __init__(self, pin=17, frequency=50):
        self.servo_pin = pin
        self.frequency = frequency
        # Note: We do NOT create self.pwm here anymore. 
        # It is created temporarily only when waving.
        self._is_moving = False

        # Configs
        self.LEFT_ANGLE  = 30
        self.RIGHT_ANGLE = 150
        self.NEUTRAL     = 90

    def _angle_to_duty(self, angle):
        return 2 + (angle / 18)

    def _perform_wave(self, waves):
        """
        The actual wave logic running in a thread.
        It handles its own GPIO setup and teardown to ensure silence when idle.
        """
        if GPIO is None:
            logger.info("RPi.GPIO not available; skipping servo wave")
            return

        self._is_moving = True
        pwm = None
        
        try:
            # 1. JUST-IN-TIME SETUP
            # We setup GPIO only when we actually need to move.
            # This prevents the "startup jitter" entirely.
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.servo_pin, GPIO.OUT)
            
            pwm = GPIO.PWM(self.servo_pin, self.frequency)
            pwm.start(0)

            # Helper for local move
            def move_sync(angle, t=0.18):
                pwm.ChangeDutyCycle(self._angle_to_duty(angle))
                time.sleep(t)

            # 2. PERFORM THE GESTURE
            logger.info("👋 Servo waking up...")
            move_sync(self.NEUTRAL)
            time.sleep(0.3)

            for _ in range(waves):
                move_sync(self.RIGHT_ANGLE)
                move_sync(self.LEFT_ANGLE)

            # Return to neutral
            move_sync(self.NEUTRAL)
            time.sleep(0.2) # Wait for it to settle

        except Exception as e:
            logger.error(f"Servo gesture failed: {e}")
            
        finally:
            # 3. AGGRESSIVE CLEANUP
            # This kills the Software PWM generator completely.
            # No signal = No Jitter.
            if pwm:
                pwm.ChangeDutyCycle(0)
                pwm.stop()
            
            # Optional: Set pin low to be safe
            try:
                GPIO.output(self.servo_pin, GPIO.LOW)
            except:
                pass
                
            self._is_moving = False
            logger.info("💤 Servo signal cut (Jitter prevention)")

    def trigger_wave(self, waves=2):
        """
        Public method to start the wave. 
        Returns immediately (non-blocking).
        """
        if GPIO is None:
            logger.info("RPi.GPIO not available; skipping servo wave")
            return

        if self._is_moving:
            logger.info("Servo already moving, skipping trigger")
            return

        logger.info("⚡ Triggering servo thread")
        t = threading.Thread(target=self._perform_wave, args=(waves,), daemon=True)
        t.start()

    def cleanup(self):
        """Final cleanup on app exit."""
        if GPIO is None:
            return

        try:
            GPIO.cleanup()
        except:
            pass

# Main Execution Block for Testing
if __name__ == "__main__":
    print("--- Starting Servo Test ---")
    controller = ServoController(pin=17) 
    
    try:
        # Note: We skip 'initialize()' because it doesn't exist anymore!
        print("1. Triggering Wave (Setup happens inside)...")
        controller.trigger_wave(waves=3)
        
        print("2. Waiting for wave to finish...")
        while controller._is_moving:
            time.sleep(0.1)
            
        print("3. Done!")

    except KeyboardInterrupt:
        print("\nStopped by user")
    finally:
        print("Cleaning up...")
        controller.cleanup()