from http.server import BaseHTTPRequestHandler
from api.index import get_countries, handle_request
import json

def app(request):
    # Parse the request path
    path = request.get('path', '')
    method = request.get('method', 'GET')
    body = request.get('body', '')

    # Handle the request
    if path == '/api/countries' and method == 'GET':
        countries = get_countries()
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
