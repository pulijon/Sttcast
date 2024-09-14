#! /usr/bin/python3

from util import logcfg
import logging
import whisper
from vosk import Model, KaldiRecognizer
import wave
import ffmpeg
import json
import datetime
import argparse
import os
import glob
import subprocess
import configparser
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import Value
from timeinterval import TimeInterval, seconds_str
import re

# MODEL = "/usr/src/vosk-models/es/vosk-model-es-0.42"
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

# Variables globales reutilizables con distintos motores
cpus = max(os.cpu_count() - 2, 1)
seconds = SECONDS
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

# def time_str(st,end):
#     return class_str(f"[{datetime.timedelta(seconds=float(st))} - "
#                       f"{datetime.timedelta(seconds=float(end))}]<br>\n", "time")

def audio_tag_str(mp3file, seconds):
    # m, s = divmod(int(seconds), 60)
    # h, m = divmod(m, 60)
    # return f'<audio controls src="{mp3file}#t={h:02d}:{m:02d}:{s:02d}"></audio>\n'
    return f'<audio controls src="{mp3file}#t={seconds_str(seconds, with_dec=False)}"></audio><br>\n'


def get_pars():
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
    parser.add_argument("--whmodel", choices=whisper.available_models(), type=str, default=WHMODEL,
                        help=f"modelo whisper a utilizar. Por defecto, {WHMODEL}")
    parser.add_argument("--whdevice", choices=['cuda', 'cpu'], default=WHDEVICE,
                        help=f"aceleración a utilizar. Por defecto, {WHDEVICE}")
    parser.add_argument("--whlanguage", default=WHLANGUAGE,
                        help=f"lenguaje a utilizar. Por defecto, {WHLANGUAGE}")
    parser.add_argument("-a", "--audio-tags", action='store_true',
                        help=f"inclusión de audio tags")
    parser.add_argument("--html-suffix", type=str, default=HTMLSUFFIX,
                        help=f"sufijo para el fichero HTML con el resultado. Por defecto '_result'")
    parser.add_argument("--min-offset", type=float, default=MINOFFSET, 
                        help=f"diferencia mínima entre inicios de marcas de tiempo. Por defecto {MINOFFSET}")
    parser.add_argument("--max-gap", type=float, default=MAXGAP, 
                        help=f"diferencia máxima entre el inicio de un segmento y el final del anterior." 
                             f" Por encima de esta diferencia, se pone una nueva marca de tiempo . Por defecto {MAXGAP}")
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

def add_result_to_transcription(transcription, result, lconf, mconf, hconf):
    for r in result:
        w = r["word"]   
        c = r["conf"]
        if c < lconf:
            transcription += class_str(w, "low")
        elif c < mconf:
            transcription += class_str(w, "medium")
        elif c < hconf:
            transcription += class_str(w, "high")
        else:
            transcription += w
        transcription += " "
    return transcription

def write_transcription(html, transcription, ti, audio_tag, mp3file):
    html.write("\n<p>\n")
    html.write(f"{class_str(ti, 'time')}<br>\n")
    if audio_tag:
        html.write(audio_tag_str(mp3file, ti.start))
    html.write(transcription)
    html.write("\n</p>\n")

def write_srt_entry(srt, start_time, end_time, str):
    srt.write("\n<>\n") # Aquí irá el múmero de párrafo
    srt.write(f"{seconds_str(start_time)}0 --> {seconds_str(end_time)}0\n".replace(".", ","))
    srt.write(f"{str.strip()}\n")
    
