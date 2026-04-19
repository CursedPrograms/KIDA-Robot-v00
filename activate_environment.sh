#!/bin/bash

VENV_DIR="psdenv"

# Check if the virtual environment directory exists
if [ ! -d "$VENV_DIR" ]; then
    # Create the virtual environment
    python -m venv "$VENV_DIR"
fi