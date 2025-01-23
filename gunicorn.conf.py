import multiprocessing

# Server socket
bind = "0.0.0.0:8080"  # Match Railway's port
backlog = 2048

# Worker processes - using sync workers for simplicity
workers = 4
worker_class = 'sync'
timeout = 120

# Logging
accesslog = '-'
errorlog = '-'
loglevel = 'debug'  # Increased log level for debugging

# Process naming
proc_name = 'finder'

# Server mechanics
daemon = False
pidfile = None

# Server hooks
def on_starting(server):
    """Called just before the master process is initialized."""
    pass

def on_reload(server):
    """Called before code is reloaded."""
    pass

def when_ready(server):
    """Called just after the server is started."""
    pass

def post_fork(server, worker):
    """Called just after a worker has been forked."""
    pass

def pre_fork(server, worker):
    """Called just before a worker is forked."""
    pass

def pre_exec(server):
    """Called just before a new master process is forked."""
    pass

def pre_request(worker, req):
    """Called just before a request."""
    worker.log.debug("%s %s" % (req.method, req.path))

def post_request(worker, req, environ, resp):
    """Called after a request."""
    pass

def child_exit(server, worker):
    """Called just after a worker has been exited, in the worker process."""
    pass

def worker_abort(worker):
    """Called when a worker received the SIGABRT signal."""
    pass
