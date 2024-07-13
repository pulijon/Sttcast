#! /usr/bin/python3

from util import logcfg
import logging
from sttcastpoolexecutor import SttcastPoolExecutor
import whisper
import datetime
import argparse
import os
import ffmpeg

# Constants
MODEL = "/mnt/ram/es/vosk-model-es-0.42"
WHMODEL = "small"
WHDEVICE = "cuda"
WHLANGUAGE = "es"
WAVFRATE = 16000
RWAVFRAMES = 4000
SECONDS = 600
HCONF = 0.95
MCONF = 0.7
LCONF = 0.5
OVERLAPTIME = 2
MINOFFSET = 30
MAXGAP = 0.8
HTMLSUFFIX = ""

# Get command line arguments
def get_pars():
    parser = argparse.ArgumentParser()
    parser.add_argument("fnames", type=str, nargs='+', help="archivos de audio o directorios a transcribir")
    parser.add_argument("-m", "--model", type=str, default=MODEL, help=f"modelo a utilizar. Por defecto, {MODEL}")
    parser.add_argument("-s", "--seconds", type=int, default=SECONDS, help=f"segundos de cada tarea. Por defecto, {SECONDS}")
    parser.add_argument("-c", "--cpus", type=int, default=max(os.cpu_count()-2, 1), help=f"CPUs a utilizar. Por defecto, {max(os.cpu_count()-2, 1)}")
    parser.add_argument("-i", "--hconf", type=float, default=HCONF, help=f"umbral de confianza alta. Por defecto, {HCONF}")
    parser.add_argument("-n", "--mconf", type=float, default=MCONF, help=f"umbral de confianza media. Por defecto, {MCONF}")
    parser.add_argument("-l", "--lconf", type=float, default=LCONF, help=f"umbral de confianza baja. Por defecto, {LCONF}")
    parser.add_argument("-o", "--overlap", type=float, default=OVERLAPTIME, help=f"tiempo de solapamiento entre fragmentos. Por defecto, {OVERLAPTIME}")
    parser.add_argument("-r", "--rwavframes", type=int, default=RWAVFRAMES, help=f"número de tramas en cada lectura del wav. Por defecto, {RWAVFRAMES}")
    parser.add_argument("-w", "--whisper", action='store_true', help="utilización de motor whisper")
    parser.add_argument("--whmodel", choices=whisper.available_models(), type=str, default=WHMODEL, help=f"modelo whisper a utilizar. Por defecto, {WHMODEL}")
    parser.add_argument("--whdevice", choices=['cuda', 'cpu'], default=WHDEVICE, help=f"aceleración a utilizar. Por defecto, {WHDEVICE}")
    parser.add_argument("--whlanguage", default=WHLANGUAGE, help=f"lenguaje a utilizar. Por defecto, {WHLANGUAGE}")
    parser.add_argument("-a", "--audio-tags", action='store_true', help="inclusión de audio tags")
    parser.add_argument("--html-suffix", type=str, default=HTMLSUFFIX, help="sufijo para el fichero HTML con el resultado")
    parser.add_argument("--min-offset", type=float, default=MINOFFSET, help=f"diferencia mínima entre inicios de marcas de tiempo. Por defecto {MINOFFSET}")
    parser.add_argument("--max-gap", type=float, default=MAXGAP, help=f"diferencia máxima entre el inicio de un segmento y el final del anterior. Por defecto {MAXGAP}")
    return parser.parse_args()

# Get MP3 file duration
def get_mp3_duration(f):
    probe = ffmpeg.probe(f)
    duration = float(probe['format']['duration'])
    return duration  

# Create file name dictionary
def create_fname_dict(fname, html_suffix):
    fname_dict = {}
    fname_dict["name"] = fname
    fname_dict["basename"] = os.path.basename(fname)
    fname_root, fname_extension = os.path.splitext(fname)
    fname_dict["root"] = fname_root
    fname_dict["extension"] = fname_extension
    fname_dict["meta"] = fname_root + ".meta"
    fname_dict["html"] = fname_root + html_suffix + ".html"
    fname_dict["wav"] = fname_root + ".wav"
    fname_dict["duration"] = get_mp3_duration(fname)
    return fname_dict

# Process file names
def get_proc_fnames(args):
    procfnames_unsorted = []
    for fname in args.fnames:
        if os.path.isdir(fname):
            logging.debug(f"Tratando directorio {fname}")
            for root, _, files in os.walk(fname):
                for file in files:
                    if file.endswith(".mp3"):
                        full_path = os.path.join(root, file)
                        fname_dict = create_fname_dict(full_path, args.html_suffix)
                        procfnames_unsorted.append(fname_dict)
        else:
            logging.debug(f"Tratando fichero {fname}")
            fname_dict = create_fname_dict(fname, args.html_suffix)
            procfnames_unsorted.append(fname_dict)

    procfnames = sorted(procfnames_unsorted, key=lambda f: f["duration"], reverse=True)
    logging.debug(f"Ficheros van a procesarse en orden: {[(pf['name'], pf['duration']) for pf in procfnames]}")
    return procfnames

def get_par_list(args):
    fnames = get_proc_fnames(args)
    del args.fnames
    return [{"fname": fname, **vars(args)} for fname in fnames ]

# Main function
def main():
    args = get_pars()
    logging.info(f"{args}")
    cpus = args.cpus
    # TBD - Borrar cpus de args
    par_list = get_par_list(args)
    executor = SttcastPoolExecutor(cpus, par_list)
    executor.execute_tasks()

# Entry point
if __name__ == "__main__":
    logcfg(__file__)
    stime = datetime.datetime.now()
    main()
    etime = datetime.datetime.now()
    logging.info(f"Ejecución del programa ha tardado {etime - stime}")
    exit(0)
