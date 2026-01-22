#! /usr/bin/python3

# Aplicar parche para PyTorch 2.6+ con omegaconf
import torch_fix

from tools.logs import logcfg
from tools.envvars import load_env_vars_from_directory
import logging
import argparse
import os
import datetime
import sttcast_core
from dotenv import load_dotenv
import glob

# CLI-specific constants
MODEL = "/mnt/ram/es/vosk-model-es-0.42"
WHMODEL = "small"
WHDEVICE = "cuda"
WHLANGUAGE = "es"
WHSUSPTIME = 60.0
RWAVFRAMES = 4000
SECONDS = 600
HCONF = 0.95
MCONF = 0.7
LCONF = 0.5
OVERLAPTIME = 2
MINOFFSET = 30
MAXGAP = 0.8
HTMLSUFFIX = ""
DEFAULT_PODCAST_CAL_FILE="calfile"
DEFAULT_PODCAST_PREFIX="ep"
DEFAULT_PODCAST_TEMPLATES= "templates"

# Variables globales reutilizables con distintos motores
cpus = max(os.cpu_count() - 2, 1)
seconds = SECONDS
duration = 0.0

# Directorio de configuración
CONF_DIR = os.path.join(os.path.dirname(__file__), ".env")

# Huggingface token
HUGGINGFACE_TOKEN = ""

# Parámetros de Pyannote para diarizacion
PYANNOTE_METHOD = "ward"
PYANNOTE_MIN_CLUSTER_SIZE = 15
PYANNOTE_THRESHOLD = 0.7147
PYANNOTE_MIN_SPEAKERS = None
PYANNOTE_MAX_SPEAKERS = None





