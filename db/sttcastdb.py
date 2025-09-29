import logging
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__),"..", "tools")))
from logs import logcfg
import sqlite3
import argparse
import os
import logging
import sqlite3
import os
from datetime import datetime

class SttcastDB:
    def __init__(self, db_path: str, create_if_not_exists=False, wal=True, timeout=60.0):
        logging.info(f"Inicializando SttcastDB con db_path='{db_path}', create_if_not_exists={create_if_not_exists}")
        self.db_path = db_path
        self.conn = None
        self.exist_file = os.path.exists(self.db_path)
        if not self.exist_file:
            if create_if_not_exists:
                self.create_db()
                self.exist_file = os.path.exists(self.db_path)
                if not self.exist_file:
                    raise FileNotFoundError(f"El fichero {self.db_path} no se ha podido crear")
            else:
                raise FileNotFoundError(f"El fichero {self.db_path} no existe")
        
        self.conn = sqlite3.connect(self.db_path,
                                    timeout=timeout,
                                    check_same_thread=False,
                                    detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys = ON;')
        
        if wal:
            self.conn.execute('PRAGMA journal_mode = WAL;')
            logging.info("Modo WAL activado para la base de datos")
            self.conn.execute('PRAGMA synchronous = NORMAL;')
            self.conn.execute('PRAGMA temp_store = MEMORY;')
            self.conn.execute('PRAGMA busy_timeout = 30000;')  # 30 segundos
            self.conn.execute('PRAGMA cache_size = -64000;')  # Tamaño del caché en páginas (ajustable)
        self.cursor = self.conn.cursor()
        self._cache_speaker_episode_stats = {}

    def build_cache_speaker_episode_stats(self):
        """Construye una caché de estadísticas de episodios por hablante para optimizar consultas repetidas."""
        tags = self.get_tags()
        nspeakers = len(tags)
        logging.info(f"Construyendo caché de estadísticas para {nspeakers} intervinientes")
        counter = 0
        for tag in tags:
            counter += 1
            logging.info(f"--- Procesando tag {counter}/{nspeakers} ---")
            self._cache_speaker_episode_stats[tag] = self._get_speaker_episode_stats(tag)

    def is_connected(self):
        """Comprueba si la conexión a la base de datos está activa."""
        return self.conn is not None
    
    def get_db_path(self):
        if not self.exist_file:
            raise FileNotFoundError(f"El fichero {self.db_path} no existe")
        return self.db_path

    def close(self):
        if self.conn:
            self.conn.close()

    def create_db(self):
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute('PRAGMA foreign_keys = ON;')
        self.cursor = self.conn.cursor()

        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS episode (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            epname VARCHAR(25) NOT NULL,
            epdate DATE NOT NULL
        );
        """)
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS speakertag (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tag VARCHAR(100) NOT NULL
        );
        """)
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS audiofile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fname VARCHAR(256) NOT NULL,
            episodeid INTEGER NOT NULL,
            FOREIGN KEY (episodeid) REFERENCES episode(id)
        );
        """)
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS speakerintervention (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tagid INTEGER NOT NULL,
            episodeid INTEGER NOT NULL,
            start REAL,
            end REAL,
            content TEXT,
            embedding BLOB,
            prompt_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            FOREIGN KEY (tagid) REFERENCES speakertag(id),
            FOREIGN KEY (episodeid) REFERENCES episode(id)
        );
        """)
        self.conn.commit()
        logging.info(f"Base de datos '{self.db_path}' creada con éxito y tablas definidas.")
    
    def del_episode_data(self, epid):
        """Elimina todos los datos de un episodio dado su ID."""
        self.cursor.execute("DELETE FROM speakerintervention WHERE episodeid = ?", (epid,))
        self.cursor.execute("DELETE FROM audiofile WHERE episodeid = ?", (epid,))
        self.cursor.execute("DELETE FROM episode WHERE id = ?", (epid,))
        self.conn.commit()
        logging.info(f"Datos del episodio con ID {epid} eliminados correctamente.")

    def add_episode(self, epname: str, epdate: datetime, epfile: str, epints: list):
        self.cursor.execute("SELECT id FROM episode WHERE epname = ?", (epname,))
        if self.cursor.fetchone() is not None:
            logging.warning(f"El episodio '{epname}' ya existe en la base de datos.")
            return None
        epdatestr = epdate.strftime("%Y-%m-%d")
        self.cursor.execute("INSERT INTO episode (epname, epdate) VALUES (?, ?)", (epname, epdatestr))
        episode_id = self.cursor.lastrowid

        self.cursor.execute("INSERT INTO audiofile (fname, episodeid) VALUES (?, ?)", (epfile, episode_id))
        invalid_cache_speakers = set()

        for epi in epints:
            self.cursor.execute("SELECT id FROM speakertag WHERE tag = ?", (epi['tag'],))
            row = self.cursor.fetchone()
            if row is None:
                self.cursor.execute("INSERT INTO speakertag (tag) VALUES (?)", (epi['tag'],))
                tag_id = self.cursor.lastrowid
            else:
                tag_id = row[0]
            invalid_cache_speakers.add(epi['tag'])
            self.cursor.execute(
                "INSERT INTO speakerintervention (tagid, episodeid, start, end, content) VALUES (?, ?, ?, ?, ?)",
                (tag_id, episode_id, epi.get('start', None), epi.get('end', None), epi.get('content', None))
            )
        # for tag in invalid_cache_speakers:
        #     self._cache_speaker_episode_stats[tag] = self._get_speaker_episode_stats(tag=tag)
        self.conn.commit()
        return episode_id
    
    def get_tags(self):
        logging.info("Obteniendo lista de tags de hablantes desde la base de datos")
        query = "SELECT DISTINCT tag FROM speakertag"
        self.cursor.execute(query)
        return [row[0] for row in self.cursor.fetchall()]

    def update_embedding(self, intervention_id, embedding, prompt_tokens=0, total_tokens=0):
        query = """
        UPDATE speakerintervention
        SET embedding = ?, prompt_tokens = ?, total_tokens = ?
        WHERE id = ?
        """
        params = (embedding, prompt_tokens, total_tokens, intervention_id)
        self.cursor.execute(query, params)
        self.conn.commit()
        
    def commit(self):
        self.conn.commit()
    
    def get_ints(self, 
                fromdate=None, 
                todate=None, 
                tag=None, 
                with_embeddings=None,
                epname=None,
                ids=None):
        query = "SELECT * FROM intview as iv WHERE 1=1"
        params = []
        if with_embeddings is not None:
            query += " AND iv.embedding IS "
            query += "NOT NULL" if with_embeddings else "NULL"
        if fromdate:
            query += " AND iv.epdate >= ?"
            params.append(fromdate)
        if todate:
            query += " AND iv.epdate <= ?"
            params.append(todate)
        if tag:
            query += " AND iv.tag = ?"
            params.append(tag)
        if epname:
            query += " AND iv.epname = ?"
            params.append(epname)
        if ids:
            placeholders = ",".join("?" for _ in ids)
            query += f" AND iv.id IN ({placeholders})"
            params.extend(ids)

        self.cursor.execute(query, params)
        return self.cursor.fetchall()
    
    def get_pending_ints(self, fromdate=None, todate=None, tag=None):
        return  self.get_ints(fromdate, todate, tag, with_embedding=False)
    
    def get_embedded_ints(self, fromdate=None, todate=None, tag=None):
        return self.get_ints(fromdate, todate, tag, with_embeddings=True)

    # Métodos de utilidad (opcional)
    def list_episodes(self):
        self.cursor.execute("SELECT id, epname, epdate FROM episode")
        return self.cursor.fetchall()

    def get_episode_id(self, epname: str):
        """Obtiene el ID de un episodio dado su nombre."""
        self.cursor.execute("SELECT id FROM episode WHERE epname = ?", (epname,))
        row = self.cursor.fetchone()
        if row:
            return row[0]
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        
    def get_general_stats(self, fromdate=None, todate=None):
        """
        Devuelve estadísticas de episodios entre dos fechas.
        
        Returns:
            dict: {
                'total_episodes': int,
                'total_duration': float,
                'speakers': [{'tag': str, 'total_duration': float}, ...]
            }
        """
        logging.info(f"Calculando estadísticas generales entre {fromdate} y {todate}")
        # Base query for filtering by date
        date_filter = "WHERE 1=1"
        params = []
        
        if fromdate:
            date_filter += " AND e.epdate >= ?"
            params.append(fromdate)
        if todate:
            date_filter += " AND e.epdate <= ?"
            params.append(todate)
        
        # Get total episodes
        episodes_query = f"SELECT COUNT(DISTINCT e.id) FROM episode e {date_filter}"
        self.cursor.execute(episodes_query, params)
        total_episodes = self.cursor.fetchone()[0]
        
        # Get total duration and speakers info
        stats_query = f"""
        SELECT
            COUNT(DISTINCT e.id) as total_episodes,
            SUM(si.end - si.start) as total_duration,
            st.tag,
            SUM(si.end - si.start) as speaker_duration
        FROM speakerintervention si
        JOIN episode e ON si.episodeid = e.id
        JOIN speakertag st ON si.tagid = st.id
        {date_filter}
        AND si.start IS NOT NULL 
        AND si.end IS NOT NULL
        GROUP BY st.tag
        """
        
        self.cursor.execute(stats_query, params)
        results = self.cursor.fetchall()
        
        speakers = []
        total_duration = 0
        
        for row in results:
            speakers.append({
                'tag': row[2],
                'total_episodes': row[0],
                'total_duration': row[3] or 0
            })
            if row[0] and total_duration == 0:  # Get total duration once
                # Calculate total duration separately to avoid duplication
                total_query = f"""
                SELECT SUM(si.end - si.start)
                FROM speakerintervention si
                JOIN episode e ON si.episodeid = e.id
                {date_filter}
                AND si.start IS NOT NULL 
                AND si.end IS NOT NULL
                """
                self.cursor.execute(total_query, params)
                total_duration = self.cursor.fetchone()[0] or 0
        
        return {
            'total_episodes': total_episodes,
            'total_duration': total_duration,
            'speakers': sorted(speakers, key=lambda x: x['total_duration'], reverse=True)
        }

    def _get_speaker_episode_stats(self, tag=None, fromdate=None, todate=None):
        """
        Devuelve estadísticas sobre un hablante en episodios entre dos fechas.

        Args:
            tag (str): El tag del hablante.
            fromdate (str, optional): La fecha de inicio en formato 'YYYY-MM-DD'.
            todate (str, optional): La fecha de fin en formato 'YYYY-MM-DD'.

        Returns:
            dict: {
            'tag': str,
            'episodes': [{
                'id': int,
                'date': str,
                'duration': float,
                'interventions': int,
                'total_episode_interventions': int,
                'total_episode_duration': float
            }],
            'total_interventions': int,
            'total_duration': float,
            'total_episodes_in_period': int
            }
        """
        # Se va a utilizar un cursor local para evitar problemas en entornos multihilo
        cursor = self.conn.cursor()
        
        logging.info(f"Calculando estadísticas para el tag '{tag}' entre {fromdate} y {todate}")
        # Base query for filtering by date
        query = "SELECT tag,epname,epdate,start,end FROM intview WHERE tag = ?"
        params = [tag]

        if fromdate:
            query += " AND epdate >= ?"
            params.append(fromdate)
        if todate:
            query += " AND epdate <= ?"
            params.append(todate)

        query += " AND start IS NOT NULL AND end IS NOT NULL"

        cursor.execute(query, params)
        results = cursor.fetchall()

        # Group by episode
        episodes_dict = {}
        episode_ids = set()
        logging.info(f"Resultados para el tag '{tag}': {len(results)} intervenciones encontradas")
        # logging.info(f"Resultados detallados: {[dict(row) for row in results]}")
        for row in results:
            episode_name = row['epname']
            duration = (row['end'] - row['start']) if row['start'] and row['end'] else 0

            if episode_name not in episodes_dict:
                episodes_dict[episode_name] = {
                    'name': episode_name,
                    'date': row['epdate'],
                    'duration': 0,
                    'interventions': 0
                }

            episodes_dict[episode_name]['duration'] += duration
            episodes_dict[episode_name]['interventions'] += 1

        # Get total interventions and duration for each episode
        total_interventions = 0
        total_duration = 0

        for episode_name in episodes_dict:
            # Get all interventions for this episode
            episode_query = """
            SELECT COUNT(*) as total_interventions, 
                   SUM(end - start) as total_duration
            FROM intview 
            WHERE epname = ? 
            AND start IS NOT NULL 
            AND end IS NOT NULL
            """
            if fromdate:
                episode_query += " AND epdate >= ?"
                episode_params = [episode_name, fromdate]
            else:
                episode_params = [episode_name]
            if todate:
                episode_query += " AND epdate <= ?"
                episode_params.append(todate)
            
            cursor.execute(episode_query, episode_params)
            episode_stats = cursor.fetchone()

            episodes_dict[episode_name]['total_episode_interventions'] = episode_stats[0] or 0
            episodes_dict[episode_name]['total_episode_duration'] = episode_stats[1] or 0

            total_interventions += episodes_dict[episode_name]['total_episode_interventions']
            total_duration += episodes_dict[episode_name]['total_episode_duration']
            # total_episode_duration += episodes_dict[episode_name]['total_episode_duration']

        # Get total episodes in the period
        total_episodes_query = "SELECT COUNT(DISTINCT id) FROM episode WHERE 1=1"
        total_episodes_params = []
        
        if fromdate:
            total_episodes_query += " AND epdate >= ?"
            total_episodes_params.append(fromdate)
        if todate:
            total_episodes_query += " AND epdate <= ?"
            total_episodes_params.append(todate)
            
        cursor.execute(total_episodes_query, total_episodes_params)
        total_episodes_in_period = cursor.fetchone()[0] or 0
        
        # Se cierra el cursor local
        cursor.close()

        episodes = list(episodes_dict.values())

        return {
            'tag': tag,
            'episodes': episodes,
            'total_interventions': total_interventions,
            'total_duration': total_duration,
            # 'total_episode_interventions': total_episode_interventions,
            # 'total_episode_duration': total_episode_duration,
            'total_episodes_in_period': total_episodes_in_period
        }

    def _filter_data(self, data, fromdate=None, todate=None):
        if not fromdate and not todate:
            return data
        
        # Pasar las fechas a objetos datetime para comparaciones precisas
        if fromdate:
            fromdate = datetime.strptime(fromdate, "%Y-%m-%d").date()
        if todate:
            todate = datetime.strptime(todate, "%Y-%m-%d").date()
        
        filtered_episodes = list(filter(
            lambda ep: (not fromdate or ep['date'] >= fromdate) and (not todate or ep['date'] <= todate),
            data['episodes']
        ))
        
        total_episodes_in_period = len(filtered_episodes)
        total_interventions = sum(ep['total_episode_interventions'] for ep in filtered_episodes)
        total_duration = sum(ep['total_episode_duration'] for ep in filtered_episodes)
        
        return {
            'tag': data['tag'],
            'episodes': filtered_episodes,  # ¿Quizás también quieras incluir esto?
            'total_episodes_in_period': total_episodes_in_period,
            'total_interventions': total_interventions,
            'total_duration': total_duration
        }

    def get_speaker_episode_stats(self, tag, fromdate=None, todate=None):
        # Primero, intenta obtener las estadísticas de la caché
        logging.info(f"Obteniendo estadísticas para el tag '{tag}' entre {fromdate} y {todate}")
        if self._cache_speaker_episode_stats is None or tag not in self._cache_speaker_episode_stats:
            logging.info(f"El tag '{tag}' no está en la caché de estadísticas")
            self._cache_speaker_episode_stats[tag] = self._get_speaker_episode_stats(tag)
        logging.info(f"Obteniendo estadísticas para el tag '{tag}' desde la caché")
        speaker_data = self._cache_speaker_episode_stats[tag]
        # Ahora hay que quitar los episodios que no estén en el rango de fechas
        return self._filter_data(speaker_data, fromdate, todate)


    # Función que obtiene una lista de estadísticas de una lista de hablantes entre dos fechas
    # utilizando la función get_speaker_episode_stats. De esa forma, no hay que abrir y cerrar
    # la base de datos varias veces.
    def get_speakers_stats(self, tags, fromdate=None, todate=None):
        logging.info(f"=== INICIO: Obteniendo estadísticas para {len(tags)} hablantes entre {fromdate} y {todate}")
        stats = []
        
        for i, tag in enumerate(tags):
            logging.info(f"--- Procesando tag {i+1}/{len(tags)}: '{tag}' ---")
            try:
                stat = self.get_speaker_episode_stats(tag, fromdate, todate)
                stats.append(stat)
                logging.info(f"✓ Tag '{tag}' procesado exitosamente. Stats length: {len(stats)}")
            except Exception as e:
                logging.error(f"✗ ERROR procesando tag '{tag}': {type(e).__name__}: {e}")
                logging.exception("Traceback completo:")
                raise  # Esto detendrá el bucle y mostrará el error completo
        
        logging.info(f"=== FIN: Procesados {len(stats)} tags exitosamente ===")
        return stats


