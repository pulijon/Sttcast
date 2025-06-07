import tkinter as tk
from tkinter import filedialog, scrolledtext
import os
from sttcastargs import SttcastArgs
from sttcast import start_stt_process
import logging
from tools.logs import logcfg, enable_logs
import whisper
import threading
import multiprocessing as mp
import threading

# Constants
MODEL = "/mnt/ram/es/vosk-model-es-0.42"
WHMODEL = "small"
WHDEVICE = "cuda"
WHLANGUAGE = "es"
SECONDS = 600
HCONF = 0.95
MCONF = 0.7
LCONF = 0.5
OVERLAPTIME = 2
RWAVFRAMES = 4000
MINOFFSET = 30
MAXGAP = 0.8
HTMLSUFFIX = ""

class LoggingHandler(logging.Handler):
    """
    This class handles logging messages and writes them to the Tkinter log_display widget.
    """

    def emit(self, record):
        msg = self.format(record)
        log_display.configure(state='normal')  # Make the text widget editable
        log_display.insert(tk.END, msg + '\n')  # Insert the log message
        log_display.configure(state='disabled')  # Make the text widget read-only
        log_display.yview(tk.END)  # Scroll to the end of the text widget

def start_transcription():
    
    args = SttcastArgs()
    
    # Collect values from GUI inputs and populate the class fields
    args.fnames = [entry_fnames.get()]  # For example, the audio file
    args.seconds = int(entry_seconds.get())
    args.cpus = int(entry_cpus.get())
    args.overlap = float(entry_overlap.get())
    args.rwavframes = int(entry_rwavframes.get())
    args.html_suffix = entry_html_suffix.get()
    args.min_offset = float(entry_min_offset.get())
    args.max_gap = float(entry_max_gap.get())
    is_whisper = radio_var.get() == "whisper"

    if is_whisper:  # Check if the whisper mode is selected
        args.whisper = True
        args.whmodel = whmodel_var.get()
        args.whdevice = whdevice_var.get()  # cuda or cpu
        args.whlanguage = entry_whlanguage.get()
        args.whtraining = entry_whtraining.get()
    else:
        args.whisper = False
        args.model = entry_model.get()
        args.hconf = float(scale_hconf.get())
        args.mconf = float(scale_mconf.get())
        args.lconf = float(scale_lconf.get())
    
    args.audio_tags = var_audio_tags.get() == 1
    
    # Now pass the args to your process as you did before
    start_stt_process(args)

from tkinter import filedialog

def select_files_and_directories():
    # Allow selection of directories
    directories = filedialog.askdirectory(title="Select Whole Directories", mustexist=True)
    
    # Allow selection of .mp3 files
    filenames = filedialog.askopenfilenames(title="Select additional MP3 Files", filetypes=[("MP3 Files", "*.mp3")])


    # Combine files and directories into a single list
    combined_list = list(filenames)  # Convert filenames (tuple) to list
    if directories:  # Only add if directory is selected
        combined_list.append(directories)
    
    # Insert the selected files and directories into the entry field
    entry_fnames.delete(0, tk.END)
    if combined_list:
        entry_fnames.insert(0, ", ".join(combined_list))

def select_training_file():
    selected_file = filedialog.askopenfilename(title="Select Training File", filetypes=[("MP3 Files", "*.mp3")])
    if selected_file:
        entry_whtraining.delete(0, tk.END)  # Clear the current content of the entry
        entry_whtraining.insert(0, selected_file)  # Insert the selected file into the entry


def select_vosk_model():
    selected_dir = filedialog.askdirectory()
    if selected_dir:
        entry_model.delete(0, tk.END)  # Clear the current content of the entry
        entry_model.insert(0, selected_dir)  # Insert the selected directory into the entry


def on_mode_change():
    """Enables or disables fields based on Vosk or Whisper mode."""
    if radio_var.get() == "vosk":
        whisper_frame.grid_forget()
        vosk_frame.grid(row=2, column=0, sticky=tk.W)
    else:
        vosk_frame.grid_forget()
        whisper_frame.grid(row=3, column=0, sticky=tk.W)


# logcfg(__file__)
enable_logs(False)

root = tk.Tk()
root.title("Sttcast GUI")

# General parameters group
general_frame = tk.LabelFrame(root, text="General Parameters", padx=10, pady=10)
general_frame.grid(row=0, column=0, padx=10, pady=10)

