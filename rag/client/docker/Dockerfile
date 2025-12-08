# Imagen base de Python
FROM python:3.11-slim

# Establecer el directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema necesarias
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copiar el archivo de requisitos
COPY rag/client/docker/requirements.txt .

# Instalar dependencias de Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código necesario de la aplicación
# Estructura modular: solo lo necesario para el cliente RAG
COPY rag/client /app/rag/client
COPY tools /app/tools
COPY api /app/api

# Crear __init__.py para el paquete rag
RUN mkdir -p /app/rag && touch /app/rag/__init__.py

# Crear directorios para volúmenes montados
RUN mkdir -p /app/.env /app/rag/client/logs

# Configurar PYTHONPATH para imports absolutos
ENV PYTHONPATH=/app

# Exponer el puerto de la aplicación
EXPOSE 8322

# Establecer el directorio de trabajo para la aplicación
WORKDIR /app/rag/client

# Comando para ejecutar la aplicación
CMD ["python", "client_rag.py"]
