# gunicorn_config.py
import os

bind = f"0.0.0.0:{os.environ.get('PORT', 8000)}"
workers = 1
threads = 2
worker_class = "gevent"
timeout = 90
keepalive = 5
preload_app = False
max_requests = 1000
max_requests_jitter = 50
accesslog = "-"
errorlog = "-"
loglevel = "info"
