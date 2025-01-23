from http.server import BaseHTTPRequestHandler
import json
import os
import logging
import requests
from flask import Flask, jsonify
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
CORS(app)

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
    """Search the web for the given query and extract URLs"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(
            f"https://www.google.com/search?q={requests.utils.quote(query)}",
            headers=headers
        )
        
        # Extract URLs from the response using regex
        urls = re.findall(r'href="(https?://[^"]+?)"', response.text)
        # Filter out Google's own URLs and other irrelevant ones
        filtered_urls = [
            url for url in urls 
            if not any(x in url for x in ['google.com', 'youtube.com', 'webcache'])
        ]
        return {'urls': filtered_urls[:5]}  # Return top 5 relevant URLs
    except Exception as e:
        logger.error(f"Error searching web: {str(e)}")
        return {'urls': []}

def read_url_content(url):
    """Read content from a URL"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        # Extract text content using regex to remove HTML tags
        text = re.sub(r'<[^>]+>', ' ', response.text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:5000]  # Limit content length
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
                    "content": f"""Based on these search results, find the employee count for {company} in {country_name}.
{backup_content}

Instructions:
1. Look for any mentions of employee count or team size
2. Consider only {country_name} office data
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
            confidence = "Low"

        return {
            "Company": company,
            "Employee Count": count if count else "0",
            "Confidence": confidence
        }

    except Exception as e:
        logger.error(f"Error searching web info: {str(e)}")
        return {
            "Company": company,
            "Employee Count": "0",
            "Confidence": "Low"
        }

def get_countries():
    """Get list of supported countries"""
    countries = [
        {"code": "sg", "name": "Singapore"},
        {"code": "my", "name": "Malaysia"},
        {"code": "id", "name": "Indonesia"},
        {"code": "th", "name": "Thailand"},
        {"code": "vn", "name": "Vietnam"},
        {"code": "ph", "name": "Philippines"},
        {"code": "jp", "name": "Japan"},
        {"code": "kr", "name": "South Korea"},
        {"code": "cn", "name": "China"},
        {"code": "hk", "name": "Hong Kong"},
        {"code": "tw", "name": "Taiwan"},
        {"code": "au", "name": "Australia"}
    ]
    return countries

def handle_request(path, method='GET', body=None):
    """Handle incoming requests"""
    if path == '/api/countries' and method == 'GET':
        return {
            'statusCode': 200,
            'body': json.dumps(get_countries())
        }
    elif path == '/api/process' and method == 'POST':
        try:
            # Process the CSV data
            data = json.loads(body)
            if not data or 'data' not in data:
                return {
                    'statusCode': 400,
                    'body': json.dumps({"error": "No CSV data provided"})
                }

            # Parse CSV data and process it
            rows = []
            for line in data['data'].split('\n'):
                if line.strip():  # Skip empty lines
                    rows.append(line.split(','))

            # Process each company
            results = []
            for i, row in enumerate(rows[1:], 1):  # Skip header row
                if len(row) >= 2:
                    company = row[0].strip()
                    country = row[1].strip().lower()
                    
                    logger.info(f"Processing {company} ({country}) - {i}/{len(rows)-1}")
                    
                    result = search_web_info(company, country)
                    if result:
                        results.append(result)
                    
                    # Add a small delay between requests
                    time.sleep(random.uniform(1, 2))

            # Create output CSV
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"employee_counts_{timestamp}.csv"
            
            with open(output_file, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=["Company", "Employee Count", "Confidence"])
                writer.writeheader()
                writer.writerows(results)
            
            logger.debug(f"Created output file: {output_file} ({os.path.getsize(output_file)} bytes)")
            
            # Return the file
            logger.info("Preparing file download...")
            with open(output_file, 'rb') as f:
                return {
                    'statusCode': 200,
                    'body': f.read(),
                    'headers': {
                        'Content-Type': 'text/csv',
                        'Content-Disposition': f'attachment; filename="{output_file}"'
                    }
                }
        except Exception as e:
            logger.error(f"Error processing file: {str(e)}\n{traceback.format_exc()}")
            return {
                'statusCode': 500,
                'body': json.dumps({"error": str(e)})
            }
    else:
        return {
            'statusCode': 404,
            'body': json.dumps({"error": "Not found"})
        }

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        response = handle_request(self.path, 'GET')
        self.send_response(response['statusCode'])
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(response['body'].encode())

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        body = self.rfile.read(content_length).decode()
        response = handle_request(self.path, 'POST', body)
        self.send_response(response['statusCode'])
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        if 'headers' in response:
            for key, value in response['headers'].items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(response['body'].encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
