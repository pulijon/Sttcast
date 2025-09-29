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

# def summarize_episode(ep: EpisodeInput) -> EpisodeOutput:
#     global openai
#     if not openai:
#         raise ValueError("OpenAI client is not initialized.")
#     transcript_text = extract_text_from_html(ep.transcription)
#     logging.debug("Extraído texto de la transcripción")

#     prompt = f"""
    
# Extrae los principales temas tratados en esta transcripción de un podcast. Devuelve la respuesta en un objeto JSON válido con campos para cada idioma:

# "es": resumen en español, "en": resumen en inglés

# El objeto JSON debe poder ser parseado por un programa. No incluyas entrecomillados en el texto con comillas dobles, usa comillas simples si es necesario, o escapa las comillas dobles correctamente.

# Los resúmenes son textos en formato HTML. En el caso del resumen en español, el texto debe estar en español y en el caso del resumen en inglés, el texto debe estar en inglés.

# Cada uno de los resúmenes debe tener un bloque span con id="topic-summary".

# Dentro de este bloque, deberá haber una lista de los asuntos tratados, precedidos del epígrafe "Asuntos tratados" (en inglés, la traducción que corresponda) y un resumen del episodio, precedidos del epígrafe "Resumen". El resumen debe ser de unas cuatrocientas palabras. Los asuntos tratados se incluirán en un bloque span con id "tslist" y el resumen en un span con id "tstext", de forma que, a posteriori se puedan aplicar estilos.

# El bloque de asuntos tratados debe tener la siguiente estructura:

# <span id="topic-summary">
#     <span id="tslist">
#     <p>Asuntos tratados:</p>
#     <ul>
#         <li>Asunto 1 - Tiempo de inicio</li>
#         <li>Asunto 2 - Tiempo de inicio</li>
#         <li>Asunto 3 - Tiempo de inicio</li>
#     </ul>
#     </span>
#     <span id="tstext">
#     <p>Resumen:</p>
#     <p>Párrafo 1 del resumen</p>
#     <p>Párrafo 2 del resumen</p>
#     <p>Párrafo 3 del resumen</p>
#     </span>
# </span>

# Ejemplo de formato JSON esperado:
# {{
#   "es": "<span id=\"topic-summary\"><span id=\"tslist\"><p>Asuntos tratados:</p><ul><li>Observatorio Vera Rubin - 00:01:28</li><li>Primera luz y primeras imágenes - 00:07:02</li></ul></span><span id=\"tstext\"><p>Resumen:</p><p>En este episodio, los contertulios discuten sobre...</p></span></span>",
#   "en": "<span id=\"topic-summary\"><span id=\"tslist\"><p>Topics discussed:</p><ul><li>Vera Rubin Observatory - 00:01:28</li><li>First light and first images - 00:07:02</li></ul></span><span id=\"tstext\"><p>Summary:</p><p>In this episode, the participants discuss...</p></span></span>"
# }}

# El tiempo de inicio de cada asunto es el momento de la grabación, expresado en horas:minutos:segundos, en el que empiezan a tratar en profundidad el asunto. Este momento se puede extraer de las marcas de tiempo de la transcripción.

# Por ejemplo, si el asunto empieza el segundo 3800 es el equivalente a 1 hora, 3 minutos y 20 segundos, por lo que deberás poner:
# <li>Asunto 1 - 01:03:20</li>

# El resumen debe ser un texto escrito en el estilo de los artículos técnicos y puede incluir, si se detectan, los papers que se comentan. Su extensión debe ser de unas trescientas palabras dividido en dos o tres párrafos.

# Cuando hables de los participantes en la tertulia, utiliza la palabra "contertulios" o "participantes".

# La identidad de los participantes se puede deducir de la transcripción. Por ejemplo, en el párrafo siguiente, quien habla es Héctor Socas, cuyo nombre está al principio, entre corchetes.

# [<span class="speaker-0">Héctor Socas</span>]:  Gracias a Marian, a Weston, a Andrés, a Javier Licandro...

# Intenta poner, cuando sea relevante, la contribución de cada uno de los participantes.

# Transcripción:

# {transcript_text}
#     """

#     response = openai.chat.completions.create(
#         model=OPENAI_GPT_MODEL,
#         messages=[{"role": "user", "content": prompt}],
#         # temperature=0.1,
#     )
#     logging.debug("Respuesta de OpenAI recibida")

#     summary_content = response.choices[0].message.content.strip()
#     logging.debug(f"Contenido recibido: {summary_content[:200]}...")
    
