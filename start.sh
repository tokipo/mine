#!/bin/bash
set -e

echo "==== Server Initialization ===="

# --- Server Configuration (runs instantly, no download here) ---
echo ">> Writing eula.txt and server.properties..."
echo "eula=true" > /app/eula.txt

if [ ! -f "/app/server.properties" ]; then
    echo "server-port=25565" > /app/server.properties
    echo "query.port=25565"  >> /app/server.properties
    echo "online-mode=false" >> /app/server.properties
else
    sed -i "s/^server-port=.*/server-port=25565/"   /app/server.properties
    sed -i "s/^query\.port=.*/query.port=25565/"    /app/server.properties
fi

chmod -R 777 /app 2>/dev/null || true

# KEY FIX: Start the web panel FIRST so HuggingFace health-check passes.
# World download + Minecraft boot now happen as background async tasks
# inside panel.py's lifespan — the HTTP server is ready on port 7860
# before any slow download begins.
echo "=========================================================="
echo ">> Starting Panel on port 7860 (world download will run"
echo "   in background after the server is already listening)."
echo "=========================================================="

exec python3 /app/panel.py