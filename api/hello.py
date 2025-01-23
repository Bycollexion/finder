from http.server import BaseHTTPRequestHandler

def handler(request):
    print("Request received:", request)  # Debug print
    return {
        "body": "Hello from Python!"
    }
