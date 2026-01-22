#! /usr/bin/python3

# Aplicar parche para PyTorch 2.6+ con omegaconf
import torch_fix

from tools.logs import logcfg
from tools.envvars import load_env_vars_from_directory
import logging
import gc
import torch
import whisperx
from whisperx.diarize import DiarizationPipeline
from vosk import Model, KaldiRecognizer
import wave
import ffmpeg
import json
import datetime
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
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader
from dateestimation import DateEstimation
import ffmpeg._probe
import tempfile
import uuid
import shutil

# Default constants
DEFAULT_MODEL = "/mnt/ram/es/vosk-model-es-0.42"
DEFAULT_WHMODEL = "small"
DEFAULT_WHDEVICE = "cuda"
DEFAULT_WHLANGUAGE = "es"
DEFAULT_WAVFRATE = 16000
DEFAULT_WHSUSPTIME = 60.0
DEFAULT_RWAVFRAMES = 4000
DEFAULT_SECONDS = 600
DEFAULT_HCONF = 0.95
DEFAULT_MCONF = 0.7
DEFAULT_LCONF = 0.5
DEFAULT_OVERLAPTIME = 2
DEFAULT_MINOFFSET = 30
DEFAULT_MAXGAP = 0.8
DEFAULT_HTMLSUFFIX = ""
DEFAULT_PODCAST_CAL_FILE = "calfile"
DEFAULT_PODCAST_PREFIX = "ep"
DEFAULT_PODCAST_TEMPLATES = "templates"


def class_str(st, cl):
    return f'<span class="{cl}">{st}</span>'


def bs4_class_str(soup, st, cl):
    """
    Crea un elemento span con la clase especificada y el texto dado.
    """
    span = soup.new_tag("span", **{"class": cl})
    span.string = str(st)
    return span


def audio_tag_str(mp3file, seconds):
    return f'<audio controls preload="none" src="{mp3file}#t={seconds_str(seconds, with_dec=False)}"></audio><br>\n'


def create_meta_file(fname, fname_meta):
    if (os.path.exists(fname_meta)):
        os.remove(fname_meta)
    return subprocess.run(["ffmpeg", 
                          "-y",
                          "-i", fname, 
                          "-f", "ffmetadata",
                          fname_meta,
                          ],
                          stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL)


