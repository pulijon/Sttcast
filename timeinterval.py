from tools.logs import logcfg
import logging
from datetime import timedelta

def seconds_str(seconds, with_dec=True):
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if with_dec:
        return f"{hours:02.0f}:{minutes:02.0f}:{seconds:05.02f}"
    else:
        return f"{hours:02.0f}:{minutes:02.0f}:{seconds:02.0f}"

class TimeInterval():
    def __init__(self, start, end):
        self.start = start
        self.end = end
    
    def extend(self, ti):
        self.end = ti.end
    
    def gap(self, ti):
        if ti is None:
            return self.start
        else:
            return self.start - ti.end
    
    def offset(self, ti):
        if ti is None:
            return self.start
        else:
            return self.start - ti.start
    
    def __repr__(self):
        return f"[{seconds_str(self.start)} - {seconds_str(self.end)}]"

if __name__ == "__main__":
    logcfg(__file__)
    logging.info(f"seconds_str(7854.21) = {seconds_str(7854.21)}")
    logging.info(f"seconds_str(7854.21, with_dec=False) = {seconds_str(7854.21, with_dec=False)}")

    t1 = TimeInterval(0.25, 1.33)
    logging.info(f"t1 = {t1}")
    t2 = TimeInterval(1.35, 2.08)
    gap = t2.gap(t1)
    offset = t2.offset(t1)
    logging.info(f"t2.gap(t1) = {gap:.2f} . t2.offse(t1) == {offset:.2f}")