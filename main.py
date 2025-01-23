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
        'ph': 'Philippines',
        'jp': 'Japan',
        'kr': 'South Korea',
        'cn': 'China',
        'hk': 'Hong Kong',
        'tw': 'Taiwan',
        'au': 'Australia'
    }
    return country_map.get(code.lower(), code)

def search_web(query):
    """Search the web for the given query"""
    try:
        response = requests.get(f"https://www.google.com/search?q={query}")
        return response.text
    except Exception as e:
        logger.error(f"Error searching web: {str(e)}")
        return ""

def read_url_content(url):
    """Read content from a URL"""
    try:
        response = requests.get(url)
        return response.text
    except Exception as e:
        logger.error(f"Error reading URL content: {str(e)}")
        return ""

def search_web_info(company, country):
    """Search for company employee count information using OpenAI and web search"""
    try:
        if company.lower() == 'company':
            return None

        country_name = get_country_name(country)
        
        # First, search the web for recent information
        search_query = f"{company} {country_name} office employees 2024 linkedin glassdoor"
        web_results = search_web(search_query)
        
        # Extract URLs from search results and read their content
        content = ""
        for url in web_results.get('urls', [])[:3]:  # Get first 3 URLs
            try:
                content += read_url_content(url) + "\n"
            except:
                continue
        
        # Use the web results in our prompt
        messages = [
            {
                "role": "system",
                "content": f"""You are an AI tasked with finding employee counts from web data.
Based on the following search results, determine the employee count for {company} in {country_name}.

Search Results:
{content}

Instructions:
1. Focus on finding the most recent employee count specifically for {country_name}
2. Consider regional office data if available
3. Return ONLY the number, no additional text"""
            },
            {
                "role": "user",
                "content": f"What is the current employee count of {company} in {country_name}?"
            }
        ]

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=messages,
            temperature=0.3,
            max_tokens=50
        )

        count = extract_number(response.choices[0].message['content'])
        
        if count and count != "0":
            # Verify the count with another search
            verify_query = f"{company} {country_name} headquarters staff size"
            verify_results = search_web(verify_query)
            
            # Read content from verification URLs
            verify_content = ""
            for url in verify_results.get('urls', [])[:2]:
                try:
                    verify_content += read_url_content(url) + "\n"
                except:
                    continue
            
            messages = [
                {
                    "role": "system",
                    "content": f"""Based on these search results, verify if the employee count is accurate:
{verify_content}

Return ONLY: YES if confident, NO if unsure, UNKNOWN if no data available"""
                },
                {
                    "role": "user",
                    "content": f"Is {count} employees accurate for {company} in {country_name}?"
                }
            ]

            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=messages,
                temperature=0.3,
                max_tokens=50
            )

            confidence_response = response.choices[0].message['content'].strip().upper()
            
            if confidence_response == "YES":
                confidence = "High"
            elif confidence_response == "NO":
                confidence = "Medium"
            else:
                confidence = "Low"
        else:
            # Try one more time with a different search
            backup_query = f"{company} {country_name} careers jobs current employees"
            backup_results = search_web(backup_query)
            
            # Read content from backup URLs
            backup_content = ""
            for url in backup_results.get('urls', [])[:2]:
                try:
                    backup_content += read_url_content(url) + "\n"
                except:
                    continue
            
            messages = [
                {
                    "role": "system",
                    "content": f"""Based on these search results, estimate the employee count:
{backup_content}

Return ONLY the number, no text."""
                },
                {
                    "role": "user",
                    "content": f"Estimate {company}'s employee count in {country_name}"
                }
            ]

            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=messages,
                temperature=0.3,
                max_tokens=50
            )

            count = extract_number(response.choices[0].message['content'])
            confidence = "Low"

        if not count or count == "0":
            logger.info(f"No presence found for {company} in {country_name}")
            return {
                "Company": company,
                "Employee Count": "0",
                "Confidence": "Low"
            }

        logger.debug(f"Got response for {company}: {count} (confidence: {confidence})")

        return {
            "Company": company,
            "Employee Count": str(count),
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
