#!/bin/bash
# Lambda entrypoint; the Web Adapter layer proxies Function URL requests to this server.
exec python3 -m uvicorn server:app --host 127.0.0.1 --port 8000
