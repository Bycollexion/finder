import os
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/')
def index():
    """Default health check endpoint for Railway"""
    return jsonify({"status": "healthy"}), 200

@app.route('/test')
def test():
    return jsonify({"message": "API is working"}), 200

# Get port from environment variable or default to 8000
port = int(os.getenv("PORT", "8000"))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=port)
