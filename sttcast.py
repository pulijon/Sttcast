#! /usr/bin/python3

from util import logcfg
import logging
from vosk import Model, KaldiRecognizer
import wave
import json
import datetime
import argparse
import os
import glob
import subprocess
import configparser
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import Value
import whisper

# MODEL = "/usr/src/vosk-models/es/vosk-model-es-0.42"
MODEL = "/mnt/ram/es/vosk-model-es-0.42"
WHMODEL = "small"
WHDEVICE = "cuda"
WHLANGUAGE = "es"
WAVFRATE = 16000
RWAVFRAMES = 4000
SECONDS = 600
HCONF = 0.9
MCONF = 0.6
LCONF = 0.4
OVERLAPTIME = 1.5

# Variables globales reutilizables con distintos motores
cpus = max(os.cpu_count() - 2, 1)
seconds = SECONDS
fname = ""
fname_root = ""
fname_extension = ""
fname_html = ""
fname_meta = ""
fname_wav = ""
duration = 0.0


HTMLHEADER = """<html>

<head>
  <style>
    .medium{
        color: orange;
    }
    .low{
        color: red;
    }
    .high{
        color: green;
    }
    .time{
        color: blue;
    }
    .title{
        border: 3px solid green;
        color: black;
    }
  </style>

</head>
<body>
"""

HTMLFOOTER = """
</body>
</html>
"""


def class_str(st, cl):
    return f'<span class="{cl}">{st}</span>'

def time_str(st,end):
    return class_str(f"[{datetime.timedelta(seconds=float(st))} - "
                      f"{datetime.timedelta(seconds=float(end))}]<br>\n", "time")

