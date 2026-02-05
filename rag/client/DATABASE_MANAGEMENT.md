# Database Management for RAG Queries

This document explains how to backup and restore the PostgreSQL database used for RAG queries.

## Overview

The RAG system uses PostgreSQL with pgvector extension to store user queries, responses, and embeddings. The `manageqdb.py` script provides command-line tools for:

- **Backup**: Create full SQL dumps of the queries database
- **Restore**: Restore databases from backup files (with optional automatic database/user creation)

This facilitates:
- Database migration between environments
- Disaster recovery
- Development/production synchronization
- Testing with production data snapshots

## Configuration

Database settings are configured in two files:

### `.env/queriesdb.env` - PostgreSQL Server Access
```dotenv
QUERIESDB_HOST = localhost
QUERIESDB_PORT = 5432
QUERIESDB_ADMIN_USER = postgres           # Admin credentials (for creating DBs/users)
QUERIESDB_ADMIN_PASSWORD = postgres_password
```

### `.env/rag_client.env` - Client Database Configuration
```dotenv
QUERIESDB_DB = coffeebreak                # Database name
QUERIESDB_USER = coffeebreak_user         # User for this database
QUERIESDB_PASSWORD = coffeebreak_password # User password
```

## Command-Line Usage

### Creating a Backup

```bash
python rag/client/manageqdb.py backup <output_file>
```

**Examples:**
```bash
# Simple backup
python rag/client/manageqdb.py backup ./backup.sql

# Backup with timestamp in filename
python rag/client/manageqdb.py backup ./backups/coffeebreak_$(date +%Y-%m-%d_%H%M%S).sql

# Create backups directory and backup
mkdir -p ./backups
python rag/client/manageqdb.py backup ./backups/coffeebreak_backup.sql
```

**Output:**
- Creates a complete SQL dump including schema and all data
- Automatically creates parent directories if they don't exist
- Displays file size and confirmation message

### Restoring from Backup

#### Option 1: Restore to Existing Database

The database and user must already exist:

```bash
python rag/client/manageqdb.py restore <input_file>
```

**Example:**
```bash
python rag/client/manageqdb.py restore ./backups/coffeebreak_backup.sql
```

#### Option 2: Restore with Automatic Database/User Creation

Creates the database and user if they don't exist (useful for new environments):

```bash
python rag/client/manageqdb.py restore <input_file> --create-db
```

**Example:**
```bash
python rag/client/manageqdb.py restore ./backups/coffeebreak_backup.sql --create-db
```

This option:
- Validates that PostgreSQL admin credentials are available
- Creates the user if it doesn't exist
- Creates the database if it doesn't exist
- Enables the pgvector extension
- Grants appropriate permissions
- Restores the data

## Programmatic Usage

The backup/restore functionality is also available as methods in the `RAGDatabase` class:

```python
from rag.client.queriesdb import db
import asyncio

async def backup_and_restore():
    # Backup
    await db.backup_to_file('./backup.sql')
    
    # Restore
    await db.restore_from_file('./backup.sql', create_db_and_user=True)

# Run
asyncio.run(backup_and_restore())
```

## Database Migration Workflow

### Scenario 1: Copy Production Database to Development

```bash
# On production server
python rag/client/manageqdb.py backup /shared/backups/coffeebreak_prod.sql

# On development server
python rag/client/manageqdb.py restore /shared/backups/coffeebreak_prod.sql
```

### Scenario 2: Set Up New Environment

```bash
# Copy backup file to new server
scp user@prodserver:/backups/coffeebreak.sql ./

# Restore with automatic setup
python rag/client/manageqdb.py restore ./coffeebreak.sql --create-db
```

### Scenario 3: Schedule Regular Backups (Cron)

```bash
# Add to crontab (backup daily at 2 AM)
0 2 * * * cd /home/user/Sttcast && python rag/client/manageqdb.py backup ./backups/coffeebreak_$(date +\%Y-\%m-\%d).sql
```

## Methods in `queriesdb.py`

### `RAGDatabase.backup_to_file(backup_file: str) -> bool`

Creates a complete SQL backup of the database.

**Parameters:**
- `backup_file`: Path where the backup will be saved

**Returns:**
- `True` if successful, `False` otherwise

**Dependencies:**
- Requires `pg_dump` (PostgreSQL client utilities)

### `RAGDatabase.restore_from_file(backup_file: str, create_db_and_user: bool = False) -> bool`

Restores the database from a backup file.

**Parameters:**
- `backup_file`: Path to the backup file
- `create_db_and_user`: If `True`, creates database and user if they don't exist (default: `False`)

**Returns:**
- `True` if successful, `False` otherwise

**Dependencies:**
- Requires `psql` (PostgreSQL client)
- For `create_db_and_user=True`: Admin credentials must be configured

## Requirements

### System Requirements

```bash
# Ubuntu/Debian
sudo apt-get install postgresql-client

# macOS (with Homebrew)
brew install postgresql

# Windows
# Download from: https://www.postgresql.org/download/windows/
```

### Python Requirements

The following are already included in `setup.py`:
- `asyncpg>=0.29.0` - Async PostgreSQL client
- `python-dotenv>=1.0.0` - Environment variable loading

## Troubleshooting

### Error: `pg_dump not found`

**Solution:** Install PostgreSQL client tools

```bash
# Ubuntu/Debian
sudo apt-get install postgresql-client

# macOS
brew install postgresql

# Windows: Download PostgreSQL installer from postgresql.org
```

### Error: `Role "user" does not exist`

**Cause:** The database user hasn't been created yet

**Solution:** Use `--create-db` flag:
```bash
python rag/client/manageqdb.py restore ./backup.sql --create-db
```

### Error: Connection refused

**Causes:**
- PostgreSQL server is not running
- Incorrect host/port in `.env/queriesdb.env`

**Solution:**
```bash
# Check PostgreSQL is running
psql -h localhost -p 5432 -U postgres -c "SELECT 1"

# Verify environment variables
echo $QUERIESDB_HOST
echo $QUERIESDB_PORT
```

### Large Backup Files

For large databases, backups may take time and produce large files:

```bash
# Show file size
ls -lh backup.sql

# Compress backup (reduces size 10-20x)
gzip backup.sql  # Creates backup.sql.gz

# Restore from compressed backup
gunzip < backup.sql.gz | psql -h localhost -U coffeebreak_user coffeebreak
```

## Security Considerations

1. **Backup Files**: Contain complete database contents. Store securely.
2. **Credentials**: Use strong passwords for database users
3. **Admin Access**: Restrict access to `.env/queriesdb.env` (contains admin password)
4. **Network**: Use SSH tunnels for remote PostgreSQL connections in production

## Version Information

- **Created:** January 2026
- **Compatible with:** PostgreSQL 12+, pgvector 0.5.0+
- **Python:** 3.9+
