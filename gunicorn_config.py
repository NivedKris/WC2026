# ==============================
# Gunicorn Config — Render Free Plan
# ==============================

# Bind to all interfaces on Render
bind = "0.0.0.0:8000"

# 🧠 Keep it light: Render free = 0.1 CPU, 512 MB RAM
workers = 1                # Only one process
threads = 2                # Two threads for small concurrency
worker_class = "gevent"
     # Default worker — simple and efficient
timeout = 90               # 90s timeout (Render can be slow to spin up)
keepalive = 5

# 🧩 Memory optimization
preload_app = False        # Don’t preload app to save memory
max_requests = 1000        # Restart worker periodically to avoid leaks
max_requests_jitter = 50   # Add randomness to restarts

# 📜 Logging
accesslog = "-"            # Log to stdout (Render shows this)
errorlog = "-"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# 🔒 Security limits
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# 🚀 Optional performance tweak
# Enable if your app doesn’t use global state
# preload_app = True  # Uncomment only if memory allows
