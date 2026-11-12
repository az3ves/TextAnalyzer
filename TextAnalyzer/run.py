import threading
import webbrowser
import os

import config
from app import app

if os.getenv("OPEN_BROWSER", "1") != "0":
    browser_host = "127.0.0.1" if config.HOST in ("0.0.0.0", "::") else config.HOST
    timer = threading.Timer(1.5, webbrowser.open, [f"http://{browser_host}:{config.PORT}"])
    timer.daemon = True
    timer.start()
app.run(host=config.HOST, port=config.PORT)
