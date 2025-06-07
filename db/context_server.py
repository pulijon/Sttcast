import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__),"../tools")))
from logs import logcfg
import logging
from logs import logcfg
from envvars import load_env_vars_from_directory
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import pandas as pd
import numpy as np
import sqlite3
from sttcastdb import SttcastDB
from openai import OpenAI
import json
import faiss
import requests
from datetime import datetime
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__),"../rag")))
from sttcast_rag_service import EmbeddingInput

class AddSegmentsRequest(BaseModel):
    epname: str
    epdate: datetime
    epfile: str
    segments: List[dict]

class GetContextRequest(BaseModel):
    query: str
    n_fragments: int = 20

class GetContextResponse(BaseModel):
    context: List[dict]

logcfg(__file__)
openai: OpenAI = None

app = FastAPI()

@app.post("/addsegments")
def addsegments(request: AddSegmentsRequest):
    global index, db_file, rag_server_url
    db = SttcastDB(db_file, create_if_not_exists=False)
    if db is None:
        raise FileNotFoundError(f"El fichero de base de datos {db_file} no ha podido ser leído")
    id  = db.get_episode_id(request.epname)
    if id is not None:
        ints = db.get_ints(with_embeddings=True, epname=request.epname)
        # Borrar del índice FAISS los segmentos asociados a este episodio
        ids = np.array([intv['id'] for intv in ints], dtype=np.int64)
        index.remove_ids(ids)
        db.del_episode_data(id)

    newid = db.add_episode(request.epname, request.epdate, request.epfile, request.segments)
    if newid is None:
        raise HTTPException(status_code=500, detail="Error al añadir el episodio a la base de datos")
    # Llamar al servicio RAG para obtener los vectores de los segmentos
    ints = db.get_ints(with_embeddings=False, epname=request.epname)
    db.close()

    segments = [
        {
            "tag": intv["tag"],
            "epname": intv["epname"],
            "epdate": intv["epdate"].strftime("%Y-%m-%d"),
            "start": intv["start"],
            "end": intv["end"],
            "content": intv["content"]
        }
        for intv in ints
    ]
    ids = [intv["id"] for intv in ints]
   
    url = f"{rag_server_url}/getembeddings"
    headers = {"Content-Type": "application/json"}
    response = requests.post(url, json=segments, headers=headers)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    rjson = response.json()
    vectors = rjson.get("embeddings")
    if not isinstance(vectors, list) or not all(isinstance(v, list) for v in vectors):
        raise HTTPException(status_code=500, detail="El formato de los vectores devueltos por el servicio RAG no es válido")
    if len(vectors) != len(segments):
        raise HTTPException(status_code=500, detail="El número de vectores devueltos por el servicio RAG no coincide con el número de segmentos")
    # Convertir los vectores a un array numpy
    vectors = np.array(vectors, dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape[0] != len(segments):
        raise HTTPException(status_code=500, detail="Los vectores devueltos por el servicio RAG no tienen la forma adecuada")
    # Añadir los vectores al índice FAISS
    if vectors.shape[1] != index.d:
        raise HTTPException(status_code=500, detail="Los vectores devueltos por el servicio RAG no tienen la dimensión adecuada")
  
    index.add_with_ids(vectors, np.array(ids, dtype=np.int64))
       

@app.post("/getcontext")
def getcontext(request: GetContextRequest):
    global index, db_file, rag_server_url
    db = SttcastDB(db_file, create_if_not_exists=False)
    if db is None:
        raise FileNotFoundError(f"El fichero de base de datos {db_file} no ha podido ser leído")
    qreq = {
        "query": request.query,
    }
    url = f"{rag_server_url}/getoneembedding"
    headers = {"Content-Type": "application/json"}
    response = requests.post(url, json=qreq, headers=headers)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    rjson = response.json()
    embedding = rjson.get("embedding")
    qvec = np.array(embedding, dtype=np.float32).reshape(1, -1)
    faiss.normalize_L2(qvec)
    D, I = index.search(qvec, k=request.n_fragments)
    ids = I[0].tolist()
    if not ids:
        raise HTTPException(status_code=404, detail="No se han encontrado segmentos relevantes para la consulta")
    context_from_db_rows = db.get_ints(with_embeddings=True, ids=ids)
    # Convertir filas a diccionarios sin el campo 'embedding'
    context_from_db = [
        {k: v for k, v in dict(r).items() if k != 'embedding'}
        for r in context_from_db_rows
    ]
    
    logging.info(f"Se han encontrado {len(context_from_db)} segmentos relevantes para la consulta")

    if not context_from_db:
        raise HTTPException(status_code=404, detail="No se han encontrado segmentos relevantes para la consulta")
    db.close()
    # Convertir los resultados a un formato adecuado para la respuesta
    return GetContextResponse(
        context=context_from_db
    )
    


if __name__ == "__main__":
    env_dir = os.path.join(os.path.dirname(__file__), '../.env')
    # Cargar variables de entorno desde el directorio actual
    load_env_vars_from_directory(directory=env_dir)
    db_file = os.getenv("STTCAST_DB_FILE", "sttcast.db")
    if not os.path.exists(db_file):
        raise FileNotFoundError(f"El fichero de base de datos {db_file} no existe")
    # db = SttcastDB(db_file, create_if_not_exists=False)
    # if db is None:
    #     raise FileNotFoundError(f"El fichero de base de datos {db_file} no ha podido ser leído")
    index_file = os.getenv("STTCAST_FAISS_FILE")
    if not os.path.exists(index_file):
        raise FileNotFoundError(f"El fichero de índice FAISS {index_file} no existe")
    index = faiss.read_index(index_file)
    if index is None:   
        raise FileNotFoundError(f"El fichero de índice FAISS {index_file} no ha podido ser leídoe")
    
    rag_server_host = os.getenv("RAG_SERVER_HOST", "localhost")
    rag_server_port = int(os.getenv("RAG_SERVER_PORT", "5500"))
    rag_server_url = f"http://{rag_server_host}:{rag_server_port}"

    server_host = os.getenv("CONTEXT_SERVER_HOST", "localhost")
    server_port = int(os.getenv("CONTEXT_SERVER_PORT", 8000))
    openai_gpt_model = os.getenv("OPENAI_GPT_MODEL", "gpt-4o-mini")
    openai_embeddings_model = os.getenv("OPENAI_EMBEDDINGS_MODEL", "text-embedding-3-small")
    relevant_fragments = int(os.getenv("STTCAST_RELEVANT_FRAGMENTS", 100))

    # Iniciar el servidor FastAPI   
    import uvicorn
    uvicorn.run(app, host=server_host, port=server_port, log_level="info")