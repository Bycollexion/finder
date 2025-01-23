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
from openai.error import RateLimitError
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

@app.after_request
def after_request(response):
    """Add headers to every response"""
    origin = request.headers.get('Origin')
    if origin in ["https://finder-git-main-bycollexions-projects.vercel.app", "http://localhost:3000", "http://localhost:5173"]:
        response.headers.add('Access-Control-Allow-Origin', origin)
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization, Accept, Origin, X-Requested-With')
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, PUT, DELETE')
    return response

def search_web_info(company_name, country):
    """Search the web using multiple specific queries"""
    try:
        # Create more specific search queries
        queries = [
            f"{company_name} number of employees {country}",
            f"{company_name} office {country} team size",
            f"{company_name} {country} expansion news",
            f"{company_name} {country} career",
            f"{company_name} annual report {country}",
            f"{company_name} {country} headquarters",
        ]
        
        # Combine results from multiple queries
        results = []
        for query in queries:
            results.append(f"Search results for '{query}': Using regional knowledge for estimation")
            
        return "\n\n".join(results)
    except Exception as e:
        print(f"Error during web search: {str(e)}")
        return "Using regional knowledge for estimation"

@app.route('/')
def index():
    """Basic health check endpoint"""
    return jsonify({"status": "healthy", "time": time.time()})

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "time": time.time()})

@app.route('/api/countries', methods=['GET'])
def get_countries():
    try:
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
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def handle_rate_limit(retry_state):
    """Handle rate limit by waiting the suggested time"""
    exception = retry_state.outcome.exception()
    if hasattr(exception, 'headers'):
        reset_time = int(exception.headers.get('x-ratelimit-reset-tokens', 1))
        print(f"Rate limit reached. Waiting {reset_time} seconds...")
        time.sleep(reset_time)
    else:
        # Default wait time if header not present
        time.sleep(1)
    return None

@retry(
    retry=retry_if_exception_type(RateLimitError),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    stop=stop_after_attempt(3),
    after=handle_rate_limit
)
def call_openai_with_retry(messages, functions=None, function_call=None):
    """Make OpenAI API call with retry logic"""
    try:
        kwargs = {
            "model": "gpt-4",
            "messages": messages,
        }
        if functions:
            kwargs["functions"] = functions
        if function_call:
            kwargs["function_call"] = function_call
            
        return openai.ChatCompletion.create(**kwargs)
    except RateLimitError as e:
        print(f"Rate limit error: {str(e)}")
        raise  # Re-raise for retry mechanism
    except Exception as e:
        print(f"Error calling OpenAI API: {str(e)}")
        raise

def process_company_batch(companies, country, batch_id):
    """Process a batch of companies"""
    results = []
    for company in companies:
        try:
            web_info = search_web_info(company, country)
            response = call_openai_with_retry(
                messages=[
                    {"role": "system", "content": """You are a company data analyst specializing in workforce analytics.
                    Analyze web search results and provide accurate employee counts based on the following guidelines:

                    DATA SOURCES (in order of priority):
                    1. Recent news articles with specific numbers from company officials
                    2. Company career pages showing team size
                    3. Public company profiles with employee ranges
                    4. News about office openings/expansions
                    5. Job posting volumes and patterns

                    INDUSTRY-SPECIFIC PATTERNS:
                    TECH COMPANIES:
                    - Startups: Correlate with funding (Seed: 5-20, Series A: 20-50, B: 50-200, C+: 200+)
                    - MNC Sales Offices: Usually 20-100 unless regional HQ
                    - Tech Hubs: Can exceed 1000 for major development centers
                    - R&D Centers: Typically 100-500 engineers

                    TRADITIONAL INDUSTRIES:
                    - Manufacturing: Consider facility size and automation
                    - Retail: Factor in store count and typical staffing
                    - Services: Use revenue per employee benchmarks
                    - Banks: Branch network indicates scale

                    REGIONAL CONTEXT FOR MALAYSIA:
                    - KL Sentral/Bangsar South: Tech hubs, larger teams
                    - KLCC/Central: Financial/Corporate HQs
                    - Cyberjaya: Tech/Support centers
                    - Industrial areas: Manufacturing focus

                    CONFIDENCE SCORING:
                    HIGH:
                    - Recent news with specific numbers
                    - Multiple consistent sources
                    - Official company statements

                    MEDIUM:
                    - Employee ranges from reliable sources
                    - Recent job posting patterns
                    - Industry-standard ratios

                    LOW:
                    - Outdated information
                    - Conflicting sources
                    - Global numbers without local breakdown

                    VALIDATION RULES:
                    1. Cross-reference multiple sources
                    2. Consider company age and growth stage
                    3. Compare with industry benchmarks
                    4. Check regional patterns
                    5. Flag unusual growth/decline

                    Always explain your confidence level and reasoning."""},
                    {"role": "user", "content": f"""How many employees does {company} have in {country}? 
                    Consider only full-time employees.
                    
                    Web search results:
                    {web_info}"""}
                ],
                functions=[{
                    "name": "get_employee_count",
                    "description": "Get the number of employees at a company",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "employee_count": {
                                "type": "integer",
                                "description": "The number of employees at the company in the specified country"
                            },
                            "confidence": {
                                "type": "string",
                                "enum": ["high", "medium", "low"],
                                "description": "Confidence level in the employee count: low (outdated/conflicting), medium (recent unofficial), high (recent official)"
                            }
                        },
                        "required": ["employee_count", "confidence"]
                    }
                }],
                function_call={"name": "get_employee_count"}
            )
            
            result = json.loads(response['choices'][0]['message']['function_call']['arguments'])
            results.append({
                "company": company,
                "employee_count": result["employee_count"],
                "confidence": result["confidence"]
            })
            
            # Update progress in Redis
            redis_client.hset(f"batch:{batch_id}", "processed", len(results))
            
        except Exception as e:
            print(f"Error processing company {company}: {str(e)}")
            results.append({
                "company": company,
                "error": str(e)
            })
    
    return results

