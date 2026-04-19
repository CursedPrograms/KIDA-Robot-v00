#!/usr/bin/env python3

import os
import sys

print("Switching to ui.py...")

os.execv(sys.executable, [sys.executable, "scripts/ui.py"])
