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
import redis
from rq import Queue
from rq.job import Job
import uuid
from datetime import datetime
import math

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app)

# Configure CORS to allow all origins
CORS(app, resources={
    r"/*": {
        "origins": ["https://finder-git-main-bycollexions-projects.vercel.app", "http://localhost:3000", "http://localhost:5173"],
        "methods": ["GET", "POST", "OPTIONS", "PUT", "DELETE"],
        "allow_headers": ["Content-Type", "Authorization", "Accept", "Origin", "X-Requested-With"],
        "expose_headers": ["Content-Type"],
        "supports_credentials": True
    }
})

def handle_preflight():
    """Handle CORS preflight request"""
    response = jsonify({})
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
    return response, 204

@app.after_request
def after_request(response):
    """Add CORS headers to all responses"""
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    return response

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
                
                DO NOT include news articles or press releases.
                Only return factual, verifiable information."""},
                {"role": "user", "content": f"Search for employee count information for {company} in {country}. Focus on LinkedIn, company website, and job sites only."}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        error_msg = str(e)
        if "quota" in error_msg.lower():
            return {"error": "quota_exceeded", "message": "API quota exceeded. Please try again later."}
        print(f"Error during web search: {error_msg}")
        return "Error occurred during search. Using available data for estimation."

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

def process_company_batch(companies, country, batch_id):
    """Process a batch of companies"""
    results = []
    quota_exceeded = False
    
    for company in companies:
        try:
            if quota_exceeded:
                results.append({
                    "company": company,
                    "error": "API quota exceeded. Please try again later.",
                    "status": "quota_exceeded"
                })
                continue

            web_info = search_web_info(company, country)
            if isinstance(web_info, dict) and web_info.get("error") == "quota_exceeded":
                quota_exceeded = True
                results.append({
                    "company": company,
                    "error": "API quota exceeded. Please try again later.",
                    "status": "quota_exceeded"
                })
                continue
            
            # Initial estimate using GPT-4
            try:
                response = call_openai_with_retry(
                    messages=[
                        {"role": "system", "content": """You are a company data analyst specializing in workforce analytics.
                        Your task is to determine EXACT employee counts for specific country offices. DO NOT provide ranges.
                        
                        ANALYSIS PRIORITIES:
                        1. LinkedIn Data (Primary Source):
                           - Use exact employee counts from LinkedIn
                           - Count employees who list the company and country
                           - Use job posting volume as a supporting indicator
                        
                        2. Official Sources (Secondary Source):
                           - Company career pages with exact team size
                           - Job postings with office size information
                           - Glassdoor/Indeed company information
                        
                        3. Office Information (Supporting Data):
                           - Exact office capacity numbers
                           - Specific floor space and employee density
                           - Precise office location data
                        
                        ESTIMATION RULES:
                        1. For All Companies:
                           - Focus ONLY on the specific country office
                           - Use ONLY current, verifiable data
                           - Count only full-time employees
                           - Exclude contractors unless specifically mentioned
                        
                        2. Data Priority:
                           - LinkedIn employee count is primary source
                           - Company career page data is secondary
                           - Job site information is tertiary
                        
                        3. Validation Rules:
                           - Cross-reference multiple sources
                           - Verify data is country-specific
                           - Check data is current (within last 6 months)
                        
                        CONFIDENCE LEVELS:
                        HIGH: Direct employee count from LinkedIn or company career page
                        MEDIUM: Derived from job postings and office data
                        LOW: Limited data available
                        
                        IMPORTANT:
                        - ALWAYS provide a single, specific number
                        - NO ranges or approximations
                        - Use the most recent data available
                        - If uncertain, use the lower estimate"""},
                        {"role": "user", "content": f"""Determine the EXACT employee count for {company}'s {country} office.
                        
                        Company: {company}
                        Country: {country}
                        Available Information:
                        {web_info}
                        
                        Requirements:
                        1. Provide ONE specific number
                        2. Focus ONLY on {country} employees
                        3. Use most recent data
                        4. No ranges or approximations"""}
                    ],
                    functions=[{
                        "name": "get_employee_count",
                        "description": "Get the exact number of employees at a company",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "employee_count": {
                                    "type": "integer",
                                    "description": "The exact number of employees (must be a specific integer)"
                                },
                                "confidence": {
                                    "type": "string",
                                    "enum": ["HIGH", "MEDIUM", "LOW"],
                                    "description": "Confidence level in the exact count"
                                },
                                "sources": {
                                    "type": "array",
                                    "items": {
                                        "type": "string"
                                    },
                                    "description": "Sources used to determine the exact count"
                                },
                                "explanation": {
                                    "type": "string",
                                    "description": "Explanation of how the exact number was determined"
                                }
                            },
                            "required": ["employee_count", "confidence", "sources", "explanation"]
                        }
                    }],
                    function_call={"name": "get_employee_count"}
                )
            except Exception as e:
                if "quota" in str(e).lower():
                    quota_exceeded = True
                    results.append({
                        "company": company,
                        "error": "API quota exceeded. Please try again later.",
                        "status": "quota_exceeded"
                    })
                    continue
                else:
                    raise e
                
            if response.choices[0].message.get("function_call"):
                initial_result = json.loads(response.choices[0].message["function_call"]["arguments"])
                
                # Validate employee count
                employee_count = validate_employee_count(initial_result.get("employee_count"))
                if employee_count is None:
                    raise ValueError(f"Invalid employee count received for {company}")
                initial_result["employee_count"] = employee_count
                
                # Have GPT-4 review the estimate with country-specific context
                try:
                    reviewed_result = review_employee_count(company, country, initial_result, web_info)
                except Exception as e:
                    if "quota" in str(e).lower():
                        # If quota exceeded during review, use initial result
                        reviewed_result = initial_result
                    else:
                        raise e
                
                # Validate reviewed count
                reviewed_count = validate_employee_count(reviewed_result.get("employee_count"))
                if reviewed_count is None:
                    # If review gives invalid count, use original
                    reviewed_result["employee_count"] = employee_count
                else:
                    reviewed_result["employee_count"] = reviewed_count
                
                results.append({
                    "company": company,
                    "employee_count": reviewed_result["employee_count"],
                    "confidence": reviewed_result["confidence"],
                    "sources": ", ".join(reviewed_result["sources"]),
                    "explanation": reviewed_result["explanation"],
                    "status": "success"
                })
                
                # Update progress in Redis if using it
                if using_redis:
                    processed = redis_client.hincrby(f"batch:{batch_id}", "processed", 1)
                    total = int(redis_client.hget(f"batch:{batch_id}", "total") or 0)
                    if processed >= total:
                        redis_client.hset(f"batch:{batch_id}", "status", "completed")
                        redis_client.set(f"results:{batch_id}", json.dumps(results))
                        
        except Exception as e:
            error_msg = str(e)
            if "quota" in error_msg.lower():
                status = "quota_exceeded"
                error_msg = "API quota exceeded. Please try again later."
            else:
                status = "error"
            
            results.append({
                "company": company,
                "error": error_msg,
                "status": status
            })
            
            if status == "quota_exceeded":
                quota_exceeded = True
                
    return results

@app.route('/')
def index():
    """Basic health check endpoint - doesn't check OpenAI"""
    try:
        # Only check Redis connection
        if using_redis:
            redis_client.ping()
            redis_status = "connected"
        else:
            redis_status = "using fallback"
            
        return jsonify({
            "status": "healthy",
            "time": time.time(),
            "redis": redis_status
        })
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "time": time.time()
        }), 500

