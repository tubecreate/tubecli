# ⚡ TubeCLI — Sistema CLI de Agentes de IA de Código Abierto

<p align="center">
  <a href="../README.md">English</a> | 
  <a href="README_zh-CN.md">简体中文</a> | 
  <a href="README_zh-TW.md">繁體中文</a> | 
  <a href="README_ja.md">日本語</a> | 
  <a href="README_ko.md">한국어</a> | 
  <b>Español</b> | 
  <a href="README_tr.md">Türkçe</a> | 
  <a href="README_ru.md">Русский</a> | 
  <a href="README_vi.md">Tiếng Việt</a>
</p>

<p align="center">
    <a href="https://github.com/tubecreate/tubecli">
        <img src="https://img.shields.io/github/stars/tubecreate/tubecli?style=for-the-badge&color=2a2a2a&labelColor=1a1a1a" alt="Stars" />
    </a>
    <a href="https://github.com/tubecreate/tubecli">
        <img src="https://img.shields.io/github/forks/tubecreate/tubecli?style=for-the-badge&color=1e7b85&labelColor=236f78" alt="Forks" />
    </a>
    <a href="https://github.com/tubecreate/tubecli/blob/main/LICENSE">
        <img src="https://img.shields.io/badge/LICENSE-MIT-00897b?style=for-the-badge&labelColor=333333" alt="License" />
    </a>
</p>

<p align="center">
    <img src="https://img.shields.io/badge/PYTHON-3.9+-0078d4?style=for-the-badge&logo=python&logoColor=white&labelColor=333333" alt="Python" />
    <img src="https://img.shields.io/badge/API-FASTAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white&labelColor=333333" alt="FastAPI" />
    <img src="https://img.shields.io/badge/UI-VUE.JS-4FC08D?style=for-the-badge&logo=vue.js&logoColor=white&labelColor=333333" alt="Vue.js" />
    <img src="https://img.shields.io/badge/3D-THREE.JS-000000?style=for-the-badge&logo=three.js&logoColor=white&labelColor=333333" alt="Three.js" />
</p>

<p align="center">
    <img src="https://img.shields.io/badge/AGENTS-BROWSER-ffd700?style=for-the-badge&labelColor=1a1a1a" alt="Agents Browser" />
    <img src="https://img.shields.io/badge/AGENTS-WORKFLOW-ff0055?style=for-the-badge&labelColor=1a1a1a" alt="Agents Workflow" />
    <img src="https://img.shields.io/badge/AGENTS-STUDIO_WORLD-00ffcc?style=for-the-badge&labelColor=1a1a1a" alt="Agents Studio World" />
</p>

Un sistema CLI sin interfaz (headless) para instalar, gestionar y orquestar **agentes de IA**, **habilidades (skills)** y **flujos de trabajo (workflows)**. Diseñado para que los agentes de IA puedan comprender, instalar y operar todo el sistema de forma autónoma.

![3D Studio Office Builder](screenshots/studio3d_builder.png)
<br>
![3D Studio Agent Teams](screenshots/studio3d_teams.png)

## 🌟 Características Clave

El sistema ha evolucionado hacia una arquitectura completa de 10 subsistemas:

- 🤖 **Agent Manager** — Crea y gestiona agentes de IA con personalidades (personas), rutinas y habilidades.
- ⚡ **Skill System** — Flujos de trabajo ejecutables marcados con etiquetas (Workflow, API, Markdown) con un visor de Markdown y un modal de ejecución en tiempo real.
- 🔄 **Workflow Engine & Builder** — Ejecutor de flujos de trabajo basado en DAG. La interfaz WebUI presenta un constructor moderno basado en nodos con nodos compactos, paneles de propiedades deslizantes contextuales y selección dinámica de modelos (Ollama local / API en la nube).
- 🎨 **Web Dashboard** — SPA (Single Page Application) integral en `localhost:5295/dashboard` para gestionar visualmente agentes, flujos de trabajo, habilidades, mercado, configuraciones y monitorear navegadores de forma nativa.
- 👥 **Teams Agents** — Orquesta múltiples agentes utilizando organigramas. Asigna roles mediante plantillas lógicas o arrastrar y soltar. La delegación de tareas enruta el trabajo a través del equipo basado en estrategias secuenciales, paralelas o jerárquicas.
- 🏢 **3D Studio (Teams 3D)** — Visualización 3D procedimental isométrica utilizando Three.js. Soporta mobiliario de múltiples asientos (mesas de reunión, mesas de conferencias) con algoritmos inteligentes orientados hacia adentro, manipulación de grupos por raycasting y más de 15 recursos integrados.
- 🎬 **Story Engine & Player** — Genera historias en 3D interactivas a partir de prompts a través de nuestro Editor de Guiones. Los agentes se comunican a través de burbujas de diálogo en 3D dentro de un reproductor de escenas animadas.
- 🔌 **Extension Manager** — Arquitectura modular compatible con `browser`, `webui`, `market` y `studio3d`. Permite la recarga en caliente de comandos CLI y rutas de API.
- 🌐 **Browser Automation** — Orquesta perfiles de navegador, proxies y huellas digitales. Inicio de sesión automático integrado para Google con TOTP 2FA.
- 🛒 **Marketplace** — Descubre, instala y comparte habilidades de la comunidad a través de un registro en línea.

