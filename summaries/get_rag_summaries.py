import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__),"..", "tools")))
from logs import logcfg
import logging
import os
import json
import argparse
import requests
import csv
from datetime import datetime

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
    csv_file = os.path.join(output_dir, "summary_stats.csv")
    csv_exists = os.path.exists(csv_file)
    fecha_procesado = datetime.now().isoformat(timespec="seconds")

    with open(csv_file, "a", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        if not csv_exists:
            writer.writerow(["ep_id", "tokens_prompt", "tokens_completion", "tokens_total", "estimated_cost_usd", "fecha_procesado"])

        for item in summaries:
            logging.debug(f"Tratando respusta: {item}")
            ep_id = item["ep_id"]
            summary_file = os.path.join(output_dir, f"{ep_id}_summary.json")
            stats_file = os.path.join(output_dir, f"{ep_id}_stats.json")
            summary_json = item['summary']
            if summary_json.startswith('"') and summary_json.endswith('"'):
                summary_json = summary_json[1:-1]
            # Sustituir tres backslashes por uno
            summary_json = summary_json.replace('\\\\\\', '\\')
            summary_json = summary_json.encode("utf-8").decode("unicode_escape")
            summary = json.loads(summary_json)
            logging.debug(f"Parseado de JSON: {summary}")

            # Guardar resumen JSON
            with open(summary_file, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)

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
        # Salvar block como JSON para depuración
        with open(f"debug_block_{block[0]['ep_id']}.json", "w", encoding="utf-8") as f:
            json.dump(block, f, indent=2, ensure_ascii=False)
        try:
            response = requests.post(args.url, json=block)
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
