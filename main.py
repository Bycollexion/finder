from flask import Flask, jsonify, request, make_response, send_file
from flask_cors import CORS
import os
import json
import csv
from io import StringIO, BytesIO
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

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app)

def clean_header(header):
    """Clean header value by removing trailing semicolons and whitespace"""
    if not header:
        return header
    return header.rstrip(';').strip()

@app.after_request
def after_request(response):
    """Add CORS headers to all responses"""
    origin = clean_header(request.headers.get('Origin'))
    print(f"Request origin: {origin}")
    
    # Always allow the Vercel frontend and localhost
    allowed_origins = [
        'https://finder-git-main-bycollexions-projects.vercel.app',
        'http://localhost:3000',
        'http://localhost:5173'
    ]
    
    if origin in allowed_origins:
        response.headers['Access-Control-Allow-Origin'] = origin
    else:
        print(f"Warning: Unknown origin {origin}")
        response.headers['Access-Control-Allow-Origin'] = '*'
        
    response.headers.update({
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Accept',
        'Access-Control-Allow-Credentials': 'true',
        'Access-Control-Max-Age': '3600',
        'Vary': 'Origin'
    })
    return response

def handle_preflight():
    """Handle CORS preflight request"""
    response = make_response()
    origin = clean_header(request.headers.get('Origin'))
    
    # Always allow the Vercel frontend and localhost
    allowed_origins = [
        'https://finder-git-main-bycollexions-projects.vercel.app',
        'http://localhost:3000',
        'http://localhost:5173'
    ]
    
    if origin in allowed_origins:
        response.headers['Access-Control-Allow-Origin'] = origin
    else:
        print(f"Warning: Unknown origin {origin}")
        response.headers['Access-Control-Allow-Origin'] = '*'
        
    response.headers.update({
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Accept',
        'Access-Control-Allow-Credentials': 'true',
        'Access-Control-Max-Age': '3600',
        'Vary': 'Origin'
    })
    return response, 204

def search_web_info(company, country):
    """Search web for company information"""
    try:
        response = call_openai_with_retry(
            messages=[
                {"role": "system", "content": """You are a web search expert. Search for employee count information.
                Focus only on:
                1. LinkedIn company profiles and employee lists
                2. Official company websites and career pages
                3. Job posting sites (Glassdoor, Indeed, JobStreet)
                
                Return information in this format:
                {
                    "company": "company name",
                    "employee_count": "number or range",
                    "confidence": "high/medium/low",
                    "sources": "list of sources",
                    "status": "success/error",
                    "explanation": "explanation of the result"
                }
                
                DO NOT include news articles or press releases.
                Only return factual, verifiable information."""},
                {"role": "user", "content": f"Search for employee count information for {company} in {country}. Focus on LinkedIn, company website, and job sites only. Return in JSON format."}
            ]
        )
        
        content = response.choices[0].message.content
        try:
            # Try to parse as JSON first
            if isinstance(content, str):
                if content.startswith('{') and content.endswith('}'):
                    result = json.loads(content)
                else:
                    # If not JSON, create a basic result
                    result = {
                        "company": company,
                        "employee_count": "Unknown",
                        "confidence": "low",
                        "sources": "GPT response",
                        "status": "partial",
                        "explanation": content
                    }
            else:
                result = content
                
            # Ensure all required fields are present
            required_fields = ["company", "employee_count", "confidence", "sources", "status", "explanation"]
            for field in required_fields:
                if field not in result:
                    result[field] = ""
                    
            return result
            
        except json.JSONDecodeError:
            # If JSON parsing fails, return structured error
            return {
                "company": company,
                "employee_count": "Unknown",
                "confidence": "low",
                "sources": "Error parsing GPT response",
                "status": "error",
                "explanation": content
            }
            
    except Exception as e:
        error_msg = str(e)
        if "quota" in error_msg.lower():
            return {
                "company": company,
                "employee_count": "Unknown",
                "confidence": "none",
                "sources": "API quota exceeded",
                "status": "error",
                "error": "API quota exceeded. Please try again later."
            }
        print(f"Error during web search: {error_msg}")
        return {
            "company": company,
            "employee_count": "Unknown",
            "confidence": "none",
            "sources": "Error occurred",
            "status": "error",
            "error": f"Error occurred during search: {error_msg}"
        }

