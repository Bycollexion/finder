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
        # Create targeted queries for different sources
        queries = [
            # LinkedIn data (primary source)
            f"{company_name} {country} site:linkedin.com employees",
            f"{company_name} {country} site:linkedin.com company size",
            f"{company_name} {country} site:linkedin.com/company headquarters",
            f"{company_name} {country} site:linkedin.com/company office",
            
            # Official company sources
            f"{company_name} {country} careers number of employees",
            f"{company_name} {country} jobs team size",
            f"{company_name} {country} official office employees",
            f"{company_name} {country} headquarters staff size",
            
            # Business directories (verified data)
            f"{company_name} {country} site:glassdoor.com size",
            f"{company_name} {country} site:glassdoor.com office",
            f"{company_name} {country} site:ambitionbox.com employees",
            
            # Location specific
            f"{company_name} office location {country} employees",
            f"{company_name} {country} regional headquarters size"
        ]
        
        # Search and combine results, prioritizing LinkedIn and official sources
        all_results = []
        linkedin_results = []
        official_results = []
        directory_results = []
        
        for query in queries:
            try:
                search_results = search_web({"query": query})
                if search_results:
                    for result in search_results:
                        try:
                            content = read_url_content({"Url": result["url"]})
                            if not content:
                                continue
                                
                            result_entry = f"Source ({result['url']}): {content}"
                            
                            # Categorize results by source
                            if "linkedin.com" in result["url"].lower():
                                linkedin_results.append(result_entry)
                            elif company_name.lower() in result["url"].lower():
                                official_results.append(result_entry)
                            elif any(domain in result["url"].lower() for domain in [
                                "glassdoor.com", "ambitionbox.com"
                            ]):
                                directory_results.append(result_entry)
                                
                        except Exception as e:
                            print(f"Error reading content from {result['url']}: {e}")
                            continue
                            
            except Exception as e:
                print(f"Error searching for {query}: {e}")
                continue
        
        # Combine results in priority order
        all_results.extend(linkedin_results)    # LinkedIn data first
        all_results.extend(official_results)    # Official company sources second
        all_results.extend(directory_results)   # Business directories last
        
        if all_results:
            return "\n\n".join(all_results)
            
        # If no results found, try a more general search on LinkedIn and official sites
        try:
            general_queries = [
                f"{company_name} {country} site:linkedin.com",
                f"{company_name} {country} careers"
            ]
            general_content = []
            
            for general_query in general_queries:
                general_results = search_web({"query": general_query})
                if general_results:
                    for result in general_results:
                        try:
                            content = read_url_content({"Url": result["url"]})
                            if content:
                                general_content.append(f"Source ({result['url']}): {content}")
                        except Exception as e:
                            continue
                            
            if general_content:
                return "\n\n".join(general_content)
                
        except Exception as e:
            print(f"Error in general search: {e}")
        
        return "No specific information found. Using regional knowledge for estimation."
        
    except Exception as e:
        print(f"Error during web search: {str(e)}")
        return "Error occurred during search. Using regional knowledge for estimation."