def get_pars():
    global PYANNOTE_METHOD, PYANNOTE_MIN_CLUSTER_SIZE, PYANNOTE_THRESHOLD, PYANNOTE_MIN_SPEAKERS, PYANNOTE_MAX_SPEAKERS
    load_env_vars_from_directory(os.path.join(os.path.dirname(__file__),'.env'))
    cal_file = os.getenv('PODCAST_CAL_FILE', DEFAULT_PODCAST_CAL_FILE)
    prefix = os.getenv('PODCAST_PREFIX', DEFAULT_PODCAST_PREFIX)
    podcast_templates = os.getenv('PODCAST_TEMPLATES', DEFAULT_PODCAST_TEMPLATES)
    
    # Cargar parámetros de Pyannote desde .env
    PYANNOTE_METHOD = os.getenv('PYANNOTE_METHOD', 'ward')
    PYANNOTE_MIN_CLUSTER_SIZE = int(os.getenv('PYANNOTE_MIN_CLUSTER_SIZE', '15'))
    PYANNOTE_THRESHOLD = float(os.getenv('PYANNOTE_THRESHOLD', '0.7147'))
    # Los parámetros de min/max speakers son opcionales
    pyannote_min_speakers_str = os.getenv('PYANNOTE_MIN_SPEAKERS', '')
    pyannote_max_speakers_str = os.getenv('PYANNOTE_MAX_SPEAKERS', '')
    PYANNOTE_MIN_SPEAKERS = int(pyannote_min_speakers_str) if pyannote_min_speakers_str else None
    PYANNOTE_MAX_SPEAKERS = int(pyannote_max_speakers_str) if pyannote_max_speakers_str else None

    parser = argparse.ArgumentParser()
    parser.add_argument("fnames", type=str, nargs='+',
                        help=f"archivos de audio o directorios a transcribir")
    parser.add_argument("-m", "--model", type=str, default=MODEL,
                        help=f"modelo a utilizar. Por defecto, {MODEL}")
    parser.add_argument("-s", "--seconds", type=int, default=SECONDS,
                        help=f"segundos de cada tarea. Por defecto, {SECONDS}")
    parser.add_argument("-c", "--cpus", type=int, default=max(os.cpu_count()-2,1),
                        help=f"CPUs (tamaño del pool de procesos) a utilizar. Por defecto, {max(os.cpu_count()-2,1)}")
    parser.add_argument("-i", "--hconf", type=float, default=HCONF,
                        help=f"umbral de confianza alta. Por defecto, {HCONF}")
    parser.add_argument("-n", "--mconf", type=float, default=MCONF,
                        help=f"umbral de confianza media. Por defecto, {MCONF}")
    parser.add_argument("-l", "--lconf", type=float, default=LCONF,
                        help=f"umbral de confianza baja. Por defecto, {LCONF}")
    parser.add_argument("-o", "--overlap", type=float, default=OVERLAPTIME,
                        help=f"tiempo de solapamientro entre fragmentos. Por defecto, {OVERLAPTIME}")
    parser.add_argument("-r", "--rwavframes", type=int, default=RWAVFRAMES,
                        help=f"número de tramas en cada lectura del wav. Por defecto, {RWAVFRAMES}")
    parser.add_argument("-w", "--whisper", action='store_true',
                        help=f"utilización de motor whisper")
    parser.add_argument("--whmodel", type=str, default=WHMODEL,
                        help=f"modelo whisper a utilizar. Por defecto, {WHMODEL}")
    parser.add_argument("--whdevice", choices=['cuda', 'cpu'], default=WHDEVICE,
                        help=f"aceleración a utilizar. Por defecto, {WHDEVICE}")
    parser.add_argument("--whlanguage", default=WHLANGUAGE,
                        help=f"lenguaje a utilizar. Por defecto, {WHLANGUAGE}")
    parser.add_argument("--whtraining", type=str, default="training.mp3",
                        help=f"nombre del fichero de entrenamiento. Por defecto, 'training.mp3'")
    parser.add_argument("--whsusptime", type=str, default=WHSUSPTIME,
                        help=f"tiempo mínimo de intervención en el segmento. Por defecto, {WHSUSPTIME}")
    parser.add_argument("-a", "--audio-tags", action='store_true',
                        help=f"inclusión de audio tags")
    parser.add_argument("--html-suffix", type=str, default=HTMLSUFFIX,
                        help=f"sufijo para el fichero HTML con el resultado. Por defecto '_result'")
    parser.add_argument("--min-offset", type=float, default=MINOFFSET, 
                        help=f"diferencia mínima entre inicios de marcas de tiempo. Por defecto {MINOFFSET}")
    parser.add_argument("--max-gap", type=float, default=MAXGAP, 
                        help=f"diferencia máxima entre el inicio de un segmento y el final del anterior." 
                             f" Por encima de esta diferencia, se pone una nueva marca de tiempo . Por defecto {MAXGAP}")
    parser.add_argument("-p", "--prefix", type=str, default=prefix,
                        help=f"prefijo para los ficheros de salida. Por defecto {prefix}")
    parser.add_argument("--calendar", type=str, default=cal_file,
                        help=f"Calendario de episodios en formato CSV. Por defecto {cal_file}")
    parser.add_argument("-t", "--templates", type=str, default=podcast_templates,
                    help=f"Plantillas para los podcasts. Por defecto {podcast_templates}")
    
    # Parámetros de Pyannote (diarización)
    parser.add_argument("--pyannote-method", type=str, default=PYANNOTE_METHOD,
                        help=f"Método de clustering para pyannote. Por defecto {PYANNOTE_METHOD}")
    parser.add_argument("--pyannote-min-cluster-size", type=int, default=PYANNOTE_MIN_CLUSTER_SIZE,
                        help=f"Tamaño mínimo de cluster para pyannote. Por defecto {PYANNOTE_MIN_CLUSTER_SIZE}")
    parser.add_argument("--pyannote-threshold", type=float, default=PYANNOTE_THRESHOLD,
                        help=f"Umbral de clustering para pyannote. Por defecto {PYANNOTE_THRESHOLD}")
    parser.add_argument("--pyannote-min-speakers", type=int, default=PYANNOTE_MIN_SPEAKERS,
                        help=f"Número mínimo de hablantes (opcional). Por defecto {PYANNOTE_MIN_SPEAKERS}")
    parser.add_argument("--pyannote-max-speakers", type=int, default=PYANNOTE_MAX_SPEAKERS,
                        help=f"Número máximo de hablantes (opcional). Por defecto {PYANNOTE_MAX_SPEAKERS}")

    return parser.parse_args()





    

def launch_vosk_tasks(args):
    global procfnames
    
    config_dict = {
        'procfnames': procfnames,
        'cpus': args.cpus,
        'seconds': args.seconds,
        'model': args.model,
        'lconf': args.lconf,
        'mconf': args.mconf,
        'hconf': args.hconf,
        'overlap': args.overlap,
        'rwavframes': args.rwavframes,
        'audio_tags': args.audio_tags,
        'min_offset': args.min_offset,
        'max_gap': args.max_gap
    }
    
    return sttcast_core.launch_vosk_tasks_core(config_dict)



