import os
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route("/")
def index():
    """Health check endpoint"""
    return jsonify({"status": "healthy"}), 200

if __name__ == "__main__":
    # Railway's default port is 3000
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
