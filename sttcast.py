#! /usr/bin/python3

from util import logcfg
import logging
import whisperx
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
from dotenv import load_dotenv
import glob
from pyannote.audio import Pipeline
import yaml
from mutagen.id3 import ID3
from pydub import AudioSegment

# MODEL = "/usr/src/vosk-models/es/vosk-model-es-0.42"
MODEL = "/mnt/ram/es/vosk-model-es-0.42"
WHMODEL = "small"
WHDEVICE = "cuda"
WHLANGUAGE = "es"
WAVFRATE = 16000
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

# Variables globales reutilizables con distintos motores
cpus = max(os.cpu_count() - 2, 1)
seconds = SECONDS
duration = 0.0

# Directorio de configuración
CONF_DIR = os.path.join(os.path.dirname(__file__), ".env")

# Huggingface token
HUGGINGFACE_TOKEN = ""



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
        .speaker-0 { color: #1f77b4; } /* Azul */
    .speaker-1 { color: #ff7f0e; } /* Naranja */
    .speaker-2 { color: #2ca02c; } /* Verde */
    .speaker-3 { color: #d62728; } /* Rojo */
    .speaker-4 { color: #9467bd; } /* Morado */
    .speaker-5 { color: #8c564b; } /* Marrón */
    .speaker-6 { color: #e377c2; } /* Rosa */
    .speaker-7 { color: #7f7f7f; } /* Gris */
    .speaker-8 { color: #bcbd22; } /* Amarillo */
    .speaker-9 { color: #17becf; } /* Cian */
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
        with open(hname, "w") as html, open(sname, "w", encoding="utf-8") as srt:
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

def build_trained_audio(training_file, audio_file):
    if training_file is None:
        logging.warning("No se ha especificado fichero de entrenamiento")
        return audio_file, 0.0
    if not os.path.exists(training_file):
        logging.error(f"El fichero de entrenamiento {training_file} no existe")
        return audio_file, 0.0
    logging.debug(f"Combinando ficheros de entrenamiento {training_file} y {audio_file}")
    combined_audio = AudioSegment.from_file(training_file, format="mp3") + \
                     AudioSegment.from_file(audio_file, format="mp3")
    training_duration = len(AudioSegment.from_file(training_file, format="mp3")) / 1000.0  # Duration in seconds
    trained_file = os.path.join(os.path.dirname(audio_file), f"trained_{os.path.basename(audio_file)}")
    combined_audio.export(trained_file, format="mp3")
    logging.debug(f"Fichero de entrenamiento combinado: {trained_file}")
    return trained_file, training_duration

def substitute_speakers(hname, speakers):
    """
    Reemplaza los nombres de usuario en un archivo HTML y guarda el resultado en el mismo archivo.

    Args:
        hname (str): Nombre del archivo HTML de entrada y salida.
        speakers (dict): Diccionario que mapea nombres de usuario a reemplazos.
    """

    logging.info(f"Reemplazando nombres de hablantes en {hname} - {speakers}")
    try:
        with open(hname, "r+", encoding="utf-8") as f:
            content = f.read()
            # logging.debug(content)

            spk_pattern = r'(\[<span[^>]*>)([^<]+)(</span>\])'
            for spk in speakers:
                substitute = f"??? {speakers[spk]}"
                spk_pattern = r'(\[<span[^>]*>)'+f"({spk})"+r'(</span>\])'
                content = re.sub(spk_pattern,r'\1'+substitute+r'\3', content)
            f.seek(0) # Go to the beginning of the file
            f.write(content)
            f.truncate() # Remove the rest of the file
    except FileNotFoundError:
        logging.error(f"Error: El archivo {hname} no fue encontrado.")
    except Exception as e:
        logging.error(f"Error: {e}")
        
def whisper_task_work(cfg):
    global HUGGINGFACE_TOKEN
    
    logcfg(__file__)
    stime = datetime.datetime.now()

    whdevice = cfg['whdevice']
    whmodel = cfg['whmodel']
    #audio_file = cfg['fname']
    model = whisperx.load_model(whmodel, device=whdevice)
    # Solución a error pytorch - ver https://github.com/openai/whisper/discussions/1068
    # result = model.transcribe(audio_file, language=cfg['whlanguage'], fp16=False)
    logging.debug(f"Construyendo el fichero de audio entrenado con {cfg.get('whtraining', None)}")
    audio_file, trained_duration = build_trained_audio(cfg.get('whtraining', None), cfg['fname'])
    logging.debug(f"Audio entrenado: {audio_file}, duración: {trained_duration}")
    result = model.transcribe(audio_file, language=cfg['whlanguage'])
    whsusptime = cfg['whsusptime']

    # Inicializar el pipeline de diarización de WhisperX
    # logging.info(HUGGINGFACE_TOKEN)
    diarization_pipeline = whisperx.DiarizationPipeline(device=whdevice, use_auth_token=HUGGINGFACE_TOKEN)
    diarization = diarization_pipeline(audio_file)
    result = whisperx.assign_word_speakers(diarization, result)
    
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
    with open(hname, "w", encoding="utf-8") as html, open(sname, "w", encoding="utf-8") as srt:
        html.write("<!-- New segment -->\n")
        last_ti = None
        speakers_dict = {}
        nspeakers = 0
        ntraining = len(cfg['speaker_mapping'].keys())
        for s in result['segments']:
            speaker_no_mapped = s.get('speaker', 'Unknown')
            if speaker_no_mapped not in speakers_dict:
                if nspeakers in cfg.get('speaker_mapping',{}):
                    speakers_dict[speaker_no_mapped] = {'id': cfg['speaker_mapping'][nspeakers],
                                                        'style': f"speaker-{nspeakers%10}"}
                    logging.debug(f"Speaker {speaker_no_mapped} mapeado a {speakers_dict[speaker_no_mapped]}")
                else:
                    speakers_dict[speaker_no_mapped] = {'id': f"Unknown {nspeakers - ntraining + 1}", 
                                                        'style': f"speaker-{nspeakers%10}"}
                nspeakers += 1
            if s['start'] < trained_duration:
                logging.debug(f"Saltando segmento {s['start']} < {trained_duration} ")
                continue
            start_time = float(s['start']) + offset_seconds - trained_duration
            end_time = float(s['end'])+ offset_seconds - trained_duration
            speaker = speakers_dict.get(speaker_no_mapped)
            text = s['text']
            
            # Se contabiliza el tiempo de cada hablante 
            speaker['time'] = speaker.get('time', 0.0) + (end_time - start_time)
            
            text_with_speaker = f"\n[{class_str(speaker['id'], speaker['style'])}]: {text}"
            write_srt_entry(srt, 
                            start_time, end_time, 
                            text_with_speaker)
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
            transcription += ("<br>" + text_with_speaker + " ")
       

        if last_ti is not None:
            # Poner entre comentarios los tiempos de cada hablante
            nsusp = 0
            strange_speakers = {}
            for speaker in speakers_dict:
                if 'time' in speakers_dict[speaker]:
                    if speakers_dict[speaker]['time'] < whsusptime:
                        logging.warning(f"El hablante {speakers_dict[speaker]['id']} ha hablado {seconds_str(speakers_dict[speaker]['time'])} en el segmento")   
                        nsusp += 1
                        strange_speakers [speakers_dict[speaker]['id']] = nsusp
                        transcription+= (f"\n<!-- ??? {nsusp} ha hablado {seconds_str(speakers_dict[speaker]['time'])} en el segmento -->")
                    else:
                      transcription+=(f"\n<!-- {speakers_dict[speaker]['id']} ha hablado {seconds_str(speakers_dict[speaker]['time'])} en el segmento -->")

            write_transcription(html, transcription, last_ti, 
                                cfg['audio_tags'], cfg['mp3file'])
    substitute_speakers(hname, strange_speakers)
    logging.info(f"Terminado fragmento con whisper {hname}")
    del diarization_pipeline
    return hname, sname, datetime.datetime.now() - stime


def build_html_file(fdata):
    pf = fdata[0]
    chunks = fdata[1]
    fname_html = pf["html"]
    fname_meta = pf["meta"]
    hnames = [chunk["hname"] for chunk in chunks]
    if os.path.exists(fname_html):
        os.remove(fname_html)
        
    with open(fname_html, "w", encoding="utf-8") as html:             
        html.write(HTMLHEADER)
        config = configparser.ConfigParser()
        try:
            with open (fname_meta, "r") as cf:
                config.read_string("[global]\n" + cf.read())
            hmsg = ""
            rold = '\\;'
            rnew = '\n</li><li>\n'
            for key in config['global']:
                hmsg += f"{key}:<br>\n<ul><li>{config.get('global', key).replace(rold,rnew)}<br></li></ul>\n"
            html.write(f'<h2 class="title"><br>{hmsg} </h2>\n')
        except:
            logging.warning(f"No se ha podido leer el fichero de metadatos {fname_meta}")
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
    with open(fname_srt, "w", encoding="utf-8") as srt:
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

def get_speaker_mapping(training_file):
    if training_file is None:
        logging.warning("No se ha especificado fichero de entrenamiento")
        return {}
    if not os.path.exists(training_file):
        logging.error(f"El fichero de entrenamiento {training_file} no existe")
        return {}
    audio = ID3(training_file)
    logging.debug(f"Metadatos de entrenamiento: {audio.pprint()}")
    
    # Buscar la clave COMM que contiene los hablantes
    comm_key = next((key for key in audio.keys() if key.startswith("COMM")), None)

    if not comm_key:
        logging.error(f"El fichero de entrenamiento {training_file} no tiene metadatos de entrenamiento")
        return {}

    speaker_data = audio[comm_key].text[0]
    
    logging.debug(f"Metadatos de entrenamiento: {speaker_data}")
    
    try:
        # Convertir texto a diccionario YAML
        speaker_mapping = yaml.safe_load(speaker_data)
        logging.info(f"Speaker mapping: {speaker_mapping}")
        return speaker_mapping
    except yaml.YAMLError as e:
        logging.error("⚠️ Error al leer los metadatos YAML:", e)
        return {}  

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
        logging.debug(f"En launch_whisper_tasks: args.whtraining={args.whtraining}")
        speaker_mapping = get_speaker_mapping(args.whtraining)
        logging.debug(f"Mapeado de hablantes: {speaker_mapping}")

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
                    "whtraining": args.whtraining,
                    "whsusptime": float(args.whsusptime),
                    "speaker_mapping": speaker_mapping
                    } for fenum in enumerate(mp3files)
                ]
            )
        )
        
    logging.debug(f"Configuracioness: {results}")

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
                        fname_dict = create_fname_dict(full_path, html_suffix)
                        procfnames_unsorted.append(fname_dict)
        else:
            # Add file
            if os.path.abspath(fname) == args.whtraining:
                logging.info(f"El fichero de entrenamiento {fname} no se procesa")
                continue
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