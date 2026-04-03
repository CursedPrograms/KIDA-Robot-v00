# server.py
# KIDA Web Control Server (Improved)

from flask import Flask, jsonify, request, Response
import threading
import queue
import cv2
from picamera2 import Picamera2

app = Flask(__name__)
command_queue = queue.Queue()

# --- Camera Setup ---
picam2 = Picamera2()
picam2.configure(picam2.create_preview_configuration())
picam2.start()

# --- Routes ---
@app.route('/')
def home():
    return """
    <h1>KIDA Control</h1>
    <p>Status: Online</p>
    <img src="/video_feed" width="480">
    """

@app.route('/status')
def status():
    return jsonify({
        'status': 'online',
        'robot': 'KIDA',
        'message': 'All systems go!'
    })

@app.route('/mode', methods=['POST'])
def set_mode():
    global current_mode
    mode_str = request.get_json().get('mode', '').upper()
    try:
        current_mode = ControlMode[mode_str]
        return jsonify({'status': 'ok', 'mode': current_mode.name})
    except KeyError:
        return jsonify({'status': 'error', 'message': 'Invalid mode'}), 400

@app.route('/command', methods=['POST'])
def receive_command():
    try:
        data = request.get_json()
        command = data.get('command')

        print(f"📡 Received command: {command}")
        command_queue.put(command)

        return jsonify({'received': command, 'status': 'queued'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# --- Video Streaming ---
def generate_frames():
    while True:
        frame = picam2.capture_array()
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        _, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

# --- Command Processor Thread ---
def command_worker():
    while True:
        cmd = command_queue.get()
        print(f"🤖 Executing: {cmd}")

        # Hook into your motor system here
        # Example:
        # if cmd == "forward": motors.forward()

# --- Start Server ---
if __name__ == '__main__':
    threading.Thread(target=command_worker, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, debug=False)