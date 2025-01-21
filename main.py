from flask import Flask, jsonify, request, make_response, send_file
from flask_cors import CORS
import os
import json
import csv
from io import StringIO
import openai

app = Flask(__name__)
CORS(app)

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

@app.route('/api/process', methods=['POST'])
def process_file():
    try:
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
        print(f"CSV headers found: {reader.fieldnames}")
        all_rows = list(reader)
        print(f"Number of rows read: {len(all_rows)}")
        
        if not all_rows:
            print("Error: No rows found in CSV")
            return jsonify({"error": "No data found in CSV file"}), 400
            
        # Check if 'company' column exists
        if 'company' not in reader.fieldnames:
            print(f"Error: 'company' column not found. Available columns: {reader.fieldnames}")
            return jsonify({"error": "CSV file must have a 'company' column"}), 400
            
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
            if 'company' not in row:
                print(f"Error: 'company' column not found in row: {row}")
                return jsonify({"error": "CSV file must have a 'company' column"}), 400
                
            company_name = row['company'].strip()
            if not company_name:
                print(f"Skipping empty company name in row: {row}")
                continue
                
            print(f"Processing company: {company_name}")
            try:
                response = openai.ChatCompletion.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that provides company information. Be conservative with confidence levels - use 'low' if the data might be outdated, 'medium' if you're reasonably sure but the number might have changed, and 'high' only if you're extremely confident about the employee count. For companies in Asia, consider their rapid growth and potential for change when assigning confidence levels."},
                        {"role": "user", "content": f"How many employees does {company_name} have in {country}? Consider only full-time employees."}
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
                                    "description": "Confidence level in the employee count: low (possibly outdated), medium (reasonably sure), high (very confident)"
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
    app.run(host='0.0.0.0', port=port, debug=False)