def review_employee_count(company, country, initial_result, web_info):
    """Review and validate employee count based on available data"""
    try:
        response = call_openai_with_retry(
            messages=[
                {"role": "system", "content": """You are a data validation expert.
                Review the employee count based ONLY on available data.
                
                VALIDATION RULES:
                1. Check if the number matches LinkedIn data
                2. Verify the count is specific to the country
                3. Ensure the data is recent (last 6 months)
                4. Cross-reference multiple sources if available
                
                CONFIDENCE ASSESSMENT:
                HIGH: Direct employee count from LinkedIn/career page
                MEDIUM: Derived from job postings and office data
                LOW: Limited or outdated data
                
                DO NOT use assumptions about company size or type.
                Focus ONLY on actual data provided."""},
                {"role": "user", "content": f"""Review this employee count for {company} in {country}.
                
                Initial Result:
                Count: {initial_result.get('employee_count')}
                Confidence: {initial_result.get('confidence')}
                Sources: {', '.join(initial_result.get('sources', []))}
                
                Additional Information:
                {web_info}
                
                Requirements:
                1. Verify if the count is accurate
                2. Adjust if better data is available
                3. Update confidence level if needed
                4. Explain your reasoning"""}
            ],
            functions=[{
                "name": "review_count",
                "description": "Review and validate employee count",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "employee_count": {
                            "type": "integer",
                            "description": "Validated employee count"
                        },
                        "confidence": {
                            "type": "string",
                            "enum": ["HIGH", "MEDIUM", "LOW"],
                            "description": "Confidence in the validated count"
                        },
                        "sources": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Sources used for validation"
                        },
                        "explanation": {
                            "type": "string",
                            "description": "Explanation of the validation process and any adjustments"
                        }
                    },
                    "required": ["employee_count", "confidence", "sources", "explanation"]
                }
            }],
            function_call={"name": "review_count"}
        )
        
        if response.choices[0].message.get("function_call"):
            return json.loads(response.choices[0].message["function_call"]["arguments"])
        return initial_result
        
    except Exception as e:
        error_msg = str(e)
        if "quota" in error_msg.lower():
            return initial_result
        print(f"Error reviewing employee count: {error_msg}")
        return initial_result

def validate_employee_count(count):
    """Validate and clean employee count value"""
    if count is None:
        return None
        
    if isinstance(count, (int, float)):
        return int(count)
        
    if isinstance(count, str):
        # Remove any non-numeric characters except decimal point
        cleaned = ''.join(c for c in count if c.isdigit() or c == '.')
        if cleaned:
            try:
                # First try converting to float (in case it has decimals)
                float_val = float(cleaned)
                # Then convert to int
                return int(float_val)
            except (ValueError, TypeError):
                # If that fails, try just getting the first sequence of numbers
                import re
                numbers = re.findall(r'\d+', count)
                if numbers:
                    return int(numbers[0])
                return None
    return None

def process_company_batch(companies, country):
    """Process a batch of companies"""
    results = []
    total = len(companies)
    
    for i, company in enumerate(companies):
        try:
            print(f"Processing company {i+1}/{total}: {company}")
            
            # Skip empty company names
            if not company or not company.strip():
                results.append({
                    'company': company,
                    'status': 'error',
                    'error': 'Empty company name'
                })
                continue

            # Get company info
            info = search_web_info(company, country)
            if not info:
                results.append({
                    'company': company,
                    'status': 'error',
                    'error': 'No information found'
                })
                continue
                
            results.append(info)
            
        except Exception as e:
            print(f"Error processing {company}: {str(e)}")
            results.append({
                'company': company,
                'status': 'error',
                'error': str(e)
            })
            
    return results