# Audio Files
tk.Label(general_frame, text="Audio Folders AND Files:").grid(row=0, column=0, sticky=tk.W)
entry_fnames = tk.Entry(general_frame, width=50)
entry_fnames.grid(row=0, column=1)
btn_browse = tk.Button(general_frame, text="Browse", command=select_files_and_directories)
btn_browse.grid(row=0, column=2)

# Seconds per task
tk.Label(general_frame, text="Seconds per Task:").grid(row=1, column=0, sticky=tk.W)
entry_seconds = tk.Entry(general_frame, width=50)
entry_seconds.grid(row=1, column=1)
entry_seconds.insert(0, SECONDS)

# CPUs
tk.Label(general_frame, text="CPUs:").grid(row=2, column=0, sticky=tk.W)
entry_cpus = tk.Entry(general_frame, width=50)
entry_cpus.grid(row=2, column=1)
entry_cpus.insert(0, max(os.cpu_count() - 2, 1))

# Overlap time
tk.Label(general_frame, text="Overlap Time:").grid(row=3, column=0, sticky=tk.W)
entry_overlap = tk.Entry(general_frame, width=50)
entry_overlap.grid(row=3, column=1)
entry_overlap.insert(0, OVERLAPTIME)

# RWAV Frames
tk.Label(general_frame, text="RWAV Frames:").grid(row=4, column=0, sticky=tk.W)
entry_rwavframes = tk.Entry(general_frame, width=50)
entry_rwavframes.grid(row=4, column=1)
entry_rwavframes.insert(0, RWAVFRAMES)

# HTML suffix
tk.Label(general_frame, text="HTML Suffix:").grid(row=5, column=0, sticky=tk.W)
entry_html_suffix = tk.Entry(general_frame, width=50)
entry_html_suffix.grid(row=5, column=1)
entry_html_suffix.insert(0, HTMLSUFFIX)

# Min offset
tk.Label(general_frame, text="Min Offset:").grid(row=6, column=0, sticky=tk.W)
entry_min_offset = tk.Entry(general_frame, width=50)
entry_min_offset.grid(row=6, column=1)
entry_min_offset.insert(0, MINOFFSET)

# Max gap
tk.Label(general_frame, text="Max Gap:").grid(row=7, column=0, sticky=tk.W)
entry_max_gap = tk.Entry(general_frame, width=50)
entry_max_gap.grid(row=7, column=1)
entry_max_gap.insert(0, MAXGAP)

# Whisper / Vosk toggle
radio_var = tk.StringVar(value="vosk")
mode_frame = tk.LabelFrame(root, text="Transcription engine", padx=10, pady=10)
mode_frame.grid(row=1, column=0, padx=10, pady=10)

radio_vosk = tk.Radiobutton(mode_frame, text="Vosk", variable=radio_var, value="vosk", command=on_mode_change)
radio_vosk.grid(row=0, column=0)
radio_whisper = tk.Radiobutton(mode_frame, text="Whisper", variable=radio_var, value="whisper", command=on_mode_change)
radio_whisper.grid(row=0, column=1)

# Vosk parameters group
vosk_frame = tk.LabelFrame(root, text="Vosk Parameters", padx=10, pady=10)
vosk_frame.grid(row=2, column=0, padx=10, pady=10)

# Model
tk.Label(vosk_frame, text="Model:").grid(row=0, column=0, sticky=tk.W)
entry_model = tk.Entry(vosk_frame, width=50)
entry_model.grid(row=0, column=1)
entry_model.insert(0, MODEL)
browse_model_button = tk.Button(vosk_frame, text="Browse", command=select_vosk_model)
browse_model_button.grid(row=0, column=2, padx=10, pady=10)

def update_conf_label(label, value):
    label.config(text=f"{float(value):.2f}")

# High confidence threshold
SCALE_LENGTH = 400
tk.Label(vosk_frame, text="High Confidence Threshold:").grid(row=1, column=0, sticky=tk.W)
scale_hconf = tk.Scale(vosk_frame, 
                       from_=0, to=1, resolution=0.01,
                       orient=tk.HORIZONTAL,
                       length=SCALE_LENGTH,
                       command=  lambda v: update_conf_label(label_hconf, v)
                       )
scale_hconf.grid(row=1, column=1)
scale_hconf.set(HCONF)
label_hconf = tk.Label(vosk_frame, text=HCONF, font=("Helvetica", 12))
label_hconf.grid(row=1, column=2)