def audio_tag(mp3file, seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f'<audio controls src="{mp3file}#t={h:02d}:{m:02d}:{s:02d}"></audio>\n'


def get_pars():
    parser = argparse.ArgumentParser()
    parser.add_argument("fname", type=str, 
                        help=f"fichero de audio a transcribir")
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
    parser.add_argument("--whmodel", choices=whisper.available_models(), type=str, default=WHMODEL,
                        help=f"modelo whisper a utilizar. Por defecto, {WHMODEL}")
    parser.add_argument("--whdevice", choices=['cuda', 'cpu'], default=WHDEVICE,
                        help=f"aceleración a utilizar. Por defecto, {WHDEVICE}")
    parser.add_argument("--whlanguage", default=WHLANGUAGE,
                        help=f"lenguaje a utilizar. Por defecto, {WHLANGUAGE}")
    parser.add_argument("-a", "--audio-tags", action='store_true',
                        help=f"inclusión de audio tags")


    return parser.parse_args()

def create_meta_file(fname, fname_meta):
    if (os.path.exists(fname_meta)):
        os.remove(fname_meta)
    return subprocess.run(["ffmpeg", 
                            "-i", fname, 
                            "-f", "ffmetadata",
                            fname_meta,
                            ])

def create_wav_file(fname, fname_wav):
    if (os.path.exists(fname_wav)):
        os.remove(fname_wav)
    return subprocess.run(["ffmpeg", 
                              "-i", fname, 
                              "-ac", "1",
                              "-c:a", "pcm_s16le",
                              "-ar", str(WAVFRATE),
                              fname_wav,
                              ])

def get_rate_and_frames(fname_wav):
    with wave.open(fname_wav, "rb") as wf:
        return wf.getframerate(), wf.getnframes()

def vosk_task_work(cfg):   
    logcfg(__file__)
    stime = datetime.datetime.now()
    with wave.open(cfg["wname"], "rb") as wf:
        model = Model(cfg["model"])
        frate = wf.getframerate()
        rec = KaldiRecognizer(model, frate)

        # Se calcula el momento de inicio en segundos
        # del presente fragmento relativo al comienzo del mp3,
        # en función de la primera trama a procesar y de la velocidad
        fframe = cfg["fframe"]
        offset_seconds = fframe / frate

        rec.SetWords(True)
        rec.SetPartialWords(True)

        # Se hace un cierto solapamiento entre el corte actual
        # y el siguiente para evitar perder audio
        overlap_frames = cfg["overlap"] * frate
        left_frames = cfg["nframes"] + overlap_frames

        # Tramas en cada lectura del wav
        rwavframes = cfg["rwavframes"]

        # Se coloca el "puntero de lectura" del wav en la trama
        # correspondiente al presente frragmento
        wf.setpos(fframe)

        hname = cfg["hname"]
        if os.path.exists(hname):
            os.remove(hname)
        with open(hname, "w") as html:
            while left_frames > 0:
                data = wf.readframes(rwavframes)
                left_frames -= rwavframes
                if len(data) == 0:
                    break
                if rec.AcceptWaveform(data):
                    res = json.loads(rec.Result())
                    if ("result" not in res) or \
                       (len(res["result"])) == 0:
                        continue
                    start_time = res["result"][0]["start"] + offset_seconds
                    end_time = res["result"][-1]["end"] + offset_seconds
                    logging.debug(f"{hname} - por procesar: {left_frames/frate} segundos - text: {res.get('text','')}")
                    html.write("<p>\n")
                    html.write(f"{time_str(start_time, end_time)}")
                    if cfg['audio_tags']:
                        html.write(audio_tag(cfg['mp3file'], start_time))
                    for r in res["result"]:
                        w = r["word"]
                        c = r["conf"]
                        if c < cfg["lconf"]:
                            html.write(class_str(w, "low"))
                        elif c < cfg["mconf"]:
                            html.write(class_str(w, "medium"))
                        elif c < cfg["hconf"]:
                            html.write(class_str(w, "high"))
                        else:
                            html.write(w)
                        html.write(" ")
                    html.write("</p>\n")
    return hname, datetime.datetime.now() - stime

def whisper_task_work(cfg):
    logcfg(__file__)
    stime = datetime.datetime.now()

    model = whisper.load_model(cfg['whmodel'], device=cfg['whdevice'])
    result = model.transcribe(cfg["fname"], language=cfg['whlanguage'])
    offset_seconds = float(cfg['cut'] * cfg['seconds'])
    logging.debug(result)

    hname = cfg["hname"]
    if os.path.exists(hname):
        os.remove(hname)
    
    with open(hname, "w") as html:
        for s in result['segments']:
            start_time = float(s['start']) + offset_seconds
            end_time = float(s['end'])+ offset_seconds
            html.write("<p>\n")
            html.write(f"{time_str(start_time, end_time)}")
            if cfg['audio_tags']:
                html.write(audio_tag(cfg['mp3file'], start_time))
            html.write(f"{s['text']}")
            html.write("</p>\n")
    return hname, datetime.datetime.now() - stime


def build_html_file(fname_html, fname_meta, hnames):
    if os.path.exists(fname_html):
        os.remove(fname_html)
    with open(fname_html, "w") as html:
                     
        html.write(HTMLHEADER)
        config = configparser.ConfigParser()
        with open (fname_meta, "r") as cf:
            config.read_string("[global]\n" + cf.read())
        hmsg = ""
        rold = '\\;'
        rnew = '\n</li><li>\n'
        for key in config['global']:
            hmsg += f"{key}:<br>\n<ul><li>{config.get('global', key).replace(rold,rnew)}<br></li></ul>\n"
        html.write(f'<h2 class="title"><br>{hmsg} </h2>\n')
        for hn in hnames:
            with open(hn, "r") as hnf:
                html.write(hnf.read())
        html.write(HTMLFOOTER)

def launch_vosk_tasks(args):
    global cpus, seconds, duration
    global fname, fname_root

    fname_wav = fname_root + ".wav"
    create_wav_file(fname, fname_wav)
    rate, frames = get_rate_and_frames(fname_wav)
    total_seconds = frames / rate
    duration = datetime.timedelta(seconds=total_seconds)

    num_frames = seconds * rate
    fframes = range(0, frames, num_frames)
    cfgs = [
        {
        "model": args.model,
        "wname": fname_wav,
        "hname": f"{fname_root}_{fenum[0]}.html",
        "nframes": num_frames,
        "lconf": args.lconf,
        "mconf": args.mconf,
        "hconf": args.hconf,
        "overlap": args.overlap,
        "fframe": fenum[1],
        "rwavframes": args.rwavframes,
        "audio_tags": args.audio_tags,
        "mp3file": fname,
        } for fenum in enumerate(range(0, frames, num_frames))
    ]
    
    with ProcessPoolExecutor(cpus) as executor:
        for f, t in  executor.map(vosk_task_work, cfgs):
            logging.info(f"{f} ha tardado {t}")
    # En cfgs se utiliza list comprehension
    # en hnames, generator comprehension, porque no vamos
    # a necesitar más que una vez los hnames
    return (cfg["hname"] for cfg in cfgs)

def split_podcast(fname_root, fname_extension, seconds):
    wildcard_mp3_files = f"{fname_root}_???{fname_extension}"
    # Se borran ficheros con formatos similares a los que se van a crear
    files_to_remove = glob.glob(wildcard_mp3_files)
    for f in files_to_remove:
        os.remove(f)
    
    subprocess.run(["ffmpeg", 
                        "-i", fname, 
                        "-f", "segment",
                        "-segment_time", str(seconds),
                        "-segment_start_number", str(1),
                        "-c", "copy", 
                        f"{fname_root}_%03d{fname_extension}"
                        ])
    return glob.glob(wildcard_mp3_files)

def launch_whisper_tasks(args):
    global cpus, seconds, duration
    global fname, fname_root

    mp3files = split_podcast(fname_root, fname_extension, seconds)

    cfgs = [
        {
        "whmodel": args.whmodel,
        "whdevice": args.whdevice,
        "whlanguage": args.whlanguage,
        "hname": f"{fname_root}_{fenum[0]}.html",
        "fname": fenum[1],
        "cut": fenum[0],
        "seconds": args.seconds,
        "audio_tags": args.audio_tags,
        "mp3file": fname,
        } for fenum in enumerate(mp3files)
    ]

    with ProcessPoolExecutor(cpus) as executor:
        for f, t in  executor.map(whisper_task_work, cfgs):
            logging.info(f"{f} ha tardado {t}")

    return (cfg["hname"] for cfg in cfgs)
   
def configure_globals(args):
    global cpus, seconds
    global fname, fname_root, fname_extension, fname_meta, fname_html

    cpus = args.cpus
    seconds = int(args.seconds)
    fname = args.fname
    fname_root, fname_extension = os.path.splitext(fname)
    fname_meta = fname_root + ".meta"
    fname_html = fname_root + ".html"



def main():
    global fname_html, fname_meta, fname

    args = get_pars()
    configure_globals(args)
    
    whisper = args.whisper
    create_meta_file(fname, fname_meta)
    if whisper:
        hnames = launch_whisper_tasks(args)
    else:
        hnames = launch_vosk_tasks(args)
    
    build_html_file(fname_html, fname_meta, hnames )
    logging.info(f"Terminado de procesar mp3 de duración {duration}")
    

if __name__ == "__main__":
    logcfg(__file__)
    stime = datetime.datetime.now()
    main()
    etime = datetime.datetime.now()
    logging.info(f"Ejecución del programa ha tardado {etime - stime}")