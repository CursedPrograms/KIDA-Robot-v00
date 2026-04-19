#!/usr/bin/env python3

import json
from pathlib import Path

# Load JSON configuration
with open("config.json") as f:
    config = json.load(f)

input_dir = Path(config["directories"]["input"])
output_dir = Path(config["directories"]["output"])

print("Input Directory:", input_dir.resolve())
print("Output Directory:", output_dir.resolve())

# Example: listing input files
for file in input_dir.glob("*.*"):
    print("Found file:", file.name)