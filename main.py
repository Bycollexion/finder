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
from googleapiclient.discovery import build

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

def search_google_custom(company_name, country):
    """Search using Google Custom Search API"""
    try:
        # Get API key and Search Engine ID from environment variables
        api_key = os.getenv('GOOGLE_API_KEY')
        search_id = os.getenv('GOOGLE_SEARCH_ID')
        
        if not api_key or not search_id:
            print("Google API key or Search Engine ID not found")
            return []

        # Create search queries
        queries = [
            # LinkedIn data (primary source)
            f'"{company_name}" "{country}" employees site:linkedin.com/company',
            f'"{company_name}" "{country}" "number of employees" site:linkedin.com/company',
            f'"{company_name}" "{country}" "team size" site:linkedin.com/company',
            
            # Career pages and job postings
            f'"{company_name}" "{country}" careers "join our team"',
            f'"{company_name}" "{country}" "current openings" "team size"',
            f'"{company_name}" "{country}" "team of" site:linkedin.com/jobs',
            
            # Official sources
            f'"{company_name}" "{country}" office employees',
            f'"{company_name}" "{country}" headquarters staff',
            
            # Business directories
            f'"{company_name}" "{country}" employees site:glassdoor.com',
            f'"{company_name}" "{country}" size site:glassdoor.com'
        ]

        # Initialize the Custom Search API service
        service = build("customsearch", "v1", developerKey=api_key)

        all_results = []
        for query in queries:
            try:
                # Execute the search
                result = service.cse().list(
                    q=query,
                    cx=search_id,  # Use the environment variable
                    num=10  # Number of results per query
                ).execute()

                # Extract and store relevant information
                if 'items' in result:
                    for item in result['items']:
                        result_data = {
                            'title': item.get('title', ''),
                            'snippet': item.get('snippet', ''),
                            'link': item.get('link', ''),
                            'source': 'linkedin.com' if 'linkedin.com' in item.get('link', '') else 'other'
                        }
                        all_results.append(result_data)

            except Exception as e:
                print(f"Error searching for query '{query}': {str(e)}")
                continue

        return all_results

    except Exception as e:
        print(f"Error in Google Custom Search: {str(e)}")
        return []

def review_employee_count(company, country, initial_result, web_info):
    """Review and validate employee count based on company type and country patterns"""
    try:
        # Prepare company name variations for better matching
        company_variations = [
            company.lower(),
            company.lower().replace(" ", ""),
            company.lower().replace(".", "")
        ]
        
        # Detect company type
        mnc_companies = ["google", "meta", "facebook", "amazon", "microsoft", "apple"]
        regional_tech = ["grab", "shopee", "lazada", "sea", "gojek", "tokopedia", "goto"]
        
        company_type = "local"
        if any(name in company_variations for name in mnc_companies):
            company_type = "mnc"
        elif any(name in company_variations for name in regional_tech):
            company_type = "regional"

        # Country-specific office patterns
        country_patterns = {
            "malaysia": {
                "mnc": {
                    "ranges": {
                        "small": (100, 500),    # Sales/Support offices
                        "medium": (500, 1000),  # Regional offices
                        "large": (1000, 2000)   # Major development centers
                    },
                    "locations": {
                        "klcc": "medium",
                        "bangsar": "medium",
                        "cyberjaya": "large",
                        "penang": "medium"
                    }
                },
                "regional": {
                    "ranges": {
                        "small": (500, 1000),   # Market entry
                        "medium": (1000, 2000), # Established
                        "large": (2000, 5000)   # Major market
                    }
                },
                "local": {
                    "ranges": {
                        "small": (50, 200),
                        "medium": (200, 1000),
                        "large": (1000, 3000)
                    }
                }
            },
            # Add patterns for other countries...
        }

        # Get initial count
        count = initial_result.get('employee_count')
        confidence = initial_result.get('confidence', 'LOW')
        sources = initial_result.get('sources', [])
        explanation = initial_result.get('explanation', '')

        # Skip validation if no count
        if not count:
            return initial_result

        # Get patterns for this company type and country
        country_info = country_patterns.get(country.lower(), {})
        company_patterns = country_info.get(company_type, {})
        
        # Validate against patterns
        ranges = company_patterns.get('ranges', {})
        is_valid = False
        size_category = None
        
        for category, (min_val, max_val) in ranges.items():
            if min_val <= count <= max_val:
                is_valid = True
                size_category = category
                break

        # Check for outliers
        if not is_valid:
            closest_range = min(ranges.items(), key=lambda x: min(
                abs(count - x[1][0]),  # Distance from min
                abs(count - x[1][1])   # Distance from max
            ))
            
            # Adjust if significantly off
            if count < closest_range[1][0] * 0.5 or count > closest_range[1][1] * 1.5:
                # Get the midpoint of the closest range
                adjusted_count = sum(closest_range[1]) // 2
                explanation += f"\nAdjusted from {count} to {adjusted_count} based on {country} {company_type} company patterns."
                count = adjusted_count
                confidence = 'LOW'  # Lower confidence due to adjustment
                sources.append("ADJUSTED")

        # Location-based validation for MNCs
        if company_type == "mnc":
            locations = company_patterns.get('locations', {})
            for location, expected_size in locations.items():
                if location in web_info.lower():
                    expected_range = ranges.get(expected_size, (0, 0))
                    if count < expected_range[0] * 0.5 or count > expected_range[1] * 1.5:
                        adjusted_count = sum(expected_range) // 2
                        explanation += f"\nAdjusted to {adjusted_count} based on {location} office patterns."
                        count = adjusted_count
                        confidence = 'MEDIUM'  # Location-based adjustment is more reliable
                        sources.append(f"LOCATION_{location.upper()}")

        # Additional validation for regional tech companies
        if company_type == "regional":
            # Check if it's their home market
            home_markets = {
                "grab": "singapore",
                "shopee": "singapore",
                "lazada": "singapore",
                "sea": "singapore",
                "gojek": "indonesia",
                "tokopedia": "indonesia",
                "goto": "indonesia"
            }
            
            company_lower = next((name for name in company_variations if name in home_markets), None)
            if company_lower:
                is_home_market = home_markets[company_lower] == country.lower()
                if is_home_market and count < ranges['large'][0]:
                    adjusted_count = sum(ranges['large']) // 2
                    explanation += f"\nAdjusted up to {adjusted_count} as {country} is the home market."
                    count = adjusted_count
                    confidence = 'MEDIUM'
                    sources.append("HOME_MARKET")
                elif not is_home_market and count > ranges['medium'][1]:
                    adjusted_count = sum(ranges['medium']) // 2
                    explanation += f"\nAdjusted down to {adjusted_count} as {country} is not the home market."
                    count = adjusted_count
                    confidence = 'MEDIUM'
                    sources.append("FOREIGN_MARKET")

        return {
            "employee_count": count,
            "confidence": confidence,
            "sources": sources,
            "explanation": explanation.strip(),
            "was_adjusted": "ADJUSTED" in sources or "LOCATION" in str(sources) or "MARKET" in str(sources)
        }

    except Exception as e:
        print(f"Error in review: {str(e)}")
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
    
    for company in companies:
        try:
            web_info = search_web_info(company, country)
            google_custom_results = search_google_custom(company, country)
            analyzed_result = analyze_search_results(company, country, google_custom_results)
            
            if analyzed_result:
                initial_result = analyzed_result
            else:
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

