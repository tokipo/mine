#!/bin/bash
set -e

echo "==== Server Initialization ===="

# --- Data Setup ---
echo ">> Loading world data..."
if command -v python3 >/dev/null 2>&1 && [ -f "download_world.py" ]; then
    python3 download_world.py || echo "⚠️  Using default world"
fi

# --- Server Configuration ---
echo ">> Setting up server environment..."
echo "eula=true" > eula.txt

if [ ! -f "server.properties" ]; then
    echo "Generating default server.properties..."
    echo "server-port=25565" > server.properties
else
    sed -i "s/^server-port=.*/server-port=25565/" server.properties
    sed -i "s/^query.port=.*/query.port=25565/" server.properties
fi

chmod -R 777 /app 2>/dev/null || true

# --- Start the Web UI & Panel ---
echo "=========================================================="
echo ">> Starting Professional Panel on Port 7860..."
echo ">> Minecraft output will be suppressed here to stop spam."
echo ">> Open the Hugging Face Space URL in your browser to access the Console and File Manager!"
echo "=========================================================="

# Run the python panel script
exec python3 panel.py