import os
import csv
import io
import asyncio
import json
import redis
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from anthropic import Anthropic
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://finder-production-4325.up.railway.app",
    "https://finder-git-main-kolexander.vercel.app",
    "https://finder-kolexander.vercel.app",
    "https://finder.vercel.app"
]}})

# Initialize Anthropic client
anthropic = Anthropic(
    api_key=os.getenv('ANTHROPIC_API_KEY'),
    base_url="https://api.anthropic.com",
)

# Initialize Redis client
redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'localhost'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    username=os.getenv('REDIS_USER', 'default'),
    password=os.getenv('REDIS_PASSWORD'),
    db=0,
    decode_responses=True
)

# Create a thread pool for parallel processing
executor = ThreadPoolExecutor(max_workers=10)

ASIAN_AUSTRALIAN_COUNTRIES = [
    "Australia",
    "China",
    "India",
    "Japan",
    "South Korea",
    "Singapore",
    "Malaysia",
    "Indonesia",
    "Thailand",
    "Vietnam",
    "Philippines",
    "New Zealand"
]

def get_cache_key(company_name, country):
    return f"employee_count:{company_name.lower()}:{country.lower()}"

def get_employee_count(company_name, country):
    try:
        # Check cache first
        cache_key = get_cache_key(company_name, country)
        cached_result = redis_client.get(cache_key)
        
        if cached_result:
            print(f"Cache hit for {company_name} in {country}")
            return cached_result
            
        print(f"Cache miss - requesting employee count for {company_name} in {country}")
        completion = anthropic.completions.create(
            model="claude-3-opus-20240229",
            max_tokens_to_sample=300,
            temperature=0,
            system="You are a helpful assistant with accurate knowledge about major companies and their employee counts in different countries. When you know the approximate number, provide it. Only respond with 'Unknown' if you really have no information about the company's presence in that country.",
            prompt=f"\n\nHuman: How many employees does {company_name} have in {country}? Respond with ONLY a number. If you're absolutely not sure, respond with 'Unknown'. For major tech companies like Google, Meta/Facebook, Amazon, etc., you should have approximate numbers. For regional companies like Singtel, Seek, JobStreet, etc., focus on their presence in the specified country.\n\nAssistant:"
        )
        response = completion.completion.strip()
        print(f"Claude response for {company_name}: {response}")
        
        # Cache the result for 24 hours (86400 seconds)
        if response.lower() != 'unknown':
            redis_client.setex(cache_key, 86400, response)
        
        try:
            int(response)
            return response
        except ValueError:
            if response.lower() == 'unknown':
                return 'No data available'
            return response
            
    except redis.RedisError as e:
        print(f"Redis error: {str(e)}")
        # Continue without caching if Redis is unavailable
        return get_employee_count_without_cache(company_name, country)
    except Exception as e:
        print(f"Error getting employee count for {company_name}: {str(e)}")
        return "Error retrieving data"

def get_employee_count_without_cache(company_name, country):
    try:
        completion = anthropic.completions.create(
            model="claude-3-opus-20240229",
            max_tokens_to_sample=300,
            temperature=0,
            system="You are a helpful assistant with accurate knowledge about major companies and their employee counts in different countries.",
            prompt=f"\n\nHuman: How many employees does {company_name} have in {country}? Respond with ONLY a number. If you're not sure, respond with 'Unknown'.\n\nAssistant:"
        )
        response = completion.completion.strip()
        return response
    except Exception as e:
        print(f"Error in fallback employee count for {company_name}: {str(e)}")
        return "Error retrieving data"

async def process_companies(companies, country):
    loop = asyncio.get_event_loop()
    # Process companies in parallel using the thread pool
    tasks = []
    for company in companies:
        task = loop.run_in_executor(executor, get_employee_count, company, country)
        tasks.append(task)
    
    # Wait for all tasks to complete
    results = await asyncio.gather(*tasks)
    return results

@app.route('/api/countries', methods=['GET'])
def get_countries():
    return jsonify(ASIAN_AUSTRALIAN_COUNTRIES)

@app.route('/api/process', methods=['POST'])
def process_file():
    print("Processing file request...")
    print("Files in request:", request.files)
    print("Form data:", request.form)

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    country = request.form.get('country')
    if not country or country not in ASIAN_AUSTRALIAN_COUNTRIES:
        return jsonify({'error': f'Invalid country selection: {country}'}), 400

    file = request.files['file']
    print("File name:", file.filename)
    
    if not file.filename.endswith('.csv'):
        return jsonify({'error': 'Invalid file format. Please upload a CSV file'}), 400

    try:
        # Read the CSV file
        content = file.read().decode('utf-8-sig')
        print("File content:", content[:200])
        csv_input = csv.reader(io.StringIO(content))
        rows = list(csv_input)
        
        if not rows:
            return jsonify({'error': 'Empty CSV file'}), 400
            
        headers = rows[0]
        print("CSV headers:", headers)
        
        # Clean up header names by stripping whitespace and BOM
        headers = [h.strip().replace('\ufeff', '') for h in headers]
        
        if 'Company Name' not in headers:
            return jsonify({'error': f'CSV file must contain a "Company Name" column. Found columns: {headers}'}), 400
            
        company_name_index = headers.index('Company Name')
        headers.append('Number of Employees')
        
        # Extract company names
        companies = [row[company_name_index] for row in rows[1:] if company_name_index < len(row)]
        
        # Process companies in parallel
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        employee_counts = loop.run_until_complete(process_companies(companies, country))
        loop.close()
        
        # Create processed rows with results
        processed_rows = [headers]
        for i, row in enumerate(rows[1:]):
            if company_name_index < len(row):
                new_row = list(row)
                new_row.append(employee_counts[i])
                processed_rows.append(new_row)
            else:
                print(f"Skipping invalid row: {row}")
                new_row = list(row)
                new_row.append('Error: Invalid row')
                processed_rows.append(new_row)

        # Create output CSV
        output = io.StringIO()
        writer = csv.writer(output, lineterminator='\n')
        writer.writerows(processed_rows)
        
        # Create response
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name='updated_companies.csv'
        )

    except Exception as e:
        print("Error processing file:", str(e))
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5006)
