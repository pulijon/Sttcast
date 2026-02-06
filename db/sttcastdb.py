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
        # DEPRECATED: caché en memoria ya no se usa. Las estadísticas se obtienen directamente de cache_stats (tabla SQLite)
        # self._cache_speaker_episode_stats = {}
        
        # Asegurar que la vista intview existe solo si la BD ya existía
        # (Si se acaba de crear, ya debería tener la vista)
        if self.exist_file:
            self.ensure_intview_exists()

    def build_cache_speaker_episode_stats(self):
        """⚠️  DEPRECATED: Ya no se necesita.
        
        Con la tabla cache_stats optimizada, todas las consultas se hacen directamente contra SQL.
        Esta función quedó obsoleta y se mantiene solo para compatibilidad hacia atrás.
        
        No hace nada.
        """
        logging.warning("⚠️  build_cache_speaker_episode_stats() fue llamado pero está DEPRECATED. Ya no es necesario.")
        logging.info("💡 La caché de estadísticas ahora se gestiona automáticamente en cache_stats (tabla SQLite)")
        return

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
        
        # Crear tabla de caché de estadísticas para optimizar consultas de stats
        temp_cursor.execute("""
        CREATE TABLE IF NOT EXISTS cache_stats (
            tag TEXT NOT NULL,
            epname TEXT NOT NULL,
            epdate DATE NOT NULL,
            interventions_in_episode_by_speaker INTEGER DEFAULT 0,
            duration_in_episode_by_speaker REAL DEFAULT 0.0,
            total_interventions_in_episode INTEGER DEFAULT 0,
            total_duration_in_episode REAL DEFAULT 0.0,
            PRIMARY KEY (tag, epname)
        );
        """)
        temp_cursor.execute("CREATE INDEX IF NOT EXISTS idx_cache_stats_tag ON cache_stats(tag);")
        temp_cursor.execute("CREATE INDEX IF NOT EXISTS idx_cache_stats_epname ON cache_stats(epname);")
        temp_cursor.execute("CREATE INDEX IF NOT EXISTS idx_cache_stats_epdate ON cache_stats(epdate);")
        
        # Crear la vista intview que es necesaria para las consultas del context_server
        self.cursor.execute("""
        CREATE VIEW IF NOT EXISTS intview AS
        SELECT si.id,
            si.start,
            si.end,
            e.epname,
            e.epdate,
            st.tag,
            si.embedding,
            si.content
        FROM  speakerintervention AS si
        JOIN episode AS e on si.episodeid = e.id
        JOIN speakertag AS st on si.tagid = st.id;
        """)
        
        self.conn.commit()
        logging.info(f"Base de datos '{self.db_path}' creada con éxito, tablas y vistas definidas.")
    
    def ensure_intview_exists(self):
        """Asegura que la vista intview existe, creándola si es necesario.
        Este método es útil para bases de datos existentes que no tienen la vista."""
        try:
            # Verificar si la vista ya existe
            self.cursor.execute("SELECT name FROM sqlite_master WHERE type='view' AND name='intview';")
            if self.cursor.fetchone() is None:
                # La vista no existe, crearla
                logging.info("La vista 'intview' no existe, creándola...")
                self.cursor.execute("""
                CREATE VIEW intview AS
                SELECT si.id,
                    si.start,
                    si.end,
                    e.epname,
                    e.epdate,
                    st.tag,
                    si.embedding,
                    si.content
                FROM  speakerintervention AS si
                JOIN episode AS e on si.episodeid = e.id
                JOIN speakertag AS st on si.tagid = st.id;
                """)
                self.conn.commit()
                logging.info("Vista 'intview' creada exitosamente.")
            else:
                logging.info("La vista 'intview' ya existe.")
        except Exception as e:
            logging.error(f"Error al verificar/crear la vista 'intview': {e}")
            raise
    
    def ensure_cache_stats_exists(self):
        """Asegura que la tabla cache_stats existe, creándola si es necesario.
        Útil para BDs existentes sin la tabla."""
        try:
            # Verificar si la tabla ya existe
            self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cache_stats';")
            if self.cursor.fetchone() is None:
                logging.info("La tabla 'cache_stats' no existe, creándola...")
                self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS cache_stats (
                    tag TEXT NOT NULL,
                    epname TEXT NOT NULL,
                    epdate DATE NOT NULL,
                    interventions_in_episode_by_speaker INTEGER DEFAULT 0,
                    duration_in_episode_by_speaker REAL DEFAULT 0.0,
                    total_interventions_in_episode INTEGER DEFAULT 0,
                    total_duration_in_episode REAL DEFAULT 0.0,
                    PRIMARY KEY (tag, epname)
                );
                """)
                self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_cache_stats_tag ON cache_stats(tag);")
                self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_cache_stats_epname ON cache_stats(epname);")
                self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_cache_stats_epdate ON cache_stats(epdate);")
                self.conn.commit()
                logging.info("Tabla 'cache_stats' creada exitosamente.")
            else:
                logging.info("La tabla 'cache_stats' ya existe.")
        except Exception as e:
            logging.error(f"Error al verificar/crear la tabla 'cache_stats': {e}")
            raise
    
    def del_episode_data(self, epid):
        """Elimina todos los datos de un episodio dado su ID."""
        # Obtener el nombre del episodio para limpiar cache_stats
        self.cursor.execute("SELECT epname FROM episode WHERE id = ?", (epid,))
        ep_row = self.cursor.fetchone()
        if ep_row:
            epname = ep_row[0]
            # Limpiar de cache_stats
            self.cursor.execute("DELETE FROM cache_stats WHERE epname = ?", (epname,))
        
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
        
        # Actualizar cache_stats para este episodio
        self.update_cache_stats_for_episode(epname, epdatestr, episode_id)
        
        self.conn.commit()
        return episode_id
    
    def update_cache_stats_for_episode(self, epname: str, epdate: str, episode_id: int):
        """Actualiza las entradas de cache_stats para un episodio específico.
        Se ejecuta después de agregar intervenciones."""
        try:
            # Asegurar que la tabla existe
            self.ensure_cache_stats_exists()
            
            # Obtener todos los tags y sus estadísticas para este episodio
            query = """
            SELECT 
                st.tag,
                COUNT(*) as interventions_in_episode_by_speaker,
                SUM(si.end - si.start) as duration_in_episode_by_speaker
            FROM speakerintervention si
            JOIN speakertag st ON si.tagid = st.id
            WHERE si.episodeid = ?
            AND si.start IS NOT NULL 
            AND si.end IS NOT NULL
            GROUP BY st.tag
            """
            self.cursor.execute(query, (episode_id,))
            speaker_stats = self.cursor.fetchall()
            
            # Obtener totales del episodio
            total_query = """
            SELECT 
                COUNT(*) as total_interventions,
                SUM(si.end - si.start) as total_duration
            FROM speakerintervention si
            WHERE si.episodeid = ?
            AND si.start IS NOT NULL 
            AND si.end IS NOT NULL
            """
            self.cursor.execute(total_query, (episode_id,))
            total_row = self.cursor.fetchone()
            total_interventions = total_row[0] or 0
            total_duration = total_row[1] or 0.0
            
            # Insertar/actualizar en cache_stats
            for speaker_row in speaker_stats:
                tag = speaker_row[0]
                interventions = speaker_row[1] or 0
                duration = speaker_row[2] or 0.0
                
                self.cursor.execute("""
                INSERT INTO cache_stats 
                (tag, epname, epdate, interventions_in_episode_by_speaker, 
                 duration_in_episode_by_speaker, total_interventions_in_episode, 
                 total_duration_in_episode)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tag, epname) DO UPDATE SET
                    interventions_in_episode_by_speaker = excluded.interventions_in_episode_by_speaker,
                    duration_in_episode_by_speaker = excluded.duration_in_episode_by_speaker,
                    total_interventions_in_episode = excluded.total_interventions_in_episode,
                    total_duration_in_episode = excluded.total_duration_in_episode
                """, (tag, epname, epdate, interventions, duration, total_interventions, total_duration))
            
            logging.info(f"Cache stats actualizado para episodio '{epname}' con {len(speaker_stats)} speakers")
        except Exception as e:
            logging.error(f"Error actualizando cache_stats para episodio '{epname}': {e}")
            raise
    
    def rebuild_cache_stats_table(self):
        """Reconstruye completamente la tabla cache_stats desde los datos de speakerintervention.
        Útil para migrar BDs existentes sin la tabla."""
        try:
            self.ensure_cache_stats_exists()
            
            logging.info("🔄 Iniciando reconstrucción de tabla cache_stats...")
            
            # Limpiar tabla
            logging.info("📋 Limpiando tabla cache_stats...")
            self.cursor.execute("DELETE FROM cache_stats")
            logging.info("✅ Tabla cache_stats limpiada")
            
            # Query OPTIMIZADA: Una sola pasada con window functions
            logging.info("🔍 Ejecutando query principal para obtener datos de speakerintervention...")
            query = """
            INSERT INTO cache_stats 
            (tag, epname, epdate, interventions_in_episode_by_speaker, 
             duration_in_episode_by_speaker, total_interventions_in_episode, 
             total_duration_in_episode)
            SELECT DISTINCT
                st.tag,
                e.epname,
                e.epdate,
                COUNT(*) OVER (PARTITION BY st.tag, e.id) as interventions_in_episode_by_speaker,
                COALESCE(SUM(si.end - si.start) OVER (PARTITION BY st.tag, e.id), 0.0) as duration_in_episode_by_speaker,
                COUNT(*) OVER (PARTITION BY e.id) as total_interventions_in_episode,
                COALESCE(SUM(si.end - si.start) OVER (PARTITION BY e.id), 0.0) as total_duration_in_episode
            FROM speakerintervention si
            JOIN episode e ON si.episodeid = e.id
            JOIN speakertag st ON si.tagid = st.id
            WHERE si.start IS NOT NULL 
            AND si.end IS NOT NULL
            """
            
            self.cursor.execute(query)
            logging.info("✅ Query completada, insertando datos...")
            
            # Contar entradas insertadas
            self.cursor.execute("SELECT COUNT(*) FROM cache_stats")
            count = self.cursor.fetchone()[0]
            logging.info(f"📊 Se han insertado {count} entradas en cache_stats")
            
            logging.info("💾 Confirmando cambios (COMMIT)...")
            self.conn.commit()
            logging.info(f"✅ Tabla cache_stats reconstruida exitosamente con {count} entradas")
            return count
        except Exception as e:
            logging.error(f"❌ Error reconstruyendo cache_stats: {e}")
            logging.exception("Traceback completo:")
            raise
    
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
        
        # OPTIMIZED: Single query using window functions to avoid N+1 query problem
        # Previously had: initial query + loop calling additional query ~200 times for total_duration
        # Now: One query with SUM(...) OVER () window function to calculate everything at once
        stats_query = f"""
        SELECT
            COUNT(DISTINCT e.id) as total_episodes,
            SUM(SUM(si.end - si.start)) OVER () as total_duration,
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
        total_episodes = 0
        
        for row in results:
            speakers.append({
                'tag': row[2],
                'total_episodes': row[0],
                'total_duration': row[3] or 0
            })
            if total_duration == 0:  # Get total_duration and total_episodes from window function
                total_duration = row[1] or 0
                total_episodes = row[0] or 0
        
        return {
            'total_episodes': total_episodes,
            'total_duration': total_duration,
            'speakers': sorted(speakers, key=lambda x: x['total_duration'], reverse=True)
        }

    def _get_speaker_episode_stats(self, tag=None, fromdate=None, todate=None):
        """
        Devuelve estadísticas sobre un hablante en episodios entre dos fechas.
        OPTIMIZADO: Usa la tabla cache_stats en lugar de intview para máximo rendimiento.

        Args:
            tag (str): El tag del hablante.
            fromdate (str, optional): La fecha de inicio en formato 'YYYY-MM-DD'.
            todate (str, optional): La fecha de fin en formato 'YYYY-MM-DD'.

        Returns:
            dict: {
            'tag': str,
            'episodes': [{
                'name': str,
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
        logging.info(f"📊 Obteniendo estadísticas para tag='{tag}' desde cache_stats (optimizado)")
        
        # Query optimizada que usa cache_stats directamente
        query = "SELECT epname, epdate, interventions_in_episode_by_speaker, duration_in_episode_by_speaker, total_interventions_in_episode, total_duration_in_episode FROM cache_stats WHERE tag = ?"
        params = [tag]

        if fromdate:
            query += " AND epdate >= ?"
            params.append(fromdate)
        if todate:
            query += " AND epdate <= ?"
            params.append(todate)

        logging.info(f"🔍 Ejecutando query contra cache_stats...")
        self.cursor.execute(query, params)
        results = self.cursor.fetchall()
        logging.info(f"✅ Se obtuvieron {len(results)} registros de cache_stats para tag='{tag}'")

        # Construir episodes desde cache_stats
        episodes = []
        total_interventions = 0
        total_duration = 0.0

        for row in results:
            episode_data = {
                'name': row[0],           # epname
                'date': row[1],           # epdate (ya es un datetime.date)
                'duration': row[3] or 0.0,                           # duration_in_episode_by_speaker
                'interventions': row[2] or 0,                        # interventions_in_episode_by_speaker
                'total_episode_interventions': row[4] or 0,          # total_interventions_in_episode
                'total_episode_duration': row[5] or 0.0              # total_duration_in_episode
            }
            episodes.append(episode_data)
            total_interventions += episode_data['total_episode_interventions']
            total_duration += episode_data['total_episode_duration']

        total_episodes_in_period = len(episodes)
        
        logging.info(f"✅ Tag '{tag}': {total_episodes_in_period} episodios, {total_interventions} intervenciones totales, {total_duration:.2f}s duración")

        return {
            'tag': tag,
            'episodes': episodes,
            'total_interventions': total_interventions,
            'total_duration': total_duration,
            'total_episodes_in_period': total_episodes_in_period
        }

    def _filter_data(self, data, fromdate=None, todate=None):
        """Método heredado, ya no se usa. La filtración se hace en SQL ahora."""
        logging.warning("⚠️  _filter_data() fue llamado pero ya no se usa (filtración en SQL)")
        return data

    def get_speaker_episode_stats(self, tag, fromdate=None, todate=None):
        """Obtiene estadísticas de un hablante directamente desde cache_stats (sin caché en memoria)"""
        logging.info(f"📈 Obteniendo estadísticas para tag='{tag}' ({fromdate} a {todate})")
        
        # Usar directamente cache_stats sin pasar por la caché en memoria
        stat = self._get_speaker_episode_stats(tag, fromdate, todate)
        logging.info(f"✓ Tag '{tag}' procesado: {stat['total_episodes_in_period']} episodios, {stat['total_interventions']} intervenciones")
        return stat


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
