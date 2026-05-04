# Gunicorn configuration — adjust bind/workers for your host.
# Start with: gunicorn -c deploy/gunicorn.conf.py ims.wsgi:application
bind = "127.0.0.1:8000"
workers = 3
threads = 2
timeout = 120
accesslog = "-"
errorlog = "-"
