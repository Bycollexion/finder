import os
import csv
import io
import json
import redis
import logging
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from dotenv import load_dotenv
from anthropic import AsyncAnthropic
from concurrent.futures import ThreadPoolExecutor

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)

# Configure for async operation
app.config['PROPAGATE_EXCEPTIONS'] = True
app.config['CORS_HEADERS'] = 'Content-Type'
app.config['CORS_RESOURCES'] = {r"/api/*": {"origins": "*", "methods": ["GET", "POST", "OPTIONS"], "allow_headers": ["Content-Type"]}}

# Initialize Anthropic client
anthropic = AsyncAnthropic()

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

# List of Asian and Australian countries
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

async def get_employee_count(company_name, country):
    try:
        # Check cache first
        cache_key = get_cache_key(company_name, country)
        cached_result = redis_client.get(cache_key)
        
        if cached_result:
            print(f"Cache hit for {company_name} in {country}")
            return cached_result
            
        print(f"Cache miss - requesting employee count for {company_name} in {country}")
        completion = await anthropic.completions.create(
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
        return await get_employee_count_without_cache(company_name, country)
    except Exception as e:
        print(f"Error getting employee count for {company_name}: {str(e)}")
        return "Error retrieving data"

async def get_employee_count_without_cache(company_name, country):
    try:
        app.logger.info(f'Querying Claude API for {company_name} in {country}')
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            app.logger.error('No ANTHROPIC_API_KEY found in environment')
            return "Error: No API key configured"

        # Log environment variables for debugging
        app.logger.info('Environment variables:')
        for key in os.environ:
            if 'KEY' in key or 'SECRET' in key:
                app.logger.info(f'{key}: {"*" * 8}{os.environ[key][-4:]}')
            else:
                app.logger.info(f'{key}: {os.environ[key]}')

        app.logger.info(f'Using API key: ***{api_key[-4:]}')
        
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
            
            app.logger.info(f'Raw API response: {message}')
            response = message.content[0].text
            app.logger.info(f'Claude API response for {company_name}: {response}')
            
            # Try to convert to number if possible
            try:
                int(response)
                return response
            except ValueError:
                if "error" in response.lower():
                    return "Error retrieving data"
                return response

        except Exception as api_error:
            app.logger.error(f'API call error: {str(api_error)}')
            app.logger.error(f'API error type: {type(api_error).__name__}')
            app.logger.error(f'API error details: {api_error.__dict__}')
            return f"Error: API call failed - {str(api_error)}"

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
            app.logger.info(f'Processing company: {company}')
            count = await get_employee_count_without_cache(company, country)
            app.logger.info(f'Result for {company}: {count}')
            results.append({
                'company': company,
                'employee_count': count
            })
        
        app.logger.info(f'Finished processing all companies. Results: {results}')
        return results
        
    except Exception as e:
        app.logger.error(f'Error processing companies: {str(e)}')
        app.logger.error(f'Error type: {type(e).__name__}')
        app.logger.error(f'Error details: {e.__dict__}')
        return [{'company': company, 'employee_count': 'Error retrieving data'} for company in companies]

@app.route('/')
def index():
    try:
        return jsonify({"status": "healthy", "message": "API is running"}), 200
    except Exception as e:
        app.logger.error(f"Error in index route: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/countries')
def get_countries():
    try:
        return jsonify(ASIAN_AUSTRALIAN_COUNTRIES)
    except Exception as e:
        app.logger.error(f"Error in get_countries route: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

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

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    debug = os.getenv('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
