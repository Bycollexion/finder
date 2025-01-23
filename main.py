from flask import Flask, jsonify, request, make_response, send_file
from flask_cors import CORS
import os
import json
import csv
from io import StringIO, BytesIO, TextIOWrapper
import openai
import traceback
import requests
from urllib.parse import quote
import time
from werkzeug.middleware.proxy_fix import ProxyFix
import time
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from openai.error import RateLimitError, APIError
import random
from datetime import datetime

# Flask app initialization
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
CORS(app, resources={r"/*": {"origins": "*"}})

# Basic error handlers
@app.errorhandler(404)
def not_found_error(error):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

def clean_header(header):
    """Clean header value by removing trailing semicolons and whitespace"""
    if not header:
        return header
    return header.rstrip(';').strip()

@app.after_request
def after_request(response):
    """Add CORS headers to all responses"""
    origin = request.headers.get('Origin')
    print(f"Request origin: {origin}")
    
    if origin:
        # List of allowed origins
        allowed_origins = [
            'http://localhost:3000',
            'https://finder-git-main-bycollexions-projects.vercel.app',
            'https://finder-bycollexions-projects.vercel.app'
        ]
        
        if origin in allowed_origins:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
            response.headers['Access-Control-Max-Age'] = '3600'
    else:
        print("Warning: Unknown origin", origin)
        
    return response

def search_web_info(company, country):
    """Search web for company information"""
    try:
        response = call_openai_with_retry(
            messages=[
                {"role": "system", "content": """You are an employee data analyst. Search these sources in order:
                1. LinkedIn (highest priority)
                2. Official company websites
                3. Glassdoor, Indeed
                4. News articles about company size/layoffs
                5. Industry reports
                
                Return ONLY this JSON format:
                {
                    "employee_count": "<specific number or range>",
                    "confidence": "<confidence>",
                    "sources": "<sources used>"
                }
                
                Confidence levels:
                - "high": LinkedIn or official company data
                - "medium": Recent news/reports
                - "low": Estimates/outdated data
                
                IMPORTANT:
                - Focus on {country} employees only
                - ALWAYS provide a number/range, even if estimated
                - Use most recent data available
                - Combine multiple sources if needed"""},
                {"role": "user", "content": f"Find employee count for {company} in {country}. MUST return a number/range."}
            ]
        )
        
        content = response.choices[0].message.content
        try:
            if isinstance(content, str) and content.startswith('{'):
                result = json.loads(content)
            else:
                result = {
                    "employee_count": "Data not found",
                    "confidence": "low",
                    "sources": "No reliable data"
                }
            
            return {
                "Company": company,
                "Employee Count": result.get("employee_count", "Data not found"),
                "Confidence": result.get("confidence", "low"),
                "Sources": result.get("sources", "No reliable data")
            }
            
        except json.JSONDecodeError:
            return {
                "Company": company,
                "Employee Count": "Data not found",
                "Confidence": "low",
                "Sources": "Error in response"
            }
            
    except Exception as e:
        return {
            "Company": company,
            "Employee Count": "Error occurred",
            "Confidence": "low",
            "Sources": "API error"
        }

def process_company_batch(companies, country):
    """Process a batch of companies"""
    try:
        return [search_web_info(company, country) for company in companies]
    except Exception as e:
        print(f"Error processing batch: {str(e)}")
        return []

def process_file():
    """Process uploaded file"""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
            
        file = request.files['file']
        country = request.form.get('country', '').strip()
        
        if not file or file.filename == '':
            return jsonify({"error": "No file selected"}), 400
            
        if not country:
            return jsonify({"error": "No country specified"}), 400
            
        print(f"Processing file '{file.filename}' for country: {country}")
        
        # Read CSV content
        content = file.read().decode('utf-8')
        print(f"Successfully read file content, length: {len(content)}")
        
        # Parse CSV
        reader = csv.reader(StringIO(content))
        companies = [row[0].strip() for row in reader if row and row[0].strip()]
        
        if not companies:
            return jsonify({"error": "No companies found in file"}), 400
            
        print(f"Found {len(companies)} companies")
        
        # Process in small batches
        batch_size = 2
        batches = [companies[i:i + batch_size] for i in range(0, len(companies), batch_size)]
        print(f"Processing companies in batches of {batch_size}")
        
        all_results = []
        for i, batch in enumerate(batches, 1):
            print(f"Processing batch {i}/{len(batches)}")
            for j, company in enumerate(batch, 1):
                print(f"Processing company {j}/{len(batch)}: {company}")
            
            results = process_company_batch(batch, country)
            all_results.extend(results)

        print("Creating output CSV...")
        # Create CSV in memory
        si = StringIO()
        writer = csv.writer(si)
        
        # Write header - simplified columns
        writer.writerow(['Company', 'Employee Count', 'Confidence'])
        
        # Write results - only the needed fields
        for result in all_results:
            writer.writerow([
                result.get('Company', ''),
                result.get('Employee Count', ''),
                result.get('Confidence', '')
            ])
        
        print("Preparing file download...")
        output = make_response(si.getvalue())
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'employee_counts_{timestamp}.csv'
        
        output.headers["Content-Disposition"] = f"attachment; filename={filename}"
        output.headers["Content-type"] = "text/csv"
        return output

