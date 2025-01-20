from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/')
def index():
    return jsonify({"status": "healthy"}), 200

@app.route('/test')
def test():
    return jsonify({"message": "API is working"}), 200