@app.route('/health')
def health_check():
    """Full health check endpoint - includes OpenAI check"""
    try:
        # Check Redis
        redis_status = "not checked"
        if using_redis:
            redis_client.ping()
            redis_status = "connected"
        else:
            redis_status = "using fallback"

        # Check OpenAI - simple completion
        openai_status = "not checked"
        try:
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[{"role": "user", "content": "test"}],
                max_tokens=5
            )
            openai_status = "connected"
        except Exception as e:
            openai_status = f"error: {str(e)}"

        return jsonify({
            "status": "healthy",
            "time": time.time(),
            "redis": redis_status,
            "openai": openai_status
        })
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "time": time.time()
        }), 500

@app.route('/api/countries', methods=['GET', 'OPTIONS'])
def get_countries():
    """Get list of supported countries"""
    try:
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
        
        # Create response with CORS headers
        response = jsonify(countries)
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response

    except Exception as e:
        print(f"Error getting countries: {str(e)}")
        traceback.print_exc()
        error_response = jsonify({
            "error": "Failed to get countries",
            "details": str(e)
        })
        error_response.headers['Access-Control-Allow-Origin'] = '*'
        error_response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        error_response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
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
            batch_size = 5
            all_results = []
            
            print(f"Processing companies in batches of {batch_size}")
            for i in range(0, len(companies), batch_size):
                batch = companies[i:i + batch_size]
                print(f"Processing batch {i//batch_size + 1}/{(len(companies) + batch_size - 1)//batch_size}")
                try:
                    results = process_company_batch(batch, country, None)
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
            output = StringIO()
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
            # Create response with file download
            output.seek(0)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # Create response with all necessary headers
            response = make_response(output.getvalue())
            response.headers.update({
                'Content-Type': 'text/csv',
                'Content-Disposition': f'attachment; filename=employee_counts_{timestamp}.csv',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Access-Control-Expose-Headers': 'Content-Disposition'
            })
            return response

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

