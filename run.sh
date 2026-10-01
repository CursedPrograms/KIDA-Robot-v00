#!/bin/bash

# Run from the repo root no matter where this is launched from
# (desktop shortcut, autostart, ssh), so relative paths in the scripts resolve.
cd "$(dirname "$(readlink -f "$0")")" || exit 1

VENV_DIR="psdenv"

# Check if the virtual environment directory exists
if [ ! -d "$VENV_DIR" ]; then
    # Create the virtual environment and install what KIDA needs
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -r requirements.txt -r gpio-requirements.txt
fi

# Audio: force ALSA on the card that `speaker-test -D hw:0,0` plays through
# (read by scripts/music_player.py). Override per run, e.g.
#   KIDA_AUDIO_DEVICE=plughw:0,0 ./run.sh
export SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-alsa}"
export KIDA_AUDIO_DEVICE="${KIDA_AUDIO_DEVICE:-hw:0,0}"

# Activate the virtual environment and run the Python script
source "$VENV_DIR/bin/activate"
python run.py

# Pause for user input before closing — only when run from a terminal,
# so autostart doesn't sit waiting for Enter
if [ -t 0 ]; then
    read -p "Press Enter to continue..."
fi
