# ⚡ TubeCLI — Открытая CLI-система агентов ИИ

<p align="center">
  <a href="../README.md">English</a> | 
  <a href="README_zh-CN.md">简体中文</a> | 
  <a href="README_zh-TW.md">繁體中文</a> | 
  <a href="README_ja.md">日本語</a> | 
  <a href="README_ko.md">한국어</a> | 
  <a href="README_es.md">Español</a> | 
  <a href="README_tr.md">Türkçe</a> | 
  <b>Русский</b> | 
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

Консольная (headless) CLI-система для установки, управления и оркестровки **агентов ИИ**, **навыков (skills)** и **процессов (workflows)**. Разработана таким образом, чтобы агенты ИИ могли самостоятельно понимать, устанавливать и эксплуатировать всю систему.

![3D Studio Office Builder](screenshots/studio3d_builder.png)
<br>
![3D Studio Agent Teams](screenshots/studio3d_teams.png)

## 🌟 Ключевые особенности

Система развилась в полноценную архитектуру из 12 подсистем:

- 💬 **Chat** — единый интерфейс общения для всей системы. Многосессионные диалоги с постоянной историей, выбор агента (или автоматическая маршрутизация к нужному специалисту) и отрисовка Markdown. Каждый ход проходит через полный конвейер — классификацию намерений без затрат токенов, выбор навыка, а затем модель, — поэтому всё, что умеет Telegram-бот, доступно и в браузере.
- 📋 **Codex** — центр управления агентской работой. Вы или ИИ создаёте задачу, делегируете её агенту или команде, утверждаете её, и фоновый обработчик выполняет её, пока вы следите за хронологией шагов. Результаты возвращаются вам на проверку. Задачи сохраняются и переживают перезапуск, а по каждой из них ведётся полный журнал аудита.
- 🤖 **Agent Manager** — создание и управление агентами ИИ с персонажами, рутинами и навыками.
- ⚡ **Skill System** — исполняемые процессы, помеченные тегами (Workflow, API, Markdown), с просмотрщиком Markdown и модальным окном выполнения в реальном времени.
- 🔄 **Workflow Engine & Builder** — движок выполнения процессов на основе DAG. WebUI содержит современный конструктор на основе узлов с компактными узлами, контекстными скользящими панелями свойств и динамическим выбором моделей (локальный Ollama / облачный API).
- 🎨 **Web Dashboard** — комплексное SPA-приложение на `localhost:5295/dashboard` для визуального управления агентами, процессами, навыками, маркетплейсом, настройками и нативного мониторинга браузеров.
- 👥 **Teams Agents** — оркестровка нескольких агентов с использованием организационных диаграмм. Назначение ролей с помощью логических шаблонов или перетаскивания. Делегирование задач распределяет работу в команде на основе последовательных, параллельных или иерархических стратегий.
- 🏢 **3D Studio (Teams 3D)** — изометрическая процедурная 3D-визуализация с использованием Three.js. Поддерживает многоместную мебель (столы для совещаний, конференц-столы) с интеллектуальными алгоритмами ориентации внутрь, манипулированием группами с помощью трассировки лучей (raycasting) и 15+ встроенными ассетами.
- 🎬 **Story Engine & Player** — создание интерактивных 3D-историй по промптам с помощью нашего редактора сценариев. Агенты общаются через 3D-облака диалогов внутри проигрывателя анимированных сцен.
- 🔌 **Extension Manager** — подключаемая архитектура. Среди встроенных расширений — `chat`, `codex`, `browser`, `browser_scripts`, `webui`, `market`, `multi_agents`, `studio3d`, `cloud_api` и другие. Каждое расширение добавляет свои CLI-команды, API-маршруты, узлы процессов, действия Telegram и собственную страницу интерфейса.
- 🌐 **Browser Automation** — управление профилями браузеров, прокси, фингерпринтами. Встроенная автоавторизация в Google с TOTP 2FA.
- 🛒 **Marketplace** — поиск, установка и совместное использование навыков сообщества через онлайн-реестр.
- 📨 **Telegram Bridge** — управляйте той же системой из Telegram-бота: маршрутизация намерений, выполнение навыков, утверждение задач и упреждающие уведомления о завершении длительных операций.