@app.route('/')
def health_check():
    """Basic health check endpoint"""
    try:
        return jsonify({"status": "healthy"}), 200
    except Exception as e:
        print(f"Health check failed: {str(e)}")
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

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
def process_file():
    """Process uploaded file"""
    try:
        if request.method == 'OPTIONS':
            return handle_preflight()

        print(f"Starting file processing... Content-Type: {request.content_type}")
        print(f"Request headers: {dict(request.headers)}")
        
        # Get file from request
        if 'file' not in request.files:
            print("No file in request.files")
            print(f"Form data: {request.form}")
            print(f"Files: {request.files}")
            return jsonify({
                "error": "No file provided",
                "details": "The request must include a file in multipart/form-data"
            }), 400
            
        file = request.files['file']
        if not file or not file.filename:
            print("File object is empty or has no filename")
            return jsonify({
                "error": "Empty file provided",
                "details": "The uploaded file is empty or has no filename"
            }), 400

        # Get country from request
        country = request.form.get('country')
        if not country:
            print("No country specified")
            return jsonify({
                "error": "No country specified",
                "details": "Please select a country from the dropdown"
            }), 400

        print(f"Processing file '{file.filename}' for country: {country}")

        try:
            # Read CSV content with explicit encoding
            content = file.read()
            if not content:
                print("File content is empty")
                return jsonify({
                    "error": "Empty file content",
                    "details": "The uploaded file contains no data"
                }), 400
                
            try:
                content = content.decode('utf-8')
            except UnicodeDecodeError:
                print("Trying alternative encoding...")
                try:
                    content = content.decode('utf-8-sig')  # Try with BOM
                except UnicodeDecodeError as e:
                    return jsonify({
                        "error": "Invalid file encoding",
                        "details": "Please ensure the file is saved as UTF-8 encoded CSV"
                    }), 400
                
            print(f"Successfully read file content, length: {len(content)}")
            
            # Parse CSV data
            try:
                csv_data = list(csv.reader(StringIO(content)))
            except csv.Error as e:
                return jsonify({
                    "error": "Invalid CSV format",
                    "details": f"CSV parsing error: {str(e)}"
                }), 400

            if len(csv_data) < 2:
                print("CSV has less than 2 rows")
                return jsonify({
                    "error": "Invalid CSV format",
                    "details": "File must contain a header row and at least one data row"
                }), 400

            # Extract company names (skip header)
            companies = [row[0].strip() for row in csv_data[1:] if row and row[0].strip()]
            print(f"Found {len(companies)} companies")
            
            if not companies:
                return jsonify({
                    "error": "No valid company names",
                    "details": "No valid company names found in the first column"
                }), 400

            # Process in smaller batches to avoid timeouts
            batch_size = 2  # Process just 2 at a time
            all_results = []
            
            print(f"Processing companies in batches of {batch_size}")
            for i in range(0, len(companies), batch_size):
                batch = companies[i:i + batch_size]
                print(f"Processing batch {i//batch_size + 1}/{(len(companies) + batch_size - 1)//batch_size}")
                try:
                    results = process_company_batch(batch, country)
                    all_results.extend(results)
                except Exception as e:
                    print(f"Error processing batch: {str(e)}")
                    traceback.print_exc()
                    # Continue with next batch
                    all_results.extend([{
                        'company': company,
                        'status': 'error',
                        'error': f"Failed to process: {str(e)}"
                    } for company in batch])

            print("Creating output CSV...")
            # Create CSV from results
            output = BytesIO()  # Use BytesIO instead of StringIO
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(['Company', 'Employee Count', 'Confidence', 'Sources', 'Status', 'Error/Explanation'])
            
            # Write results
            for result in all_results:
                writer.writerow([
                    result.get('company', ''),
                    result.get('employee_count', ''),
                    result.get('confidence', ''),
                    result.get('sources', ''),
                    result.get('status', 'error'),
                    result.get('error', result.get('explanation', ''))
                ])
            
            print("Preparing file download...")
            # Prepare file for download
            output.seek(0)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'employee_counts_{timestamp}.csv'
            
            try:
                # Use send_file for proper file download handling
                return send_file(
                    output,
                    mimetype='text/csv',
                    as_attachment=True,
                    download_name=filename,
                    max_age=0
                )
            except Exception as e:
                print(f"Error sending file: {str(e)}")
                return jsonify({
                    "error": "Failed to generate download",
                    "details": str(e)
                }), 500
            
        except csv.Error as e:
            print(f"CSV parsing error: {str(e)}")
            return jsonify({
                "error": "Invalid CSV format",
                "details": str(e)
            }), 400
            
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        traceback.print_exc()
        return jsonify({
            "error": "Failed to process file",
            "details": str(e),
            "type": "network_error" if "Network" in str(e) else "processing_error"
        }), 500

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
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
