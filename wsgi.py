import os
from werkzeug.middleware.proxy_fix import ProxyFix
from clubapp import create_app

app = create_app()
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
app.config["SESSION_COOKIE_SECURE"] = os.getenv("DBXM_HTTPS", "0") == "1"
app.config["TRUSTED_HOSTS"] = [
    host.strip()
    for host in os.getenv("DBXM_TRUSTED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]
