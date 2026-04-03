from enum import Enum, auto

class ControlMode(Enum):
    USER = auto()
    AUTONOMOUS = auto()
    LINE_FOLLOWER = auto()

# Example usage
if __name__ == "__main__":
    current_mode = ControlMode.USER

    print(f"Current mode: {current_mode.name}")

    # Switching modes
    current_mode = ControlMode.LINE_FOLLOWER
    print(f"Switched to mode: {current_mode.name}")