#     try:
#         # Intentar parsear el JSON para validarlo
#         summary_json = json.loads(summary_content)
#         logging.debug("JSON parseado correctamente")
#     except json.JSONDecodeError as e:
#         logging.error(f"Error al decodificar JSON: {e}")
#         logging.error(f"Contenido recibido: {summary_content}")
#         raise ValueError(f"La respuesta de OpenAI no es JSON válido: {e}")
    
#     usage = response.usage  # tokens

#     return EpisodeOutput(
#             ep_id=ep.ep_id,
#             summary=summary_content,  # Guardar la cadena JSON directamente, no hacer json.dumps
#             tokens_prompt=usage.prompt_tokens,
#             tokens_completion=usage.completion_tokens,
#             tokens_total=usage.total_tokens,
#             estimated_cost_usd=calculate_cost_usd(usage.prompt_tokens, usage.completion_tokens)
#     )

# def summarize_episode(ep: EpisodeInput) -> EpisodeOutput:
#     global openai
#     if not openai:
#         raise ValueError("OpenAI client is not initialized.")
#     transcript_text = extract_text_from_html(ep.transcription)
#     logging.debug("Extraído texto de la transcripción")

#     prompt = f"""
# Por favor, devuelve un objeto válido JSON, no lo empaquetes en un bloque de código ni de texto.


# Extrae los principales temas tratados en esta transcripción de un podcast. Devuelve la respuesta en un fichero JSON con campos para cada idioma:

# "es": resumen en español, "en": resumen en inglés

# El objeto JSON debe poder ser parseado por un programa, no lo empaquetes en un bloque de código ni de texto. No incluyas entrecomillados en el texto con comillas dobles, porque harían que el JSON no fuera válido. 

# Los resúmenes son textos en formato HTML. En el caso del resumen en español, el texto debe estar en español y en el caso del resumen en inglés, el texto debe estar en inglés.

# Cada uno de los resúmenes debe teber un bloque span con id="topic-summary". 

# Dentro de este bloque, deberá haber una lista de los asuntos tratados, precedidos del epígrafe "Asuntos tratados" (en inglés, la traducción que corresponda) y un resumen del episodio, precedidos del epígrafe "Resumen". El resumen debe ser de unas cuatrocientas palabras. Los asuntos tratados se incluirán en un bloque span con id "tslist" y el resumen en un span con id "tstext", de forma que, a posteriori se puedan aplicar estilos.

# El bloque de asuntos tratados debe tener la siguiente estructura:

# <span id="topic-summary">
#     <span id="tslist">
#     <p>Asuntos tratados:</p>
#     <ul>
#         <li>Asunto 1 - Tiempo de inicio</li>
#         <li>Asunto 2 - Tiempo de inicio</li>
#         <li>Asunto 3 - Tiempo de inicio</li>
#     </ul>
#     </span>
#     <span id="tstext">
#     <p>Resumen:</p>
#     <p>Párrafo 1 del resumen</p>
#     <p>Párrafo 2 del resumen</p>
#     <p>Párrafo 3 del resumen</p>
#     </span>
# </span>

# El siguiente es un ejemplo de cómo debe ser el contenido del objeto JSON devuelto. No te olvides de incluir las llaves de apertura y cierre del objeto JSON. No incluyas más backslashes ni comillas que las necesarias para que el JSON sea válido


