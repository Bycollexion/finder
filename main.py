from flask import Flask, jsonify, request, make_response, send_file
from flask_cors import CORS
import os
import json
import csv
from io import StringIO
import openai
import traceback
import requests
from urllib.parse import quote
import time

app = Flask(__name__)
# Configure CORS to allow all origins
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

def search_web_info(company_name, country):
    """Search the web using multiple specific queries"""
    try:
        # Build queries to check multiple sources
        queries = [
            f"site:linkedin.com {company_name} {country} employees company size",
            f"{company_name} {country} office employees staff size 2024 2023",
            f"{company_name} {country} headquarters number of employees"
        ]
        
        all_results = []
        for query in queries:
            try:
                results = search_web(query=query)
                if results and len(results) > 0:
                    for result in results[:2]:  # Get top 2 results per query
                        title = result.get('title', '')
                        snippet = result.get('snippet', '')
                        # Only add if it contains employee-related information
                        if any(term in (title + snippet).lower() for term in ['employees', 'staff', 'company size', 'team size', 'headcount']):
                            all_results.append(f"Source: {title}")
                            all_results.append(snippet)
                            all_results.append("")
            except Exception as e:
                print(f"Error with query '{query}': {str(e)}")
                continue
        
        if all_results:
            return "\n".join(all_results)
        return "Using regional knowledge for estimation"
    except Exception as e:
        print(f"Error during web search: {str(e)}")
        return "Using regional knowledge for estimation"

@app.route('/')
def index():
    return jsonify({"status": "healthy"})

@app.route('/api/countries', methods=['GET'])
def get_countries():
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

