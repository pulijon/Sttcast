from util import logcfg
import logging
from envvars import load_env_vars_from_directory
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
from bs4 import BeautifulSoup
from openai import OpenAI
from dotenv import load_dotenv
import uvicorn

MODEL="gpt-4o-mini"
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

    prompt = f"""
Extrae los principales temas tratados en esta transcripción de un podcast. Devuelve la respuesta en formato HTML en un bloque span con id="topic-summary". 

Dentro de este bloque, deberá haber una lista de los asuntos tratados, precedidos del epígrafe "Asuntos tratados"y un resumen del episodio, precedidos del epígrafe "Resumen". El resumen debe ser de unas veinte líneas. Los asuntos tratados se incluirán en un bloque span con id "tslist" y el resumen en un span con id "tstext", de forma que, a posteriori se puedan aplicar estilos.

El resultado debe ser como el ejemplo:

<span id="topic-summary">
    <span id="tslist">
    <p>Asuntos tratados:</p>
    <ul>
        <li>Asunto 1</li>
        <li>Asunto 2</li>
        <li>Asunto 3</li>
    </ul>
    </span>
    <span id="tstext">
    <p>Resumen:</p>
    <p>Párrafo 1 del resumen</p>
    <p>Párrafo 2 del resumen</p>
    <p>Párrafo 3 del resumen</p>
    </span>
</span>

El resumen debe ser un texto escrito en el estilo de los artículos técnicos y puede incluir, si se detectan, los papers que se comentan. Su extensión debe ser de uno a cuatro párrafos. 

Cuando hables de los participantes en la tertulia, utiliza la palabra "contertulios". No incluyas etiquetas HTML adicionales fuera del bloque span.

Transcripción:

{transcript_text}
"""

    response = openai.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )

    summary_html = response.choices[0].message.content.strip()
    usage = response.usage  # tokens

    return EpisodeOutput(
            ep_id=ep.ep_id,
            summary=summary_html,
            tokens_prompt=usage.prompt_tokens,
            tokens_completion=usage.completion_tokens,
            tokens_total=usage.total_tokens,
            estimated_cost_usd=calculate_cost_usd(usage.prompt_tokens, usage.completion_tokens)
    )

@app.post("/summarize", response_model=List[EpisodeOutput])
def summarize(episodes: List[EpisodeInput]):
    try:
        return [summarize_episode(ep) for ep in episodes]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == '__main__':
    # Configurar logging

    logging.info("Iniciando API RAG Gateway")
    
    # Cargar variables de entorno
    load_env_vars_from_directory(".env")
    logging.info(os.getenv("OPENAI_API_KEY"))
    openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    if not openai.api_key:
        logging.error("API key for OpenAI is missing.")
        raise ValueError("API key for OpenAI is missing. Please set the OPENAI_API_KEY environment variable.")
    
    # Iniciar el servidor FastAPI con Uvicorn
    uvicorn.run(app, host='0.0.0.0', port=5500)
    logging.info("API Gateway detenido.")

