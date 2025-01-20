import os
from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import httpx

app = Flask(__name__)
CORS(app)

@app.route("/")
def health_check():
    return jsonify({"status": "healthy"}), 200

@app.route("/employee_count", methods=["POST"])
def get_employee_count():
    try:
        data = request.get_json()
        company_name = data.get("company")
        
        if not company_name:
            return jsonify({"error": "Company name is required"}), 400

        # Use Gemini API
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        if not gemini_api_key:
            return jsonify({"error": "Gemini API key not configured"}), 500
            
        # Make request to Gemini API
        gemini_url = "https://api.gemini.ai/v1/employee_count"
        headers = {
            "Authorization": f"Bearer {gemini_api_key}",
            "Content-Type": "application/json"
        }
        data = {"company": company_name}
        
        with httpx.Client() as client:
            response = client.post(gemini_url, headers=headers, json=data)
            
        if response.status_code == 200:
            result = response.json()
            return jsonify({
                "company": company_name,
                "employee_count": result.get("employee_count"),
                "source": "gemini"
            })
        else:
            return jsonify({
                "error": f"Gemini API error: {response.text}"
            }), response.status_code

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
