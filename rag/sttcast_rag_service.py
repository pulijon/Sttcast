import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__),"../tools")))
import logging
from logs import logcfg
from envvars import load_env_vars_from_directory
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
from bs4 import BeautifulSoup
from openai import OpenAI
from dotenv import load_dotenv
import json
import uvicorn
import datetime
import numpy as np

logcfg(__file__)
openai: OpenAI = None

app = FastAPI()

class EpisodeInput(BaseModel):
    ep_id: str
    transcription: str

class EpisodeOutput(BaseModel):
    ep_id: str
    summary: str
    tokens_prompt: int
    tokens_completion: int
    tokens_total: int
    estimated_cost_usd: float

class EmbeddingInput(BaseModel):
    tag: str
    epname: str
    epdate: str
    start: float
    end: float
    content: str
    
class RelSearchRequest(BaseModel):
    query:str
    embeddings: List[EmbeddingInput]

class MultiLangText(BaseModel):
    es: str
    en: str

class References(BaseModel):
    label: MultiLangText
    file: str
    time: float
    tag: str
    
    
class RelSearchResponse(BaseModel):
    tokens_prompt: int
    tokens_completion: int
    tokens_total: int
    estimated_cost_usd: float
    search: MultiLangText
    refs: List[References]

class GetEmbeddingsResponse(BaseModel):
    embeddings: List[List[float]] # List of byte arrays for embeddings
    tokens_prompt: int
    tokens_total: int

class GetOneEmbeddingRequest(BaseModel):
    query: str

class GetOneEmbeddingResponse(BaseModel):
    embedding: List[float]  # List of floats for the vector
    
def calculate_cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    cost_input = (prompt_tokens / 1_000_000) * 0.15  # $0.15 / millón
    cost_output = (completion_tokens / 1_000_000) * 0.60  # $0.60 / millón
    return round(cost_input + cost_output, 6)

def extract_text_from_html(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "html.parser")
    speaker_summary = soup.find("span", {"id": "speaker-summary"})
    if speaker_summary:
        speaker_summary.decompose()
    return soup.get_text(separator="\n")

