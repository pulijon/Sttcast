import os
from pathlib import Path
import ffmpeg
import subprocess
import glob
from timeinterval import TimeInterval, seconds_str
import configparser
import wave

HTMLHEADER = """<html>

<head>
  <style>
    .medium {
        color: orange;
    }
    .low {
        color: red;
    }
    .high {
        color: green;
    }
    .time {
        color: blue;
    }
    .title {
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
WAVFRATE = 16000


class SttcastTask:
    def __init__(self, pars):
        self.pars = pars
       
    @staticmethod
    def class_str(st, cl):
        return f'<span class="{cl}">{st}</span>'
    
    def audio_tag_str(self, seconds):
        return f'<audio controls src="{self.pars["fname"]}#t={seconds_str(seconds, with_dec=False)}"></audio><br>\n'

    def write_transcription(self, html, transcription, ti):
        html.write("\n<p>\n")
        html.write(f'{self.class_str(ti, "time")}<br>\n')
        if self.pars["audio_tag"]:
            html.write(self.audio_tag_str(ti.start))
        html.write(transcription)
        html.write("\n</p>\n")

    def add_result_to_transcription(self, transcription, result):
        lconf = self.pars["lconf"]
        mconf = self.pars["mconf"]
        hconf = self.pars["hconf"]
        for r in result:
            w = r["word"]   
            c = r["conf"]
            if c < lconf:
                transcription += self.class_str(w, "low")
            elif c < mconf:
                transcription += self.class_str(w, "medium")
            elif c < hconf:
                transcription += self.class_str(w, "high")
            else:
                transcription += w
            transcription += " "
        return transcription



class SttcastTaskSet:
    def __init__(self, pars):
        self.pars = pars
        self.create_meta_file()

    def create_meta_file(self):
        fname = self.pars["fname"]["name"]
        fname_meta = self.pars["fname"]["meta"]

        if (os.path.exists(fname_meta)):
              os.remove(fname_meta)

        ffmpeg.input(fname).output(fname_meta, f='ffmetadata').run()

    def create_wav_file(self):
        fname = self.pars["fname"]["name"]
        
        fname_wav = self.pars["fname"]["wav"]

        if (os.path.exists(fname_wav)):
              os.remove(fname_wav)

        ffmpeg.input(fname).output(fname_wav, ac=1, c='pcm_s16le', ar=WAVFRATE).run()
    
    def get_rate_and_frames(self):
        with wave.open(self.pars["fname"]["wav"], "rb") as wf:
            return wf.getframerate(), wf.getnframes()

