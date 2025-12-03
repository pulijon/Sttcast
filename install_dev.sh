#!/bin/bash
# Script to install Sttcast in development mode
# Author: José Miguel Robles Román
# Date: 2025-12-03
# License: GPL v3

set -e

echo "=== Installing Sttcast in development mode ==="

# Verify we are in the correct directory
if [ ! -f "setup.py" ]; then
    echo "Error: This script must be run from the root directory of the Sttcast project"
    echo "Current location: $(pwd)"
    exit 1
fi

# Verify virtual environment exists
if [ ! -d ".venv" ]; then
    echo "Error: The virtual environment .venv does not exist"
    echo "Please create the virtual environment before running this script."
    echo "Example:"
    echo "  python3.11 -m venv .venv"
    echo "  source .venv/bin/activate"
    echo "  pip install -r requirements.txt"
    exit 1
fi

# Verify virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo "Error: Virtual environment is not activated"
    echo "Please activate the virtual environment before running this script:"
    echo "  source .venv/bin/activate"
    exit 1
fi

# Verify we are in the correct virtual environment
if [ "$VIRTUAL_ENV" != "$(pwd)/.venv" ]; then
    echo "Error: You are in a different virtual environment"
    echo "Current environment: $VIRTUAL_ENV"
    echo "Expected environment: $(pwd)/.venv"
    echo "Please activate the correct virtual environment:"
    echo "  deactivate"
    echo "  source .venv/bin/activate"
    exit 1
fi

echo "Correct virtual environment: $VIRTUAL_ENV"
echo "Installing package in editable mode..."
pip install -e .

echo ""
echo "=== Verifying installation ==="
python -c "import tools.logs; import api.apicontext; print('✓ Imports working correctly')"

echo ""
echo "=== Installation completed ==="
echo "Now you can use imports like:"
echo "  from tools.logs import logcfg"
echo "  from api.apicontext import GetContextRequest"
echo ""
echo "To activate the virtual environment in future sessions:"
echo "  source .venv/bin/activate"
echo ""
echo "To dockerize the RAG client:"
echo "  cd rag/client/docker"
echo "  docker-compose build"
echo "  docker-compose up -d"
