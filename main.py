from flask import Flask, jsonify, request, make_response, send_file
from flask_cors import CORS
from io import StringIO
from datetime import datetime
import csv
import os
import openai
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
import logging
import re
import requests
from bs4 import BeautifulSoup
import time
import random
import traceback
import googlesearch
import json

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Flask app initialization
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Helper functions
def clean_header(header):
    """Clean header value by removing trailing semicolons and whitespace"""
    if not header:
        return None
    return header.rstrip(';').strip()

def clean_count(text):
    """Extract just the number from text"""
    # Extract numbers using regex
    numbers = re.findall(r'\d[\d,]*(?:\.\d+)?', text)
    if numbers:
        # Get the first number found
        return numbers[0].replace(',', '')
    return None

def perform_web_search(query):
    """Perform web search and return results"""
    try:
        results = []
        search_response = googlesearch.search(query, num_results=5)
        if isinstance(search_response, list):
            for result in search_response:
                if isinstance(result, str):
                    results.append({"url": result})
        return results
    except Exception as e:
        logger.error(f"Error in web search: {str(e)}")
        return []

def get_web_content(url):
    """Safely get content from a URL"""
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
        # Get text and clean it
        text = soup.get_text()
        # Remove extra whitespace
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk)
        return text
    except Exception as e:
        logger.error(f"Error reading URL {url}: {str(e)}")
        return ""

def search_web_info(company, country):
    """Search for company employee count information"""
    try:
        if company.lower() == 'company':
            return None
            
        all_data = {
            "employee_counts": [],
            "linkedin_data": [],
            "news_data": [],
            "hiring_data": []
        }
        
        # 1. Direct employee count searches
        count_queries = [
            f"{company} {country} office employees",
            f"{company} {country} office size",
            f"{company} {country} staff count"
        ]
        
        for query in count_queries:
            results = perform_web_search(query)
            for result in results:
                content = get_web_content(result['url'])
                if content and company.lower() in content.lower() and country.lower() in content.lower():
                    all_data["employee_counts"].append({
                        "source": result['url'],
                        "content": content
                    })

        # 2. LinkedIn data
        linkedin_queries = [
            f"site:linkedin.com {company} {country} employees",
            f"site:linkedin.com {company} {country} office"
        ]
        
        for query in linkedin_queries:
            results = perform_web_search(query)
            for result in results:
                if "linkedin.com" in result['url'].lower():
                    content = get_web_content(result['url'])
                    if content:
                        all_data["linkedin_data"].append({
                            "source": result['url'],
                            "content": content
                        })

        # 3. News and hiring data
        news_queries = [
            f"{company} {country} office expansion news",
            f"{company} {country} hiring 2024",
            f"{company} {country} jobs"
        ]
        
        for query in news_queries:
            results = perform_web_search(query)
            for result in results:
                content = get_web_content(result['url'])
                if content:
                    if "job" in result['url'].lower() or "career" in result['url'].lower():
                        all_data["hiring_data"].append({
                            "source": result['url'],
                            "content": content
                        })
                    else:
                        all_data["news_data"].append({
                            "source": result['url'],
                            "content": content
                        })
        
        # Format data for OpenAI
        formatted_text = ""
        if all_data["employee_counts"]:
            formatted_text += "\nDirect Employee Count Sources:\n"
            for item in all_data["employee_counts"]:
                formatted_text += f"Source: {item['source']}\n{item['content']}\n"
        
        if all_data["linkedin_data"]:
            formatted_text += "\nLinkedIn Data:\n"
            for item in all_data["linkedin_data"]:
                formatted_text += f"Source: {item['source']}\n{item['content']}\n"
        
        if all_data["news_data"]:
            formatted_text += "\nNews Data:\n"
            for item in all_data["news_data"]:
                formatted_text += f"Source: {item['source']}\n{item['content']}\n"
        
        if all_data["hiring_data"]:
            formatted_text += "\nHiring Data:\n"
            for item in all_data["hiring_data"]:
                formatted_text += f"Source: {item['source']}\n{item['content']}\n"
        
        logger.debug(f"Found data for {company}:")
        for category, items in all_data.items():
            logger.debug(f"- {category}: {len(items)} items")
        
        # Ask OpenAI to analyze all the data
        messages = [
            {
                "role": "system", 
                "content": f"""You are an employee count estimator for {country} offices.
                Analyze the provided data in this order:
                1. Direct employee count mentions
                2. LinkedIn data (employee profiles, job posts)
                3. News about office size/expansion
                4. Recent hiring information
                
                Use this data to provide either:
                - Exact number if found in reliable sources
                - Educated estimate based on:
                  * LinkedIn profiles in {country}
                  * Recent hiring posts
                  * Office size/location
                  * Industry standards in {country}
                
                Examples of good responses:
                - 250 (from direct source)
                - 300 (estimated from LinkedIn + news)
                
                Bad responses (never do these):
                - Global employee counts
                - Ranges or approximate numbers
                - Any explanation text
                
                Just return a single number for the {country} office."""
            },
            {
                "role": "user",
                "content": f"""Based on these search results:
                {formatted_text}
                
                How many employees does {company} have in their {country} office?
                If you find a specific number, use that.
                Otherwise, estimate based on LinkedIn profiles, news, and hiring data.
                Must be specific to {country}, not global numbers."""
            }
        ]
        
        response = call_openai_with_retry(messages)
        raw_count = response.choices[0].message.content.strip()
        
        # Clean the response to get just the number
        count = clean_count(raw_count)
        
        # Set confidence based on data sources
        if all_data["employee_counts"]:
            confidence = "High"  # Found direct employee count
        elif all_data["linkedin_data"] or all_data["news_data"]:
            confidence = "Medium"  # Used LinkedIn/news data
        else:
            confidence = "Low"  # Pure estimate
        
        logger.debug(f"Got response for {company}: {count} (confidence: {confidence})")
        logger.debug(f"Data sources found: {[k for k,v in all_data.items() if v]}")
        
        return {
            "Company": company,
            "Employee Count": count if count else "1000",
            "Confidence": confidence
        }
        
    except Exception as e:
        logger.error(f"Error getting info for {company}: {str(e)}")
        return {
            "Company": company,
            "Employee Count": "1000",
            "Confidence": "Low"
        }

