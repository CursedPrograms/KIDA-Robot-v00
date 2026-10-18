#!/bin/bash
# camera_centre.sh - point KIDA's camera straight ahead (its servo on GPIO 13 to 90°).
# While KIDA runs, she owns the pin, so this asks her (POST /camera_servo centre);
# otherwise it drives the servo itself (scripts/camera_servo.py).
cd "$(dirname "$0")"
if curl -s -m 2 -X POST -H 'Content-Type: application/json' -d '{"action":"centre"}' \
     http://127.0.0.1:5003/camera_servo >/dev/null; then
  echo "Centred (asked KIDA)."
else
  [ -f psdenv/bin/activate ] && source psdenv/bin/activate
  python3 scripts/camera_servo.py
fi
