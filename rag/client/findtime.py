from bs4 import BeautifulSoup
import os
import logging

def find_nearest_time_id(html_path, target_seconds):
    """Busca el id 'time-HH-MM-SS' más cercano anterior a target_seconds en un HTML."""
    logging.debug(f"Buscando el id más cercano a {target_seconds} segundos en {html_path}")
    if not os.path.exists(html_path):
        return None
    with open(html_path, encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")
    time_spans = soup.find_all("span", class_="time")
    if not time_spans:
        logging.warning(f"No se encontraron spans de tiempo en {html_path}")
        return None
    logging.debug(f"Se encontraron {len(time_spans)} spans de tiempo en {html_path}")
    best_id = None
    best_secs = -1
    for span in time_spans:
        sid = span.get("id", "")
        try:
            hh, mm, ss = map(int, sid.replace("time-", "").split("-"))
            secs = hh*3600 + mm*60 + ss
            if secs <= target_seconds and secs > best_secs:
                best_secs = secs
                best_id = sid
        except Exception:
            logging.error(f"Error al procesar el id {sid} en {html_path}: {str(Exception)}")
            continue
    return best_id
