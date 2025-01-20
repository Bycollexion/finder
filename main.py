from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.route('/')
def index():
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