@app.route('/')
def health_check():
    """Basic health check endpoint"""
    return "OK", 200  # Simple text response for health checks

@app.route('/api/countries', methods=['GET', 'OPTIONS'])
def get_countries():
    """Get list of supported countries"""
    try:
        print(f"Countries request received. Method: {request.method}")
        print(f"Headers: {dict(request.headers)}")
        print(f"Origin: {clean_header(request.headers.get('Origin'))}")

        if request.method == 'OPTIONS':
            return handle_preflight()

        print("Getting countries list")
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
        
        print(f"Returning {len(countries)} countries")
        
        # Create response with CORS headers
        response = make_response(jsonify(countries))
        return response

    except Exception as e:
        print(f"Error getting countries: {str(e)}")
        traceback.print_exc()
        error_response = make_response(jsonify({
            "error": "Failed to get countries",
            "details": str(e)
        }))
        return error_response, 500

@app.route('/api/process', methods=['POST', 'OPTIONS'])
def handle_process_file():
    """Handle file processing endpoint"""
    if request.method == 'OPTIONS':
        return handle_preflight()
    return process_file()

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
            
        openai.api_key = openai_api_key
        response = call_openai_with_retry(
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
        
        function_call = response['choices'][0]['message']['function_call']
        result = json.loads(function_call['arguments'])
            
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

def handle_preflight():
    """Handle CORS preflight request"""
    response = make_response()
    origin = request.headers.get('Origin')
    
    # List of allowed origins
    allowed_origins = [
        'http://localhost:3000',
        'https://finder-git-main-bycollexions-projects.vercel.app',
        'https://finder-bycollexions-projects.vercel.app'
    ]
    
    if origin in allowed_origins:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        response.headers['Access-Control-Max-Age'] = '3600'
    
    return response, 204

@retry(
    retry=retry_if_exception_type((RateLimitError, APIError)),
    wait=wait_exponential(multiplier=2, min=4, max=60),  # Longer wait times with more exponential backoff
    stop=stop_after_attempt(5)  # More attempts before giving up
)
def call_openai_with_retry(messages, functions=None, function_call=None, model="gpt-4"):
    """Make OpenAI API call with retry logic and model fallback"""
    try:
        # Add jitter to help prevent rate limits
        time.sleep(random.uniform(0.1, 0.5))
        
        if functions:
            return openai.ChatCompletion.create(
                model=model,
                messages=messages,
                functions=functions,
                function_call=function_call,
                request_timeout=45  # Increased timeout
            )
        return openai.ChatCompletion.create(
            model=model,
            messages=messages,
            request_timeout=45  # Increased timeout
        )
    except RateLimitError as e:
        print(f"Rate limit error with {model}: {str(e)}")
        if model == "gpt-4":
            print("Falling back to GPT-3.5-turbo...")
            # Try GPT-3.5-turbo as fallback
            try:
                return call_openai_with_retry(messages, functions, function_call, model="gpt-3.5-turbo")
            except Exception as fallback_error:
                print(f"Fallback to GPT-3.5-turbo failed: {str(fallback_error)}")
                raise
        print("Rate limit reached. Waiting before retry...")
        raise  # Let retry handle it
    except APIError as e:
        print(f"API error with {model}: {str(e)}")
        print("API error occurred. Waiting before retry...")
        raise  # Let retry handle it
    except Exception as e:
        if "quota" in str(e).lower():
            if model == "gpt-4":
                print("Quota exceeded for GPT-4, trying GPT-3.5-turbo...")
                try:
                    return call_openai_with_retry(messages, functions, function_call, model="gpt-3.5-turbo")
                except Exception as fallback_error:
                    print(f"Fallback to GPT-3.5-turbo failed: {str(fallback_error)}")
                    raise RateLimitError("All models quota exceeded")
            raise RateLimitError(f"Quota exceeded for {model}")
        raise

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
