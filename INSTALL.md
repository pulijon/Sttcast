# Sttcast Installation and Configuration

This document explains how to set up the development environment to work with the Sttcast project.

## Development Mode Installation

To use absolute imports like `import tools.logs`, `import api.apicontext`, etc., install the package in development mode from the project root:

```bash
cd /home/jmrobles/Podcasts/Cowboys\ de\ Medianoche/Sttcast
pip install -e .
```

The `-e` (editable) option allows code changes to be reflected immediately without needing to reinstall.

## Project Structure

```
Sttcast/
├── api/                    # Shared API models (Pydantic)
│   ├── __init__.py
│   ├── apicontext.py      # Models for context_server
│   └── apihmac.py         # HMAC functions for authentication
├── tools/                  # Shared utilities
│   ├── __init__.py
│   ├── logs.py            # Logging configuration
│   └── envvars.py         # Environment variables loading
├── rag/                    # RAG Services
│   ├── __init__.py
│   ├── sttcast_rag_service.py  # RAG Server
│   └── client/            # RAG Web Client
│       ├── client_rag.py
│       └── docker/        # Client Dockerization
├── db/                     # Database Services
│   ├── __init__.py
│   ├── context_server.py  # Context Server
│   └── sttcastdb.py       # Database ORM
├── summaries/             # Summary scripts
│   └── get_rag_summaries.py
├── notebooks/             # Jupyter notebooks
│   └── addepisodes.ipynb
├── setup.py               # Python package configuration
└── .env/                  # Environment variables
```

## Modular Imports

After installing the package, you can use absolute imports:

```python
# Shared tools
from tools.logs import logcfg
from tools.envvars import load_env_vars_from_directory

# API Models
from api.apicontext import GetContextRequest, GetContextResponse
from api.apihmac import create_auth_headers, validate_hmac_auth, serialize_body
```

## Benefits

1. **No `sys.path` manipulation**: No more `sys.path.append(...)` 
2. **Clear imports**: `import tools.logs` instead of relative paths
3. **Modularity**: Clear separation between API, tools, and services
4. **Reusability**: API models and HMAC functions are shared between services
5. **Optimized Docker**: Each service copies only what it needs
6. **Centralization**: HMAC authentication code in one place (`api/apihmac.py`)

## For Docker

The Dockerfile is already configured with `PYTHONPATH=/app`, so absolute imports work automatically inside the container.

## Verification

Verify that the installation worked correctly:

```python
python3 -c "import tools.logs; import api.apicontext; print('OK')"
```

If there are no errors, the configuration is correct.

## Running Services

All main services require the package to be installed with `pip install -e .`:

### Context Server
```bash
source .venv/bin/activate
cd db
python context_server.py
```

### RAG Client
```bash
source .venv/bin/activate
cd rag/client
python client_rag.py
```

### Summary Scripts
```bash
source .venv/bin/activate
cd summaries
python get_rag_summaries.py --help
```

### Notebooks
The notebooks in `notebooks/` also require the package to be installed. Make sure to select the kernel from the `.venv` virtual environment.