def vosk_task_work(cfg):   
    logcfg(__file__)
    stime = datetime.datetime.now()
    with wave.open(cfg["wname"], "rb") as wf:
        model = Model(cfg["model"])
        frate = wf.getframerate()
        rec = KaldiRecognizer(model, frate)
        fnumframes = wf.getnframes()

        # Se calcula el momento de inicio en segundos
        # del presente fragmento relativo al comienzo del mp3,
        # en función de la primera trama a procesar y de la velocidad
        fframe = cfg["fframe"]
        offset_seconds = fframe / frate
        min_offset = cfg["min_offset"]
        max_gap = cfg["max_gap"]

        rec.SetWords(True)
        rec.SetPartialWords(True)

        # Se hace un cierto solapamiento entre el corte actual
        # y el siguiente para evitar perder audio
        overlap_frames = cfg["overlap"] * frate
        # Las tramas a leer no pueden ser más que las que tiene el fichero
        left_frames = min(cfg["nframes"] + overlap_frames, fnumframes)

        # Tramas en cada lectura del wav
        rwavframes = cfg["rwavframes"]

        # Se coloca el "puntero de lectura" del wav en la trama
        # correspondiente al presente frragmento
        wf.setpos(fframe)
        
        hname = cfg["hname"]
        sname = cfg["sname"]
        if os.path.exists(hname):
            os.remove(hname)
        if os.path.exists(sname):
            os.remove(sname)

        logging.info(f"Comenzando fragmento con vosk {hname}")
        with open(hname, "w") as html, open(sname, "w") as srt:
            html.write("<!-- New segment -->\n")
            last_ti = None
            while left_frames > 0:
                # No hace falta leer rwavframes frames si no quedan tantas por leer
                frames_to_read = min(rwavframes, left_frames - rwavframes)
                data = wf.readframes(frames_to_read)
                left_frames -= frames_to_read
                if len(data) == 0:
                    break
                last_accepted = True
                if rec.AcceptWaveform(data):
                    last_accepted = True
                    res = json.loads(rec.Result())
                    if ("result" not in res) or \
                       (len(res["result"])) == 0:
                        continue
                    start_time = res["result"][0]["start"] + offset_seconds
                    end_time = res["result"][-1]["end"] + offset_seconds
                    write_srt_entry(srt, 
                                    start_time, end_time, 
                                    " ".join([r['word'] for r in res['result']]))

                    new_ti = TimeInterval(start_time, end_time)
                    logging.debug(f"{hname} - por procesar: {left_frames/frate} segundos - text: {res.get('text','')}")
                    gap = new_ti.gap(last_ti)
                    offset = new_ti.offset(last_ti)
                    logging.debug(f"gap = {gap} - offset = {offset}")
                    if (last_ti != None) and (gap < max_gap) and (offset < min_offset) :
                        last_ti.extend(new_ti)
                        logging.debug(f"Alargando last_ti: {last_ti}")
                    else:
                        if last_ti != None:
                            write_transcription(html, transcription, last_ti, 
                                                cfg['audio_tags'], cfg['mp3file'])

                        last_ti = new_ti
                        logging.debug(f"Nuevo last_ti: {last_ti}")
                        transcription = ""

                    transcription = add_result_to_transcription(transcription, res['result'],
                                                                cfg['lconf'], cfg['mconf'], cfg['hconf'])                   
                    
                else:
                    last_accepted = False
            # Si la última lectura no cerró un párrafo, este párrafo podría perderse
            # Como mal menor, se acepta el resultado parcial
            # TBD - Reutilizar el código duplicado con una función process_result(html, result, last_ti) que devuelva un TimeInterval
            if not last_accepted:
                res = json.loads(rec.PartialResult())
                if res["partial"] != "":
                    start_time = res["partial_result"][0]["start"] + offset_seconds
                    end_time = res["partial_result"][-1]["end"] + offset_seconds
                    write_srt_entry(srt, 
                                    start_time, end_time, 
                                    ' '.join([r['word'] for r in res['partial_result']]))
                    new_ti = TimeInterval(start_time, end_time)
                    gap = new_ti.gap(last_ti)
                    offset = new_ti.offset(last_ti)
                    logging.debug(f"gap = {gap} - offset = {offset}")
                    if (last_ti != None) and (gap < max_gap) and (offset < min_offset) :
                        last_ti.extend(new_ti)
                        logging.debug(f"Alargando last_ti: {last_ti}")
                    else:
                        if last_ti != None:
                            write_transcription(html, transcription, last_ti, 
                                                cfg['audio_tags'], cfg['mp3file'])
                        last_ti = new_ti
                        logging.debug(f"Nuevo last_ti: {last_ti}")
                        transcription = ""
                    add_result_to_transcription(transcription, res["partial_result"],
                                                cfg['lconf'], cfg['mconf'], cfg['hconf'])                   

            if last_ti is not None:
                write_transcription(html, transcription, last_ti, 
                                    cfg['audio_tags'], cfg['mp3file'])
        logging.info(f"Terminado fragmento con vosk {hname}")

    return hname, sname, datetime.datetime.now() - stime

