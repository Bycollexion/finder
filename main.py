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

def clean_count(text, company):
    """Extract employee count with comparison operators"""
    # If response contains error indicators, return None
    error_phrases = ["sorry", "can't", "cannot", "don't", "unable", "exact number", "request"]
    if any(phrase in text.lower() for phrase in error_phrases):
        return None
        
    text = text.lower().strip()
    
    # Define companies that typically have smaller employee counts
    small_companies = {'jobstreet', 'jobs db', 'tokopedia', 'goto'}
    needs_scaling = company.lower() not in small_companies
    
    # Extract numbers
    numbers = re.findall(r'\d[\d,]*(?:\.\d+)?', text)
    if not numbers:
        return None
        
    try:
        num = int(numbers[0].replace(',', ''))
        # Only scale up if it's a large company and number seems too small
        if needs_scaling and num < 1000:
            num *= 1000
            
        # Handle comparison operators
        if '>' in text or 'greater than' in text or 'more than' in text:
            return f">{num}"
        elif '<' in text or 'less than' in text:
            return f"<{num}"
        elif '>=' in text or 'greater than or equal' in text:
            return f"≥{num}"
        elif '<=' in text or 'less than or equal' in text:
            return f"≤{num}"
        else:
            return str(num)
    except:
        return None

def search_web(query):
    """Perform web search"""
    try:
        # Implement web search logic here
        # For demonstration purposes, return dummy results
        results = googlesearch.search(query, num_results=5)
        return [{"url": result} for result in results]
    except Exception as e:
        logger.error(f"Error performing web search: {str(e)}")
        return []

def read_url_content(url):
    """Read content from URL"""
    try:
        # Implement URL content reading logic here
        # For demonstration purposes, return dummy content
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        return soup.get_text()
    except Exception as e:
        logger.error(f"Error reading URL content: {str(e)}")
        return None

def search_web_info(company, country):
    """Search for company employee count information"""
    try:
        # Skip if company name is a header
        if company.lower() == 'company':
            return None
            
        # Try multiple search queries to get better data
        search_queries = [
            f"{company} {country} office employees site:linkedin.com",
            f"{company} {country} headquarters employees",
            f"{company} {country} local office size"
        ]
        
        relevant_text = ""
        for query in search_queries:
            search_results = search_web({"query": query})
            if search_results:
                for result in search_results:
                    try:
                        content = read_url_content({"Url": result["url"]})
                        if content:
                            # Only include text that mentions both company and country
                            if company.lower() in content.lower() and country.lower() in content.lower():
                                relevant_text += f"\nSource ({result['url']}):\n{content}\n"
                    except:
                        continue
        
        # Now ask OpenAI with the search results as context
        messages = [
            {
                "role": "system", 
                "content": f"""You are an employee count bot that provides ONLY local office numbers for {country}.
                NEVER return global employee counts.
                ALWAYS use comparison operators (>, <, =).
                
                Examples for Singapore office sizes:
                - >200 (more than 200 employees in Singapore office)
                - <500 (less than 500 in Singapore)
                - >50 (more than 50 local employees)
                
                Bad responses (never do these):
                - Global employee counts
                - Numbers over 10,000 (very rare for local offices)
                - "Sorry, I can't..."
                - Any explanation text
                
                Just return the local office number with operator, nothing else."""
            },
            {
                "role": "user",
                "content": f"""Based on these search results:
                {relevant_text}
                
                How many employees does {company} have in their {country} office specifically? 
                Return ONLY a number with comparison operator (>, <, =).
                Must be the local office number, not global employees.
                If unsure, return a conservative estimate."""
            }
        ]
        
        response = call_openai_with_retry(messages)
        raw_count = response.choices[0].message.content.strip()
        
        # Clean the response
        count = clean_count(raw_count, company)
        
        # If cleaning failed or number seems too high, use conservative defaults
        if count is None or (count.isdigit() and int(count) > 10000):
            if company.lower() in ['google', 'facebook', 'amazon']:
                count = '>1000'
            elif company.lower() in ['grab', 'shopee', 'sea']:
                count = '>500'
            elif company.lower() in ['jobstreet', 'jobs db', 'tokopedia', 'goto']:
                count = '>50'
            else:
                count = '>100'
            confidence = "Low"
        else:
            # Add comparison operator if missing
            if not any(op in count for op in ['>', '<', '=']):
                count = f">{count}"
            confidence = "High" if relevant_text else "Medium"
        
        logger.debug(f"Got response for {company}: {count} (confidence: {confidence})")
        
        return {
            "Company": company,
            "Employee Count": count,
            "Confidence": confidence
        }
        
    except Exception as e:
        logger.error(f"Error getting info for {company}: {str(e)}")
        return {
            "Company": company,
            "Employee Count": ">100",
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
