#!/bin/bash

# Exit on error
set -e

# Go to project root (script location)
cd "$(dirname "$0")"

# Activate virtual environment
source venv/bin/activate

# Run the line follower script
python scripts/obstacle_avoidance.py

# Deactivate (optional, happens automatically when script exits)
deactivate
