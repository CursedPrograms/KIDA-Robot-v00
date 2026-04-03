# server.py

from flask import Flask, jsonify, request

app = Flask(__name__)

# --- Routes ---
@app.route('/')
def home():
    return "Welcome to KIDA's Flask Server!"

@app.route('/status')
def status():
    return jsonify({
        'status': 'online',
        'robot': 'KIDA',
        'message': 'All systems go!'
    })

@app.route('/command', methods=['POST'])
def receive_command():
    data = request.get_json()
    command = data.get('command')
    # Process the command here (e.g., send to robot controller)
    print(f"📡 Received command: {command}")
    return jsonify({'received': command, 'status': 'executed'})

# --- Start Server ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
