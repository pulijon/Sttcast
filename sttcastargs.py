class SttcastArgs:
    def __init__(self):
        self.fnames = []
        self.model = ""
        self.seconds = 600
        self.cpus = 1
        self.hconf = 0.95
        self.mconf = 0.70
        self.lconf = 0.50
        self.overlap = 5
        self.rwavframes = 4000
        self.whisper = False
        self.whmodel = "small"
        self.whdevice = "cuda"
        self.whlanguage = "es"
        self.html_suffix = ""
        self.min_offset = 60
        self.max_gap = 0.8
        self.audio_tags = False
