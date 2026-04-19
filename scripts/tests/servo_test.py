from gpiozero import Servo
from time import sleep

# Hardware Configuration
# Updated to include the new GPIO 19
PINS = [12, 13, 19]
servos = []

print("--- KIDA Triple Servo Initialization ---")

for pin in PINS:
    try:
        servos.append(Servo(pin))
        print(f"✅ Servo initialized on GPIO {pin}")
    except Exception as e:
        print(f"❌ Failed to initialize GPIO {pin}: {e}")

def sweep_test():
    try:
        while True:
            for i, s in enumerate(servos):
                pin_num = PINS[i]
                print(f"\nTesting Servo on Pin {pin_num}")
                
                print("  Moving to MIN...")
                s.min()
                sleep(0.8)
                
                print("  Moving to MAX...")
                s.max()
                sleep(0.8)
                
                print("  Centering...")
                s.mid()
                sleep(0.5)
                
            print("\n--- Cycle Complete. Restarting in 2s... ---")
            sleep(2)

except KeyboardInterrupt:
    print("\nStopping tests...")
finally:
    # Release the pins
    for s in servos:
        s.value = None
    print("Cleanup complete.")

if __name__ == "__main__":
    sweep_test()