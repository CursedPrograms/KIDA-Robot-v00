import os
import sys

print("Switching to ui.py...")

os.execv(sys.executable, [sys.executable, "ui.py"])