import os
import logging
import requests
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import pandas as pd
import openai
import re
import csv
from datetime import datetime
import time
import random
import traceback

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Configure CORS
CORS(app, resources={
    r"/*": {
        "origins": [
            "http://localhost:3000",
            "https://finder-git-main-bycollexions-projects.vercel.app",
            "https://finder-bycollexions-projects.vercel.app",
            "https://finder.bycollexion.com"
        ],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"],
        "expose_headers": ["Content-Disposition"],
        "supports_credentials": True,
        "max_age": 3600
    }
})

@app.after_request
def after_request(response):
    """Ensure CORS headers are set correctly"""
    origin = request.headers.get('Origin')
    if origin in [
        "http://localhost:3000",
        "https://finder-git-main-bycollexions-projects.vercel.app",
        "https://finder-bycollexions-projects.vercel.app",
        "https://finder.bycollexion.com"
    ]:
        response.headers['Access-Control-Allow-Origin'] = origin
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Expose-Headers'] = 'Content-Disposition'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    response.headers['Access-Control-Max-Age'] = '3600'
    return response

# Configure OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

def extract_number(text):
    """Extract the first number from text"""
    numbers = re.findall(r'\b\d{2,6}\b', text)  # Look for numbers between 2-6 digits
    if numbers:
        return numbers[0].replace(',', '')
    return None

def get_country_name(code):
    """Convert country code to full name"""
    country_map = {
        'sg': 'Singapore',
        'my': 'Malaysia',
        'id': 'Indonesia',
        'th': 'Thailand',
        'vn': 'Vietnam',
        'ph': 'Philippines'
    }
    return country_map.get(code.lower(), code)

def search_web_info(company, country):
    """Search for company employee count information using OpenAI"""
    try:
        if company.lower() == 'company':
            return None

        country_name = get_country_name(country)

        # First ask GPT to search and analyze
        messages = [
            {
                "role": "system",
                "content": f"""You are the CompanyDataAPI, a corporate intelligence database. You have been queried for information about {company}'s presence in {country_name}.

AVAILABLE ENDPOINTS:
/api/v1/office_presence
/api/v1/employee_data
/api/v1/real_estate
/api/v1/hiring_status

RESPONSE FORMAT:
{{
    "query_timestamp": "2025-01-23",
    "company": "{company}",
    "region": "{country_name}",
    "office_presence": {{
        "status": "ACTIVE|NONE|UNKNOWN",
        "primary_location": {{
            "address": "string",
            "type": "HQ|REGIONAL|SALES|R&D",
            "size_sqft": number,
            "lease_status": "OWNED|LEASED|UNKNOWN"
        }}
    }},
    "employee_data": {{
        "headcount": {{
            "current": number,
            "last_updated": "YYYY-MM-DD",
            "yoy_change_pct": number
        }},
        "data_source": "LINKEDIN|ANNUAL_REPORT|NEWS|ESTIMATE"
    }},
    "hiring_status": {{
        "active_roles": number,
        "key_departments": ["string"],
        "trend": "EXPANDING|STABLE|REDUCING"
    }},
    "confidence_score": number // 0.0-1.0
}}

Return a complete JSON response with real numbers and data. Do not return instructions or placeholders. If data is unknown, use null."""
            },
            {
                "role": "user",
                "content": f"GET /api/v1/company_data?name={company}&region={country_name}"
            }
        ]

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=messages,
            temperature=0.1,  # Very low temperature for factual responses
            max_tokens=1000
        )

        web_data = response.choices[0].message['content']
        logger.debug(f"Web search results for {company}:\n{web_data}")

        # Now analyze the data to get a number
        messages = [
            {
                "role": "system",
                "content": f"""You are the HeadcountAnalyzer API. Extract the most accurate employee count from the CompanyDataAPI response.

CALCULATION RULES:
1. If headcount.current exists and last_updated is within 2 years:
   RETURN headcount.current

2. If office_presence.primary_location.size_sqft exists:
   - Tech companies: size_sqft / 150 (rounded to nearest 50)
   - Others: size_sqft / 100 (rounded to nearest 50)
   RETURN calculated_headcount

3. If hiring_status.active_roles exists:
   RETURN active_roles * 15 (rounded to nearest 50)

4. If only office_presence.primary_location.type exists:
   - HQ: 1500
   - REGIONAL: 350
   - SALES: 75
   - R&D: 200
   RETURN type_based_estimate

5. If office_presence.status != "ACTIVE":
   RETURN 0

Return ONLY the final number, no explanation."""
            },
            {
                "role": "user",
                "content": f"Calculate headcount from API response:\n{web_data}"
            }
        ]

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=messages,
            temperature=0.1,
            max_tokens=150
        )

        count = extract_number(response.choices[0].message['content'])
        
        # Check if the response had a high confidence score
        try:
            import json
            data = json.loads(web_data)
            confidence = "High" if data.get("confidence_score", 0) > 0.7 else "Low"
        except:
            confidence = "Low"
        
        if not count or count == "0":
            logger.info(f"No presence found for {company} in {country_name}")
            return {
                "Company": company,
                "Employee Count": "0",
                "Confidence": confidence
            }

        logger.debug(f"Got response for {company}: {count} (confidence: {confidence})")

        return {
            "Company": company,
            "Employee Count": count,
            "Confidence": confidence
        }

    except Exception as e:
        logger.error(f"Error searching web info: {str(e)}")
        return {
            "Company": company,
            "Employee Count": "0",
            "Confidence": "Low"
        }