def analyze_search_results(company, country, search_results):
    """Analyze search results using GPT-4"""
    try:
        # Organize results by source
        organized_results = {
            "linkedin_data": [],
            "official_statements": [],
            "job_postings": [],
            "other_sources": []
        }

        for result in search_results:
            if 'linkedin.com/company' in result['link']:
                organized_results['linkedin_data'].append(result)
            elif 'linkedin.com/jobs' in result['link']:
                organized_results['job_postings'].append(result)
            elif company.lower() in result['link'].lower():
                organized_results['official_statements'].append(result)
            else:
                organized_results['other_sources'].append(result)

        # Create GPT-4 prompt
        prompt = f"""Analyze these search results to determine employee count for {company} in {country}.

SEARCH RESULTS:

LinkedIn Company Data:
{format_results(organized_results['linkedin_data'])}

Official Statements:
{format_results(organized_results['official_statements'])}

Job Postings:
{format_results(organized_results['job_postings'])}

Other Sources:
{format_results(organized_results['other_sources'])}

Focus on:
1. Direct mentions of employee numbers
2. Recent data (within last year)
3. Country-specific information
4. Consistency across sources
5. Context of numbers (global vs local)

Provide:
1. Most likely employee count
2. Confidence level
3. Sources used
4. Key evidence
5. Any conflicting data"""

        # Call GPT-4 for analysis
        response = call_openai_with_retry(
            messages=[
                {"role": "system", "content": """You are an expert data analyst specializing in workforce analytics.
                Your task is to analyze search results and determine accurate employee counts for specific country offices.
                
                ANALYSIS PRIORITIES:
                1. Direct employee count mentions
                2. Recent data over old
                3. Local numbers over global
                4. Official sources over unofficial
                5. Consistent patterns across sources
                
                Be conservative in estimates and clearly explain your reasoning."""},
                {"role": "user", "content": prompt}
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
                            "enum": ["HIGH", "MEDIUM", "LOW"],
                            "description": "Confidence level in the count"
                        },
                        "sources": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of sources used"
                        },
                        "explanation": {
                            "type": "string",
                            "description": "Explanation of the analysis"
                        }
                    },
                    "required": ["employee_count", "confidence", "sources", "explanation"]
                }
            }],
            function_call={"name": "get_employee_count"}
        )

        if response.choices[0].message.get("function_call"):
            return json.loads(response.choices[0].message["function_call"]["arguments"])
        return None

    except Exception as e:
        print(f"Error analyzing search results: {str(e)}")
        return None

def format_results(results):
    """Format search results for GPT-4 prompt"""
    formatted = []
    for result in results:
        formatted.append(f"Source ({result['link']}):\n{result['snippet']}\n")
    return "\n".join(formatted) if formatted else "No data found."

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