@app.route('/api/process', methods=['POST', 'OPTIONS'])
def process_file():
    if request.method == 'OPTIONS':
        return '', 204
        
    try:
        print("=== Starting file processing ===")
        print(f"Request headers: {dict(request.headers)}")
        print(f"Request form data: {dict(request.form)}")
        print(f"Request files: {dict(request.files)}")
        
        if 'file' not in request.files:
            print("Error: No file in request")
            return jsonify({"error": "No file provided"}), 400
            
        file = request.files['file']
        country = request.form.get('country')
        
        if not file or not country:
            print(f"Error: Missing data - file: {bool(file)}, country: {bool(country)}")
            return jsonify({"error": "Both file and country are required"}), 400
            
        # Read the CSV file
        content = file.read().decode('utf-8')
        print(f"CSV content: {content}")
        csv_input = StringIO(content)
        
        # First, read all rows to ensure we have the data
        reader = csv.DictReader(csv_input)
        # Clean up header names by removing BOM and whitespace
        cleaned_headers = [h.replace('\ufeff', '').strip().lower() for h in reader.fieldnames]
        print(f"Original headers: {reader.fieldnames}")
        print(f"Cleaned headers: {cleaned_headers}")
        all_rows = list(reader)
        print(f"Number of rows read: {len(all_rows)}")
        
        if not all_rows:
            print("Error: No rows found in CSV")
            return jsonify({"error": "No data found in CSV file"}), 400
            
        # Check for various possible column names
        possible_names = ['company', 'company name', 'companyname', 'name']
        company_column = None
        for header in reader.fieldnames:
            cleaned_header = header.replace('\ufeff', '').strip().lower()
            if cleaned_header in possible_names:
                company_column = header
                break
                
        if not company_column:
            print(f"Error: No valid company column found. Available columns: {reader.fieldnames}")
            print(f"Looking for any of these column names: {possible_names}")
            return jsonify({"error": "CSV file must have a column named 'Company', 'Company Name', or similar"}), 400
            
        # Prepare output
        output = StringIO()
        fieldnames = ['company', 'employee_count', 'confidence', 'source']
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        # Initialize OpenAI client
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            print("Error: OpenAI API key not found in environment")
            return jsonify({"error": "OpenAI API key not configured"}), 500
            
        print(f"OpenAI API key found (length: {len(openai_api_key)})")
        openai.api_key = openai_api_key
        
        # Process each company
        for row in all_rows:
            print(f"Processing row: {row}")
            company_name = row[company_column].strip()
            if not company_name:
                print(f"Skipping empty company name in row: {row}")
                continue
                
            print(f"Processing company: {company_name}")
            try:
                # Get web information
                web_info = search_web_info(company_name, country)
                print(f"Web search results for {company_name}: {web_info}")

                # Now use GPT-4 to analyze all information with specific regional knowledge
                response = openai.ChatCompletion.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": """You are a helpful assistant that provides company information. 
                        Analyze the web search results and your knowledge to provide accurate employee counts.
                        
                        When determining confidence and employee count:
                        
                        HIGH confidence requirements (must have specific numbers):
                        - LinkedIn company page showing exact employee count for the country
                        - Company's official career page showing local team size
                        - Recent news article with exact numbers from company officials
                        - Annual reports or official documents with country breakdown
                        
                        MEDIUM confidence requirements:
                        - LinkedIn showing employee range (e.g., 501-1000)
                        - Recent job postings indicating department sizes
                        - News articles mentioning approximate numbers
                        - Industry reports with regional breakdowns
                        
                        LOW confidence (use only if no better source):
                        - Outdated information
                        - Global numbers without country breakdown
                        - Estimates without clear sources
                        
                        For employee count in Malaysia:
                        
                        VERIFIED RANGES (Use these with MEDIUM confidence if LinkedIn shows this range):
                        - JobStreet: 501-1000 employees (LinkedIn verified)
                        - Grab: >1000 employees (major tech hub)
                        - Shopee: >1000 employees (major presence)
                        - Lazada: >800 employees (significant presence)
                        
                        ESTIMATED RANGES (Use with LOW confidence):
                        TECH COMPANIES:
                        - Google Malaysia: 50-100 (sales/support)
                        - Meta/Facebook: 30-50 (sales office)
                        - Amazon: 100-200 (AWS focus)
                        - LinkedIn: 20-40 (sales)
                        
                        OTHERS:
                        - Singtel: 200-300 (telecoms)
                        - GoTo: 100-200 (regional)
                        - Tokopedia: 50-100 (part of GoTo)
                        - Jobs DB: 50-100 (local team)
                        - Seek: 100-150 (regional)
                        
                        IMPORTANT RULES:
                        1. If LinkedIn shows a specific range (e.g., 501-1000), use the middle of that range with MEDIUM confidence
                        2. If you find a recent exact number from a reliable source, use it with HIGH confidence
                        3. If you only have estimated ranges, use them with LOW confidence
                        4. Always prefer actual data from web search over estimated ranges"""},
                        {"role": "user", "content": f"""How many employees does {company_name} have in {country}? 
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
                
                function_call = response['choices'][0]['message']['function_call']
                result = json.loads(function_call['arguments'])
                print(f"Initial result for {company_name}: {result}")
                
                # Add sense-checking step
                sense_check_response = openai.ChatCompletion.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": """You are a data validator checking employee counts for accuracy.
                        
                        VALIDATION RULES for Malaysia offices:
                        
                        1. Size Constraints:
                        - No tech company sales office should have >200 employees unless it's a major tech hub
                        - Regional HQs typically have 200-500 employees
                        - Tech hubs (like Grab) can have >1000 employees
                        
                        2. Company-Specific Rules:
                        TECH COMPANIES (Sales/Support Offices):
                        - Google: 50-100 typical range
                        - Meta/Facebook: 30-50 typical range
                        - Amazon: 100-200 typical range (AWS)
                        - LinkedIn: 20-40 typical range
                        
                        REGIONAL TECH:
                        - Grab: 1000-2000 (major tech hub)
                        - Shopee: 1000-1500 (major presence)
                        - Lazada: 800-1200 (major presence)
                        - Sea Limited: 1000-1500 (major office)
                        
                        JOB PORTALS:
                        - JobStreet: 500-1000 (LinkedIn verified)
                        - Jobs DB: 50-100
                        - Seek: 100-150
                        
                        3. Red Flags:
                        - Numbers too high for sales offices
                        - Numbers too low for regional HQs
                        - Extreme outliers from typical ranges
                        
                        If the number violates these rules, adjust it to the typical range and set confidence to LOW."""},
                        {"role": "user", "content": f"""Please validate this employee count:
                        Company: {company_name}
                        Country: {country}
                        Employee Count: {result['employee_count']}
                        Confidence: {result['confidence']}
                        
                        Source Data:
                        {web_info}
                        
                        Is this number reasonable? If not, what should it be?"""}
                    ],
                    functions=[{
                        "name": "validate_employee_count",
                        "description": "Validate and potentially adjust employee count",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "employee_count": {
                                    "type": "integer",
                                    "description": "The validated/adjusted employee count"
                                },
                                "confidence": {
                                    "type": "string",
                                    "enum": ["high", "medium", "low"],
                                    "description": "Confidence level after validation"
                                },
                                "adjustment_reason": {
                                    "type": "string",
                                    "description": "Reason for any adjustment made"
                                }
                            },
                            "required": ["employee_count", "confidence", "adjustment_reason"]
                        }
                    }],
                    function_call={"name": "validate_employee_count"}
                )
                
                validation_result = json.loads(sense_check_response['choices'][0]['message']['function_call']['arguments'])
                print(f"Validation result for {company_name}: {validation_result}")
                
                # Use the validated result
                writer.writerow({
                    'company': company_name,
                    'employee_count': validation_result['employee_count'],
                    'confidence': validation_result['confidence'],
                    'source': f"openai ({validation_result['adjustment_reason']})"
                })
                
                # Flush the output after each write
                output.flush()
                
            except Exception as e:
                print(f"Error processing {company_name}: {str(e)}")
                print(f"Traceback: {traceback.format_exc()}")
                writer.writerow({
                    'company': company_name,
                    'employee_count': 0,
                    'confidence': 'low',
                    'source': f'error: {str(e)}'
                })
                output.flush()
        
        # Get the final CSV content
        output.seek(0)
        final_content = output.getvalue()
        print(f"Final CSV content: {final_content}")
        
        # Prepare the response
        response = make_response(final_content)
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = 'attachment; filename=updated_companies.csv'
        return response
        
    except Exception as e:
        print(f"Global error in process_file: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
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
        response = openai.ChatCompletion.create(
            model="gpt-4",
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

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