def summarize_episode(ep: EpisodeInput) -> EpisodeOutput:
    global openai
    if not openai:
        raise ValueError("OpenAI client is not initialized.")
    transcript_text = extract_text_from_html(ep.transcription)
    logging.debug("Extraído texto de la transcripción")

    prompt = f"""
Por favor, devuelve un objeto válido JSON, no lo empaquetes en un bloque de código ni de texto.


Extrae los principales temas tratados en esta transcripción de un podcast. Devuelve la respuesta en un fichero JSON con campos para cada idioma:

"es": resumen en español, "en": resumen en inglés

Los resúmenes son textos en formato HTMKL. En el caso del resumen en español, el texto debe estar en español y en el caso del resumen en inglés, el texto debe estar en inglés.

Cada uno de los resúmenes debe teber un bloque span con id="topic-summary". 

Dentro de este bloque, deberá haber una lista de los asuntos tratados, precedidos del epígrafe "Asuntos tratados" (en inglés, la traducción que corresponda) y un resumen del episodio, precedidos del epígrafe "Resumen". El resumen debe ser de unas v   einte líneas. Los asuntos tratados se incluirán en un bloque span con id "tslist" y el resumen en un span con id "tstext", de forma que, a posteriori se puedan aplicar estilos.

El resultado debe ser como el ejemplo:

<span id="topic-summary">
    <span id="tslist">
    <p>Asuntos tratados:</p>
    <ul>
        <li>Asunto 1 - Tiempo de inicio</li>
        <li>Asunto 2 - Tiempo de inicio</li>
        <li>Asunto 3 - Tiempo de inicio</li>
    </ul>
    </span>
    <span id="tstext">
    <p>Resumen:</p>
    <p>Párrafo 1 del resumen</p>
    <p>Párrafo 2 del resumen</p>
    <p>Párrafo 3 del resumen</p>
    </span>
</span>

El tiempo de inicio de cada asunto es el momento de la grabación, expresado en horas:minutos:segundos, en el que empiezan a tratar en profundidad el asunto (al principio del audio suelen sólo presentarlo). Este momento se puede extraer de las marcas de tiempo de la transcripción.. 

Por ejemplo, si el asunto empieza el segundo 3800 es el equivalente a 1 hota, 3 minutos y 20 segundos, por lo que deberás poner
<li>Asunto 1 - 01:03:20</li>


El resumen debe ser un texto escrito en el estilo de los artículos técnicos y puede incluir, si se detectan, los papers que se comentan. Su extensión debe ser de unas trescientas palabras dividido en dos o tres párrafos.

Cuando hables de los participantes en la tertulia, utiliza la palabra "contertulios" o "participantes".

La identidad de los participantes se puede deducir de la transcripción. Por ejemplo, en el párrafo siguiente, quien habla es Héctor Socas, cuyo nombre está al principio, entre corchetes.

[<span class="speaker-0">Héctor Socas</span>]:  Gracias a Marian, a Weston, a Andrés, a Javier Licandro, a Darwich, a Manolo Vázquez, a Alfred, a José Alberto, a Nayra, a Maya, a Juan Antonio Belmonte. Gracias a todos los con tertulios que han pasado, a José Rra. <br/>

Intenta poner, cuando sea relevante, la contribución de cada uno de los participantes. 

No incluyas etiquetas HTML adicionales fuera del bloque span.

Transcripción:

{transcript_text}
"""

    response = openai.chat.completions.create(
        model=OPENAI_GPT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    logging.debug("Respuesta de OpenAI recibida")

    summary_json = response.choices[0].message.content.strip()
    usage = response.usage  # tokens

    return EpisodeOutput(
            ep_id=ep.ep_id,
            summary=json.dumps(summary_json),
            tokens_prompt=usage.prompt_tokens,
            tokens_completion=usage.completion_tokens,
            tokens_total=usage.total_tokens,
            estimated_cost_usd=calculate_cost_usd(usage.prompt_tokens, usage.completion_tokens)
    )

@app.post("/summarize", response_model=List[EpisodeOutput])
def summarize(episodes: List[EpisodeInput]):
    try:
        logging.debug(f"Received {len(episodes)} episodes for summarization: {[ep.ep_id for ep in episodes]}")
        return [summarize_episode(ep) for ep in episodes]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/relsearch", response_model=RelSearchResponse)
def relsearch(req: RelSearchRequest):
    global openai
    if not openai:
        raise ValueError("OpenAI client is not initialized.")
    global OPENAI_GPT_MODEL

    context = "\n\n".join(f"{emb.tag} en {emb.epname}, [{emb.epdate}], a partir de {emb.start} :\n{emb.content}" for emb in req.embeddings)
    prompt = f"""
Por favor, devuelve un objeto válido JSON, no lo empaquetes en un bloque de código ni de texto.

Eres un asistente experto en podcasts de divulgación científica. Responde a la pregunta que aparece al final del prompt utilizando el contexto proporcionado. El contexto contiene información de varios episodios de un podcast, cada uno con un tag, nombre del episodio, fecha y un texto que resume los puntos clave tratados en ese episodio.

En el texto de la respuesta harásreferencia a las principales contribuciones sobre el tema. Utiliza html para que el texto resultado pueda tener párrafos, listas y enlaces y para resaltar los nombres de los participantes. 

El contexto es el siguiente:
{context}

Por favor, cíñete lo más posible al contexto. Puedes añadir algo fuera de ese contexto, pero indicándolo.

La respuesta debe ser un objeto JSON con los siguientes campos:
"search": respuesta a la pregunta, con una longitud estimada de unas trescientas palabras en cada idiona   Aquí habrá  dos campos, uno por cada idioma:
"es": respuesta en español, "en": respuesta en inglés.
"refs" : lista de referencias a los episodios más relevantes en los que se basa la respuesta (en el entorno de 5, si bien pueden ser más o menos), con los siguientes campos:
"label": etiqueta descriptiva de la referencia, con dos campos, uno por cada idioma:
"es": etiqueta en español, "en": etiqueta en inglés.:
"file": nombre del archivo del episodio,
"time": tiempo en segundos desde el inicio del episodio donde se habla de la referencia.
"tag": Hablante de la referencia.

No incluyas etiquetas HTML adicionales fuera del bloque span.


Pregunta: {req.query}
    """
    
    response = openai.chat.completions.create(
        model=OPENAI_GPT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    logging.debug("Respuesta de OpenAI recibida")
    search_json = json.loads(response.choices[0].message.content.strip())
    logging.debug(search_json)
    usage = response.usage  # tokens


    return RelSearchResponse(
            search=MultiLangText(
                es=search_json.get('search', {}).get('es', ''),
                en=search_json.get('search', {}).get('en', '')
            ),
            refs=[
                References(
                    label=MultiLangText(es=ref['label']['es'], en=ref['label']['en']),
                    file=ref['file'],
                    time=ref['time'],
                    tag=ref['tag']
                ) for ref in search_json.get('refs', [])
            ],

            tokens_prompt=usage.prompt_tokens,
            tokens_completion=usage.completion_tokens,
            tokens_total=usage.total_tokens,
            estimated_cost_usd=calculate_cost_usd(usage.prompt_tokens, usage.completion_tokens)
    )



@app.post("/getembeddings", response_model=GetEmbeddingsResponse)
def get_embeddings(embeddings: List[EmbeddingInput]):
    def get_text_from_iv(iv):
        return (f"[Episodio {iv.epname}] "
            f"[Fecha: {iv.epdate}] "
            f"[Hablante: {iv.tag}] "
            f"[Inicio: {iv.tag}s Fin: {iv.end}] "
            f"{iv.content}")

    global OPENAI_EMBEDDING_MODEL
    global openai
    if not openai:
        raise ValueError("OpenAI client is not initialized.")
    resp = openai.embeddings.create(
        model=OPENAI_EMBEDDING_MODEL,
        input= [get_text_from_iv(iv) for iv in embeddings]
    )
    usage = resp.usage
    prompt_tokens = int(usage.prompt_tokens / len(embeddings))
    total_tokens = int(usage.total_tokens / len(embeddings))
    embs = [np.array(data.embedding, dtype=np.float32) for data in resp.data]

    return GetEmbeddingsResponse(
        embeddings=embs,
        tokens_prompt=prompt_tokens,
        tokens_total=total_tokens,
    )

@app.post("/getoneembedding", response_model=GetOneEmbeddingResponse)
def get_one_embedding(request: GetOneEmbeddingRequest):
    global openai
    if not openai:
        raise ValueError("OpenAI client is not initialized.")
    global OPENAI_EMBEDDING_MODEL

    resp = openai.embeddings.create(
        model=OPENAI_EMBEDDING_MODEL,
        input=[request.query]
    )
    # usage = resp.usage
    return GetOneEmbeddingResponse (
        embedding=resp.data[0].embedding
    )
  
    
    

    

if __name__ == '__main__':
    # Configurar logging

    logging.info("Iniciando API RAG Gateway")
    
    # Cargar variables de entorno
    load_env_vars_from_directory(os.path.join(os.path.dirname(__file__), '../.env'))
    logging.info(os.getenv("OPENAI_API_KEY"))
    openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    if not openai.api_key:
        logging.error("API key for OpenAI is missing.")
        raise ValueError("API key for OpenAI is missing. Please set the OPENAI_API_KEY environment variable.")
    OPENAI_GPT_MODEL = os.getenv("OPENAI_GPT_MODEL", "gpt-4o-mini")
    OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    RAG_SERVER_HOST = os.getenv("RAG_SERVER_HOST", "localhost")
    RAG_SERVER_PORT = int(os.getenv("RAG_SERVER_PORT", "5500"))
    
    # Iniciar el servidor FastAPI con Uvicorn
    uvicorn.run(app, host=RAG_SERVER_HOST, port=RAG_SERVER_PORT)
    logging.info("API Gateway detenido.")