## 🚀 Быстрый старт и установка

### Вариант 1: Автоматическая установка в один клик (рекомендуется для пользователей)
**Для Windows:** Откройте **PowerShell** (запуск от имени администратора) и вставьте следующую команду:
```powershell
powershell -c "irm https://raw.githubusercontent.com/tubecreate/tubecli/main/install/install_ru.ps1 | iex"
```

**Для Linux / MacOS:** Откройте терминал и выполните:
```bash
curl -fsSL https://raw.githubusercontent.com/tubecreate/tubecli/main/install/install_ru.sh | bash
```

Скрипт автоматически установит Python, Git (если отсутствуют), клонирует репозиторий и настроит всё под ключ.

### Вариант 2: Ручная установка (для разработчиков)

#### Системные требования
- Python 3.9+
- Ollama (опционально, требуется для локального запуска ИИ)
- Git

#### 1. Клонирование и установка
```bash
git clone https://github.com/tubecreate/tubecli.git
cd tubecli
pip install -e .
```

### 2. Инициализация рабочей среды
Запустите команду инициализации для настройки каталога `data/`, извлечения стандартных навыков, активации основных расширений и настройки порта по умолчанию.
```bash
tubecli init --lang ru --port 5295
```

### 3. Запуск веб-панели (Web Dashboard)
После инициализации запустите API-сервер для доступа к графическому интерфейсу.
```bash
tubecli api start
```
Откройте браузер и перейдите по адресу: **http://localhost:5295/dashboard**

## 💻 Использование CLI

Управляйте всей системой напрямую из терминала, если предпочитаете консольный подход:

### Управление агентами
```bash
tubecli agent create "My Assistant" --description "General purpose AI agent"
tubecli agent list
tubecli agent show <id>
tubecli agent delete <id>
```

### Выполнение навыков (Skills)
```bash
tubecli skill list
tubecli skill run "AI Summarizer" --input "Long text content..."
```

### API и процессы (Workflows)
```bash
tubecli api start --port 5295
tubecli api stop
tubecli workflow run <path_to_workflow.json>
```

### Доска задач (Codex)
```bash
tubecli codex create "Research the top 5 competitor channels" --agent "Researcher"
tubecli codex list --status pending_approval
tubecli codex approve 3
tubecli codex show 3
```
> Задачи, созданные ИИ, всегда ожидают вашего утверждения перед запуском.

### Расширения и Маркетплейс
```bash
tubecli extension list
tubecli extension enable webui
tubecli market search "seo"
tubecli market install "seo-analyzer"
```
> Расширения привязывают свои API-маршруты в момент их импорта сервером, поэтому **перезапустите сервер** после включения или добавления расширения.

## 🧠 Обзор архитектуры

```
tubecli/
├── tubecli/           # Основной пакет
│   ├── api/           # REST API сервер (FastAPI)
│   ├── cli/           # Модули команд CLI
│   ├── core/          # Ядро бизнес-логики
│   ├── extensions/    # Расширения (Chat, Codex, Browser, WebUI, Market, Studio3D, …)
│   ├── nodes/         # Реализации узлов процессов
│   └── skills/        # Встроенные системные навыки
├── .agents/           # Документация для чтения ИИ (SKILL.md)
├── data/              # База данных и состояние среды выполнения (в gitignore)
└── tests/             # Тесты
```

## 📖 Документация для ИИ
Папки `.agents/` и `skills` содержат документацию, созданную специально для больших языковых моделей (LLM) (`SKILL.md`). Внешние агенты ИИ (такие как Claude или GPT-4) могут считывать эти файлы, чтобы полностью автономно обучаться управлению системой TubeCLI, написанию плагинов и отладке процессов без участия человека.

## 📝 Лицензия
Лицензия MIT - сделано с помощью 🤖 командой TubeCreate
