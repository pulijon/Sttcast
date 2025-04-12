#!/usr/bin/env python3
import argparse
import csv
import json
import os
import re
from typing import Dict, List, Tuple


def parse_arguments():
    """Procesa los argumentos de línea de comandos."""
    parser = argparse.ArgumentParser(
        description='Genera un archivo JSON con transcripciones y fechas.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Ejemplos:
  python %(prog)s -d dates.csv -f *.html -o transcripciones.json
  python %(prog)s -d dates.csv -f ep500_A_whisper_audio_es.html ep500_B_whisper_audio_es.html -o salida.json

Formato del archivo CSV de fechas:
  fecha,id_episodio
  2025-02-21,ep500_A
  2025-02-21,ep500_B

Formato del archivo JSON de salida:
  {
    "data": [
      {
        "id": "ep500_A",
        "date": "2025-02-21",
        "transcription": "<contenido html>"
      },
      ...
    ]
  }
'''
    )
    parser.add_argument(
        '-d', '--dates',
        required=True,
        help='Archivo CSV con fechas y IDs de episodios'
    )
    parser.add_argument(
        '-f', '--files',
        required=True,
        nargs='+',
        help='Lista de archivos HTML de transcripción'
    )
    parser.add_argument(
        '-o', '--output',
        required=True,
        help='Archivo JSON de salida'
    )
    return parser.parse_args()


def read_dates_file(dates_file: str) -> Dict[str, str]:
    """
    Lee el archivo CSV de fechas y devuelve un diccionario con
    id de episodio como clave y fecha como valor.
    """
    episode_dates = {}
    with open(dates_file, 'r', encoding='utf-8') as csvfile:
        csv_reader = csv.reader(csvfile)
        for row in csv_reader:
            if len(row) >= 2:
                date, episode_id = row[0], row[1]
                episode_dates[episode_id] = date
    return episode_dates


def read_transcription_files(html_files: List[str]) -> Dict[str, str]:
    """
    Lee los archivos HTML de transcripción y devuelve un diccionario con
    id de episodio como clave y contenido HTML como valor.
    """
    transcriptions = {}
    pattern = r'^(ep\d+_[AB])_whisper_audio_es\.html$'
    
    for html_file in html_files:
        filename = os.path.basename(html_file)
        match = re.match(pattern, filename)
        
        if match:
            episode_id = match.group(1)
            with open(html_file, 'r', encoding='utf-8') as file:
                content = file.read()
                transcriptions[episode_id] = content
    
    return transcriptions


def generate_json(episode_dates: Dict[str, str], 
                 transcriptions: Dict[str, str]) -> List[Dict]:
    """
    Genera la estructura de datos para el JSON con los episodios,
    sus fechas y transcripciones.
    """
    result = []
    
    for episode_id, content in transcriptions.items():
        if episode_id in episode_dates:
            episode_data = {
                "id": episode_id,
                "date": episode_dates[episode_id],
                "transcription": content
            }
            result.append(episode_data)
    
    return result


def main():
    """Función principal del programa."""
    args = parse_arguments()
    
    # Leer archivo de fechas
    episode_dates = read_dates_file(args.dates)
    
    # Leer archivos de transcripción
    transcriptions = read_transcription_files(args.files)
    
    # Generar estructura de datos para el JSON
    data = generate_json(episode_dates, transcriptions)
    
    # Escribir JSON de salida
    with open(args.output, 'w', encoding='utf-8') as outfile:
        json.dump({"data": data}, outfile, ensure_ascii=False, indent=2)
    
    print(f"Archivo JSON generado correctamente: {args.output}")
    print(f"Total de episodios procesados: {len(data)}")


if __name__ == "__main__":
    main()