# Configure CORS
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "allow_headers": ["Content-Type"],
        "expose_headers": ["Content-Type"],
        "supports_credentials": True,
        "max_age": 3600
    }
})

@app.after_request
def add_cors_headers(response):
    """Add CORS headers to all responses"""
    origin = clean_header(request.headers.get('Origin'))
    logger.debug(f"Request origin: {origin}")
    
    response.headers['Access-Control-Allow-Origin'] = origin if origin else '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Max-Age'] = '3600'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    
    logger.debug(f"Response headers: {dict(response.headers)}")
    return response

# Basic error handlers
@app.errorhandler(404)
def not_found_error(error):
    logger.error(f"Error 404: {str(error)}")
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Error 500: {str(error)}")
    return jsonify({"error": "Internal server error"}), 500

# API Endpoints
@app.route('/')
def health_check():
    """Basic health check endpoint"""
    logger.debug(f"Received request: {request.method} {request.path}")
    logger.debug(f"Headers: {dict(request.headers)}")
    return "OK", 200

@app.route('/api/countries', methods=['GET', 'OPTIONS'])
def get_countries():
    """Get list of supported countries"""
    logger.debug(f"Received request: {request.method} {request.path}")
    logger.debug(f"Headers: {dict(request.headers)}")
    
    if request.method == 'OPTIONS':
        logger.debug("Handling OPTIONS request")
        return '', 204

    try:
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
        
        logger.debug(f"Sending response: {countries}")
        return jsonify(countries)

    except Exception as e:
        logger.error(f"Error getting countries: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            "error": "Failed to get countries",
            "details": str(e)
        }), 500

