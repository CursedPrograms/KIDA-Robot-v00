#!/bin/bash

echo "🔧 Setting execute permissions..."

FILES=(
    "run.sh"
    "install_requirements.sh"
    "freeze_requirements.sh"
    "run.sh"
    "setup.sh"
    "led_test.sh"
    "line_test.sh"
    "linefollower.sh"
    "ultrasonic_sensor_test.sh"
    "obstacle_avoidance.sh"
    "servo_test.sh"
    "clear_commits.sh"
    "filetree.sh"
    "activate_environment.sh"
    "app_test.sh"
)

for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        # Remove Windows carriage returns if they exist
        sed -i 's/\r$//' "$file" 2>/dev/null
        
        # Set execute permission
        chmod +x "$file"
        echo "✔ $file (Permissions set & Line endings fixed)"
    else
        echo "⚠ $file not found"
    fi
done

echo "---"
echo "✅ Done! You can now run your scripts using ./script_name.sh"

