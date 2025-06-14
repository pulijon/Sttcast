import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
import logging
from datetime import datetime

INTERESTING_YEARS = 3
COMMON_WDAY_FREQUENCY = 0.5

def calculate_most_common_weekday(int_df):
    """Calcula el día de la semana más común en un DataFrame"""
    most_common_weekday = int_df['weekday'].mode()[0]
    weekday_counts = int_df['weekday'].value_counts()
    if weekday_counts[most_common_weekday] > COMMON_WDAY_FREQUENCY * len(int_df):
        logging.debug(f"El día de la semana más frecuente es {most_common_weekday} con {weekday_counts[most_common_weekday]} episodios.")
        logging.debug(f"La frecuencia de la moda es {weekday_counts[most_common_weekday] / len(int_df) * 100:.2f}% de los episodios.")
        return most_common_weekday
    else:
        logging.debug("No hay un día de la semana suficientemente frecuente para ser considerado como moda.")
        return None


class DateEstimation:
    def __init__(self, cal_file):
        # Si el fichero no existe, se informa en el log y
        # se pone a None el DataFrame
        if not cal_file or not isinstance(cal_file, str) or not cal_file.strip():
            logging.error("El fichero de calendario no es válido.")
            self.df = None
            return
        try:
            self.df = pd.read_csv(cal_file, parse_dates=["date"], index_col="episode")
        except FileNotFoundError:
            logging.error(f"El fichero de calendario {cal_file} no existe.")
            self.df = None
            return
        except pd.errors.EmptyDataError:
            logging.error(f"El fichero de calendario {cal_file} está vacío.")
            self.df = None
            return
        except pd.errors.ParserError:
            logging.error(f"Error al parsear el fichero de calendario {cal_file}.")
            self.df = None
            return
        except Exception as e:
            logging.error(f"Error al cargar el fichero de calendario {cal_file}: {e}")
            self.df = None
            return
        self.df = pd.read_csv(cal_file, parse_dates=["date"], index_col="episode" )
        self.df['month'] = self.df['date'].dt.month
        self.df['weekday'] = self.df['date'].dt.dayofweek
        self.df['day'] = self.df['date'].dt.day
        self.df['ep_ordinal'] = self.df['date'].apply(lambda x: x.toordinal())


    def estimate_date_from_epnumber(self, ep_number):
        # Si no existe el DataFrame, se informa en el log y se devuelve 
        # la fecha actual
        if self.df is None:
            logging.warning("No hay calendario disponible para estimar la fecha.")
            logging.warning("Se devuelve la fecha actual.")
            return datetime.now()
        if ep_number in self.df.index:
            return self.df.loc[ep_number, 'date']
        
        # Se calcula en función de los INTERESTING_YEARS anteriore
        self.df = self.df[self.df.index <= ep_number].copy()
        self.df = self.df[self.df['date'] >= self.df['date'].max() - pd.DateOffset(years=INTERESTING_YEARS)]
        
        self.most_common_weekday = self.calculate_most_common_weekday()
        self.period = self.calculate_period()
        self.inactive_months = self.calculate_inactive_months()
        return self.predict_date(ep_number)
    
    def calculate_most_common_weekday(self):
        """Calcula el día de la semana más común en un DataFrame"""
        most_common_weekday = self.df['weekday'].mode()[0]
        weekday_counts = self.df['weekday'].value_counts()
        if weekday_counts[most_common_weekday] > COMMON_WDAY_FREQUENCY * len(self.df):
            logging.debug(f"El día de la semana más frecuente es {most_common_weekday} con {weekday_counts[most_common_weekday]} episodios.")
            logging.debug(f"La frecuencia de la moda es {weekday_counts[most_common_weekday] / len(self.df) * 100:.2f}% de los episodios.")
            return most_common_weekday
        else:
            logging.debug("No hay un día de la semana suficientemente frecuente para ser considerado como moda.")
            return None
    
    def calculate_period(self):
        """Calcula el periodo de emisión de los episodios"""
        diffs = self.df['ep_ordinal'].diff() / self.df.index.to_series().diff()
        diffs_mode = diffs.value_counts().idxmax()
        diffs_mode_freq = diffs.value_counts()[diffs_mode]/ len(diffs)
        logging.debug(f"El periodo de tiempo más frecuente entre episodios es {diffs_mode} días, con una frecuencia de {diffs_mode_freq * 100:.2f}%.")
        if diffs_mode_freq > 0.8:
            period = diffs_mode
        else:
            period = diffs.mean()
        return period
    
    def calculate_inactive_months(self):
        """Calcula los meses sin episodios"""
        month_counts = self.df['month'].value_counts(normalize=True)
        return month_counts[month_counts < 0.05]
    
    def predict_date(self, ep_number):
        """Predice la fecha de emisión de un episodio dado su número"""
        
        # Cálculo de la fecha teórica del último episodio
        last_episode = self.df.loc[self.df.index.max()]
        # Calculamos el valor absoluto entre el día de la semana del último episodio y el día de la semana más frecuente
        diff_weekday = self.most_common_weekday - last_episode['weekday']
        last_theoretical_date = last_episode['date'] + pd.DateOffset(days=diff_weekday)
        
        ld = last_theoretical_date
        for i in range(self.df.index.max() + 1, ep_number + 1):
            ld += pd.DateOffset(days=self.period)
            if (self.inactive_months is not None) and (ld.month in self.inactive_months.index):
                logging.debug(f"Mes inactivo: {ld.month} - Episodio {i} no se añadirá.")
                continue
        if self.most_common_weekday is not None:
            offset = self.most_common_weekday - ld.weekday()
            ld += pd.DateOffset(days=offset)
        logging.info(f"Próximo episodio teórico: {ld} (Día de la semana: {self.most_common_weekday})") 
        return ld

if __name__ == "__main__":
    from tools.logs import logcfg
    from tools.envvars import load_env_vars_from_directory
    import os
    
    load_env_vars_from_directory(os.path.join(os.path.dirname(__file__), ".env"))
    import os
    podcast_cal_file = os.getenv("PODCAST_CAL_FILE", "data/episodes.csv")
    
    logcfg(__file__)
    de = DateEstimation(podcast_cal_file)
    for i in range(500, 600):
        logging.info(f"Episodio {i}: {de.esimate_date_from_epnumber(i)}")
        
        
