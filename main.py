import os
import sys
import logging
from flask import Flask, jsonify, request
from flask_cors import CORS
import json
from openai import OpenAI

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

@app.route("/")
def health_check():
    logger.info("Health check endpoint called")
    try:
        return jsonify({"status": "healthy"}), 200
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route("/employee_count", methods=["POST"])
def get_employee_count():
    logger.info("Employee count endpoint called")
    try:
        data = request.get_json()
        logger.info(f"Received request data: {data}")
        
        company_name = data.get("company")
        if not company_name:
            logger.error("No company name provided")
            return jsonify({"error": "Company name is required"}), 400

        # Use OpenAI API
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            logger.error("OpenAI API key not configured")
            return jsonify({"error": "OpenAI API key not configured"}), 500
            
        logger.info(f"Making OpenAI API request for company: {company_name}")
        client = OpenAI(api_key=openai_api_key)
        
        # Use function calling to get structured data
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
        
        logger.info("Successfully received OpenAI API response")
        function_call = response.choices[0].message.function_call
        result = json.loads(function_call.arguments)
        logger.info(f"Parsed result: {result}")
            
        return jsonify({
            "company": company_name,
            "employee_count": result["employee_count"],
            "confidence": result["confidence"],
            "source": "openai"
        })

    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    try:
        port = int(os.getenv("PORT", 8000))
        logger.info(f"Starting server on port {port}")
        app.run(host="0.0.0.0", port=port)
    except Exception as e:
        logger.error(f"Failed to start server: {str(e)}", exc_info=True)