# Medium confidence threshold
tk.Label(vosk_frame, text="Medium Confidence Threshold:").grid(row=2, column=0, sticky=tk.W)
scale_mconf = tk.Scale(vosk_frame, 
                       from_=0, to=1, resolution=0.01,
                       orient=tk.HORIZONTAL,
                       length=SCALE_LENGTH,
                       command=lambda v: update_conf_label(label_mconf, v)
                       )                      
scale_mconf.grid(row=2, column=1)
scale_mconf.set(MCONF)
label_mconf = tk.Label(vosk_frame, text=MCONF, font=("Helvetica", 12))
label_mconf.grid(row=2, column=2)

# Low confidence threshold
tk.Label(vosk_frame, text="Low Confidence Threshold:").grid(row=3, column=0, sticky=tk.W)
scale_lconf = tk.Scale(vosk_frame, 
                       from_=0, to=1, resolution=0.01,
                       orient=tk.HORIZONTAL,
                       length=SCALE_LENGTH,
                       command=lambda v: update_conf_label(label_lconf, v)
                       )
scale_lconf.grid(row=3, column=1)
scale_lconf.set(LCONF)
label_lconf = tk.Label(vosk_frame, text=LCONF, font=("Helvetica", 12))
label_lconf.grid(row=3, column=2)

# Whisper parameters group
whisper_frame = tk.LabelFrame(root, text="Whisper Parameters", padx=10, pady=10)
whisper_frame.grid(row=3, column=0, padx=10, pady=10)

# Whisper model
whisper_models = whisper.available_models()
whmodel_var = tk.StringVar(value=WHMODEL)
tk.Label(whisper_frame, text="Whisper Model:").grid(row=0, column=0, sticky=tk.W)
option_whmodel = tk.OptionMenu(whisper_frame, whmodel_var, *whisper_models)
option_whmodel.grid(row=0, column=1)

# Whisper device
whisper_devices = ["cuda", "cpu"]
whdevice_var = tk.StringVar(value=WHDEVICE)
tk.Label(whisper_frame, text="Whisper Device:").grid(row=1, column=0, sticky=tk.W)
option_whdevice = tk.OptionMenu(whisper_frame, whdevice_var, *whisper_devices)
option_whdevice.grid(row=1, column=1)

# Whisper language
tk.Label(whisper_frame, text="Whisper Language:").grid(row=2, column=0, sticky=tk.W)
entry_whlanguage = tk.Entry(whisper_frame, width=50)
entry_whlanguage.grid(row=2, column=1)
entry_whlanguage.insert(0, WHLANGUAGE)

# Whisper trainig file
tk.Label(whisper_frame, text="Whisper Training File:").grid(row=3, column=0, sticky=tk.W)
entry_whtraining = tk.Entry(whisper_frame, width=50)
entry_whtraining.grid(row=3, column=1)
btn_browse_whtraining = tk.Button(whisper_frame, text="Browse", command=select_training_file)
btn_browse_whtraining.grid(row=3, column=2)

# Audio tags
var_audio_tags = tk.IntVar()
chk_audio_tags = tk.Checkbutton(root, text="Include Audio Tags", variable=var_audio_tags)
chk_audio_tags.grid(row=4, column=0)

def start_process():
    # Disable the button and update the status
    btn_start.config(state=tk.DISABLED)
    status_label.config(text="Processing...", fg="red")
    log_display.grid_forget()
    root.update()  # Force UI to update before starting the thread
    
    # threading.Thread(target=run_transcription_process).start()
    start_transcription()
    
    btn_start.config(state=tk.NORMAL)
    status_label.config(text="Process completed", fg="green")
    log_display.grid()

# Whisper parameters group
start_frame = tk.LabelFrame(root, text="Process", padx=10, pady=10)
start_frame.grid(row=5, column=0, padx=10, pady=10)

btn_start = tk.Button(start_frame, text="Start Transcription", command=start_process)
btn_start.grid(row=5, column=0, sticky=tk.E)
status_label = tk.Label(start_frame, text="Idle", fg="green")
status_label.grid(row= 5, column=1, sticky=tk.W)

# Log space
# Create the Text widget to display log messages
log_display = scrolledtext.ScrolledText(root, width=80, height=10, state='disabled')
log_display.grid(row=6, column=0, padx=10, pady=10)

log_display.grid_forget()

# Initialize the mode (enable/disable fields based on the selected mode)
on_mode_change()

root.mainloop()
