import datetime
from sttcasttask import SttcastTask, SttcastTaskSet
import logging
import os
from timeinterval import TimeInterval, seconds_str
import whisper
from util import logcfg
from sttaux import sm_create, sm_notice, sm_cleanup, split_podcast,  write_transcription

def whisper_task_work(pars):
    logcfg(__file__)
    stime = datetime.datetime.now()

    
    whmodel = pars['whmodel']
    whdevice = pars['whdevice']
    whlanguage = pars['whlanguage']
    cname = pars['cname']
    min_offset = pars['min_offset']
    max_gap = pars['max_gap']
    cut = pars['cut']
    seconds = pars['seconds']
    offset_seconds = float(cut * seconds)
    hname = pars['hname']

    model = whisper.load_model(whmodel, device=whdevice)
    # Solución a error pytorch - ver https://github.com/openai/whisper/discussions/1068
    result = model.transcribe(cname, language=whlanguage, fp16=False)
    
    os.remove(cname)
    if os.path.exists(hname):
        os.remove(hname)

    logging.info(f"Comenzando fragmento con whisper {hname}")

    with open(hname, "w") as html:
        html.write("<!-- New segment -->\n")
        last_ti = None
        for s in result['segments']:
            start_time = float(s['start']) + offset_seconds
            end_time = float(s['end'])+ offset_seconds
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
            transcription += (f"{s['text']}")

        if last_ti is not None:
            write_transcription(pars, html, transcription, last_ti)
    sm_notice(hname,1)                            
    logging.info(f"Terminado fragmento con whisper {hname}")
    return hname, datetime.datetime.now() - stime


class SttcastWhisperTrans(SttcastTask):
    def __init__(self, pars):
        super().__init__(pars)
        
    def task_work(self):
        pass
    
class SttcastWhisperMakeHtml(SttcastTask):
    def __init__(self, sttcast_set):
        self.sttcast_set = sttcast_set
    
    def task_work(self):
        pass

class SttcastWhisperTaskSet(SttcastTaskSet):
    
    def get_tasks(self):
        
        fname_root = self.pars["fname"]["root"]

        tasks = []
        self.hnames = []

        fname = self.pars["fname"]
        seconds = self.pars["seconds"]
        self.mp3files =split_podcast(fname, seconds)

        tasks = []
        self.hnames = []
        
        for fenum in enumerate(self.mp3files):
            hname = f"{fname['root']}_{fenum[0]}.html"
            sm_cleanup(hname)
            sm_create(hname)           
            trans_task_pars = {**self.pars, 
                               "cut": fenum[0],
                               "cname": fenum[1],
                               "hname": hname,
                              }
            self.hnames.append(hname)
            # tasks.append(SttcastWhisperTrans(trans_task_pars))
            tasks.append({"data": trans_task_pars,
                "func": whisper_task_work})
        # tasks.append(SttcastVoskMakeHtml(self))
        build_task_pars = {**self.pars, 
                           "hnames": self.hnames}
        # tasks.append({"data": build_task_pars,
        #               "func": build_html_file})
        return tasks, build_task_pars

