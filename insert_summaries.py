#!/usr/bin/env python3
"""
Script para insertar resúmenes en archivos de transcripción HTML.
"""

from util import logcfg
import logging
import os
import re
import argparse
import glob
from bs4 import BeautifulSoup


def extract_ep_id(filename):
    """Extrae el ID del episodio del nombre del archivo."""
    match = re.search(r'(.*)_(whisper|vosk|summary).*', os.path.basename(filename))
    if match:
        return match.group(1)
    return None


def get_summary_content(summary_file):
    """Extrae el contenido del resumen del archivo."""
    try:
        with open(summary_file, 'r', encoding='utf-8') as file:
            soup = BeautifulSoup(file, 'html.parser')
            summary_span = soup.find('span', id='topic-summary')
            if summary_span:
                return str(summary_span)
            else:
                return None
    except Exception as e:
        logging.error(f"Error al procesar el archivo de resumen {summary_file}: {e}")
        return None


def update_transcript_file(transcript_file, summary_content):
    """
    Actualiza el archivo de transcripción con el contenido del resumen.
    Si ya existe un resumen, lo reemplaza; si no, lo agrega después del título.
    """
    try:
        with open(transcript_file, 'r', encoding='utf-8') as file:
            content = file.read()
            
        soup = BeautifulSoup(content, 'html.parser')
        
        # Buscar si ya existe un resumen
        existing_summary = soup.find('span', id='topic-summary')
        # Crear un nuevo elemento para el resumen
        summary_soup = BeautifulSoup(summary_content, 'html.parser')
        logging.info(f"Resumen encontrado")
        logging.debug(f"Resumen: {summary_soup}")

        if existing_summary:
            # Reemplazar el resumen existente
            existing_summary.replace_with(summary_soup)
            logging.info(f"Resumen reemplazado en {transcript_file}")
        else:
            # Buscar el título para insertar el resumen después
            title = soup.find('h2', class_='title')
            if title:
                # Añadir el resumen al título
                title.append(summary_soup)
                logging.info(f"Resumen añadido después del título en {transcript_file}")
            else:
                logging.warning(f"No se encontró el título en {transcript_file}")
                return False
        
        # Guardar el archivo actualizado
        with open(transcript_file, 'w', encoding='utf-8') as file:
            file.write(str(soup))
        
        return True
    except Exception as e:
        logging.error(f"Error al actualizar el archivo de transcripción {transcript_file}: {e}")
        return False


def find_matching_transcripts(ep_id, transcript_dir):
    """Encuentra todos los archivos de transcripción que coinciden con el ID del episodio."""
    pattern = os.path.join(transcript_dir, f"{ep_id}_[wv]*.*html")
    # Hacer un log de tipo debug para mostrar los ficheros encontrados
    logging.debug(f"Buscando archivos de transcripción con patrón: {pattern}")
    files = glob.glob(pattern)
    logging.debug(f"Archivos encontrados: {files}")
    return glob.glob(pattern)


def process_files(summary_dir, transcript_dir):
    """Procesa todos los archivos de resumen y actualiza los archivos de transcripción correspondientes."""
    summary_files = glob.glob(os.path.join(summary_dir, "ep*.html"))
    
    for summary_file in summary_files:
        ep_id = extract_ep_id(summary_file)
        if not ep_id:
            logging.warning(f"No se pudo extraer el ID del episodio de {summary_file}")
            continue
        
        logging.info(f"Procesando resumen para episodio {ep_id}")
        
        # Obtener el contenido del resumen
        summary_content = get_summary_content(summary_file)
        if not summary_content:
            logging.warning(f"No se encontró el resumen en {summary_file}")
            continue
        
        # Encontrar archivos de transcripción correspondientes
        transcript_files = find_matching_transcripts(ep_id, transcript_dir)
        if not transcript_files:
            logging.warning(f"No se encontraron archivos de transcripción para el episodio {ep_id}")
            continue
        
        # Actualizar cada archivo de transcripción
        for transcript_file in transcript_files:
            logging.info(f"Actualizando {transcript_file}")
            update_transcript_file(transcript_file, summary_content)


def get_args():
    """Obtiene los argumentos de la línea de comandos."""
    parser = argparse.ArgumentParser(
        description='Inserta resúmenes en archivos de transcripción HTML.'
    )
    parser.add_argument(
        '-s', '--summary-dir',
        required=True,
        help='Directorio donde se encuentran los archivos de resumen'
    )
    parser.add_argument(
        '-t', '--transcript-dir',
        required=True,
        help='Directorio donde se encuentran los archivos de transcripción'
    )
    
    return parser.parse_args()
    
    
def main():
    
    args = get_args()
    logging.info(f"Argumentos: {args}")

    # Verificar que los directorios existen
    if not os.path.isdir(args.summary_dir):
        logging.error(f"El directorio de resúmenes {args.summary_dir} no existe")
        return 1
    
    if not os.path.isdir(args.transcript_dir):
        logging.error(f"El directorio de transcripciones {args.transcript_dir} no existe")
        return 1
    
    logging.info(f"Procesando resúmenes de {args.summary_dir} para transcripciones en {args.transcript_dir}")
    process_files(args.summary_dir, args.transcript_dir)
    logging.info("Proceso completado")
    
    return 0


if __name__ == "__main__":
    logcfg(__file__)
    exit(main())