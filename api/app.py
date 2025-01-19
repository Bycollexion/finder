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
CORS(app, resources={r"/api/*": {
    "origins": "*",  # Allow all origins temporarily for debugging
    "methods": ["GET", "POST", "OPTIONS"],
    "allow_headers": ["Content-Type"]
}})

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

async def get_employee_count_without_cache(company_name, country):
    try:
        app.logger.info(f'Querying Claude API for {company_name} in {country}')
        if not os.getenv("ANTHROPIC_API_KEY"):
            app.logger.error('No ANTHROPIC_API_KEY found in environment')
            return "Error: No API key configured"

        app.logger.info(f'Using API key starting with: {os.getenv("ANTHROPIC_API_KEY")[:8]}...')
        
        # Try the new messages API first
        try:
            message = await anthropic.messages.create(
                model="claude-3-opus-20240229",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": f"How many employees does {company_name} have in {country}? Please respond with ONLY a number. If you cannot find the information, respond with 'Error retrieving data'"
                }],
                temperature=0
            )
            response = message.content
        except AttributeError:
            # Fallback to older completions API
            app.logger.info('Falling back to completions API')
            completion = anthropic.completions.create(
                model="claude-2.1",
                max_tokens_to_sample=1024,
                prompt=f"\n\nHuman: How many employees does {company_name} have in {country}? Respond with ONLY a number. If you cannot find the information, respond with 'Error retrieving data'\n\nAssistant:",
                temperature=0
            )
            response = completion.completion.strip()
        
        app.logger.info(f'Claude API response for {company_name}: {response}')
        
        # Try to convert to number if possible
        try:
            int(response)
            return response
        except ValueError:
            if "error" in response.lower():
                return "Error retrieving data"
            return response

    except Exception as e:
        app.logger.error(f'Error calling Claude API: {str(e)}')
        app.logger.error(f'Error type: {type(e).__name__}')
        app.logger.error(f'Full error details: {e.__dict__}')
        return f"Error: {str(e)}"

async def process_companies(companies, country):
    try:
        app.logger.info(f'Processing {len(companies)} companies for {country}')
        results = []
        for company in companies:
            count = await get_employee_count(company, country)
            app.logger.info(f'Got count for {company}: {count}')
            results.append({'company': company, 'employee_count': count})
        return results
    except Exception as e:
        app.logger.error(f'Error processing companies: {str(e)}')
        return [{'company': company, 'employee_count': 'Error retrieving data'} for company in companies]

@app.route('/api/countries', methods=['GET'])
def get_countries():
    app.logger.info('Countries endpoint called')
    app.logger.info(f'Returning countries: {ASIAN_AUSTRALIAN_COUNTRIES}')
    return jsonify(ASIAN_AUSTRALIAN_COUNTRIES)

@app.route('/api/process', methods=['POST'])
async def process_file():
    try:
        app.logger.info('Process file endpoint called')
        
        # Get file from request
        if 'file' not in request.files:
            app.logger.error('No file part in request')
            return jsonify({'error': 'No file part'}), 400
        
        file = request.files['file']
        if not file:
            app.logger.error('No file selected')
            return jsonify({'error': 'No file selected'}), 400
        
        # Get country from form
        country = request.form.get('country')
        if not country:
            app.logger.error('No country specified')
            return jsonify({'error': 'No country specified'}), 400
        
        app.logger.info(f'Processing file for country: {country}')
        
        # Read the CSV file
        file_content = file.read()
        if isinstance(file_content, bytes):
            file_content = file_content.decode('UTF8')
        stream = io.StringIO(file_content, newline=None)
        csv_input = csv.reader(stream)
        
        # Get headers and rows
        try:
            headers = next(csv_input)  # Get header row
            rows = list(csv_input)     # Get all data rows
        except Exception as e:
            app.logger.error(f'Error reading CSV: {str(e)}')
            return jsonify({'error': 'Invalid CSV format'}), 400
            
        app.logger.info(f'CSV headers: {headers}')
        app.logger.info(f'Found {len(rows)} companies to process')
        
        # Find company name column
        company_name_index = next((i for i, h in enumerate(headers) if 'company' in h.lower()), 0)
        
        # Get company names
        companies = [row[company_name_index] for row in rows if len(row) > company_name_index]
        
        # Process companies
        employee_counts = await process_companies(companies, country)
        
        # Create new CSV with results
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write headers
        new_headers = headers + ['Employee Count']
        writer.writerow(new_headers)
        
        # Write data rows with employee counts
        for i, row in enumerate(rows):
            if company_name_index < len(row):
                new_row = list(row)
                count = employee_counts[i]['employee_count'] if i < len(employee_counts) else 'Error: No data'
                new_row.append(count)
                writer.writerow(new_row)
                app.logger.info(f'Processed {row[company_name_index]}: {count}')
        
        # Prepare response
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name='processed_companies.csv'
        )
        
    except Exception as e:
        app.logger.error(f'Error in process_file: {str(e)}')
        app.logger.error(f'Error type: {type(e).__name__}')
        app.logger.error(f'Full error details: {e.__dict__}')
        return jsonify({'error': str(e)}), 500

@app.route('/')
def health_check():
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    debug = os.getenv('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