def whisper_task_work(cfg):
    logcfg(__file__)
    stime = datetime.datetime.now()

    model = whisper.load_model(cfg['whmodel'], device=cfg['whdevice'])
    # Solución a error pytorch - ver https://github.com/openai/whisper/discussions/1068
    result = model.transcribe(cfg["fname"], language=cfg['whlanguage'], fp16=False)
    offset_seconds = float(cfg['cut'] * cfg['seconds'])
    min_offset = cfg["min_offset"]
    max_gap = cfg["max_gap"]

    logging.debug(result)
    os.remove(cfg['fname'])

    hname = cfg["hname"]
    sname = cfg["sname"]
    if os.path.exists(hname):
        os.remove(hname)
    logging.info(f"Comenzando fragmento con whisper {hname}")
    with open(hname, "w") as html, open(sname, "w") as srt:
        html.write("<!-- New segment -->\n")
        last_ti = None
        for s in result['segments']:
            start_time = float(s['start']) + offset_seconds
            end_time = float(s['end'])+ offset_seconds
            write_srt_entry(srt, 
                            start_time, end_time, 
                            s['text'])
            new_ti = TimeInterval(start_time, end_time)
            gap = new_ti.gap(last_ti)
            offset = new_ti.offset(last_ti)
            logging.debug(f"gap = {gap} - offset = {offset}")
            if (last_ti != None) and (gap < max_gap) and (offset < min_offset) :
                last_ti.extend(new_ti)
                logging.debug(f"Alargando last_ti: {last_ti}")
            else:
                if last_ti != None:
                    write_transcription(html, transcription, last_ti, 
                                        cfg['audio_tags'], cfg['mp3file'])
                last_ti = new_ti
                logging.debug(f"Nuevo last_ti: {last_ti}")
                transcription = ""
            transcription += (f"{s['text']}")

        if last_ti is not None:
            write_transcription(html, transcription, last_ti, 
                                cfg['audio_tags'], cfg['mp3file'])
    logging.info(f"Terminado fragmento con whisper {hname}")
    return hname, sname, datetime.datetime.now() - stime


def build_html_file(fdata):
    pf = fdata[0]
    chunks = fdata[1]
    fname_html = pf["html"]
    fname_meta = pf["meta"]
    hnames = [chunk["hname"] for chunk in chunks]
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
            os.remove(hn)
        html.write(HTMLFOOTER)

def replace_with_numbers(match):
    replace_with_numbers.counter += 1
    return str(replace_with_numbers.counter)

def build_srt_file(fdata):
    pf = fdata[0]
    chunks = fdata[1]
    fname_srt = pf['srt']
    if (os.path.exists(fname_srt)):
        os.remove(fname_srt)
    snames = [chunk["sname"] for chunk in chunks]
    raw_srt_content = ""
    replace_with_numbers.counter = 0
    for sn in snames:
        with open(sn, "r") as snf:
            raw_srt_content += snf.read()
        os.remove(sn)
    srt_content = re.sub(r"<>", replace_with_numbers, raw_srt_content)
    with open(fname_srt, "w") as srt:
        srt.write(srt_content)
    

def launch_vosk_tasks(args):
    global cpus, seconds, duration
    global procfnames
    
    results = []
    
    for pf in procfnames:
        fname = pf["name"]
        fname_root = pf["root"]
        fname_wav = pf["wav"]
        fname_meta = pf["meta"]
        create_meta_file(fname, fname_meta)
        create_wav_file(fname, fname_wav)
        rate, frames = get_rate_and_frames(fname_wav)
        total_seconds = frames / rate
        duration = datetime.timedelta(seconds=total_seconds)

        num_frames = seconds * rate
        results.append(
            (
                pf,
                [
                    {
                    "model": args.model,
                    "wname": fname_wav,
                    "hname": f"{fname_root}_{fenum[0]}.html",
                    "sname": f"{fname_root}_{fenum[0]}.srt",
                    "nframes": num_frames,
                    "lconf": args.lconf,
                    "mconf": args.mconf,
                    "hconf": args.hconf,
                    "overlap": args.overlap,
                    "fframe": fenum[1],
                    "rwavframes": args.rwavframes,
                    "audio_tags": args.audio_tags,
                    "mp3file": os.path.basename(fname),
                    "min_offset": args.min_offset,
                    "max_gap": args.max_gap
                    } for fenum in enumerate(range(0, frames, num_frames))
                ]
            )
        )
    with ProcessPoolExecutor(cpus) as executor:
        tasks = []
        for result in results:
            tasks.extend(result[1])
        for f, s, t in  executor.map(vosk_task_work, tasks):
           logging.info(f"{f} y {s} han tardado {t}")
    
    for pf in procfnames:
        os.remove(pf['wav'])

    return results