def review_employee_count(company, country, initial_result, web_info):
    """Have GPT-4 review the initial employee count estimate"""
    try:
        response = call_openai_with_retry(
            messages=[
                {"role": "system", "content": f"""You are a senior data analyst reviewing employee count estimates.
                Your job is to validate and potentially adjust estimates based on the following criteria:

                VALIDATION CHECKLIST:
                1. Check if the estimate matches known patterns for {country}:
                   
                   TECH MNC OFFICE SIZES BY COUNTRY:
                   Singapore:
                   * Regional HQ: 1000-5000+ employees
                   * Tech Hub: 500-2000 employees
                   * Sales/Support: 100-500 employees

                   Malaysia:
                   * Regional HQ: 500+ employees
                   * Development Center: 200-500 employees
                   * Regional Office: 50-200 employees
                   * Sales/Support: 10-50 employees

                   Indonesia:
                   * Country HQ: 500-2000 employees
                   * Tech Center: 200-1000 employees
                   * Regional: 100-500 employees
                   * Sales: 50-200 employees

                   Vietnam:
                   * Tech Hub: 500-2000 employees
                   * Dev Center: 200-1000 employees
                   * Sales: 50-200 employees

                   Thailand:
                   * Country HQ: 200-1000 employees
                   * Tech/Support: 100-500 employees
                   * Sales: 50-200 employees

                   Philippines:
                   * Support Hub: 500-2000 employees
                   * Tech Center: 200-1000 employees
                   * Sales: 50-200 employees

                   Japan:
                   * Country HQ: 1000-5000+ employees
                   * Tech Center: 500-2000 employees
                   * Regional: 200-1000 employees

                   South Korea:
                   * Country HQ: 1000-5000+ employees
                   * R&D Center: 500-2000 employees
                   * Sales: 100-500 employees

                   China:
                   * Country HQ: 2000-10000+ employees
                   * R&D Centers: 1000-5000 employees
                   * Regional: 500-2000 employees
                   * City Office: 100-500 employees

                   Hong Kong:
                   * Regional HQ: 500-2000 employees
                   * Financial: 200-1000 employees
                   * Sales: 100-500 employees

                   Taiwan:
                   * R&D Center: 500-2000 employees
                   * Country HQ: 200-1000 employees
                   * Sales: 100-500 employees

                   Australia:
                   * Country HQ: 1000-5000+ employees
                   * Tech Hub: 500-2000 employees
                   * Regional: 200-1000 employees
                   * Sales: 100-500 employees

                   TECH STARTUP SIZES BY FUNDING (All Countries):
                   * Seed: 5-20 employees
                   * Series A: 20-50 employees
                   * Series B: 50-200 employees
                   * Series C+: 200-1000+ employees

                   TRADITIONAL INDUSTRIES BY COUNTRY TIER:
                   Tier 1 (SG, JP, KR, AU):
                   * Manufacturing: 200-2000+ per facility
                   * Retail: 20-100 per location
                   * Services: 50-200 per office
                   * Banks: 100-500 per major branch

                   Tier 2 (HK, TW, MY):
                   * Manufacturing: 100-1000 per facility
                   * Retail: 10-50 per location
                   * Services: 20-100 per office
                   * Banks: 50-200 per major branch

                   Tier 3 (ID, TH, VN, PH):
                   * Manufacturing: 200-2000+ per facility (labor intensive)
                   * Retail: 5-30 per location
                   * Services: 10-50 per office
                   * Banks: 20-100 per major branch

                   China (Special Case):
                   * Manufacturing: 500-5000+ per facility
                   * Retail: 10-50 per location
                   * Services: 50-200 per office
                   * Banks: 100-500 per major branch
                   
                2. Common Red Flags:
                   - Numbers too high for market size
                   - Global numbers instead of local office
                   - Outdated or pre-pandemic numbers
                   - Inconsistent with office location/type
                
                3. Location-Based Validation:
                   SINGAPORE:
                   - CBD/Marina Bay: Finance/Tech HQs (500-2000)
                   - One-North: R&D/Tech (200-1000)
                   - Changi: Support Centers (100-500)

                   MALAYSIA:
                   - KL Sentral/Bangsar South: Tech (50-200)
                   - KLCC/Central: Corporate (100-300)
                   - Cyberjaya: Support/Dev (200-500)

                   INDONESIA:
                   - Jakarta CBD: Corporate (200-1000)
                   - BSD City: Tech Hub (100-500)
                   - Industrial: Manufacturing (500-2000)

                   VIETNAM:
                   - HCMC D1/D2: Corporate (100-500)
                   - Hanoi West: Tech Hub (200-1000)
                   - Industrial Parks: Manufacturing (1000-5000)

                   THAILAND:
                   - Sukhumvit: Corporate (100-500)
                   - Sathorn: Finance (200-1000)
                   - Eastern Seaboard: Manufacturing (500-2000)

                   PHILIPPINES:
                   - BGC/Makati: Corporate (200-1000)
                   - Cebu IT Park: Support (500-2000)
                   - Clark/Subic: Manufacturing (1000-5000)

                4. Industry-Specific Checks:
                   - Tech: Compare with similar tech companies in same city
                   - Manufacturing: Check against facility size and automation level
                   - Services: Validate against market share and city tier
                   - Retail: Cross-check with store count and country tier

                If you find issues:
                1. Adjust the number to a more realistic range for the specific country
                2. Update the confidence level if needed
                3. Add your reasoning to the explanation
                4. Add "REVIEWED" to the sources list

                If the estimate looks correct:
                1. Confirm the number
                2. Add validation notes
                3. Add "VALIDATED" to the sources list"""},
                {"role": "user", "content": f"""Review this employee count estimate for {company} in {country}:

Initial Estimate:
- Count: {initial_result.get('employee_count')}
- Confidence: {initial_result.get('confidence')}
- Sources: {initial_result.get('sources')}
- Explanation: {initial_result.get('explanation')}

Available Information:
{web_info}

Is this estimate realistic for {country}? Should it be adjusted based on the country-specific patterns?"""}
            ],
            functions=[{
                "name": "review_estimate",
                "description": "Review and potentially adjust the employee count estimate",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "employee_count": {
                            "type": "integer",
                            "description": "The validated or adjusted employee count"
                        },
                        "confidence": {
                            "type": "string",
                            "enum": ["HIGH", "MEDIUM", "LOW"],
                            "description": "Updated confidence level in the count"
                        },
                        "sources": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Updated list of sources, including review status"
                        },
                        "explanation": {
                            "type": "string",
                            "description": "Updated explanation including review notes"
                        },
                        "was_adjusted": {
                            "type": "boolean",
                            "description": "Whether the estimate was adjusted during review"
                        }
                    },
                    "required": ["employee_count", "confidence", "sources", "explanation", "was_adjusted"]
                }
            }],
            function_call={"name": "review_estimate"}
        )
        
        if response.choices[0].message.get("function_call"):
            return json.loads(response.choices[0].message["function_call"]["arguments"])
        return initial_result
        
    except Exception as e:
        print(f"Error during review: {str(e)}")
        return initial_result

