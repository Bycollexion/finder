from app import app

# For WSGI servers
application = app

if __name__ == "__main__":
    app.run()