def split_podcast(pf, seconds):
    fname_root = pf["root"]
    fname_extension = pf["extension"]
    fname = pf["name"]
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
    return sorted(glob.glob(wildcard_mp3_files))

def launch_whisper_tasks(args):
    global cpus, seconds, duration
    global procfnames
    
    results = []
    for pf in procfnames:
        fname_root = pf["root"]
        fname = pf["name"]
        fname_meta = pf["meta"]
        create_meta_file(fname, fname_meta)
        mp3files =split_podcast(pf, seconds)

        results.append(
            (
                pf,
                [
                    {
                    "whmodel": args.whmodel,
                    "whdevice": args.whdevice,
                    "whlanguage": args.whlanguage,
                    "hname": f"{fname_root}_{fenum[0]}.html",
                    "sname": f"{fname_root}_{fenum[0]}.srt",
                    "fname": fenum[1],
                    "cut": fenum[0],
                    "seconds": args.seconds,
                    "audio_tags": args.audio_tags,
                    "mp3file": os.path.basename(fname),
                    "min_offset": args.min_offset,
                    "max_gap": args.max_gap,
                    } for fenum in enumerate(mp3files)
                ]
            )
        )

    with ProcessPoolExecutor(cpus) as executor:
        tasks = []
        for result in results:
            tasks.extend(result[1])
        for f, s, t in  executor.map(whisper_task_work, tasks):
            logging.info(f"{f} y {s} han tardado {t}")

    return results
 
def get_mp3_duration(f):
    probe = ffmpeg.probe(f)
    duration = float(probe['format']['duration'])
    return duration  

def configure_globals(args):
    global cpus, seconds
    global procfnames

    cpus = args.cpus
    seconds = int(args.seconds)
    procfnames_unsorted = []
    html_suffix = "" if args.html_suffix == "" else "_" + args.html_suffix

    for fname in args.fnames:
        if os.path.isdir(fname):
            # Add .mp3 files in dir
            logging.info(f"Tratando directorio {fname}")
            for root, dirs, files in os.walk(fname):
                for file in files:
                    if file.endswith(".mp3"):
                        full_path = os.path.join(root, file)
                        fname_dict = create_fname_dict(full_path, html_suffix)
                        procfnames_unsorted.append(fname_dict)
        else:
            # Add file
            logging.info(f"Tratando fichero {fname}")
            fname_dict = create_fname_dict(fname, html_suffix)
            procfnames_unsorted.append(fname_dict)

    logging.info(f"Se van a procesar {len(procfnames_unsorted)} ficheros con un total de {sum([pf['duration'] for pf in procfnames_unsorted])} segundos")
    # Se ordenan los ficheros en función del tamaño de manera descendente
    # Así se optimiza el proceso de transcripción
    procfnames = sorted(procfnames_unsorted,
                        key = lambda f: f["duration"],
                        reverse = True)
    logging.debug(f"Ficheros van a procesarse en orden: {[(pf['name'], get_mp3_duration(pf['name'])) for pf in procfnames]}")

def create_fname_dict(fname, html_suffix):
    fname_dict = {}
    fname_dict["name"] = fname
    fname_root, fname_extension = os.path.splitext(fname)
    fname_dict["root"] = fname_root
    fname_dict["extension"] = fname_extension
    fname_dict["meta"] = fname_root + ".meta"
    fname_dict["html"] = fname_root + html_suffix + ".html"
    fname_dict["wav"] = fname_root + ".wav"
    fname_dict['srt'] = fname_root + html_suffix + ".srt"
    fname_dict["duration"] = get_mp3_duration(fname)
    return fname_dict

def start_stt_process(args):
    configure_globals(args)
    
    whisper = args.whisper
    if whisper:
        results = launch_whisper_tasks(args)
    else:
        results = launch_vosk_tasks(args)
    
    for result in results:
        build_html_file(result)
        build_srt_file(result)
    logging.info(f"Terminado de procesar mp3 de duración {duration}")

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