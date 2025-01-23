from flask import Flask, jsonify, request, make_response, send_file
from flask_cors import CORS
import os
import json
import csv
import openai
import time
import random
import traceback
from io import StringIO
from datetime import datetime
from werkzeug.middleware.proxy_fix import ProxyFix
import logging

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
def search_web_info(company, country):
    """Search web for company information"""
    try:
        messages = [
            {"role": "system", "content": f"You are a helpful assistant that finds employee counts for companies in {country}."},
            {"role": "user", "content": f"What is the employee count for {company} in {country}? Only return a number or range."}
        ]
        
        response = call_openai_with_retry(messages)
        
        if not response:
            return {
                "Company": company,
                "Employee Count": "Unknown",
                "Confidence": "Low"
            }
            
        answer = response.choices[0].message.content.strip()
        
        return {
            "Company": company,
            "Employee Count": answer,
            "Confidence": "Medium"
        }
        
    except Exception as e:
        logger.error(f"Error getting info for {company}: {str(e)}")
        return {
            "Company": company,
            "Employee Count": "Error",
            "Confidence": "None"
        }

def process_company_batch(companies, country):
    """Process a batch of companies"""
    try:
        return [search_web_info(company, country) for company in companies]
    except Exception as e:
        logger.error(f"Error processing batch: {str(e)}")
        return []

@app.route('/api/process', methods=['POST', 'OPTIONS'])
def handle_process_file():
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
        country = request.form.get('country', '').strip()
        
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
        companies = [row[0].strip() for row in reader if row and row[0].strip()]
        
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
        
        # Write header - simplified columns
        writer.writerow(['Company', 'Employee Count', 'Confidence'])
        
        # Write results - only the needed fields
        for result in all_results:
            writer.writerow([
                result.get('Company', ''),
                result.get('Employee Count', ''),
                result.get('Confidence', '')
            ])
        
        logger.debug("Preparing file download...")
        output = make_response(si.getvalue())
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'employee_counts_{timestamp}.csv'
        
        output.headers["Content-Disposition"] = f"attachment; filename={filename}"
        output.headers["Content-type"] = "text/csv"
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
