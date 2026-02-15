#!/bin/bash
pkill -f "python main.py" 2>/dev/null || true
echo "SMS AI Agent stopped"
