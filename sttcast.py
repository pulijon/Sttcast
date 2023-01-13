from util import logcfg
import logging
from vosk import Model, KaldiRecognizer
import wave
import json
import datetime
import argparse
import os
import subprocess
import configparser
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import Value

# MODEL = "/usr/src/vosk-models/es/vosk-model-es-0.42"
MODEL = "/mnt/ram/es/vosk-model-es-0.42"
WAVFRATE = 16000
NREADFRAMES = 4000
SECONDS = 600
HCONF = 0.9
MCONF = 0.6
LCONF = 0.4
OVERLAPTIME = 1.5

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

def task_work(model_str, 
             fname_wav, 
             fname_html, 
             fframe, 
             nframes,
             conf):   
    logcfg(__file__)
    stime = datetime.datetime.now()
    with wave.open(fname_wav, "rb") as wf:
        model = Model(model_str)
        frate = wf.getframerate()
        rec = KaldiRecognizer(model, frate)
        offset = fframe / frate
        rec.SetWords(True)
        rec.SetPartialWords(True)
        # Se hace un cierto solapamiento entre el corte actual
        # y el siguiente para evitar perder audio
        nframes += OVERLAPTIME*frate

        wf.setpos(fframe)
        if os.path.exists(fname_html):
            os.remove(fname_html)
        with open(fname_html, "w") as html:
            while nframes > 0:
                data = wf.readframes(NREADFRAMES)
                nframes -= NREADFRAMES
                if len(data) == 0:
                    break
                if rec.AcceptWaveform(data):
                    res = json.loads(rec.Result())
                    if ("result" not in res) or \
                       (len(res["result"])) == 0:
                        continue
                    start_time = res["result"][0]["start"] + offset
                    end_time = res["result"][-1]["end"] + offset
                    logging.debug(f"{fname_html} - por procesar: {nframes/frate} segundos - text: {res.get('text','')}")
                    html.write("<p>\n")
                    html.write(f"{time_str(start_time, end_time)}")
                    for r in res["result"]:
                        w = r["word"]
                        c = r["conf"]
                        if c < conf["lconf"]:
                            html.write(class_str(w, "low"))
                        elif c < conf["mconf"]:
                            html.write(class_str(w, "medium"))
                        elif c < conf["hconf"]:
                            html.write(class_str(w, "high"))
                        else:
                            html.write(w)
                        html.write(" ")
                    html.write("</p>\n")
    return fname_html, datetime.datetime.now() - stime

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
        html.write(f'<h2 class="title"><br>{hmsg} </h1>\n')
        for hn in hnames:
            with open(hn, "r") as hnf:
                html.write(hnf.read())
        html.write(HTMLFOOTER)

def main():
    args = get_pars()
    model_str = args.model
    fname = args.fname
    cpus = args.cpus
    seconds = int(args.seconds)
    fname_root = os.path.splitext(fname)[0]
    fname_meta = fname_root + ".meta"
    fname_wav = fname_root + ".wav"
    fname_html = fname_root + ".html"
    conf = {
        "lconf": args.lconf,
        "mconf": args.mconf,
        "hconf": args.hconf
    }
    create_meta_file(fname, fname_meta)
    create_wav_file(fname, fname_wav)
    rate, frames = get_rate_and_frames(fname_wav)
    num_frames = seconds * rate
    r = range(0, frames, num_frames)
    wnames = [fname_wav for _ in r]
    hnames = [f"{fname_root}_{i}.html" for i in range(len(r))]
    nframes = [num_frames for _ in r]
    model_strs = [model_str for _ in r]
    confs = [conf for _ in r]
    
    with ProcessPoolExecutor(cpus) as executor:
        for f, t in  executor.map(task_work, model_strs, wnames, hnames, r, nframes, confs):
            logging.info(f"{f} ha tardado {t}")

    build_html_file(fname_html, fname_meta, hnames)
    

if __name__ == "__main__":
    logcfg(__file__)
    stime = datetime.datetime.now()
    main()
    etime = datetime.datetime.now()
    logging.info(f"Proceso ha durado {etime - stime} segundos")