## 🚀 Inicio Rápido e Instalación

### Opción 1: Instalación Automática en un Clic (Recomendado para Usuarios)
**Para Windows:** Abra **PowerShell** (Ejecutar como Administrador) y pegue el siguiente comando:
```powershell
powershell -c "irm https://raw.githubusercontent.com/tubecreate/tubecli/main/install/install_es.ps1 | iex"
```

**Para Linux / MacOS:** Abra su terminal y ejecute:
```bash
curl -fsSL https://raw.githubusercontent.com/tubecreate/tubecli/main/install/install_es.sh | bash
```

Instalará automáticamente Python, Git (si falta), clonará el repositorio y configurará todo de la A a la Z.

### Opción 2: Instalación Manual (Para Desarrolladores)

#### Prerrequisitos
- Python 3.9+
- Ollama (Opcional, requerido para la ejecución de IA local)
- Git

#### 1. Clonar e Instalar
```bash
git clone https://github.com/tubecreate/tubecli.git
cd tubecli
pip install -e .
```

### 2. Inicializar el Espacio de Trabajo
Ejecute el comando de inicialización para configurar el directorio `data/`, extraer las habilidades predeterminadas, activar las extensiones principales y configurar el puerto predeterminado.
```bash
tubecli init --lang es --port 5295
```

### 3. Iniciar el Panel Web (Web Dashboard)
Después de la inicialización, inicie el servidor API para acceder a la GUI.
```bash
tubecli api start
```
Abra su navegador y navegue a: **http://localhost:5295/dashboard**

## 💻 Uso de la CLI

Gestione todo el sistema directamente desde la terminal si prefiere un enfoque sin interfaz (headless):

### Gestión de Agentes (Agent Management)
```bash
tubecli agent create "My Assistant" --description "General purpose AI agent"
tubecli agent list
tubecli agent show <id>
tubecli agent delete <id>
```

### Ejecución de Habilidades (Skill Execution)
```bash
tubecli skill list
tubecli skill run "AI Summarizer" --input "Long text content..."
```

### API y Flujos de Trabajo
```bash
tubecli api start --port 5295
tubecli api stop
tubecli workflow run <path_to_workflow.json>
```

### Extensiones y Mercado
```bash
tubecli extension list
tubecli extension enable webui
tubecli market search "seo"
tubecli market install "seo-analyzer"
```

## 🧠 Descripción General de la Arquitectura

```
tubecli/
├── tubecli/           # Paquete principal
│   ├── api/           # Servidor API REST (FastAPI)
│   ├── cli/           # Módulos de comandos CLI
│   ├── core/          # Lógica de negocio principal
│   ├── extensions/    # Extensiones (Browser, WebUI, Market, Studio3D)
│   ├── nodes/         # Implementaciones de nodos de flujo de trabajo
│   └── skills/        # Habilidades integradas del sistema
├── .agents/           # Documentación legible por IA (SKILL.md)
├── data/              # Estado y Base de Datos en tiempo de ejecución (gitignored)
└── tests/             # Suite de pruebas
```

## 📖 Documentación Legible por IA
Las carpetas `.agents/` y skills contienen documentación diseñada explícitamente para LLMs (`SKILL.md`). Los agentes de IA externos (como Claude o GPT-4) pueden leer estos archivos para aprender a operar el sistema TubeCLI, escribir complementos y depurar flujos de trabajo de forma completamente autónoma sin intervención humana.

## 📝 Licencia
Licencia MIT - Hecho con 🤖 por el Equipo de TubeCreate