# Basic error handlers
@app.errorhandler(404)
def not_found_error(error):
    logger.error(f"Error 404: {str(error)}")
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Error 500: {str(error)}")
    return jsonify({"error": "Internal server error"}), 500

@app.route('/')
def health_check():
    """Basic health check endpoint"""
    return "OK", 200

@app.route('/api/countries', methods=['GET'])
def get_countries():
    """Get list of supported countries"""
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
        return jsonify(countries)
    except Exception as e:
        logger.error(f"Error getting countries: {str(e)}")
        return jsonify({"error": "Failed to get countries"}), 500

@app.route('/api/process', methods=['POST'])
def process_file():
    """Process uploaded CSV file"""
    try:
        logger.debug(f"Received file upload request. Files: {request.files}")
        logger.debug(f"Form data: {request.form}")
        
        if 'file' not in request.files:
            logger.error("No file part in request")
            return jsonify({"error": "No file uploaded"}), 400

        if 'country' not in request.form:
            logger.error("No country specified in form")
            return jsonify({"error": "No country specified"}), 400

        country = request.form['country']
        file = request.files['file']
        
        if not file.filename:
            logger.error("No file selected")
            return jsonify({"error": "No file selected"}), 400
            
        if not file.filename.endswith('.csv'):
            logger.error(f"Invalid file type: {file.filename}")
            return jsonify({"error": "File must be a CSV"}), 400

        # Read CSV file
        logger.debug(f"Reading CSV file: {file.filename}")
        df = pd.read_csv(file)
        
        logger.debug(f"CSV columns: {df.columns.tolist()}")
        if 'Company' not in df.columns:
            logger.error("Missing Company column")
            return jsonify({"error": "CSV must contain a Company column"}), 400

        # Process each company
        results = []
        total_rows = len(df)
        logger.info(f"Processing {total_rows} companies for country: {country}")

        for index, row in df.iterrows():
            company = row['Company'].strip()
            
            logger.info(f"Processing {company} ({country}) - {index + 1}/{total_rows}")
            result = search_web_info(company, country)
            if result:
                results.append(result)
                logger.debug(f"Got result for {company}: {result}")
            else:
                logger.warning(f"No result found for {company}")

        # Create output CSV
        logger.info("Creating output CSV...")
        output_filename = f"employee_counts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        with open(output_filename, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['Company', 'Employee Count', 'Confidence'])
            writer.writeheader()
            writer.writerows(results)

        logger.debug(f"Created output file: {output_filename} ({os.path.getsize(output_filename)} bytes)")

        # Prepare file download
        logger.info("Preparing file download...")
        
        return send_file(
            output_filename,
            mimetype='text/csv',
            as_attachment=True,
            download_name=output_filename
        )

    except pd.errors.EmptyDataError:
        logger.error("Empty CSV file uploaded")
        return jsonify({"error": "The CSV file is empty"}), 400
    except pd.errors.ParserError as e:
        logger.error(f"CSV parsing error: {str(e)}")
        return jsonify({"error": "Invalid CSV format"}), 400
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
