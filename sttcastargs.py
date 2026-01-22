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
        # Parámetros de Pyannote para diarización
        self.pyannote_method = "ward"
        self.pyannote_min_cluster_size = 15
        self.pyannote_threshold = 0.7147
        self.pyannote_min_speakers = None
        self.pyannote_max_speakers = None
