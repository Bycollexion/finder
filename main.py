from flask import Flask, jsonify, request, make_response, send_file
from flask_cors import CORS
import os
import json
import csv
from io import StringIO
import openai
import traceback
import requests

app = Flask(__name__)
# Configure CORS to allow all origins
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

# Log environment variables on startup
print("=== Environment Variables ===")
print(f"PORT: {os.environ.get('PORT', '(not set)')}")
print(f"OPENAI_API_KEY set: {'yes' if os.environ.get('OPENAI_API_KEY') else 'no'}")
if os.environ.get('OPENAI_API_KEY'):
    print(f"OPENAI_API_KEY length: {len(os.environ.get('OPENAI_API_KEY'))}")
print("=========================")

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
                # First, try to get information from web search
                search_query = f"{company_name} number of employees {country} 2024"
                web_info = ""
                
                try:
                    # Search web for recent information
                    search_response = requests.get(
                        f"https://api.codeium.com/cascade/v1/search_web",
                        params={"query": search_query},
                        headers={"Content-Type": "application/json"}
                    )
                    
                    if search_response.status_code == 200:
                        search_results = search_response.json()
                        # Combine search results into a summary
                        web_info = "\n".join([
                            f"Source {i+1}: {result['title']}\n{result['snippet']}\n"
                            for i, result in enumerate(search_results[:3])
                        ])
                    else:
                        web_info = "Web search failed to return results."
                    
                    print(f"Web search results for {company_name}: {web_info}")
                except Exception as e:
                    print(f"Error during web search for {company_name}: {str(e)}")
                    web_info = "No web search results available."

                # Now use GPT-4 to analyze all information
                response = openai.ChatCompletion.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": """You are a helpful assistant that provides company information. 
                        Analyze the web search results and your knowledge to provide accurate employee counts.
                        Be conservative with confidence levels:
                        - Use 'low' if the data might be outdated or if sources conflict
                        - Use 'medium' if you have recent data but it's not from an official source
                        - Use 'high' only if you have very recent, official data from company reports
                        
                        When determining confidence:
                        - HIGH: Recent (within 6 months) official company reports or regulatory filings
                        - MEDIUM: Recent news articles, LinkedIn data, or market research
                        - LOW: Older data, conflicting sources, or estimates
                        
                        For the employee count:
                        1. Prioritize country-specific numbers when available
                        2. If only regional numbers are available, estimate based on market presence
                        3. If only global numbers are available, estimate based on market size
                        
                        Include source citations in your reasoning."""},
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
                print(f"Got result for {company_name}: {result}")
                
                writer.writerow({
                    'company': company_name,
                    'employee_count': result['employee_count'],
                    'confidence': result['confidence'],
                    'source': 'openai'
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
