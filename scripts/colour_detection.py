#!/usr/bin/env python3

import cv2
import numpy as np

def detect_colors():
    # Initialize Pi Camera (0 is usually the ribbon cable camera)
    cap = cv2.VideoCapture(0)
    
    # Define HSV color ranges
    # Note: Hue ranges from 0-180 in OpenCV
    colors = {
        "RED":    {"lower": [0, 120, 70],    "upper": [10, 255, 255]},
        "YELLOW": {"lower": [20, 100, 100],  "upper": [30, 255, 255]},
        "GREEN":  {"lower": [35, 100, 100],  "upper": [85, 255, 255]},
        "CYAN":   {"lower": [85, 100, 100],  "upper": [100, 255, 255]},
        "BLUE":   {"lower": [100, 150, 0],   "upper": [140, 255, 255]},
        "PINK":   {"lower": [140, 100, 100], "upper": [170, 255, 255]}
    }

    print("KIDA Vision System Active. Press 'q' to exit.")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Blur to reduce noise and convert to HSV
        blurred = cv2.GaussianBlur(frame, (11, 11), 0)
        hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)

        for color_name, range_val in colors.items():
            lower = np.array(range_val["lower"])
            upper = np.array(range_val["upper"])
            
            # Create a mask for the specific color
            mask = cv2.inRange(hsv, lower, upper)
            
            # Find contours (blobs) of that color
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area > 500: # Only detect large enough objects
                    x, y, w, h = cv2.boundingRect(cnt)
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    cv2.putText(frame, color_name, (x, y - 10), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        # Show the output
        cv2.imshow("KIDA Vision - Color Detection", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    detect_colors()