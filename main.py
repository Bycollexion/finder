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
from functools import lru_cache

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Configure OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

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

def extract_number(text):
    """Extract the first number from text"""
    numbers = re.findall(r'\b\d{2,6}\b', text)  # Look for numbers between 2-6 digits
    if numbers:
        return numbers[0].replace(',', '')
    return None

# Cache for search results
search_cache = {}
last_search_time = 0
MIN_SEARCH_DELAY = 2  # Minimum seconds between searches

@lru_cache(maxsize=100)
def cached_web_search(query):
    """Cached version of web search using Google Custom Search API"""
    try:
        api_key = os.getenv("GOOGLE_API_KEY")
        cx = os.getenv("GOOGLE_CX")  # Custom Search Engine ID
        
        if not api_key or not cx:
            logger.error("Google API credentials not found")
            return []
            
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": api_key,
            "cx": cx,
            "q": query,
            "num": 5
        }
        
        response = requests.get(url, params=params)
        response.raise_for_status()
        
        results = []
        data = response.json()
        
        if "items" in data:
            for item in data["items"]:
                results.append({
                    "url": item.get("link"),
                    "title": item.get("title"),
                    "snippet": item.get("snippet", "")
                })
                
        logger.debug(f"Search for '{query}' found {len(results)} results")
        return results
    except Exception as e:
        logger.error(f"Error in web search: {str(e)}")
        return []

@lru_cache(maxsize=100)
def cached_web_content(url):
    """Cached version of web content fetching"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove unwanted elements
        for element in soup(['script', 'style', 'nav', 'footer', 'header']):
            element.decompose()
            
        # Get text and clean it
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk)
        
        logger.debug(f"Successfully fetched content from {url}")
        return text
    except Exception as e:
        logger.error(f"Error reading URL {url}: {str(e)}")
        return ""

def search_web_info(company, country):
    """Search for company employee count information using OpenAI"""
    try:
        if company.lower() == 'company':
            return None

        # First ask GPT to search and analyze
        messages = [
            {
                "role": "system",
                "content": f"""You are an expert at finding employee counts for company offices. 
                Search for information about {company}'s office in {country}.
                Focus on:
                1. Direct employee counts for the {country} office
                2. LinkedIn data about employees in {country}
                3. Recent news about office size/expansion in {country}
                4. Job postings and hiring information in {country}

                Format your response as:
                Employee Counts:
                [List specific numbers found with sources]

                LinkedIn Data:
                [Summary of LinkedIn information]

                News:
                [Relevant news about office size]

                Hiring:
                [Information about current hiring]

                Be specific to {country} office, not global numbers.
                Include URLs for sources when available."""
            },
            {
                "role": "user",
                "content": f"How many employees does {company} have in their {country} office? Search the web and analyze the data."
            }
        ]

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=messages,
            temperature=0.7,
            max_tokens=1000
        )

        web_data = response.choices[0].message['content']

        return call_openai_with_retry(company, country, web_data)
        
    except Exception as e:
        logger.error(f"Error searching web info: {str(e)}")
        return None

def call_openai_with_retry(company, country, web_data):
    """Call OpenAI API with retry logic"""
    max_retries = 3
    base_delay = 1
    
    for attempt in range(max_retries):
        try:
            messages = [
                {
                    "role": "system",
                    "content": f"""You are an expert at estimating employee counts for company offices.
                    Analyze the provided data about {company}'s office in {country}.
                    Return ONLY a number representing your best estimate of employees in the {country} office.
                    If you find a specific number from a reliable source, use that.
                    Otherwise, estimate based on available data.
                    Must be specific to {country} office, not global numbers.
                    
                    Rules:
                    1. Return ONLY a number, no text
                    2. Numbers should be between 20-50,000
                    3. If no reliable data, estimate based on office size/type
                    4. Prefer recent data over old
                    5. Local office numbers only, not global
                    
                    Example good responses:
                    250
                    1500
                    
                    Bad responses (never do these):
                    "About 250 employees"
                    "250-300 employees"
                    "250 globally"
                    """
                },
                {
                    "role": "user",
                    "content": f"Based on this data, estimate employees in {company}'s {country} office:\n{web_data}"
                }
            ]
            
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=messages,
                temperature=0.7,
                max_tokens=150
            )
            
            count = extract_number(response.choices[0].message['content'])
            confidence = "High" if count else "Low"
            
            logger.debug(f"Got response for {company}: {count} (confidence: {confidence})")
            logger.debug(f"Data sources found: {web_data}")
            
            return {
                "Company": company,
                "Employee Count": count if count else "1000",
                "Confidence": confidence
            }
            
        except Exception as e:
            if attempt == max_retries - 1:  # Last attempt
                logger.error(f"Error calling OpenAI API: {str(e)}")
                return None
            else:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.1)
                time.sleep(delay)

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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
