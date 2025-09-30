#!/bin/bash
set -e

echo "==== Server Initialization ===="

# --- Server Configuration ---
echo ">> Setting up server environment..."

if [ -f "server.properties" ]; then
    sed -i "s/^server-port=.*/server-port=7860/" server.properties
    sed -i "s/^query.port=.*/query.port=7860/" server.properties
    echo "✅ Port configured: 7860"
else
    echo "⚠️  Using default configuration"
fi

# --- Data Setup ---
echo ">> Loading world data..."
if command -v python3 >/dev/null 2>&1 && [ -f "download_world.py" ]; then
    python3 download_world.py || echo "⚠️  Using default world"
else
    echo "ℹ️  No custom data found"
fi

chmod -R 777 /app/world* 2>/dev/null || true
chmod -R 777 /app/plugins 2>/dev/null || true

echo "Available data folders:"
ls -la /app/ | grep world || echo "No custom data - generating new"

# --- Start Main Service ---
echo ">> Starting main service on port 7860..."
echo ">> Java: $(java -version 2>&1 | head -n 1)"
echo ">> Memory: 8GB allocated"
echo ">> CPU: Optimized for 2 cores with fast world generation"

exec java -server -Xmx8G -Xms8G \
    -XX:+UseG1GC \
    -XX:+ParallelRefProcEnabled \
    -XX:ParallelGCThreads=2 \
    -XX:ConcGCThreads=1 \
    -XX:MaxGCPauseMillis=50 \
    -XX:+UnlockExperimentalVMOptions \
    -XX:+DisableExplicitGC \
    -XX:+AlwaysPreTouch \
    -XX:G1NewSizePercent=30 \
    -XX:G1MaxNewSizePercent=50 \
    -XX:G1HeapRegionSize=16M \
    -XX:G1ReservePercent=15 \
    -XX:G1HeapWastePercent=5 \
    -XX:G1MixedGCCountTarget=3 \
    -XX:InitiatingHeapOccupancyPercent=10 \
    -XX:G1MixedGCLiveThresholdPercent=90 \
    -XX:G1RSetUpdatingPauseTimePercent=5 \
    -XX:SurvivorRatio=32 \
    -XX:+PerfDisableSharedMem \
    -XX:MaxTenuringThreshold=1 \
    -XX:G1SATBBufferEnqueueingThresholdPercent=30 \
    -XX:G1ConcMarkStepDurationMillis=5 \
    -XX:G1ConcRSHotCardLimit=16 \
    -XX:+UseStringDeduplication \
    -Dfile.encoding=UTF-8 \
    -Dcom.mojang.eula.agree=true \
    -jar purpur.jar --nogui