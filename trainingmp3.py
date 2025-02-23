import logging
from util import logcfg
import yaml
import os
import argparse
from pydub import AudioSegment
from mutagen.id3 import ID3, TIT2, TPE1, COMM

def load_config(yaml_file):
    """ Carga el diccionario de hablantes y archivos desde un fichero YAML """
    with open(yaml_file, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)

def create_training_audio(config_file, output_file, silence_between_speakers, target_duration):
    """ Genera un archivo MP3 concatenando los audios de hablantes con silencios entre ellos y guarda los metadatos. """
    
    # Cargar la configuración desde el YAML
    audio_data = load_config(config_file)

    # Silencio configurado entre hablantes
    silence_segment = AudioSegment.silent(duration=silence_between_speakers * 1000)  # Convertir segundos a ms

    # Construir el audio concatenado
    final_audio = AudioSegment.empty()
    speaker_mapping = {}  # Diccionario para mapear X a nombres reales
    speaker_index = 0  # Para asignar 0, 1, etc.

    for segment in audio_data:
        if not "name" in audio_data[segment]:
            logging.warning("⚠️ Advertencia: Segmento sin hablante, será omitido.")
            continue
        speaker = audio_data[segment]["name"]
        files = audio_data[segment]["files"]
        logging.info(f" Procesando audios del segmento {segment}- Speaker: {speaker}...")

        # Concatenar todos los archivos de este hablante sin espacios entre ellos
        speaker_audio = AudioSegment.empty()
        for file in files:
            if os.path.exists(file):
                speaker_audio += AudioSegment.from_file(file, format="mp3")
            else:
                logging.warning(f"⚠️ Advertencia: El archivo {file} no existe y será omitido.")

        # Añadir la voz del hablante al audio final
        final_audio += speaker_audio

        # Guardar la asignación de X -> Nombre
        speaker_mapping[speaker_index] = speaker
        speaker_index += 1

        # Añadir silencio entre hablantes (excepto después del último)
        final_audio += silence_segment
    final_audio += silence_segment  # Añadir un silencio final
    final_audio += silence_segment  # Añadir un silencio final

    # Calcular la duración actual
    current_duration = len(final_audio)

    # Si la duración es menor que la deseada, añadir un silencio final
    target_duration_ms = target_duration * 1000  # Convertir segundos a milisegundos
    if current_duration < target_duration_ms:
        silence_needed = target_duration_ms - current_duration
        final_audio += AudioSegment.silent(duration=silence_needed)

    # Exportar el audio final
    final_audio.export(output_file, format="mp3")

    # Guardar metadatos en el MP3 y el YAML de respaldo
    save_metadata(output_file, speaker_mapping)
    save_yaml_mapping(output_file.replace(".mp3", "_mapa.yaml"), speaker_mapping)

    logging.info(f"✅ Archivo generado: {output_file} con duración final de {len(final_audio) / 1000} segundos.")
    logging.info(f"📌 Metadatos guardados en el MP3 y en {output_file.replace('.mp3', '_mapa.yaml')}")

def save_metadata(mp3_file, speaker_mapping):
    """ Guarda la correspondencia de hablantes en los metadatos ID3 del MP3 """
    audio = ID3()
    
    # Agregar título y artista genérico
    audio.add(TIT2(encoding=3, text="Audio de Entrenamiento"))
    audio.add(TPE1(encoding=3, text="WhisperX Training"))

    # Agregar la correspondencia SPEAKER_X -> Nombre en formato YAML con delimitadores
    speaker_data = "---\n"  # Inicio del YAML
    speaker_data += "\n".join([f"{k}: {v}" for k, v in speaker_mapping.items()])

    audio.add(COMM(encoding=3, desc="Speakers", lang='eng', text=speaker_data))
    
    # Guardar los metadatos en el archivo
    audio.save(mp3_file)
    logging.info("✅ Metadatos ID3 añadidos correctamente con formato YAML.")

def save_yaml_mapping(yaml_file, speaker_mapping):
    """ Guarda la correspondencia de hablantes en un archivo YAML """
    with open(yaml_file, "w", encoding="utf-8") as file:
        yaml.dump(speaker_mapping, file, default_flow_style=False, allow_unicode=True)
    logging.info(f"✅ Respaldo YAML creado en {yaml_file}")

# Configuración de argparse para recibir parámetros desde la línea de comandos
def parse_arguments():
    parser = argparse.ArgumentParser(description="Genera un archivo de entrenamiento a partir de audios etiquetados en un YAML.")
    
    parser.add_argument(
        "-c", "--config", type=str, default="training.yml",
        help="Archivo YAML con la lista de hablantes y sus archivos de audio (Predeterminado: training.yml)."
    )
    
    parser.add_argument(
        "-o", "--output", type=str, default="training.mp3",
        help="Nombre del archivo de salida (MP3). Predeterminado: training.mp3."
    )
    
    parser.add_argument(
        "-s", "--silence", type=int, default=5,
        help="Duración del silencio entre hablantes en segundos. (Predeterminado: 5s)"
    )
    
    parser.add_argument(
        "-t", "--time", type=int, default=600,
        help="Duración total del fragmento en segundos. (Predeterminado: 600)"
    )
    
    return parser.parse_args()

if __name__ == "__main__":
    logcfg(__file__)
    logging.info("Iniciando proceso de generación de audio de entrenamiento.")
    args = parse_arguments()
    
    # Ejecutar el proceso con los parámetros obtenidos
    create_training_audio(args.config, args.output, args.silence, args.time)
