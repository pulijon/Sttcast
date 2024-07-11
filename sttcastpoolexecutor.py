from concurrent.futures import ProcessPoolExecutor
import logging

class SttcastPoolExecutor(ProcessPoolExecutor):
    def __init__(self, cpus):
        super().__init__(max_workers=cpus)
        self.cpus = cpus
        self.tasks = []

    def add_task(self, task):
        self.tasks.append(task)

    def task_work(self, task):
        return task.task_work()
    
    def get_tasks(self):
        return self.tasks

    def execute_tasks(self):
        with self as executor:
            for f, t in executor.map(self.task_work, self.tasks):
                logging.info(f"{f} ha tardado {t}")

