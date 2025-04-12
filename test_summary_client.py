from util import logcfg
import logging
import requests
import json
import logging

# Configuración
HTML_FILE = "ep507_A_whisper_audio_es.html"
EP_ID = "ep507_A"
SERVER_URL = "http://localhost:5500/summarize"

logging.basicConfig(level=logging.INFO)

def main():
    logcfg(__file__)
    try:
        with open(HTML_FILE, "r", encoding="utf-8") as f:
            html_content = f.read()
    except FileNotFoundError:
        logging.error(f"No se encontró el fichero '{HTML_FILE}'")
        return

    payload = [{"ep_id": EP_ID, "transcription": html_content}]
    logging.info("Enviando la transcripción al servicio...")

    try:
        response = requests.post(SERVER_URL, json=payload)
        response.raise_for_status()
    except requests.RequestException as e:
        logging.error("Error al conectar con el servicio: %s", e)
        return

    results = response.json()
    for result in results:
        logging.info("Resumen generado para episodio '%s'", result["ep_id"])
        logging.info("Tokens prompt: %d, completion: %d, total: %d",
                     result["tokens_prompt"], result["tokens_completion"], result["tokens_total"])
        logging.info("Coste estimado: $%.6f", result["estimated_cost_usd"])
        logging.info(f"\nResumen HTML:\n {result["summary"]}")

if __name__ == "__main__":
    main()

