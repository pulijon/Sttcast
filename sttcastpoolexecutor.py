from concurrent.futures import ProcessPoolExecutor
import logging
from sttcastvosktasks import SttcastVoskTaskSet
from sttcastwhispertasks import SttcastWhisperTaskSet
from sttaux import build_html_files

def task_work(task):
    return task["func"](task["data"])

class SttcastPoolExecutor(ProcessPoolExecutor):
    def __init__(self, cpus, par_list):
        super().__init__(max_workers=cpus)
        self.tasks = []
        build_task_pars_array = []
        for par in par_list:
            task_set_class = SttcastWhisperTaskSet if par["whisper"] else SttcastVoskTaskSet
            tset = task_set_class(par)
            new_tasks, new_build_pars = tset.get_tasks()
            self.tasks.extend(new_tasks)
            build_task_pars_array.append(new_build_pars)
        # Last, but not least, build html files
        self.tasks.append({"data": build_task_pars_array,
                           "func": build_html_files})


    # def task_work(self, task):
    #     return task["func"].task_work()
    
    def execute_tasks(self):
        with self as executor:
            for f, t in executor.map(task_work, self.tasks):
                logging.info(f"{f} ha tardado {t}")

