import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__),"..", "tools")))
from logs import logcfg
from envvars import load_env_vars_from_directory
import logging
import os
import json
import argparse
import requests
import csv
from datetime import datetime
import hmac
import hashlib
import time
from urllib.parse import urlparse
import hmac
import hashlib
import time
from urllib.parse import urlparse

def create_hmac_signature(secret_key: str, method: str, path: str, body: str, timestamp: str) -> str:
    """Crea una firma HMAC para autenticar la solicitud."""
    message = f"{method}|{path}|{body}|{timestamp}"
    return hmac.new(
        secret_key.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

def create_auth_headers(secret_key: str, method: str, url: str, body: list) -> dict:
    """Crea los headers de autenticación HMAC."""
    parsed_url = urlparse(url)
    path = parsed_url.path
    timestamp = str(int(time.time()))
    body_str = json.dumps(body, separators=(',', ':'), sort_keys=True)
    signature = create_hmac_signature(secret_key, method, path, body_str, timestamp)
    
    return {
        'X-Timestamp': timestamp,
        'X-Signature': signature,
        'X-Client-ID': 'get_rag_summaries',
        'Content-Type': 'application/json'
    }

def load_transcriptions(input_dir, max_per_block):
    """Prepara los archivos de transcripción en bloques para enviar al servicio de resúmenes.
    Esta función busca archivos con el sufijo "_whisper_audio_es.html" en el directorio de entrada,
    los carga y los agrupa en bloques de tamaño máximo especificado. Cada bloque se envía al servicio
    de resúmenes para su procesamiento.

    Args:
        input_dir (string): Directorio de entrada con archivos de transcripción
        max_per_block (string): Número máximo de archivos a enviar en un bloque
    
    Yields:
        list: Lista de diccionarios con el ID del episodio y la transcripción HTML
    """
    buffer = []
    for file in os.listdir(input_dir):
        if file.endswith("_whisper_audio_es.html"):
            ep_id = file.replace("_whisper_audio_es.html", "")
            with open(os.path.join(input_dir, file), "r", encoding="utf-8") as f:
                html = f.read()
                buffer.append({"ep_id": ep_id, "transcription": html})
                if len(buffer) == max_per_block:
                    yield buffer
                    buffer = []
    if buffer:
        yield buffer


def save_summaries(output_dir, summaries):
    """Escibe los resúmenes generados en archivos HTML y guarda estadísticas en un archivo CSV.
    Cada resumen se guarda en un archivo HTML separado y las estadísticas se guardan en un archivo CSV.
    El CSV contiene información como el ID del episodio, el número de tokens en la entrada y salida,
    el costo estimado y la fecha de procesamiento.

    Args:
        output_dir (string): Directorio de salida para guardar los resúmenes y estadísticas
        summaries (list): Lista de resúmenes generados por el servicio
    """
    logging.info(f"Guardando {len(summaries)} resúmenes en directorio: {output_dir}")
    
    # Crear directorio si no existe
    os.makedirs(output_dir, exist_ok=True)
    logging.debug(f"Directorio de salida verificado/creado: {output_dir}")
    
    csv_file = os.path.join(output_dir, "summary_stats.csv")
    csv_exists = os.path.exists(csv_file)
    fecha_procesado = datetime.now().isoformat(timespec="seconds")

    with open(csv_file, "a", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        if not csv_exists:
            writer.writerow(["ep_id", "tokens_prompt", "tokens_completion", "tokens_total", "estimated_cost_usd", "fecha_procesado"])

        for item in summaries:
            logging.info(f"Procesando respuesta para episodio: {item.get('ep_id', 'UNKNOWN')}")
            logging.debug(f"Tratando respuesta completa: {item}")
            ep_id = item["ep_id"]
            summary_file = os.path.join(output_dir, f"{ep_id}_summary.json")
            stats_file = os.path.join(output_dir, f"{ep_id}_stats.json")
            
            logging.info(f"Guardando resumen en: {summary_file}")
            
            # El summary ahora viene como JSON válido desde el servicio
            try:
                summary = json.loads(item['summary'])
                logging.info(f"JSON parseado exitosamente para {ep_id}")
                logging.debug(f"Contenido del resumen: {summary}")
            except json.JSONDecodeError as e:
                logging.error(f"Error parseando JSON para episodio {ep_id}: {e}")
                logging.error(f"Contenido recibido: {item['summary']}")
                # Crear un resumen por defecto en caso de error
                summary = {
                    "es": "Error al procesar el resumen",
                    "en": "Error processing summary"
                }

            # Guardar resumen JSON
            try:
                with open(summary_file, "w", encoding="utf-8") as f:
                    json.dump(summary, f, indent=2, ensure_ascii=False)
                logging.info(f"✅ Resumen guardado exitosamente: {summary_file}")
            except Exception as e:
                logging.error(f"❌ Error guardando resumen en {summary_file}: {e}")

            # Guardar estadísticas en JSON
            with open(stats_file, "w", encoding="utf-8") as f:
                json.dump(item, f, indent=2, ensure_ascii=False)

            # Añadir al CSV
            writer.writerow([
                ep_id,
                item.get("tokens_prompt"),
                item.get("tokens_completion"),
                item.get("tokens_total"),
                item.get("estimated_cost_usd"),
                fecha_procesado
            ])

def main():
    """Función principal que configura el registro, carga las transcripciones y envía solicitudes al servicio de resúmenes.
    """
    # Cargar variables de entorno
    load_env_vars_from_directory(os.path.join(os.path.dirname(__file__), "..", ".env"))
    
    # Obtener clave de autenticación
    rag_server_api_key = os.getenv('RAG_SERVER_API_KEY')
    if not rag_server_api_key:
        logging.error("RAG_SERVER_API_KEY not found in environment variables")
        raise ValueError("RAG_SERVER_API_KEY is required")
    
    DEFAULT_MAX_FILES = 6
    parser = argparse.ArgumentParser(description="Obtener resúmenes RAG de transcripciones de podcast")
    parser.add_argument("-t", "--transcriptions", required=True, help="Directorio de entrada con transcripciones HTML")
    parser.add_argument("-s", "--summaries", required=True, help="Directorio de salida para resúmenes HTML")
    parser.add_argument("--url", default="http://localhost:5500/summarize", help="URL del servicio de resúmenes")
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES, help="Número máximo de archivos a enviar en un bloque")
    args = parser.parse_args()

    logging.info(f"📝 Cargando transcripciones desde {args.transcriptions}")

    logging.info("📡 Enviando transcripciones al servicio de resúmenes...")
    for block in load_transcriptions(args.transcriptions, args.max_files):
        logging.info(f"📦 Enviando bloque de {len(block)} episodios...: {[b['ep_id'] for b in block]}")
        try:
            # Crear headers de autenticación HMAC
            auth_headers = create_auth_headers(rag_server_api_key, "POST", args.url, block)
            
            # ENVIAR EL JSON EXACTO QUE USAMOS PARA LA FIRMA
            body_str = json.dumps(block, separators=(',', ':'), sort_keys=True)
            response = requests.post(args.url, data=body_str, headers=auth_headers)
            response.raise_for_status()
            summaries = response.json()
            save_summaries(args.summaries, summaries)
        except requests.RequestException as e:
            logging.error("❌ Error al enviar bloque: %s", e)
        logging.info("✅ Proceso completado")

if __name__ == "__main__":
    logcfg(__file__)
    logging.info("🔄 Iniciando proceso de resúmenes RAG")
    main()
