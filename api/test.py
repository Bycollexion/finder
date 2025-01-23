from http.server import BaseHTTPRequestHandler

def handler(request, response):
    return {
        "statusCode": 200,
        "body": "Hello from Python!"
    }