def create_wav_file(fname, fname_wav, wavfrate=DEFAULT_WAVFRATE):
    if (os.path.exists(fname_wav)):
        os.remove(fname_wav)
    return subprocess.run(["ffmpeg", 
                          "-y",
                          "-i", fname, 
                          "-ac", "1",
                          "-c:a", "pcm_s16le",
                          "-ar", str(wavfrate),
                          fname_wav,
                          ],
                          stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL)


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

    
def bs4_write_transcription(soup, transcription, ti, audio_tag, mp3file):
    """
    Escribe la transcripción en el objeto BeautifulSoup.
    """
    if not transcription or len(transcription.strip()) == 0:
        logging.debug(f"No hay transcripción para {ti} - audio_tag={audio_tag} - mp3file={mp3file}")
        return
    logging.debug(f"Escribiendo transcripción en {ti} - audio_tag={audio_tag} - mp3file={mp3file} - Transcripción: {transcription}")
    p = soup.new_tag("p")
    p.append(bs4_class_str(soup, ti, "time"))
    if audio_tag:
        audio_tag = soup.new_tag("audio", controls="", preload="none", src=f"{mp3file}#t={seconds_str(ti.start, with_dec=False)}")
        p.append(audio_tag)
    p.append(soup.new_tag("br"))
    transcription_span = soup.new_tag("span")
    frag = BeautifulSoup(f"<div>{transcription}</div>", "html.parser")
    for node in frag.contents:
        transcription_span.append(node)
    p.append(transcription_span)
    soup.append(p)


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
        sh = BeautifulSoup("", "html.parser")
        with open(hname, "w") as html, open(sname, "w", encoding="utf-8") as srt:
            html.write("<!-- New segment -->\n")
            sh.append(sh.new_tag("comment", "New segment"))
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
                            bs4_write_transcription(sh, transcription, last_ti,
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
                            bs4_write_transcription(sh, transcription, last_ti,
                                                    cfg['audio_tags'], cfg['mp3file'])
                        last_ti = new_ti
                        logging.debug(f"Nuevo last_ti: {last_ti}")
                        transcription = ""
                    add_result_to_transcription(transcription, res["partial_result"],
                                                cfg['lconf'], cfg['mconf'], cfg['hconf'])                   

            if last_ti is not None:
                bs4_write_transcription(sh, transcription, last_ti,
                                        cfg['audio_tags'], cfg['mp3file'])
        logging.info(f"Terminado fragmento con vosk {hname}")
        with open(hname, "w", encoding="utf-8") as f:
            f.write(sh.prettify())
    return hname, sname, datetime.datetime.now() - stime


def build_trained_audio(training_file, audio_file, temp_dir=None):
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
    
    # Usar directorio temporal único si se proporciona
    if temp_dir:
        os.makedirs(temp_dir, exist_ok=True)
        trained_file = os.path.join(temp_dir, f"trained_{os.path.basename(audio_file)}")
    else:
        trained_file = os.path.join(os.path.dirname(audio_file), f"trained_{os.path.basename(audio_file)}")
    
    combined_audio.export(trained_file, format="mp3")
    logging.debug(f"Fichero de entrenamiento combinado: {trained_file}")
    return trained_file, training_duration


def bs4_substitute_speakers(hs: BeautifulSoup, speakers: dict, normal_speakers: list):
    """
    Reemplaza nombres de hablantes en spans cuya clase coincida con speaker-\d+,
    y añade una clase auxiliar 'speaker-tagged' antes de modificar el contenido.

    Args:
        hs (BeautifulSoup): Documento HTML como objeto BeautifulSoup.
        speakers (dict): Diccionario que mapea nombres originales a pseudónimos.
        normal_speakers (list): Lista de hablantes que no deben modificarse.
    """
    logging.info(f"Reemplazando nombres de hablantes - {speakers}")
    
    try:
        # Buscar todos los span que tengan clase speaker-0, speaker-1, etc.
        for span in hs.find_all("span", class_=lambda x: x and any(re.match(r"speaker-\d+", c) for c in x if isinstance(c, str))):
            nombre = span.get_text(strip=True)

            # Si el nombre del hablante está en el diccionario de speakers
            # y no está en la lista de hablantes normales, se reemplaza
            if nombre in speakers and nombre not in normal_speakers:
                nuevo = f"??? {speakers[nombre]}"
                span.string.replace_with(nuevo)

    except Exception as e:
        logging.error(f"Error al reemplazar hablantes: {e}")


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


def whisper_task_work(cfg):
    logcfg(__file__)
    stime = datetime.datetime.now()

    whdevice = cfg['whdevice']
    whmodel = cfg['whmodel']
    model = whisperx.load_model(whmodel, device=whdevice)
    logging.debug(f"Construyendo el fichero de audio entrenado con {cfg.get('whtraining', None)}")
    audio_file, training_duration = build_trained_audio(cfg.get('whtraining', None), cfg['fname'], cfg.get('temp_dir'))
    logging.debug(f"Audio entrenado: {audio_file}, duración de fragmento de entrenamiento: {training_duration}")
    result = model.transcribe(audio_file, language=cfg['whlanguage'])
    whsusptime = cfg['whsusptime']

    # Inicializar el pipeline de diarización de WhisperX con parámetros configurables
    huggingface_token = cfg.get('huggingface_token', '')
    logging.info(f"Inicializando Pyannote con parámetros: método={cfg.get('pyannote_method', 'ward')}, "
                 f"min_cluster_size={cfg.get('pyannote_min_cluster_size', 15)}, "
                 f"threshold={cfg.get('pyannote_threshold', 0.7147)}, "
                 f"min_speakers={cfg.get('pyannote_min_speakers')}, "
                 f"max_speakers={cfg.get('pyannote_max_speakers')}")
    
    diarization_pipeline = DiarizationPipeline(device=whdevice, use_auth_token=huggingface_token)
    
    # Configurar los parámetros de clustering si están disponibles
    # El pipeline de whisperx envuelve el Pipeline de pyannote en el atributo .model
    pyannote_params = {
        "clustering": {
            "method": cfg.get('pyannote_method', 'ward'),
            "min_cluster_size": cfg.get('pyannote_min_cluster_size', 15),
            "threshold": cfg.get('pyannote_threshold', 0.7147)
        }
    }
    
    try:
        diarization_pipeline.model.instantiate(pyannote_params)
        logging.info(f"Parámetros de Pyannote aplicados correctamente")
    except Exception as e:
        logging.warning(f"No se pudieron aplicar los parámetros de Pyannote: {e}. "
                       f"Se usarán los valores por defecto")
    
    # Pasar min_speakers y max_speakers a diarization_pipeline si están configurados
    diarization = diarization_pipeline(
        audio_file,
        min_speakers=cfg.get('pyannote_min_speakers'),
        max_speakers=cfg.get('pyannote_max_speakers')
    )
    result = whisperx.assign_word_speakers(diarization, result)
    
    offset_seconds = float(cfg['cut'] * cfg['seconds'])
    min_offset = cfg["min_offset"]
    max_gap = cfg["max_gap"]

    # logging.debug(result)
    os.remove(cfg['fname'])

    hname = cfg["hname"]
    sname = cfg["sname"]
    if os.path.exists(hname):
        os.remove(hname)
    sh = BeautifulSoup("", "html.parser")
    logging.info(f"Comenzando fragmento con whisper {hname}")
    with open(hname, "w", encoding="utf-8") as html, open(sname, "w", encoding="utf-8") as srt:
        # html.write("<!-- New segment -->\n")
        sh.append(sh.new_tag("comment", "New segment"))
        last_ti = None
        speakers_dict = {}
        nspeakers = 0
        ntraining = len(cfg['speaker_mapping'].keys())
        in_training = True
        last_speaker = "Ninguno"
        training_warning = False
        for s in result['segments']:
            speaker_no_mapped = s.get('speaker', 'Unknown')
            if speaker_no_mapped not in speakers_dict:
                if nspeakers in cfg.get('speaker_mapping',{}):
                    speakers_dict[speaker_no_mapped] = {'id': cfg['speaker_mapping'][nspeakers],
                                                        'style': f"speaker-{nspeakers%10}"}
                    logging.debug(f"[{nspeakers +1}] Speaker {speaker_no_mapped} mapeado a {speakers_dict[speaker_no_mapped]}")
                    last_speaker = speaker_no_mapped
                else:
                    speakers_dict[speaker_no_mapped] = {'id': f"Unknown {nspeakers - ntraining + 1}", 
                                                        'style': f"speaker-{nspeakers%10}"}
                nspeakers += 1
            elif in_training and (speaker_no_mapped != last_speaker):
                # Si el hablante ya ha sido mapeado y estamos en el periodo de entrenamiento, 
                # el mp3 de entrenamiento no sirve. Esta comprobación no detecta si dos hablantes
                # sucesivos en el fichero de entranamiento son el mismo. Para que pudiéramos saber
                # dónde está el problema, habría que comparar tiempos con entrenamiento
                logging.warning(f"Podría haber problemas nspeakers = {nspeakers}. En entrenamiento, {speaker_no_mapped} ya mapeado a {speakers_dict[speaker_no_mapped]}, last_speaker = {last_speaker}")             
            if s['start'] < training_duration:
                logging.debug(f"Saltando segmento {s['start']} < {training_duration} ")
                continue
            # Cuando se alcanza el periodo de entrenamiento, el número de speakers debe 
            # ser el mismo que el del entrenamiento
            if in_training:
                # Si el número de speakers es distinto al del entrenamiento, se lanza una advertencia
                training_warning = training_warning  or (not(nspeakers == ntraining))
                if nspeakers < ntraining:
                    logging.error(f"El número de hablantes ({nspeakers}) es menor que el del entrenamiento tras el entrenamiento ({ntraining})")
                    logging.error(f"Es casi seguro que dos hablantes del conjunto de entrenamiento han sido mapeados a uno solo")
                if nspeakers > ntraining:
                    logging.error(f"El número de hablantes ({nspeakers}) es mayor que el del entrenamiento tras el entrenamiento ({ntraining})")
                    logging.error(f"Es casi seguro que un hablante del conjunto de entrenamiento ha sido mapeado a dos")
                
            in_training = False
            start_time = float(s['start']) + offset_seconds - training_duration
            end_time = float(s['end'])+ offset_seconds - training_duration
            speaker = speakers_dict.get(speaker_no_mapped)
            text = s['text']
            
            # Se contabiliza el tiempo de cada hablante 
            time_to_add = end_time - start_time
            logging.debug(f"Speaker {speaker['id']} ha hablado {time_to_add} en el segmento")
            speaker['time'] = speaker.get('time', 0.0) + time_to_add
            
            text_with_speaker = f"\n[{class_str(speaker['id'], speaker['style'])}]: {text}"
            text_with_speaker_srt = f"\n[{speaker['id']}]: {text}"
            write_srt_entry(srt, 
                            start_time, end_time, 
                            text_with_speaker_srt)
            new_ti = TimeInterval(start_time, end_time)
            gap = new_ti.gap(last_ti)
            offset = new_ti.offset(last_ti)
            # logging.debug(f"gap = {gap} - offset = {offset}")
            if (last_ti != None) and (gap < max_gap) and (offset < min_offset) :
                last_ti.extend(new_ti)
                # logging.debug(f"Alargando last_ti: {last_ti}")
            else:
                if last_ti != None:
                    bs4_write_transcription(sh, transcription, last_ti,
                                            cfg['audio_tags'], cfg['mp3file'])
                last_ti = new_ti
                # logging.debug(f"Nuevo last_ti: {last_ti}")
                transcription = ""
            transcription += ("<br>" + text_with_speaker + " ")
       

        if last_ti is not None:
            # Poner entre comentarios los tiempos de cada hablante
            nsusp = 0
            strange_speakers = {}
            # Los hablantes que han hablado más del tiempo mínimo entrarán en normal_speakers
            normal_speakers = set()
            logging.debug(f'Justo antes de poner comentarios finales, speakers_dict: {speakers_dict}')
            if training_warning:
                transcription += f"\n<!-- WARNING: El número de hablantes real del conjunto de entrenamiento es distinto del teórico (ver logs) -->"
            for speaker in speakers_dict:
                if 'time' in speakers_dict[speaker]:
                    if speakers_dict[speaker]['time'] < whsusptime:
                        logging.warning(f"El hablante {speakers_dict[speaker]['id']} ha hablado {seconds_str(speakers_dict[speaker]['time'])} en el segmento")   
                        nsusp += 1
                        strange_speakers [speakers_dict[speaker]['id']] = nsusp
                        transcription+= (f"\n<!-- ??? {nsusp} ha hablado {seconds_str(speakers_dict[speaker]['time'])} en el segmento -->")
                    else:
                      transcription+=(f"\n<!-- {speakers_dict[speaker]['id']} ha hablado {seconds_str(speakers_dict[speaker]['time'])} en el segmento -->")
                      normal_speakers.add(speakers_dict[speaker]['id'])

            bs4_write_transcription(sh, transcription, last_ti,
                                    cfg['audio_tags'], cfg['mp3file'])
    bs4_substitute_speakers(sh, strange_speakers, normal_speakers)
    logging.info(f"Terminado fragmento con whisper {hname}")
    with open(hname, "w", encoding="utf-8") as f:
        f.write(sh.prettify())
    
    # Liberar memoria GPU explícitamente
    del diarization_pipeline
    del model
    del result
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        logging.debug(f"Memoria GPU liberada. VRAM libre: {torch.cuda.memory_reserved() / 1024**3:.2f} GB")
    
    return hname, sname, datetime.datetime.now() - stime


def get_metadata(fname_meta):
    """
    Obtiene los metadatos de un fichero de metadatos ffmpeg
    """
    hmsg = ""
    if not os.path.exists(fname_meta):
        logging.error(f"El fichero de metadatos {fname_meta} no existe")
    else:
        config = configparser.ConfigParser()
        try:
            with open(fname_meta, "r") as f:
                config.read_string("[global]\n" + f.read())
            rold = '\\;'
            rnew = '\n</li><li>\n'
            for key in config['global']:
                hmsg += f"{key}:<br>\n<ul><li>{config.get('global', key).replace(rold,rnew)}<br></li></ul>\n"
        except configparser.Error as e:
            logging.error(f"Error al leer el fichero de metadatos {fname_meta}: {e}")
    return hmsg


def get_epnumber(epname, prefix):
    epnumber_regex = re.compile(rf"{prefix}(\d+).*")
    match = re.search(epnumber_regex, epname)
    if match:
        return int(match.group(1))
    else:
        # Si no coincide el patrón, extraer números del nombre del archivo
        numbers = re.findall(r'\d+', epname)
        if numbers:
            return int(numbers[-1])  # Usar el último número encontrado
        else:
            return 0  # Valor por defecto si no se encuentran números


def build_html_file(fdata):
    pf = fdata[0]
    chunks = fdata[1]
    fname_html = pf["html"]
    fname_meta = pf["meta"]
    hnames = [chunk["hname"] for chunk in chunks]
    if os.path.exists(fname_html):
        os.remove(fname_html)
        
    env = Environment(loader=FileSystemLoader(pf['templates']))
    html_template = env.get_template("podcast.html")
    de = DateEstimation(pf['calendar'])
    epnumber = get_epnumber(pf["root"], pf["prefix"])
    try:
        epdate = de.estimate_date_from_epnumber(epnumber).strftime("%Y-%m-%d")
    except Exception as e:
        logging.error(f"Error al estimar la fecha del episodio {epnumber}: {e}")
        epdate = "Desconocida"
    epname = os.path.basename(pf["root"])
    vars = {
        "epname": epname,
        "epdate": epdate
    }
    html_content = html_template.render(vars)
    soup = BeautifulSoup(html_content, "html.parser")
    for hn in hnames:
        with open(hn, "r", encoding="utf-8") as hnf:
            frag = BeautifulSoup(hnf.read(), "html.parser")
            soup.body.append(frag)
        os.remove(hn)
    with open(fname_html, "w", encoding="utf-8") as f:
       f.write(soup.prettify())


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


def split_podcast(pf, seconds, temp_dir=None, work_id=None):
    fname_root = pf["root"]
    fname_extension = pf["extension"]
    fname = pf["name"]
    
    # Usar directorio temporal único si se proporciona
    if temp_dir:
        os.makedirs(temp_dir, exist_ok=True)
        base_name = os.path.basename(fname_root)
        if work_id:
            output_pattern = os.path.join(temp_dir, f"{base_name}_{work_id}_%03d{fname_extension}")
            wildcard_mp3_files = os.path.join(temp_dir, f"{base_name}_{work_id}_???{fname_extension}")
        else:
            output_pattern = os.path.join(temp_dir, f"{base_name}_%03d{fname_extension}")
            wildcard_mp3_files = os.path.join(temp_dir, f"{base_name}_???{fname_extension}")
    else:
        # Modo legacy
        output_pattern = f"{fname_root}_%03d{fname_extension}"
        wildcard_mp3_files = f"{fname_root}_???{fname_extension}"
    
    # Se borran ficheros con formatos similares a los que se van a crear
    files_to_remove = glob.glob(wildcard_mp3_files)
    for f in files_to_remove:
        os.remove(f)
    
    subprocess.run(["ffmpeg", 
                    "-y",
                    "-i", fname, 
                    "-f", "segment",
                    "-segment_time", str(seconds),
                    "-segment_start_number", str(1),
                    "-c", "copy", 
                    output_pattern
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL)
    return sorted(glob.glob(wildcard_mp3_files))


def get_mp3_duration(filepath):
    """
    Devuelve la duración de un archivo MP3 en segundos (float).
    Si hay error, devuelve None.
    """
    try:
        # Expandir ruta con ~
        path = os.path.expanduser(filepath)

        # Usar ffprobe para obtener info
        info = ffmpeg._probe.probe(path)
        duration = float(info['format']['duration'])
        return duration

    except ffmpeg.Error as e:
        print(f"[ffmpeg error] {e.stderr.decode().strip()}" if e.stderr else str(e))
    except subprocess.CalledProcessError as e:
        print(f"[subprocess error] {e}")
    except Exception as e:
        print(f"[unexpected error] {e}")

    return None


def create_fname_dict(fname, html_suffix, prefix, calendar, templates, temp_dir=None, work_id=None):
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
    fname_dict['prefix'] = prefix
    fname_dict['calendar'] = calendar
    fname_dict['templates'] = templates
    
    # Agregar información de directorio temporal y work_id
    fname_dict['temp_dir'] = temp_dir
    fname_dict['work_id'] = work_id
    
    return fname_dict


def launch_vosk_tasks_core(config_dict):
    """
    Core function to launch Vosk transcription tasks using configuration dictionary.
    
    Args:
        config_dict: Dictionary containing all configuration parameters
        
    Returns:
        List of tuples containing (file_data, chunks) for processing results
    """
    results = []
    cpus = config_dict.get('cpus', max(os.cpu_count() - 2, 1))
    seconds = config_dict.get('seconds', DEFAULT_SECONDS)
    
    for pf in config_dict['procfnames']:
        fname = pf["name"]
        fname_root = pf["root"]
        fname_wav = pf["wav"]
        fname_meta = pf["meta"]
        create_meta_file(fname, fname_meta)
        create_wav_file(fname, fname_wav, config_dict.get('wavfrate', DEFAULT_WAVFRATE))
        rate, frames = get_rate_and_frames(fname_wav)
        total_seconds = frames / rate

        num_frames = seconds * rate
        results.append(
            (
                pf,
                [
                    {
                    "model": config_dict.get('model', DEFAULT_MODEL),
                    "wname": fname_wav,
                    "hname": f"{fname_root}_{fenum[0]}.html",
                    "sname": f"{fname_root}_{fenum[0]}.srt",
                    "nframes": num_frames,
                    "lconf": config_dict.get('lconf', DEFAULT_LCONF),
                    "mconf": config_dict.get('mconf', DEFAULT_MCONF),
                    "hconf": config_dict.get('hconf', DEFAULT_HCONF),
                    "overlap": config_dict.get('overlap', DEFAULT_OVERLAPTIME),
                    "fframe": fenum[1],
                    "rwavframes": config_dict.get('rwavframes', DEFAULT_RWAVFRAMES),
                    "audio_tags": config_dict.get('audio_tags', False),
                    "mp3file": os.path.basename(fname),
                    "min_offset": config_dict.get('min_offset', DEFAULT_MINOFFSET),
                    "max_gap": config_dict.get('max_gap', DEFAULT_MAXGAP)
                    } for fenum in enumerate(range(0, frames, num_frames))
                ]
            )
        )
        
    executor = config_dict.get('executor')
    if executor is None:
        with ProcessPoolExecutor(cpus) as executor:
            tasks = []
            for result in results:
                tasks.extend(result[1])
            for f, s, t in  executor.map(vosk_task_work, tasks):
               logging.info(f"{f} y {s} han tardado {t}")
    else:
        tasks = []
        for result in results:
            tasks.extend(result[1])
        for f, s, t in executor.map(vosk_task_work, tasks):
            logging.info(f"{f} y {s} han tardado {t}")
    
    for pf in config_dict['procfnames']:
        os.remove(pf['wav'])

    return results


def launch_whisper_tasks_core(config_dict):
    """
    Core function to launch Whisper transcription tasks using configuration dictionary.
    
    Args:
        config_dict: Dictionary containing all configuration parameters
        
    Returns:
        List of tuples containing (file_data, chunks) for processing results
    """
    results = []
    cpus = config_dict.get('cpus', max(os.cpu_count() - 2, 1))
    seconds = config_dict.get('seconds', DEFAULT_SECONDS)
    
    for pf in config_dict['procfnames']:
        fname_root = pf["root"]
        fname = pf["name"]
        fname_meta = pf["meta"]
        create_meta_file(fname, fname_meta)
        
        # Usar directorio temporal y work_id si están disponibles
        temp_dir = config_dict.get('temp_dir')
        work_id = config_dict.get('work_id')
        mp3files = split_podcast(pf, seconds, temp_dir, work_id)
        
        logging.debug(f"En launch_whisper_tasks_core: whtraining={config_dict.get('whtraining')}")
        speaker_mapping = get_speaker_mapping(config_dict.get('whtraining'))
        logging.debug(f"Mapeado de hablantes: {speaker_mapping}")

        results.append(
            (
                pf,
                [
                    {
                    "whmodel": config_dict.get('whmodel', DEFAULT_WHMODEL),
                    "whdevice": config_dict.get('whdevice', DEFAULT_WHDEVICE),
                    "whlanguage": config_dict.get('whlanguage', DEFAULT_WHLANGUAGE),
                    "hname": f"{fname_root}_{fenum[0]}.html",
                    "sname": f"{fname_root}_{fenum[0]}.srt",
                    "fname": fenum[1],
                    "cut": fenum[0],
                    "seconds": seconds,
                    "audio_tags": config_dict.get('audio_tags', False),
                    "mp3file": os.path.basename(fname),
                    "min_offset": config_dict.get('min_offset', DEFAULT_MINOFFSET),
                    "max_gap": config_dict.get('max_gap', DEFAULT_MAXGAP),
                    "whtraining": config_dict.get('whtraining'),
                    "whsusptime": float(config_dict.get('whsusptime', DEFAULT_WHSUSPTIME)),
                    "speaker_mapping": speaker_mapping,
                    "pyannote_method": config_dict.get('pyannote_method', 'ward'),
                    "pyannote_min_cluster_size": config_dict.get('pyannote_min_cluster_size', 15),
                    "pyannote_threshold": config_dict.get('pyannote_threshold', 0.7147),
                    "pyannote_min_speakers": config_dict.get('pyannote_min_speakers'),
                    "pyannote_max_speakers": config_dict.get('pyannote_max_speakers'),
                    "huggingface_token": config_dict.get('huggingface_token', ''),
                    "temp_dir": config_dict.get('temp_dir'),
                    } for fenum in enumerate(mp3files)
                ]
            )
        )
        
    logging.debug(f"Configuraciones: {results}")

    executor = config_dict.get('executor')
    if executor is None:
        with ProcessPoolExecutor(cpus) as executor:
            tasks = []
            for result in results:
                tasks.extend(result[1])
            for f, s, t in  executor.map(whisper_task_work, tasks):
                logging.info(f"{f} y {s} han tardado {t}")
    else:
        tasks = []
        for result in results:
            tasks.extend(result[1])
        for f, s, t in executor.map(whisper_task_work, tasks):
            logging.info(f"{f} y {s} han tardado {t}")

    return results


def transcribe_audio(config_dict):
    """
    High-level transcription function that orchestrates the full transcription process.
    
    Args:
        config_dict: Configuration dictionary with all transcription parameters
        
    Returns:
        dict: Results dictionary with transcribed files info and processing statistics
    """
    logcfg(__file__)
    stime = datetime.datetime.now()
    
    # Load environment configuration if specified
    conf_dir = config_dict.get('conf_dir')
    if conf_dir and os.path.exists(conf_dir):
        logging.info(f"Directorio de configuración: {conf_dir}")
        conf_files = glob.glob(os.path.join(conf_dir, "*.conf"))
        for conf_file in conf_files:
            logging.info(f"Cargando variables de entorno de {conf_file}")
            load_dotenv(conf_file)
    
    # Get HuggingFace token from environment if not provided
    if 'huggingface_token' not in config_dict:
        config_dict['huggingface_token'] = os.getenv("HUGGINGFACE_TOKEN", "")
    
    # Crear directorio temporal único para este trabajo si no se especifica
    if 'temp_dir' not in config_dict or config_dict['temp_dir'] is None:
        import tempfile
        work_id = str(uuid.uuid4())[:8]
        config_dict['work_id'] = work_id
        config_dict['temp_dir'] = os.path.join(tempfile.gettempdir(), f"sttcast_work_{work_id}")
        logging.info(f"Creando directorio temporal: {config_dict['temp_dir']}")
    else:
        work_id = config_dict.get('work_id', str(uuid.uuid4())[:8])
        config_dict['work_id'] = work_id
    
    # Process files
    procfnames_unsorted = []
    html_suffix = "" if config_dict.get('html_suffix', '') == "" else "_" + config_dict.get('html_suffix', '')
    
    # Get the absolute path for training file if specified
    if config_dict.get('whtraining') is not None:
        config_dict['whtraining'] = os.path.abspath(config_dict['whtraining'])
    
    for fname in config_dict['fnames']:
        if os.path.isdir(fname):
            # Add .mp3 files in dir
            logging.info(f"Tratando directorio {fname}")
            for root, dirs, files in os.walk(fname):
                for file in files:
                    if file.endswith(".mp3"):
                        full_path = os.path.join(root, file)
                        if full_path == config_dict.get('whtraining'):
                            logging.info(f"El fichero de entrenamiento {full_path} no se procesa")
                            continue
                        logging.info(f"Tratando fichero {full_path}")
                        fname_dict = create_fname_dict(full_path, html_suffix, 
                                                     config_dict.get('prefix', DEFAULT_PODCAST_PREFIX), 
                                                     config_dict.get('calendar', DEFAULT_PODCAST_CAL_FILE), 
                                                     config_dict.get('templates', DEFAULT_PODCAST_TEMPLATES),
                                                     config_dict.get('temp_dir'),
                                                     config_dict.get('work_id'))
                        procfnames_unsorted.append(fname_dict)
        else:
            # Add file
            if os.path.abspath(fname) == config_dict.get('whtraining'):
                logging.info(f"El fichero de entrenamiento {fname} no se procesa")
                continue
            logging.info(f"Tratando fichero {fname}")
            fname_dict = create_fname_dict(fname, html_suffix, 
                                         config_dict.get('prefix', DEFAULT_PODCAST_PREFIX), 
                                         config_dict.get('calendar', DEFAULT_PODCAST_CAL_FILE), 
                                         config_dict.get('templates', DEFAULT_PODCAST_TEMPLATES),
                                         config_dict.get('temp_dir'),
                                         config_dict.get('work_id'))
            procfnames_unsorted.append(fname_dict)

    logging.info(f"Se van a procesar {len(procfnames_unsorted)} ficheros con un total de {sum([pf['duration'] for pf in procfnames_unsorted])} segundos")
    
    # Sort files by size in descending order for optimization
    config_dict['procfnames'] = sorted(procfnames_unsorted,
                                      key = lambda f: f["duration"],
                                      reverse = True)
    logging.debug(f"Ficheros van a procesarse en orden: {[(pf['name'], get_mp3_duration(pf['name'])) for pf in config_dict['procfnames']]}")

    # Choose transcription engine and run
    whisper = config_dict.get('whisper', False)
    if whisper:
        results = launch_whisper_tasks_core(config_dict)
    else:
        results = launch_vosk_tasks_core(config_dict)
    
    # Build final output files
    output_files = []
    for result in results:
        build_html_file(result)
        build_srt_file(result)
        pf = result[0]
        output_files.append({
            'html': pf['html'],
            'srt': pf['srt'],
            'source': pf['name']
        })
    
    etime = datetime.datetime.now()
    duration = etime - stime
    
    # Limpiar directorio temporal si se creó automáticamente
    if config_dict.get('temp_dir') and config_dict.get('work_id'):
        temp_dir = config_dict['temp_dir']
        try:
            if os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir)
                logging.info(f"Directorio temporal limpiado: {temp_dir}")
        except Exception as e:
            logging.warning(f"Error limpiando directorio temporal {temp_dir}: {e}")
    
    logging.info(f"Transcripción completada en {duration}")
    
    return {
        'success': True,
        'duration': str(duration),
        'files_processed': len(procfnames_unsorted),
        'output_files': output_files,
        'engine': 'whisper' if whisper else 'vosk'
    }