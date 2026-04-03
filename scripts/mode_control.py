from mode_control import ControlMode

# State
current_mode = ControlMode.USER  # default

# Inside your main loop
if current_mode == ControlMode.USER:
    # Control via D-pad / web commands
    # Example: motors.forward(speed) when "forward" command received
    pass

elif current_mode == ControlMode.AUTONOMOUS:
    # Use obstacle avoidance
    avoider.check_and_avoid()

elif current_mode == ControlMode.LINE_FOLLOWER:
    # Example: call a LineFollower class / function
    # line_follower.follow_line()
    pass