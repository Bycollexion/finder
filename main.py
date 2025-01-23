from http.server import BaseHTTPRequestHandler
from api.index import get_countries, handle_request
import json

def app(request):
    print("Received request:", request)  # Debug print
    
    # Handle request object more safely
    try:
        # Check if request is a dictionary
        if isinstance(request, dict):
            path = request.get('url', '')
            if path:
                path = path.split('?')[0]  # Get path without query params
            method = request.get('method', 'GET')
            body = request.get('body', '')
        else:
            # Try to access as object attributes
            path = getattr(request, 'url', '')
            if path:
                path = path.split('?')[0]
            method = getattr(request, 'method', 'GET')
            body = getattr(request, 'body', '')
        
        print(f"Path: {path}, Method: {method}")  # Debug print

        # Handle OPTIONS request for CORS
        if method == 'OPTIONS':
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                    'Access-Control-Allow-Headers': 'Content-Type'
                },
                'body': ''
            }

        # Health check endpoint
        if path.endswith('/api/health'):
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'status': 'ok'})
            }

        # Handle the request
        if path.endswith('/api/countries') and method == 'GET':
            print("Getting countries")  # Debug print
            countries = get_countries()
            print("Countries:", countries)  # Debug print
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                    'Access-Control-Allow-Headers': 'Content-Type'
                },
                'body': json.dumps(countries)
            }
        
        # Handle other requests
        response = handle_request(path, method, body)
        response['headers'] = {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type'
        }
        return response

    except Exception as e:
        print(f"Error processing request: {str(e)}")  # Debug print
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'error': str(e)})
        }