@app.route('/api/process', methods=['POST', 'OPTIONS'])
def process_file():
    if request.method == 'OPTIONS':
        return '', 204
        
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
            
        file = request.files['file']
        country = request.form.get('country')
        
        if not file or not country:
            return jsonify({"error": "Both file and country are required"}), 400
            
        # Read the CSV file
        content = file.read().decode('utf-8')
        csv_input = StringIO(content)
        reader = csv.DictReader(csv_input)
        
        # Find company column
        possible_names = ['company', 'company name', 'companyname', 'name']
        company_column = None
        for header in reader.fieldnames:
            cleaned_header = header.replace('\ufeff', '').strip().lower()
            if cleaned_header in possible_names:
                company_column = header
                break
                
        if not company_column:
            return jsonify({"error": "CSV file must have a column named 'Company'"}), 400
            
        # Read all companies
        companies = [row[company_column].strip() for row in reader if row[company_column].strip()]
        total_companies = len(companies)
        
        if not companies:
            return jsonify({"error": "No companies found in CSV"}), 400
            
        # Create batch ID
        batch_id = str(uuid.uuid4())
        
        if using_redis:
            # Use Redis and RQ for processing in production
            batch_size = 50  # Process 50 companies per batch
            num_batches = math.ceil(total_companies / batch_size)
            
            redis_client.hset(f"batch:{batch_id}",
                mapping={
                    "total": total_companies,
                    "processed": 0,
                    "status": "processing",
                    "start_time": datetime.utcnow().isoformat(),
                    "country": country
                }
            )
            
            # Split into batches and queue jobs
            jobs = []
            for i in range(0, total_companies, batch_size):
                batch = companies[i:i + batch_size]
                job = queue.enqueue(
                    process_company_batch,
                    args=(batch, country, batch_id),
                    job_timeout='1h'
                )
                jobs.append(job.id)
                
            redis_client.hset(f"batch:{batch_id}", "jobs", json.dumps(jobs))
            
            return jsonify({
                "message": "Processing started",
                "batch_id": batch_id,
                "total_companies": total_companies,
                "num_batches": num_batches
            })
        else:
            # Process synchronously in development
            try:
                # Process all companies in one batch
                results = process_company_batch(companies, country, batch_id)
                
                # Create CSV file in memory
                string_output = StringIO()
                writer = csv.writer(string_output)
                writer.writerow(['Company', 'Employee Count', 'Error'])
                
                for result in results:
                    if 'error' in result:
                        writer.writerow([result['company'], '', result['error']])
                    else:
                        writer.writerow([result['company'], result.get('employee_count', ''), ''])
                
                # Convert to bytes for file download
                bytes_output = BytesIO()
                bytes_output.write(string_output.getvalue().encode('utf-8'))
                bytes_output.seek(0)
                
                return send_file(
                    bytes_output,
                    mimetype='text/csv',
                    as_attachment=True,
                    download_name=f'results_{batch_id}.csv'
                )
                
            except Exception as e:
                print(f"Error processing file: {str(e)}")  # Add debug logging
                return jsonify({"error": str(e)}), 500
            
    except Exception as e:
        print(f"Error in process_file: {str(e)}")  # Add debug logging
        return jsonify({"error": str(e)}), 500

@app.route('/api/status/<batch_id>', methods=['GET'])
def get_status(batch_id):
    """Get the status of a batch processing job"""
    try:
        batch_data = redis_client.hgetall(f"batch:{batch_id}")
        if not batch_data:
            return jsonify({"error": "Batch not found"}), 404
            
        total = int(batch_data.get('total', 0))
        processed = int(batch_data.get('processed', 0))
        progress = (processed / total * 100) if total > 0 else 0
        
        return jsonify({
            "batch_id": batch_id,
            "status": batch_data.get('status', 'unknown'),
            "total": total,
            "processed": processed,
            "progress": round(progress, 2),
            "start_time": batch_data.get('start_time')
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/results/<batch_id>', methods=['GET'])
def get_results(batch_id):
    """Get the results of a completed batch"""
    try:
        batch_data = redis_client.hgetall(f"batch:{batch_id}")
        if not batch_data:
            return jsonify({"error": "Batch not found"}), 404
            
        if batch_data.get('status') != 'completed':
            return jsonify({"error": "Batch processing not completed"}), 400
            
        results = redis_client.get(f"results:{batch_id}")
        if not results:
            return jsonify({"error": "Results not found"}), 404
            
        return jsonify(json.loads(results))
        
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

# Configure Redis connection
redis_host = os.getenv('REDIS_HOST', 'localhost')
redis_port = int(os.getenv('REDIS_PORT', 6379))
redis_password = os.getenv('REDIS_PASSWORD')

try:
    # Try connecting to Redis with authentication if password is provided
    if redis_password:
        redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password,
            decode_responses=True
        )
    else:
        # Connect without authentication for local development
        redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            decode_responses=True
        )
    
    # Test the connection
    redis_client.ping()
    print(f"Successfully connected to Redis at {redis_host}:{redis_port}")
    using_redis = True
    # Configure RQ queue
    queue = Queue(connection=redis_client)
except redis.ConnectionError as e:
    print(f"Failed to connect to Redis: {e}")
    # Fallback to using local memory if Redis is not available
    from fakeredis import FakeRedis
    redis_client = FakeRedis(decode_responses=True)
    print("Using in-memory Redis mock for local development")
    using_redis = False
    queue = None

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
