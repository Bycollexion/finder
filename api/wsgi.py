from asgiref.wsgi import WsgiToAsgi
from app import app

# Convert WSGI app to ASGI
application = WsgiToAsgi(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(application, host="0.0.0.0", port=8080)
