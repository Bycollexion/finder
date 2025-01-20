import os
import io
import csv
import json
import redis
import logging
import httpx
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables from .env only if they don't exist
load_dotenv(override=False)

app = Flask(__name__)
CORS(app)

# Configure for async operation
app.config['PROPAGATE_EXCEPTIONS'] = True
app.config['CORS_HEADERS'] = 'Content-Type'
app.config['CORS_RESOURCES'] = {r"/api/*": {"origins": "*", "methods": ["GET", "POST", "OPTIONS"], "allow_headers": ["Content-Type"]}}

# Initialize API client
proxycurl_api_key = os.environ.get("PROXYCURL_API_KEY", "bj1qdFmUqZR6Vkiyiny1LA")

# Initialize Redis client
redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'localhost'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    username=os.getenv('REDIS_USER'),
    password=os.getenv('REDIS_PASSWORD'),
    db=0,
    decode_responses=True
)

SUPPORTED_COUNTRIES = [
    "Malaysia",
    "Singapore",
    "Indonesia",
    "Thailand",
    "Vietnam",
    "Philippines",
    "Australia",
    "New Zealand"
]

async def get_company_linkedin_url(company_name):
    """Convert company name to LinkedIn vanity name"""
    # Map of common company names to their LinkedIn vanity names
    company_map = {
        'google': 'google',
        'facebook': 'meta',
        'meta': 'meta',
        'amazon': 'amazon',
        'linkedin': 'linkedin',
        'linkedln': 'linkedin',
        'jobstreet': 'jobstreet-com',
        'seek': 'seek',
        'jobs db': 'jobsdb',
        'jobsdb': 'jobsdb',
        'singtel': 'singtel'
    }
    
    return company_map.get(company_name.lower())

async def get_employee_count_from_proxycurl(company_name):
    """Get employee count from Proxycurl Company Profile API"""
    try:
        # Get company vanity name
        vanity_name = await get_company_linkedin_url(company_name)
        if not vanity_name:
            logger.error(f"No vanity name mapping found for {company_name}")
            return "Error retrieving data"
            
        # Construct LinkedIn company URL
        company_url = f"https://www.linkedin.com/company/{vanity_name}/"
        logger.info(f"Using LinkedIn URL: {company_url}")
            
        api_endpoint = "https://nubela.co/proxycurl/api/linkedin/company"
        params = {'url': company_url}
        headers = {'Authorization': f'Bearer {proxycurl_api_key}'}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(api_endpoint, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            # Get employee count from response
            employee_count = data.get('employee_count')
            if employee_count:
                return str(employee_count)
            return "Error retrieving data"
            
    except Exception as e:
        logger.error(f"Error getting company data: {str(e)}")
        return "Error retrieving data"

async def get_employee_count_without_cache(company_name, country):
    try:
        logger.info(f'Getting employee count for {company_name} in {country}')
        return await get_employee_count_from_proxycurl(company_name)
    except Exception as e:
        logger.error(f'Error getting employee count: {str(e)}')
        logger.error(f'Error type: {type(e).__name__}')
        logger.error(f'Full error details: {e.__dict__}')
        return "Error retrieving data"

async def get_employee_count(company_name, country):
    try:
        # Check cache first
        cache_key = f"{company_name}_{country}"
        try:
            cached_result = redis_client.get(cache_key)
            if cached_result:
                logger.info(f'Cache hit for {company_name}')
                return cached_result
        except Exception as redis_error:
            logger.error(f'Redis error: {str(redis_error)}')
            # Continue without cache if Redis is not available
            pass

        # Get fresh data
        result = await get_employee_count_without_cache(company_name, country)
        
        # Cache the result
        try:
            if result and result != "Error retrieving data":
                redis_client.set(cache_key, result)
                redis_client.expire(cache_key, 60 * 60 * 24)  # Cache for 24 hours
        except Exception as redis_error:
            logger.error(f'Redis caching error: {str(redis_error)}')
            # Continue without caching if Redis is not available
            pass
            
        return result
    except Exception as e:
        logger.error(f'Error in get_employee_count: {str(e)}')
        return "Error retrieving data"

async def process_companies(companies, country):
    try:
        logger.info(f'Processing {len(companies)} companies for {country}')
        results = []
        
        for company in companies:
            logger.info(f'Processing company: {company}')
            count = await get_employee_count(company, country)
            logger.info(f'Result for {company}: {count}')
            results.append({
                'company': company,
                'employee_count': count
            })
        
        logger.info(f'Finished processing all companies. Results: {results}')
        return results
        
    except Exception as e:
        logger.error(f'Error processing companies: {str(e)}')
        logger.error(f'Error type: {type(e).__name__}')
        logger.error(f'Error details: {e.__dict__}')
        return [{'company': company, 'employee_count': 'Error retrieving data'} for company in companies]

@app.route('/')
def index():
    try:
        return jsonify({"status": "healthy", "message": "API is running"}), 200
    except Exception as e:
        logger.error(f"Error in index route: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/countries')
def get_countries():
    try:
        return jsonify(SUPPORTED_COUNTRIES)
    except Exception as e:
        logger.error(f"Error in get_countries route: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/process', methods=['POST'])
async def process_file():
    try:
        logger.info('Process file endpoint called')
        
        # Get file from request
        if 'file' not in request.files:
            logger.error('No file part in request')
            return jsonify({'error': 'No file part'}), 400
        
        file = request.files['file']
        if not file:
            logger.error('No file selected')
            return jsonify({'error': 'No file selected'}), 400
        
        # Get country from form
        country = request.form.get('country')
        if not country:
            logger.error('No country specified')
            return jsonify({'error': 'No country specified'}), 400
        
        logger.info(f'Processing file for country: {country}')
        
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
            logger.error(f'Error reading CSV: {str(e)}')
            return jsonify({'error': 'Invalid CSV format'}), 400
            
        logger.info(f'CSV headers: {headers}')
        logger.info(f'Found {len(rows)} companies to process')
        
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
                logger.info(f'Processed {row[company_name_index]}: {count}')
        
        # Prepare response
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name='processed_companies.csv'
        )
        
    except Exception as e:
        logger.error(f'Error in process_file: {str(e)}')
        logger.error(f'Error type: {type(e).__name__}')
        logger.error(f'Full error details: {e.__dict__}')
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    debug = os.getenv('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
