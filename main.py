from flask import Flask, jsonify, request
import os
import json
from openai import OpenAI

app = Flask(__name__)

@app.route('/')
def index():
    return jsonify({"status": "healthy"})

@app.route('/employee_count', methods=['POST'])
def get_employee_count():
    try:
        data = request.get_json()
        company_name = data.get('company')
        
        if not company_name:
            return jsonify({"error": "Company name is required"}), 400

        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            return jsonify({"error": "OpenAI API key not configured"}), 500
            
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
            
        return jsonify({
            "company": company_name,
            "employee_count": result["employee_count"],
            "confidence": result["confidence"],
            "source": "openai"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(debug=os.getenv("DEBUG", False), host='0.0.0.0', port=port)
