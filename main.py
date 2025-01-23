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
CORS(app, resources={r"/api/*": {"origins": ["http://localhost:3000", "https://finder-git-main-bycollexions-projects.vercel.app"]}})

# Configure OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

def extract_number(text):
    """Extract the first number from text"""
    numbers = re.findall(r'\b\d{2,6}\b', text)  # Look for numbers between 2-6 digits
    if numbers:
        return numbers[0].replace(',', '')
    return None

def search_web_info(company, country):
    """Search for company employee count information using OpenAI"""
    try:
        if company.lower() == 'company':
            return None

        # First ask GPT to search and analyze
        messages = [
            {
                "role": "system",
                "content": f"""You are an expert at finding employee counts for company offices. 
                Search for information about {company}'s office in {country}.
                Focus on:
                1. Direct employee counts for the {country} office
                2. LinkedIn data about employees in {country}
                3. Recent news about office size/expansion in {country}
                4. Job postings and hiring information in {country}

                Format your response as:
                Employee Counts:
                [List specific numbers found with sources]

                LinkedIn Data:
                [Summary of LinkedIn information]

                News:
                [Relevant news about office size]

                Hiring:
                [Information about current hiring]

                Be specific to {country} office, not global numbers.
                Include URLs for sources when available."""
            },
            {
                "role": "user",
                "content": f"How many employees does {company} have in their {country} office? Search the web and analyze the data."
            }
        ]

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=messages,
            temperature=0.7,
            max_tokens=1000
        )

        web_data = response.choices[0].message['content']
        logger.debug(f"Web search results for {company}:\n{web_data}")

        # Now analyze the data to get a number
        messages = [
            {
                "role": "system",
                "content": f"""You are an expert at estimating employee counts for company offices.
                Analyze the provided data about {company}'s office in {country}.
                Return ONLY a number representing your best estimate of employees in the {country} office.
                If you find a specific number from a reliable source, use that.
                Otherwise, estimate based on available data.
                Must be specific to {country} office, not global numbers.
                
                Rules:
                1. Return ONLY a number, no text
                2. Numbers should be between 20-50,000
                3. If no reliable data, estimate based on office size/type
                4. Prefer recent data over old
                5. Local office numbers only, not global
                
                Example good responses:
                250
                1500
                
                Bad responses (never do these):
                "About 250 employees"
                "250-300 employees"
                "250 globally"
                """
            },
            {
                "role": "user",
                "content": f"Based on this data, estimate employees in {company}'s {country} office:\n{web_data}"
            }
        ]

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=messages,
            temperature=0.7,
            max_tokens=150
        )

        count = extract_number(response.choices[0].message['content'])
        confidence = "High" if "Direct Employee Count" in web_data else "Low"

        logger.debug(f"Got response for {company}: {count} (confidence: {confidence})")

        return {
            "Company": company,
            "Employee Count": count if count else "1000",
            "Confidence": confidence
        }

    except Exception as e:
        logger.error(f"Error searching web info: {str(e)}")
        return {
            "Company": company,
            "Employee Count": "1000",
            "Confidence": "Low"
        }

@app.route('/api/process', methods=['POST'])
def process_file():
    """Process uploaded CSV file"""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files['file']
        if not file.filename.endswith('.csv'):
            return jsonify({"error": "File must be a CSV"}), 400

        # Read CSV file
        df = pd.read_csv(file)
        required_columns = ['Company', 'Country']
        if not all(col in df.columns for col in required_columns):
            return jsonify({"error": "CSV must contain Company and Country columns"}), 400

        # Process each company
        results = []
        total_rows = len(df)
        logger.debug(f"Processing {total_rows} companies")

        for index, row in df.iterrows():
            company = row['Company'].strip()
            country = row['Country'].strip()
            
            logger.debug(f"Processing batch {index + 1}/{total_rows}")
            result = search_web_info(company, country)
            if result:
                results.append(result)

        # Create output CSV
        logger.debug("Creating output CSV...")
        output_filename = f"employee_counts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        with open(output_filename, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['Company', 'Employee Count', 'Confidence'])
            writer.writeheader()
            writer.writerows(results)

        # Prepare file download
        logger.debug("Preparing file download...")
        
        # Set CORS headers
        logger.debug(f"Request origin: {request.headers.get('Origin')}")
        headers = {
            'Content-Type': 'text/csv',
            'Content-Length': os.path.getsize(output_filename),
            'Content-Disposition': f'attachment; filename={output_filename}',
            'Access-Control-Allow-Origin': request.headers.get('Origin'),
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Max-Age': '3600',
            'Access-Control-Allow-Credentials': 'true'
        }
        logger.debug(f"Response headers: {headers}")

        return send_file(
            output_filename,
            mimetype='text/csv',
            as_attachment=True,
            download_name=output_filename
        )

    except Exception as e:
        logger.error(f"Error processing file: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