if __name__ == "__main__":
    
    def get_pars():
        parser = argparse.ArgumentParser()
        parser.add_argument("dbname", type=str, 
                            help=f"Nombre de la base de datos")
        parser.add_argument("-c", "--create", action="store_true",
                            help="Crear la base de datos si no existe")
        return parser.parse_args()

    def main():
        args = get_pars()
        logging.info(f"{args}")
        db = SttcastDB(args.dbname, create_if_not_exists=args.create)
    
        if not db.get_db_path():
            logging.error(f"El fichero {args.dbname} no existe")
            return 1
        lep = db.list_episodes()
        if not lep:
            logging.info("No hay episodios en la base de datos")
            return 0
        logging.info(f"Lista de primeros 10 episodios en la base de datos {args.dbname}:")
        for ep in lep[:10]:
            logging.info(f"  {dict(ep)})")
        logging.info(f"Total de episodios: {len(lep)}")
        fromdate = None
        todate = None
        ints = db.get_pending_ints(fromdate=fromdate, todate=todate)
        if not ints:
            logging.info("No hay intervenciones en la base de datos")
            return 0
        logging.info(f"Lista de primeras 10 intervenciones entre {fromdate} y {todate} en la base de datos {args.dbname}:")
        for i in ints[:10]:
            logging.info(f"  {i['epdate']}: [{i['tag']} - {i['start']} - {i['end']}] ({i['content'][:40]}...)")
        logging.info(f"Total de intervenciones: {len(ints)}")
        db.close()
        logging.info(f"Base de datos {args.dbname} procesada correctamente")
        return 0

    logcfg(__file__)
    stime = datetime.now()
    result = main()
    etime = datetime.now()
    logging.info(f"Ejecución del programa ha tardado {etime - stime}")
    exit(result)