#   "es": '<span id="topic-summary"><span id="tslist"><p>Asuntos tratados:</p><ul><li>Observatorio Vera Rubin - 00:01:28</li><li>Primera luz y primeras imágenes - 00:07:02</li><li>Telescopio LSST y su financiación - 00:09:15</li><li>Datos y software del Vera Rubin - 00:03:23</li><li>Estudio de agujeros negros y su rotación - 01:28:11</li></ul></span><span id="tstext"><p>Resumen:</p><p>En este episodio, los contertulios discuten sobre el Observatorio Vera Rubin, un nuevo telescopio que promete revolucionar la astronomía con su capacidad para observar el cielo en tiempo real. Se presentan las primeras imágenes obtenidas y se analiza la importancia de la financiación privada en su desarrollo. Se menciona el telescopio LSST, que ha sido renombrado en honor a Vera Rubin, y se discuten los desafíos técnicos relacionados con la obtención y el análisis de los datos generados por el telescopio.</p><p>Además, se aborda el tema de los agujeros negros, centrándose en el agujero negro supermasivo M87 y su rotación. Los participantes comentan sobre las implicaciones de la velocidad de rotación de estos objetos y cómo esto afecta a la formación de jets y otros fenómenos astrofísicos. Se destaca la importancia de la colaboración entre diferentes instituciones y la necesidad de un enfoque riguroso en el análisis de datos para evitar errores en la interpretación de los resultados.</p><p>Finalmente, se reflexiona sobre la evolución de la astronomía y la necesidad de adaptarse a nuevas tecnologías y métodos de análisis, así como la importancia de la divulgación científica para el público en general.</p></span></span>',
#   "en": '<span id="topic-summary"><span id="tslist"><p>Topics discussed:</p><ul><li>Vera Rubin Observatory - 00:01:28</li><li>First light and first images - 00:07:02</li><li>LSST telescope and its funding - 00:09:15</li><li>Data and software from Vera Rubin - 00:03:23</li><li>Study of black holes and their rotation - 01:28:11</li></ul></span><span id="tstext"><p>Summary:</p><p>In this episode, the participants discuss the Vera Rubin Observatory, a new telescope that promises to revolutionize astronomy with its ability to observe the sky in real-time. The first images obtained are presented, and the importance of private funding in its development is analyzed. The LSST telescope, which has been renamed in honor of Vera Rubin, is mentioned, along with the technical challenges related to obtaining and analyzing the data generated by the telescope.</p><p>Additionally, the topic of black holes is addressed, focusing on the supermassive black hole M87 and its rotation. The participants comment on the implications of the rotation speed of these objects and how it affects the formation of jets and other astrophysical phenomena. The importance of collaboration between different institutions and the need for a rigorous approach in data analysis to avoid errors in result interpretation is highlighted.</p><p>Finally, reflections on the evolution of astronomy and the need to adapt to new technologies and analysis methods are discussed, as well as the importance of scientific outreach to the general public.</p></span></span>'

# El tiempo de inicio de cada asunto es el momento de la grabación, expresado en horas:minutos:segundos, en el que empiezan a tratar en profundidad el asunto (al principio del audio suelen sólo presentarlo). Este momento se puede extraer de las marcas de tiempo de la transcripción.. 

# Por ejemplo, si el asunto empieza el segundo 3800 es el equivalente a 1 hota, 3 minutos y 20 segundos, por lo que deberás poner
# <li>Asunto 1 - 01:03:20</li>


# El resumen debe ser un texto escrito en el estilo de los artículos técnicos y puede incluir, si se detectan, los papers que se comentan. Su extensión debe ser de unas trescientas palabras dividido en dos o tres párrafos.

# Cuando hables de los participantes en la tertulia, utiliza la palabra "contertulios" o "participantes".

# La identidad de los participantes se puede deducir de la transcripción. Por ejemplo, en el párrafo siguiente, quien habla es Héctor Socas, cuyo nombre está al principio, entre corchetes.

# [<span class="speaker-0">Héctor Socas</span>]:  Gracias a Marian, a Weston, a Andrés, a Javier Licandro, a Darwich, a Manolo Vázquez, a Alfred, a José Alberto, a Nayra, a Maya, a Juan Antonio Belmonte. Gracias a todos los con tertulios que han pasado, a José Rra. <br/>

# Intenta poner, cuando sea relevante, la contribución de cada uno de los participantes. 

# No incluyas etiquetas HTML adicionales fuera del bloque span.

# Transcripción:

# {transcript_text}
#     """

#     response = openai.chat.completions.create(
#         model=OPENAI_GPT_MODEL,
#         messages=[{"role": "user", "content": prompt}],
#         # temperature=0.1,
#     )
#     logging.debug("Respuesta de OpenAI recibida")

#     summary_json = response.choices[0].message.content.strip()
#     usage = response.usage  # tokens

#     return EpisodeOutput(
#             ep_id=ep.ep_id,
#             summary=json.dumps(summary_json),
#             tokens_prompt=usage.prompt_tokens,
#             tokens_completion=usage.completion_tokens,
#             tokens_total=usage.total_tokens,
#             estimated_cost_usd=calculate_cost_usd(usage.prompt_tokens, usage.completion_tokens)
#     )

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

El objeto JSON debe poder ser parseado por un programa, no lo empaquetes en un bloque de código ni de texto. No incluyas entrecomillados en el texto con comillas dobles, porque harían que el JSON no fuera válido. 

