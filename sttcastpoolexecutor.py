from concurrent.futures import ProcessPoolExecutor
import logging
from sttcastvosktasks import SttcastVoskTaskSet
from sttcastwhispertasks import SttcastWhisperTaskSet

def task_work(task):
    return task["func"](task["data"])

class SttcastPoolExecutor(ProcessPoolExecutor):
    def __init__(self, cpus, par_list):
        super().__init__(max_workers=cpus)
        self.tasks = []
        for par in par_list:
            task_set_class = SttcastWhisperTaskSet if par["whisper"] else SttcastVoskTaskSet
            tset = task_set_class(par)
            self.tasks.extend(tset.get_tasks())

    # def task_work(self, task):
    #     return task["func"].task_work()
    
    def execute_tasks(self):
        with self as executor:
            for f, t in executor.map(task_work, self.tasks):
                logging.info(f"{f} ha tardado {t}")

