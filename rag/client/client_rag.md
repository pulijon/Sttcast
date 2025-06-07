# Cliente RAG

Por supuesto, te voy a crear la aplicación en Python usando Flask con una interfaz web moderna. Esto te dará más control sobre el backend y será más fácil de integrar con tu servicio web.

Ahora voy a crear el template HTML con la interfaz moderna:

Ahora voy a crear el archivo de requisitos para Python:

Y finalmente, un archivo de configuración de ejemplo:

¡Perfecto! He convertido la aplicación a Python usando Flask. Aquí tienes una aplicación completa con las siguientes características:

## 🐍 **Aplicación Python Flask**

### **Estructura del proyecto:**

```
tu_proyecto/
├── app.py                 # Aplicación Flask principal
├── templates/
│   └── index.html        # Template HTML con interfaz moderna
├── requirements.txt      # Dependencias Python
└── .env.example         # Variables de entorno de ejemplo
```

### **Características principales:**

**🚀 Backend Flask:**

- API REST endpoint `/api/ask` para procesar preguntas
- Manejo robusto de errores y timeouts
- Integración con tu función `get_mark()`
- Validación de datos de entrada
- Endpoint de salud `/health` para monitoreo

**🎨 Frontend moderno:**

- Interfaz idéntica a la versión React pero en HTML/CSS/JS vanilla
- Totalmente responsive (PC y móvil)
- Animaciones suaves y efectos visuales
- Estados de carga con indicadores

**⚙️ Configuración flexible:**

- Variables de entorno para toda la configuración
- Timeout configurable para el servicio web
- URLs base configurables

### **Instalación y uso:**

1. **Instalar dependencias:**

```bash
pip install -r requirements.txt
```

1. **Configurar variables de entorno:**

```bash
cp .env.example .env
# Editar .env con tus valores
```

1. **Ejecutar la aplicación:**

```bash
python app.py
```

### **Funcionalidades implementadas:**

✅ **Formulario de preguntas** con selector de idioma
✅ **Estados de carga** durante los ~10 segundos de espera
✅ **Limpieza automática** de respuestas anteriores
✅ **Visualización de respuestas** en paneles separados
✅ **Referencias clickeables** que abren en nueva ventana
✅ **Integración con tu función** `get_mark()`
✅ **Manejo robusto de errores** y timeouts
✅ **API REST** para fácil integración

### **Personalización:**

- **Función `get_mark()`**: Implementa tu lógica específica en la línea 13 de `app.py`
- **URLs y timeouts**: Configura en el archivo `.env`
- **Estilos**: Modifica el CSS en `templates/index.html`

La aplicación está lista para funcionar con tu servicio web que debe responder en formato JSON con los campos `txt` y `refs` como especificaste. ¿Te gustaría que ajuste algún aspecto específico?