from http.server import BaseHTTPRequestHandler
from main import app

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write('Health check OK'.encode())
        
    def do_POST(self):
        # Get the content length
        content_length = int(self.headers['Content-Length'])
        # Get the request body
        body = self.rfile.read(content_length)
        
        # Create a test client
        with app.test_client() as client:
            # Forward the request to Flask
            response = client.post(self.path, data=body, headers=dict(self.headers))
            
            # Send the response back
            self.send_response(response.status_code)
            for header, value in response.headers:
                self.send_header(header, value)
            self.end_headers()
            self.wfile.write(response.data)
