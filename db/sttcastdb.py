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
    def __init__(self, db_path: str, create_if_not_exists=False):
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
        self.conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys = ON;')
        self.cursor = self.conn.cursor()
    
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
        self.cursor.execute("""
        CREATE view intview AS
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

        for epi in epints:
            self.cursor.execute("SELECT id FROM speakertag WHERE tag = ?", (epi['tag'],))
            row = self.cursor.fetchone()
            if row is None:
                self.cursor.execute("INSERT INTO speakertag (tag) VALUES (?)", (epi['tag'],))
                tag_id = self.cursor.lastrowid
            else:
                tag_id = row[0]
            self.cursor.execute(
                "INSERT INTO speakerintervention (tagid, episodeid, start, end, content) VALUES (?, ?, ?, ?, ?)",
                (tag_id, episode_id, epi.get('start', None), epi.get('end', None), epi.get('content', None))
            )
        self.conn.commit()
        return episode_id
    
    def update_embedding(self, intervention_id, embedding, prompt_tokens=0, total_tokens=0):
        query = """
        UPDATE speakerintervention
        SET embedding = ?, prompt_tokens = ?, total_tokens = ?
        WHERE id = ?
        """
        params = (embedding, prompt_tokens, total_tokens, intervention_id)
        self.cursor.execute(query, params)
        
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
