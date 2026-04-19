#!/usr/bin/env python3

import cv2
import time
from picamera2 import Picamera2

# Initialize PiCamera2
cam = Picamera2()
cam.preview_configuration.main.size = (640, 480)
cam.preview_configuration.main.format = "RGB888"
cam.configure("preview")
cam.start()
time.sleep(1)  # Let the camera warm up

# Load the Haar Cascade face detector
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

print("👁️ Press 'q' to quit.")

while True:
    # Capture frame from PiCamera
    frame = cam.capture_array()

    # Convert to grayscale for face detection
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

    # Detect faces
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=5, minSize=(30, 30))

    # Draw rectangles around faces
    for (x, y, w, h) in faces:
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

    # Display the result
    cv2.imshow('🎥 PiCamera Face Detection', cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

    # Quit if 'q' is pressed
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Cleanup
cv2.destroyAllWindows()
cam.stop()