Los resúmenes son textos en formato HTML. En el caso del resumen en español, el texto debe estar en español y en el caso del resumen en inglés, el texto debe estar en inglés.

Cada uno de los resúmenes debe teber un bloque span con id="topic-summary". 

Dentro de este bloque, deberá haber una lista de los asuntos tratados, precedidos del epígrafe "Asuntos tratados" (en inglés, la traducción que corresponda) y un resumen del episodio, precedidos del epígrafe "Resumen". El resumen debe ser de unas cuatrocientas palabras. Los asuntos tratados se incluirán en un bloque span con id "tslist" y el resumen en un span con id "tstext", de forma que, a posteriori se puedan aplicar estilos.

El bloque de asuntos tratados debe tener la siguiente estructura:

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

Ejemplo de formato JSON esperado:
{{
  "es": "<span id=\"topic-summary\"><span id=\"tslist\"><p>Asuntos tratados:</p><ul><li>Observatorio Vera Rubin - 00:01:28</li><li>Primera luz y primeras imágenes - 00:07:02</li></ul></span><span id=\"tstext\"><p>Resumen:</p><p>En este episodio, los contertulios discuten sobre...</p></span></span>",
  "en": "<span id=\"topic-summary\"><span id=\"tslist\"><p>Topics discussed:</p><ul><li>Vera Rubin Observatory - 00:01:28</li><li>First light and first images - 00:07:02</li></ul></span><span id=\"tstext\"><p>Summary:</p><p>In this episode, the participants discuss...</p></span></span>"
}}

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
        # temperature=0.1,
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
    
resp_example = '''
{
  "search": {   
    "es": "Respuesta en español de unas cuatrocientas palabras...",
    "en": "Respuesta en inglés de unas cuatrocientas palabras..."
    },
    "refs": [
        {
        "label": {
            "es": "Etiqueta descriptiva en español",
            "en": "Descriptive label in English"
        },
        "file": "nombre del archivo del episodio",
        "time": 123.45,
        "tag": "Nombre del hablante"
        }
    ]
}
'''
@app.post("/relsearch", response_model=RelSearchResponse)
def relsearch(req: RelSearchRequest):
    global openai
    if not openai:
        raise ValueError("OpenAI client is not initialized.")
    global OPENAI_GPT_MODEL
    # if (len(req.query)> 0) and (req.query[0] =='ù'):
    #     req.query = req.query[1:]
    #     model = 'gpt-5-mini'
    # else:
    #     model = OPENAI_GPT_MODEL
    model = 'gpt-5-mini'
    logging.info(f"Using model: {model} para query: {req.query}")

    context = "\n\n".join(f"{emb.tag} en {emb.epname}, [{emb.epdate}], a partir de {emb.start} :\n{emb.content}" for emb in req.embeddings)
    prompt = f"""


Eres un asistente experto en podcasts de divulgación cultural. Responde a la pregunta que aparece al final del prompt utilizando el contexto proporcionado. El contexto contiene información de varios episodios de un podcast, cada uno con un tag, nombre del episodio, fecha y un texto que resume los puntos clave tratados en ese episodio.


La respuesta debe ser un objeto JSON válido con la estructura del ejemplo siguiente. No te olvides de incluir las llaves de apertura y cierre del objeto JSON. No incluyas más backslashes ni comillas que las necesarias para que el JSON sea válido. El número de elementos en el array refs puede variar, si bien podría estar en el entorno de 10
{resp_example}

En el texto de la respuesta harás referencia a las principales contribuciones halladas en el contexto sobre el tema. Utiliza html para que el texto resultado pueda tener párrafos, listas y enlaces y para resaltar los nombres de los participantes. 

El contexto es el siguiente:

{context}

Por favor, cíñete lo más posible al contexto. Puedes añadir algo fuera de ese contexto, pero indicándolo.



Pregunta: {req.query}
    """
    
    response = openai.chat.completions.create(
        #model=OPENAI_GPT_MODEL,
        model=model,
        messages=[{"role": "user", "content": prompt}],
        # temperature=0.1,
    )
    logging.debug("Respuesta de OpenAI recibida")
    try:
        search_json = json.loads(response.choices[0].message.content.strip())
    except json.JSONDecodeError as e:
        logging.error(f"Error al decodificar JSON: response: {response} ")
        logging.error(f"Error: JSON esperado: {response.choices[0].message.content.strip()}")
        logging.error(f"Excepción: {e}")
        raise HTTPException(status_code=500, detail="Error al procesar la respuesta de OpenAI")

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



