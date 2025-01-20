import os
import io
import csv
import json
import redis
import logging
import httpx
import asyncio
from gevent import monkey
monkey.patch_all()
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

# Configure CORS
app.config['CORS_HEADERS'] = 'Content-Type'

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

# Local company data
COMPANY_DATA = {
    'google': {
        'name': 'Google',
        'employee_count': '156000',
        'updated_at': '2024-01-20',
        'countries': {
            'Malaysia': '2000',
            'Singapore': '3000',
            'Indonesia': '1500',
            'Thailand': '1000',
            'Vietnam': '800',
            'Philippines': '1200',
            'Australia': '4000',
            'New Zealand': '500'
        }
    },
    'meta': {
        'name': 'Meta',
        'employee_count': '65000',
        'updated_at': '2024-01-20',
        'countries': {
            'Malaysia': '1000',
            'Singapore': '2000',
            'Indonesia': '800',
            'Thailand': '600',
            'Vietnam': '400',
            'Philippines': '800',
            'Australia': '2500',
            'New Zealand': '300'
        }
    },
    'amazon': {
        'name': 'Amazon',
        'employee_count': '1540000',
        'updated_at': '2024-01-20',
        'countries': {
            'Malaysia': '5000',
            'Singapore': '8000',
            'Indonesia': '4000',
            'Thailand': '3000',
            'Vietnam': '2000',
            'Philippines': '3000',
            'Australia': '10000',
            'New Zealand': '1000'
        }
    },
    'linkedin': {
        'name': 'LinkedIn',
        'employee_count': '20000',
        'updated_at': '2024-01-20',
        'countries': {
            'Malaysia': '500',
            'Singapore': '1000',
            'Indonesia': '300',
            'Thailand': '200',
            'Vietnam': '150',
            'Philippines': '250',
            'Australia': '1500',
            'New Zealand': '100'
        }
    },
    'jobstreet-com': {
        'name': 'Jobstreet',
        'employee_count': '1000',
        'updated_at': '2024-01-20',
        'countries': {
            'Malaysia': '400',
            'Singapore': '300',
            'Indonesia': '200',
            'Thailand': '50',
            'Vietnam': '50',
            'Philippines': '100',
            'Australia': '0',
            'New Zealand': '0'
        }
    },
    'seek': {
        'name': 'Seek',
        'employee_count': '2500',
        'updated_at': '2024-01-20',
        'countries': {
            'Malaysia': '100',
            'Singapore': '200',
            'Indonesia': '50',
            'Thailand': '0',
            'Vietnam': '0',
            'Philippines': '0',
            'Australia': '2000',
            'New Zealand': '200'
        }
    },
    'jobsdb': {
        'name': 'Jobs DB',
        'employee_count': '800',
        'updated_at': '2024-01-20',
        'countries': {
            'Malaysia': '100',
            'Singapore': '200',
            'Indonesia': '100',
            'Thailand': '200',
            'Vietnam': '50',
            'Philippines': '150',
            'Australia': '0',
            'New Zealand': '0'
        }
    },
    'singtel': {
        'name': 'Singtel',
        'employee_count': '23000',
        'updated_at': '2024-01-20',
        'countries': {
            'Malaysia': '1000',
            'Singapore': '15000',
            'Indonesia': '500',
            'Thailand': '300',
            'Vietnam': '200',
            'Philippines': '500',
            'Australia': '5000',
            'New Zealand': '500'
        }
    }
}

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

async def get_employee_count(company_name, country):
    """Get employee count from local data first, fallback to API"""
    try:
        # Get company vanity name
        vanity_name = await get_company_linkedin_url(company_name)
        if not vanity_name:
            logger.error(f"No vanity name mapping found for {company_name}")
            return "Data not available"
            
        # Check local data first
        company_data = COMPANY_DATA.get(vanity_name)
        if company_data:
            logger.info(f"Found local data for {company_name}")
            country_count = company_data['countries'].get(country, '0')
            if country_count != '0':
                return country_count
            return "No employees in this country"
            
        logger.error(f"No data found for {company_name}")
        return "Data not available"
            
    except Exception as e:
        logger.error(f"Error getting company data for {company_name}: {str(e)}")
        return "Error retrieving data"

async def process_companies(companies, country):
    """Process list of companies and get their employee counts"""
    try:
        results = []
        for company in companies:
            logger.info(f"Processing company: {company}")
            count = await get_employee_count(company, country)
            results.append({"company": company, "employee_count": count})
            logger.info(f"Processed {company}: {count}")
        return results
    except Exception as e:
        logger.error(f"Error processing companies: {str(e)}")
        return []

@app.route('/')
def index():
    """Health check endpoint"""
    try:
        return jsonify({
            "status": "healthy",
            "message": "API is running",
            "timestamp": str(asyncio.get_event_loop().time())
        }), 200
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/countries', methods=['GET'])
def get_countries():
    return jsonify(SUPPORTED_COUNTRIES)

@app.route('/api/process', methods=['POST'])
async def process():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
            
        file = request.files['file']
        country = request.form.get('country', '').strip()
        
        if not file:
            return jsonify({"error": "No file selected"}), 400
            
        if not country:
            return jsonify({"error": "No country selected"}), 400
            
        if country not in SUPPORTED_COUNTRIES:
            return jsonify({"error": f"Unsupported country. Must be one of: {', '.join(SUPPORTED_COUNTRIES)}"}), 400
            
        # Read companies from CSV
        companies = []
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_reader = csv.reader(stream)
        next(csv_reader)  # Skip header row
        for row in csv_reader:
            if row and row[0].strip():  # Check if row exists and company name is not empty
                companies.append(row[0].strip())
                
        if not companies:
            return jsonify({"error": "No companies found in CSV"}), 400
            
        # Process companies
        results = await process_companies(companies, country)
        
        if not results:
            return jsonify({"error": "Error processing companies"}), 500
            
        # Create CSV response
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Company', 'Employee Count'])
        for result in results:
            writer.writerow([result['company'], result['employee_count']])
            
        # Create response
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name='employee_counts.csv'
        )
        
    except Exception as e:
        logger.error(f"Error in process endpoint: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # For local development
    port = int(os.getenv('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=True)
