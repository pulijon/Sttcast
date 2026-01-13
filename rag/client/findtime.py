from bs4 import BeautifulSoup
import os
import logging
import requests

def find_nearest_time_id(html_path, target_seconds):
    """Busca el id 'time-HH-MM-SS' más cercano anterior a target_seconds en un HTML.
    Acepta tanto rutas locales como URLs.
    """
    logging.debug(f"Buscando el id más cercano a {target_seconds} segundos en {html_path}")
    
    html_content = None
    
    # Si es una URL (comienza con http:// o https://)
    if html_path.startswith(('http://', 'https://')):
        try:
            response = requests.get(html_path, timeout=10)
            if response.status_code == 200:
                html_content = response.text
                logging.debug(f"HTML descargado desde URL: {html_path}")
            else:
                logging.warning(f"Error al descargar URL {html_path}: {response.status_code}")
                return None
        except requests.exceptions.Timeout:
            logging.error(f"Timeout descargando {html_path}")
            return None
        except Exception as e:
            logging.error(f"Error descargando URL {html_path}: {e}")
            return None
    # Si es una ruta local
    elif os.path.exists(html_path):
        try:
            with open(html_path, encoding="utf-8") as f:
                html_content = f.read()
            logging.debug(f"HTML cargado desde filesystem: {html_path}")
        except Exception as e:
            logging.error(f"Error al leer archivo local {html_path}: {e}")
            return None
    else:
        logging.warning(f"No se encontró archivo o URL: {html_path}")
        return None
    
    # Procesar el HTML
    if not html_content:
        return None
    
    soup = BeautifulSoup(html_content, "html.parser")
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
