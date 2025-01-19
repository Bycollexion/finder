import logging
from asgiref.wsgi import WsgiToAsgi
from app import app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("Starting ASGI application...")
# This needs to be named 'application' for Railway/Uvicorn to find it
application = WsgiToAsgi(app)
logger.info("ASGI application ready")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(application, host="0.0.0.0", port=8080)
