from flask import Flask, jsonify, request, make_response
from flask_cors import CORS
import os
import json
from openai import OpenAI

app = Flask(__name__)
CORS(app)

@app.route('/')
def index():
    return jsonify({"status": "healthy"})

@app.route('/api/countries', methods=['GET'])
def get_countries():
    # Return a list of Asian countries and Australia
    countries = [
        {"id": "sg", "name": "Singapore"},
        {"id": "my", "name": "Malaysia"},
        {"id": "id", "name": "Indonesia"},
        {"id": "th", "name": "Thailand"},
        {"id": "vn", "name": "Vietnam"},
        {"id": "ph", "name": "Philippines"},
        {"id": "jp", "name": "Japan"},
        {"id": "kr", "name": "South Korea"},
        {"id": "cn", "name": "China"},
        {"id": "hk", "name": "Hong Kong"},
        {"id": "tw", "name": "Taiwan"},
        {"id": "au", "name": "Australia"}
    ]
    return jsonify(countries)

@app.route('/employee_count', methods=['POST'])
def get_employee_count():
    try:
        data = request.get_json()
        company_name = data.get('company')
        
        if not company_name:
            response = make_response(jsonify({"error": "Company name is required"}), 400)
            response.headers['Content-Type'] = 'application/json'
            return response

        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            response = make_response(jsonify({"error": "OpenAI API key not configured"}), 500)
            response.headers['Content-Type'] = 'application/json'
            return response
            
        client = OpenAI(api_key=openai_api_key)
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that provides company information."},
                {"role": "user", "content": f"How many employees does {company_name} have?"}
            ],
            functions=[{
                "name": "get_employee_count",
                "description": "Get the number of employees at a company",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "employee_count": {
                            "type": "integer",
                            "description": "The number of employees at the company"
                        },
                        "confidence": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                            "description": "Confidence level in the employee count"
                        }
                    },
                    "required": ["employee_count", "confidence"]
                }
            }],
            function_call={"name": "get_employee_count"}
        )
        
        function_call = response.choices[0].message.function_call
        result = json.loads(function_call.arguments)
            
        response = make_response(jsonify({
            "company": company_name,
            "employee_count": result["employee_count"],
            "confidence": result["confidence"],
            "source": "openai"
        }))
        response.headers['Content-Type'] = 'application/json'
        return response

    except Exception as e:
        response = make_response(jsonify({"error": str(e)}), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
