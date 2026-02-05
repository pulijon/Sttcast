# Work to be done

## Nombres y fechas en html de episodios
Actualmente los ficheros html no incluyen los nombres ni las fechas de los episodios.
El nombre del episodio puede ser deducido del nombre del fichero mp3 y del prefijo.

El prefijo del episodio, por defecto, será lo que hay a la izquierda del primer número
del nombre del fichero mp3.
Si existe una variable de entorno, se tomará este valor.
Si se utiliza la opción --prefix, esta opción tendrá prioridad

La fecha del episodio puede ser obtenida del módulo dateestimation.py que ofrece una
clase que se inicia con el nombre de un calendario.
El calendario por defecto será "calfile.csv". Si existe una variable de entorno,
sobreescribirá este valor. Existirá una opción en la línea de comando con la máxima
prioridad.

## Utilización de Jinja2 y BeautifulSoup para la edición de ficheros
Ahora se utiliza escritura directa sobre el fichero html. Los estilos se definen
en una constante. Esto no es muy mantenible, además de que podemos querer tener
distintos estilos para distintas colecciones de transcripciones.

Se utilizarán plantillas Jinja2 para el html y para la hoja de estilos. 
Se cargará la plantilla parseada y se utilizará Beauitiful Soup para ir añadiendo elementos.
Esto permitirá también embellecer (prettify) el resultado