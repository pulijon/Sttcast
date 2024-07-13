import datetime
from vosk import Model, KaldiRecognizer
import wave
from sttcasttask import SttcastTask
import logging
import os
from timeinterval import TimeInterval
import json
from util import logcfg
from sttcasttask import SttcastTaskSet
from timeinterval import TimeInterval, seconds_str
from copy import copy, deepcopy
from sttaux import write_transcription, add_result_to_transcription, sm_create, sm_notice, build_html_file, sm_cleanup

def vosk_task_work(pars):
    stt_model = pars["model"]
    wname = pars["fname"]["wav"]
    fframe = pars["fframe"]
    min_offset = pars["min_offset"]
    max_gap = pars["max_gap"]
    overlap = pars["overlap"]
    nframes = pars["nframes"]
    rwavframes = pars["rwavframes"]
    hname = pars["hname"]
      
    logcfg(__file__)
    stime = datetime.datetime.now()
    model = Model(stt_model)
    with wave.open(wname, "rb") as wf:
        model = Model(stt_model)
        frate = wf.getframerate()
        offset_seconds = fframe / frate
        rec = KaldiRecognizer(model, frate)
        fnumframes = wf.getnframes()
        rec.SetWords(True)
        rec.SetPartialWords(True)

        # Se hace un cierto solapamiento entre el corte actual
        # y el siguiente para evitar perder audio
        overlap_frames = overlap * frate
        # Las tramas a leer no pueden ser más que las que tiene el fichero
        left_frames = min(nframes + overlap_frames, fnumframes)

        # Se coloca el "puntero de lectura" del wav en la trama
        # correspondiente al presente frragmento
        wf.setpos(fframe)
    
        if os.path.exists(hname):
            os.remove(hname)

        logging.info(f"Comenzando fragmento con vosk {hname}")
        with open(hname, "w") as html:
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
                    last_accepted = True
                    res = json.loads(rec.Result())
                    if ("result" not in res) or \
                    (len(res["result"])) == 0:
                        continue
                    start_time = res["result"][0]["start"] + offset_seconds
                    end_time = res["result"][-1]["end"] + offset_seconds
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
                            write_transcription(pars, html, transcription, last_ti)
                        
                        last_ti = new_ti
                        logging.debug(f"Nuevo last_ti: {last_ti}")
                        transcription = ""

                    transcription = add_result_to_transcription(pars, transcription, res['result'])    
                    
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
                    new_ti = TimeInterval(start_time, end_time)
                    gap = new_ti.gap(last_ti)
                    offset = new_ti.offset(last_ti)
                    logging.debug(f"gap = {gap} - offset = {offset}")

                    if (last_ti != None) and (gap < max_gap) and (offset < min_offset) :
                        last_ti.extend(new_ti)
                        logging.debug(f"Alargando last_ti: {last_ti}")
                    else:
                        if last_ti != None:
                            write_transcription(pars, html, transcription, last_ti)
                        last_ti = new_ti
                        logging.debug(f"Nuevo last_ti: {last_ti}")
                        transcription = ""

                    add_result_to_transcription(pars, transcription, res["partial_result"])

            if last_ti is not None:
                write_transcription(pars, html, transcription, last_ti)
    sm_notice(hname, 1)
    # TBD - Wav file deletion
    logging.info(f"Terminado fragmento con vosk {hname}")
    return hname, datetime.datetime.now() - stime

class SttcastVoskTrans(SttcastTask):
    def __init__(self, pars):
        super().__init__(pars)
        
    def task_work(self):
        pass

class SttcastVoskMakeHtml(SttcastTask):
    def __init__(self, sttcast_set):
        self.sttcast_set = sttcast_set
    
    def task_work(self):
        self.sttcast_set.buid_html_file()

class SttcastVoskTaskSet(SttcastTaskSet):
    
    def __init__(self, pars):
        super().__init__(pars)
        self.create_wav_file()
        self.rate, self.frames = self.get_rate_and_frames()
        self.total_seconds = self.frames / self.rate 
        self.duration = datetime.timedelta(seconds=self.total_seconds)
        self.nframes = self.pars["seconds"] * self.rate


    def get_tasks(self):
  
        fname_root = self.pars["fname"]["root"]

        tasks = []
        self.hnames = []
        
        for fenum in enumerate(range(0, self.frames, self.nframes)):
            hname = f"{fname_root}_{fenum[0]}.html"
            sm_cleanup(hname)
            sm_create(hname)
            trans_task_pars = {**self.pars, 
                               "cut": fenum[0],
                               "fframe": fenum[1],
                               "hname": hname,
                               "nframes": self.nframes,
                              }
            self.hnames.append(hname)
            # tasks.append(SttcastVoskTrans(trans_task_pars))
            tasks.append({"data": trans_task_pars,
                          "func": vosk_task_work})
        # tasks.append(SttcastVoskMakeHtml(self))
        build_task_pars = {**self.pars, 
                           "hnames": self.hnames}
        tasks.append({"data": build_task_pars,
                      "func": build_html_file})
        return tasks