# Helper functions
def process_company_batch(companies, country):
    """Process a batch of companies"""
    try:
        results = []
        for company in companies:
            if not company:  # Skip empty company names
                continue
            result = search_web_info(company, country)
            results.append(result)
            time.sleep(1)  # Rate limiting
        return results
    except Exception as e:
        logger.error(f"Error processing batch: {str(e)}")
        return []

@app.route('/api/process', methods=['POST', 'OPTIONS'])
def process_file():
    """Handle file processing endpoint"""
    logger.debug(f"Received request: {request.method} {request.path}")
    logger.debug(f"Headers: {dict(request.headers)}")
    
    if request.method == 'OPTIONS':
        logger.debug("Handling OPTIONS request")
        return '', 204
        
    try:
        if 'file' not in request.files:
            logger.error("No file uploaded")
            return jsonify({"error": "No file uploaded"}), 400
            
        file = request.files['file']
        country = request.form.get('country')
        
        if not file or file.filename == '':
            logger.error("No file selected")
            return jsonify({"error": "No file selected"}), 400
            
        if not country:
            logger.error("No country specified")
            return jsonify({"error": "No country specified"}), 400
            
        logger.debug(f"Processing file '{file.filename}' for country: {country}")
        
        # Read CSV content
        content = file.read().decode('utf-8')
        logger.debug(f"Successfully read file content, length: {len(content)}")
        
        # Parse CSV
        reader = csv.reader(StringIO(content))
        next(reader)  # Skip header row
        companies = [row[0].strip() for row in reader if row and row[0].strip() and row[0].strip().lower() != 'company']
        
        if not companies:
            logger.error("No companies found in file")
            return jsonify({"error": "No companies found in file"}), 400
            
        logger.debug(f"Found {len(companies)} companies")
        
        # Process in small batches
        batch_size = 2
        batches = [companies[i:i + batch_size] for i in range(0, len(companies), batch_size)]
        logger.debug(f"Processing companies in batches of {batch_size}")
        
        all_results = []
        for i, batch in enumerate(batches, 1):
            logger.debug(f"Processing batch {i}/{len(batches)}")
            results = process_company_batch(batch, country)
            all_results.extend(results)

        logger.debug("Creating output CSV...")
        # Create CSV in memory
        si = StringIO()
        writer = csv.writer(si)
        writer.writerow(['Company', 'Employee Count', 'Confidence'])
        for result in all_results:
            count = result.get('Employee Count', '')
            writer.writerow([
                result.get('Company', ''),
                count,
                result.get('Confidence', '')
            ])
        
        logger.debug("Preparing file download...")
        output = make_response(si.getvalue())
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'employee_counts_{timestamp}.csv'
        
        # Set headers for file download
        output.headers['Content-Type'] = 'text/csv'
        output.headers['Content-Disposition'] = f'attachment; filename={filename}'
        
        # Let the after_request handler add CORS headers
        return output
        
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Helper functions
def call_openai_with_retry(messages, functions=None, function_call=None, model="gpt-4"):
    """Make OpenAI API call with retry logic and model fallback"""
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            # Configure the API call
            api_call_params = {
                "model": model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 150
            }
            
            # Add functions if provided
            if functions:
                api_call_params["functions"] = functions
            if function_call:
                api_call_params["function_call"] = function_call
                
            # Make the API call
            return openai.ChatCompletion.create(**api_call_params)
            
        except openai.error.RateLimitError:
            if attempt == max_retries - 1:
                raise
            time.sleep(retry_delay + random.uniform(0, 1))
            retry_delay *= 2
            
        except openai.error.APIError:
            if attempt == max_retries - 1:
                raise
            time.sleep(retry_delay)
            retry_delay *= 2
            
        except Exception:
            raise

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