def validate_employee_count(count):
    """Validate and clean employee count value"""
    if isinstance(count, int):
        return count
    if isinstance(count, str):
        # Remove any non-numeric characters
        cleaned = ''.join(c for c in count if c.isdigit())
        if cleaned:
            try:
                return int(cleaned)
            except ValueError:
                return None
    return None

def process_company_batch(companies, country, batch_id):
    """Process a batch of companies"""
    results = []
    for company in companies:
        try:
            web_info = search_web_info(company, country)
            
            # Initial estimate
            response = call_openai_with_retry(
                messages=[
                    {"role": "system", "content": """You are a company data analyst specializing in workforce analytics.
                    Your task is to analyze company information and provide accurate employee counts for specific country offices.
                    
                    ANALYSIS PRIORITIES:
                    1. LinkedIn Data:
                       - Look for specific employee counts or ranges for the country
                       - Check number of employees who list the company and country
                       - Analyze job postings volume in the country
                    
                    2. Official Sources:
                       - Company career pages showing local team size
                       - Official announcements about office size/expansion
                       - Press releases about local operations
                    
                    3. Office Information:
                       - Office locations and their typical capacity
                       - Number of offices in the country
                       - Office type (HQ, R&D, Sales, etc.)
                    
                    ESTIMATION RULES:
                    1. For MNCs (like Google, Meta, Amazon):
                       - Focus ONLY on the specific country office
                       - DO NOT use global employee counts
                       - Consider office type and location
                       - Compare with similar companies in the same area
                    
                    2. For Regional Companies (like Grab, Shopee):
                       - Consider if it's their home market
                       - Look at office locations and types
                       - Factor in market share in the country
                    
                    3. For Local Companies:
                       - Use direct local employee data
                       - Consider market presence and coverage
                       - Factor in industry standards
                    
                    CONFIDENCE LEVELS:
                    HIGH: Direct employee count from LinkedIn or official sources
                    MEDIUM: Clear office information or consistent indirect data
                    LOW: Only regional patterns or limited information
                    
                    IMPORTANT:
                    - Always return conservative estimates
                    - Prefer hard data over assumptions
                    - Consider recent market conditions
                    - Flag if numbers seem unusually high/low"""},
                    {"role": "user", "content": f"""Analyze this information and provide an accurate employee count for {company}'s {country} office.
                    
                    Company: {company}
                    Country: {country}
                    Available Information:
                    {web_info}
                    
                    Remember:
                    1. Focus ONLY on {country} employees
                    2. Do not use global numbers
                    3. Be conservative in estimates
                    4. Consider the type of company and office"""}
                ],
                functions=[{
                    "name": "get_employee_count",
                    "description": "Get the number of employees at a company",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "employee_count": {
                                "type": "integer",
                                "description": "The number of employees at the company (must be a plain integer)"
                            },
                            "confidence": {
                                "type": "string",
                                "enum": ["HIGH", "MEDIUM", "LOW"],
                                "description": "Confidence level in the employee count"
                            },
                            "sources": {
                                "type": "array",
                                "items": {
                                    "type": "string"
                                },
                                "description": "List of sources used to determine the count"
                            },
                            "explanation": {
                                "type": "string",
                                "description": "Brief explanation of the reasoning"
                            }
                        },
                        "required": ["employee_count", "confidence", "sources", "explanation"]
                    }
                }],
                function_call={"name": "get_employee_count"}
            )
            
            if response.choices[0].message.get("function_call"):
                initial_result = json.loads(response.choices[0].message["function_call"]["arguments"])
                
                # Validate employee count
                employee_count = validate_employee_count(initial_result.get("employee_count"))
                if employee_count is None:
                    raise ValueError(f"Invalid employee count received for {company}")
                initial_result["employee_count"] = employee_count
                
                # Have GPT-4 review the estimate with country-specific context
                reviewed_result = review_employee_count(company, country, initial_result, web_info)
                
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
                    "was_adjusted": reviewed_result.get("was_adjusted", False)
                })
            else:
                results.append({
                    "company": company,
                    "error": "Failed to process company information"
                })
                
            # Update progress in Redis if using it
            if using_redis:
                processed = redis_client.hincrby(f"batch:{batch_id}", "processed", 1)
                total = int(redis_client.hget(f"batch:{batch_id}", "total") or 0)
                if processed >= total:
                    redis_client.hset(f"batch:{batch_id}", "status", "completed")
                    redis_client.set(f"results:{batch_id}", json.dumps(results))
                    
        except Exception as e:
            print(f"Error processing company {company}: {str(e)}")
            results.append({
                "company": company,
                "error": str(e)
            })
    
    return results

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
                writer.writerow(['Company', 'Employee Count', 'Confidence', 'Sources', 'Explanation', 'Was Adjusted', 'Error'])
                
                for result in results:
                    if 'error' in result:
                        writer.writerow([result['company'], '', '', '', '', '', result['error']])
                    else:
                        writer.writerow([
                            result['company'],
                            result.get('employee_count', ''),
                            result.get('confidence', ''),
                            result.get('sources', ''),
                            result.get('explanation', ''),
                            'Yes' if result.get('was_adjusted', False) else 'No',
                            ''
                        ])
                
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
                print(f"Error processing file: {str(e)}")
                return jsonify({"error": str(e)}), 500
            
    except Exception as e:
        print(f"Error in process_file: {str(e)}")
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
