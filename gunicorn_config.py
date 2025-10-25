import os

# ✅ Server socket — Render sets PORT env variable
bind = f"0.0.0.0:{os.environ.get('PORT', 8000)}"

# ✅ Worker setup (keep it tiny)
workers = 1                 # One worker — 0.1 CPU can’t handle more
threads = 2                 # Two threads (enough for lightweight Flask)
worker_class = "sync"       # Simplest, safest for small CPU/RAM
timeout = 90
keepalive = 5

# ✅ Memory optimization
preload_app = False          # Don’t preload, saves memory
max_requests = 500           # Restart occasionally to free memory
max_requests_jitter = 25

# ✅ Logging
accesslog = "-"              # Output logs to stdout (Render shows these)
errorlog = "-"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# ✅ Security / limits
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190