@app.route('/api/status/<batch_id>', methods=['GET'])
def get_status(batch_id):
    """Get the status of a batch processing job"""
    try:
        if not using_redis:
            return jsonify({"error": "Status tracking not available"}), 400

        status = redis_client.hget(f"batch:{batch_id}", "status")
        if not status:
            return jsonify({"error": "Batch not found"}), 404

        total = int(redis_client.hget(f"batch:{batch_id}", "total") or 0)
        processed = int(redis_client.hget(f"batch:{batch_id}", "processed") or 0)
        
        return jsonify({
            "status": status,
            "total": total,
            "processed": processed,
            "progress": (processed / total * 100) if total > 0 else 0
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/results/<batch_id>', methods=['GET'])
def get_results(batch_id):
    """Get the results of a completed batch"""
    try:
        if not using_redis:
            return jsonify({"error": "Results not available"}), 400

        results = redis_client.get(f"results:{batch_id}")
        if not results:
            return jsonify({"error": "Results not found"}), 404

        # Create CSV from results
        results = json.loads(results)
        output = StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow(['Company', 'Employee Count', 'Confidence', 'Sources', 'Status', 'Error/Explanation'])
        
        # Write results
        for result in results:
            writer.writerow([
                result.get('company', ''),
                result.get('employee_count', ''),
                result.get('confidence', ''),
                result.get('sources', ''),
                result.get('status', 'error'),
                result.get('error', result.get('explanation', ''))
            ])
        
        # Create response with file download
        output.seek(0)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return send_file(
            BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'employee_counts_{timestamp}.csv'
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
    wait=wait_exponential(multiplier=1, min=4, max=10),  # Shorter max wait to avoid worker timeout
    stop=stop_after_attempt(3)  # Fewer attempts
)
def call_openai_with_retry(messages, functions=None, function_call=None):
    """Make OpenAI API call with retry logic"""
    try:
        if functions:
            return openai.ChatCompletion.create(
                model="gpt-4",
                messages=messages,
                functions=functions,
                function_call=function_call,
                request_timeout=30  # 30 second timeout
            )
        return openai.ChatCompletion.create(
            model="gpt-4",
            messages=messages,
            request_timeout=30  # 30 second timeout
        )
    except RateLimitError as e:
        print(f"Rate limit error: {str(e)}")
        print("Rate limit reached. Waiting before retry...")
        raise  # Let retry handle it
    except APIError as e:
        print(f"API error: {str(e)}")
        print("API error occurred. Waiting before retry...")
        raise  # Let retry handle it
    except Exception as e:
        if "quota" in str(e).lower():
            raise RateLimitError("Quota exceeded")
        raise

# Configure Redis connection
redis_url = os.getenv('REDIS_URL', os.getenv('REDISCLOUD_URL'))  # Try both Railway and Redis Cloud URLs
redis_client = None
using_redis = False
queue = None

try:
    if redis_url:
        print(f"Attempting to connect to Redis using URL")
        # Parse Redis URL for connection
        redis_client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5
        )
    else:
        print("No Redis URL found, attempting local connection")
        # Fallback for local development
        redis_host = os.getenv('REDIS_HOST', 'localhost')
        redis_port = int(os.getenv('REDIS_PORT', 6379))
        redis_password = os.getenv('REDIS_PASSWORD')
        
        if redis_password:
            redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                password=redis_password,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5
            )
        else:
            redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5
            )
    
    # Test the connection
    redis_client.ping()
    print("Successfully connected to Redis")
    using_redis = True
    # Configure RQ queue
    queue = Queue(connection=redis_client)
except (redis.ConnectionError, redis.TimeoutError) as e:
    print(f"Failed to connect to Redis: {e}")
    print("Environment variables available:", ", ".join([k for k in os.environ.keys() if 'REDIS' in k.upper()]))
    # Fallback to using local memory if Redis is not available
    from fakeredis import FakeRedis
    redis_client = FakeRedis(decode_responses=True)
    print("Using in-memory Redis mock for development")
    using_redis = False
    queue = None

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