def launch_whisper_tasks(args):
    global procfnames
    
    # Usar valores de argumentos si están definidos, si no usar los globales (de .env)
    pyannote_method = getattr(args, 'pyannote_method', None) or PYANNOTE_METHOD
    pyannote_min_cluster_size = getattr(args, 'pyannote_min_cluster_size', None) or PYANNOTE_MIN_CLUSTER_SIZE
    pyannote_threshold = getattr(args, 'pyannote_threshold', None) or PYANNOTE_THRESHOLD
    pyannote_min_speakers = getattr(args, 'pyannote_min_speakers', None) or PYANNOTE_MIN_SPEAKERS
    pyannote_max_speakers = getattr(args, 'pyannote_max_speakers', None) or PYANNOTE_MAX_SPEAKERS
    
    config_dict = {
        'procfnames': procfnames,
        'cpus': args.cpus,
        'seconds': args.seconds,
        'whmodel': args.whmodel,
        'whdevice': args.whdevice,
        'whlanguage': args.whlanguage,
        'audio_tags': args.audio_tags,
        'min_offset': args.min_offset,
        'max_gap': args.max_gap,
        'whtraining': args.whtraining,
        'whsusptime': args.whsusptime,
        'pyannote_method': pyannote_method,
        'pyannote_min_cluster_size': pyannote_min_cluster_size,
        'pyannote_threshold': pyannote_threshold,
        'pyannote_min_speakers': pyannote_min_speakers,
        'pyannote_max_speakers': pyannote_max_speakers,
    }
    
    return sttcast_core.launch_whisper_tasks_core(config_dict)

def configure_globals(args):
    global cpus, seconds
    global procfnames
    global HUGGINGFACE_TOKEN

    cpus = args.cpus
    seconds = int(args.seconds)
    procfnames_unsorted = []
    html_suffix = "" if args.html_suffix == "" else "_" + args.html_suffix
    
    # Obtener el path completo del fichero de entrenamiento 
    if args.whtraining is not None:
        args.whtraining = os.path.abspath(args.whtraining)
    
    # Variables de entorno en .venv
    logging.info(f"Directorio de configuración: {CONF_DIR}")
    conf_files = glob.glob(os.path.join(CONF_DIR, "*.conf"))
    for conf_file in conf_files:
        logging.info(f"Cargando variables de entorno de {conf_file}")
        load_dotenv(conf_file)
            
    HUGGINGFACE_TOKEN = os.getenv("HUGGINGFACE_TOKEN")
    # logging.info(f"Token de Huggingface: {HUGGINGFACE_TOKEN}")
    

    for fname in args.fnames:
        if os.path.isdir(fname):
            # Add .mp3 files in dir
            logging.info(f"Tratando directorio {fname}")
            for root, dirs, files in os.walk(fname):
                for file in files:
                    if file.endswith(".mp3"):
                        full_path = os.path.join(root, file)
                        if full_path == args.whtraining:
                            logging.info(f"El fichero de entrenamiento {full_path} no se procesa")
                            continue
                        logging.info(f"Tratando fichero {full_path}")
                        fname_dict = sttcast_core.create_fname_dict(full_path, html_suffix, args.prefix, args.calendar, args.templates)
                        procfnames_unsorted.append(fname_dict)
        else:
            # Add file
            if os.path.abspath(fname) == args.whtraining:
                logging.info(f"El fichero de entrenamiento {fname} no se procesa")
                continue
            logging.info(f"Tratando fichero {fname}")
            fname_dict = sttcast_core.create_fname_dict(fname, html_suffix, args.prefix, args.calendar, args.templates)
            procfnames_unsorted.append(fname_dict)

    logging.info(f"Se van a procesar {len(procfnames_unsorted)} ficheros con un total de {sum([pf['duration'] for pf in procfnames_unsorted])} segundos")
    # Se ordenan los ficheros en función del tamaño de manera descendente
    # Así se optimiza el proceso de transcripción
    procfnames = sorted(procfnames_unsorted,
                        key = lambda f: f["duration"],
                        reverse = True)
    logging.debug(f"Ficheros van a procesarse en orden: {[(pf['name'], sttcast_core.get_mp3_duration(pf['name'])) for pf in procfnames]}")

def start_stt_process(args):
    configure_globals(args)
    
    whisper = args.whisper
    if whisper:
        results = launch_whisper_tasks(args)
    else:
        results = launch_vosk_tasks(args)
    
    for result in results:
        sttcast_core.build_html_file(result)
        sttcast_core.build_srt_file(result)
    logging.info(f"Terminado de procesar mp3")

def main():
    args = get_pars()
    logging.info(f"{args}")

    start_stt_process(args)
    
    

if __name__ == "__main__":
    logcfg(__file__)
    stime = datetime.datetime.now()
    main()
    etime = datetime.datetime.now()
    logging.info(f"Ejecución del programa ha tardado {etime - stime}")
    exit(0)
