# ⚡ TubeCLI — Açık Kaynak Yapay Zeka Ajanı CLI Sistemi

<p align="center">
  <a href="../README.md">English</a> | 
  <a href="README_zh-CN.md">简体中文</a> | 
  <a href="README_zh-TW.md">繁體中文</a> | 
  <a href="README_ja.md">日本語</a> | 
  <a href="README_ko.md">한국어</a> | 
  <a href="README_es.md">Español</a> | 
  <b>Türkçe</b> | 
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

**Yapay zeka ajanları (agents)**, **yetenekler (skills)** ve **iş akışlarını (workflows)** yüklemek, yönetmek ve koordine etmek için tasarlanmış arayüzsüz (headless) bir CLI sistemi. Yapay zeka ajanlarının tüm sistemi otonom olarak anlayabilmesi, yükleyebilmesi ve çalıştırabilmesi için tasarlanmıştır.

![3D Studio Office Builder](screenshots/studio3d_builder.png)
<br>
![3D Studio Agent Teams](screenshots/studio3d_teams.png)

## 🌟 Önemli Özellikler

Sistem, 12 alt sistemden oluşan kapsamlı bir mimariye dönüşmüştür:

- 💬 **Chat** — Tüm sistem için birleşik bir sohbet arayüzü. Kalıcı geçmişe sahip çoklu oturum başlıkları, ajan seçici (veya doğru uzmana otomatik yönlendirme) ve markdown görüntüleme sunar. Her etkileşim tüm hattı çalıştırır — sıfır token maliyetli niyet sınıflandırması, yetenek seçimi ve ardından model — böylece Telegram botunun yapabildiği her şeyi tarayıcı da yapabilir.
- 📋 **Codex** — Ajan tabanlı çalışmalar için görev merkezi. Siz veya yapay zeka bir görev oluşturur, onu bir ajana ya da bir ekibe devreder, onaylar ve arka plandaki bir çalışan görevi yürütürken siz adım zaman çizelgesini izlersiniz. Sonuçlar incelemeniz için geri döner. Görevler kalıcıdır, yeniden başlatmalardan etkilenmez ve her görev için eksiksiz bir denetim kaydı tutulur.
- 🤖 **Agent Manager (Ajan Yöneticisi)** — Personalar, rutinler ve yeteneklerle yapay zeka ajanları oluşturun ve yönetin.
- ⚡ **Skill System (Yetenek Sistemi)** — Markdown Görüntüleyici ve Gerçek Zamanlı Yürütme Modalı sunan, etiketlerle (İş Akışı, API, Markdown) işaretlenmiş çalıştırılabilir iş akışları.
- 🔄 **Workflow Engine & Builder (İş Akışı Motoru ve Tasarımcısı)** — DAG tabanlı iş akışı yürütücüsü. Web arayüzü, kompakt düğümler, bağlamsal kayar özellik panelleri ve dinamik model seçimi (yerel Ollama / Bulut API) içeren modern düğüm tabanlı bir tasarımcı sunar.
- 🎨 **Web Dashboard (Web Paneli)** — Ajanları, iş akışlarını, yetenekleri, pazaryerini, ayarları görsel olarak yönetmek ve tarayıcıları yerel olarak izlemek için `localhost:5295/dashboard` adresinde yer alan kapsamlı SPA (Tek Sayfa Uygulaması).
- 👥 **Teams Agents (Ajan Ekipleri)** — Organizasyon Şemalarını kullanarak birden fazla ajanı koordine edin. Mantıksal şablonlar veya sürükle-bırak yoluyla roller atayın. Görev Delege Etme, işi ardışık, paralel veya hiyerarşik stratejilere göre ekip üzerinden yönlendirir.
- 🏢 **3D Studio (Teams 3D)** — Three.js kullanan izometrik prosedürel 3D görselleştirme. Akıllı içe dönük algoritmalar, raycasting grup manipülasyonu ve 15'ten fazla yerleşik varlık ile çok koltuklu mobilyaları (toplantı masaları vb.) destekler.
- 🎬 **Story Engine & Player (Hikaye Motoru ve Oynatıcı)** — Senaryo Editörümüz aracılığıyla yönlendirmelerden (prompts) etkileşimli 3D hikayeler oluşturun. Ajanlar, animasyonlu sahne oynatıcı içinde 3D konuşma balonları aracılığıyla iletişim kurarlar.
- 🔌 **Extension Manager (Eklenti Yöneticisi)** — Takılabilir mimari. Yerleşik eklentiler arasında `chat`, `codex`, `browser`, `browser_scripts`, `webui`, `market`, `multi_agents`, `studio3d`, `cloud_api` ve daha fazlası bulunur. Her eklenti; CLI komutları, API rotaları, iş akışı düğümleri, Telegram eylemleri ve kendi arayüz sayfasını sisteme kazandırır.
- 🌐 **Browser Automation (Tarayıcı Otomasyonu)** — Tarayıcı profillerini, proxy'leri, parmak izlerini yönetin. TOTP 2FA ile Google için yerleşik Otomatik Giriş.
- 🛒 **Marketplace (Pazaryeri)** — Çevrimiçi bir kayıt defteri aracılığıyla topluluk yeteneklerini keşfedin, yükleyin ve paylaşın.
- 📨 **Telegram Bridge (Telegram Köprüsü)** — Aynı sistemi bir Telegram botu üzerinden yönetin: niyet yönlendirme, yetenek yürütme, görev onaylama ve uzun süren işler tamamlandığında proaktif bildirimler.

## 🚀 Hızlı Başlangıç & Kurulum

### Seçenek 1: Tek Tıkla Otomatik Kurulum (Kullanıcılar için Önerilen)
**Windows için:** **PowerShell**'i (Yönetici olarak çalıştırın) açın ve aşağıdaki komutu yapıştırın:
```powershell
powershell -c "irm https://raw.githubusercontent.com/tubecreate/tubecli/main/install/install_tr.ps1 | iex"
```

**Linux / MacOS için:** Terminalinizi açın ve çalıştırın:
```bash
curl -fsSL https://raw.githubusercontent.com/tubecreate/tubecli/main/install/install_tr.sh | bash
```

Python, Git (eksikse) otomatik olarak yüklenecek, depo klonlanacak ve A'dan Z'ye her şey sizin için kurulacaktır.

### Seçenek 2: Manuel Kurulum (Geliştiriciler için)

#### Gereksinimler
- Python 3.9+
- Ollama (İsteğe bağlı, yerel yapay zeka yürütmesi için gereklidir)
- Git

#### 1. Klonlama ve Yükleme
```bash
git clone https://github.com/tubecreate/tubecli.git
cd tubecli
pip install -e .
```

### 2. Çalışma Alanını Başlatma
`data/` dizinini kurmak, varsayılan yetenekleri çıkarmak, çekirdek eklentileri etkinleştirmek ve varsayılan bağlantı noktasını yapılandırmak için başlatma komutunu çalıştırın.
```bash
tubecli init --lang tr --port 5295
```

### 3. Web Panelini Başlatma
Başlatma işleminden sonra, arayüze erişmek için API sunucusunu başlatın.
```bash
tubecli api start
```
Tarayıcınızı açın ve şu adrese gidin: **http://localhost:5295/dashboard**

## 💻 CLI Kullanımı

Arayüzsüz bir yaklaşımı tercih ediyorsanız, tüm sistemi doğrudan terminalden yönetin:

### Ajan Yönetimi
```bash
tubecli agent create "My Assistant" --description "General purpose AI agent"
tubecli agent list
tubecli agent show <id>
tubecli agent delete <id>
```

### Yetenek Yürütme
```bash
tubecli skill list
tubecli skill run "AI Summarizer" --input "Long text content..."
```

### API ve İş Akışları
```bash
tubecli api start --port 5295
tubecli api stop
tubecli workflow run <path_to_workflow.json>
```

### Görev Panosu (Codex)
```bash
tubecli codex create "Research the top 5 competitor channels" --agent "Researcher"
tubecli codex list --status pending_approval
tubecli codex approve 3
tubecli codex show 3
```
> Yapay zekanın oluşturduğu görevler, çalıştırılmadan önce her zaman sizin onayınızı bekler.

### Eklentiler ve Pazar
```bash
tubecli extension list
tubecli extension enable webui
tubecli market search "seo"
tubecli market install "seo-analyzer"
```
> Eklentiler, API rotalarını sunucu tarafından içe aktarıldıkları anda bağlar; bu nedenle bir eklentiyi etkinleştirdikten veya eklendikten sonra **sunucuyu yeniden başlatın**.

## 🧠 Mimariye Genel Bakış

```
tubecli/
├── tubecli/           # Ana paket
│   ├── api/           # REST API sunucusu (FastAPI)
│   ├── cli/           # CLI komut modülleri
│   ├── core/          # Çekirdek iş mantığı
│   ├── extensions/    # Eklentiler (Chat, Codex, Browser, WebUI, Market, Studio3D, …)
│   ├── nodes/         # İş akışı düğüm uygulamaları
│   └── skills/        # Yerleşik sistem yetenekleri
├── .agents/           # Yapay zeka tarafından okunabilir dokümantasyon (SKILL.md)
├── data/              # Çalışma zamanı veritabanı ve durumu (gitignored)
└── tests/             # Test paketi
```

## 📖 Yapay Zeka Tarafından Okunabilir Dokümantasyon
`.agents/` ve yetenekler klasörleri, LLM'ler için özel olarak hazırlanmış dokümanlar içerir (`SKILL.md`). Harici yapay zeka ajanları (Claude veya GPT-4 gibi), insan müdahalesi olmadan TubeCLI sistemini nasıl çalıştıracaklarını, eklentiler yazacaklarını ve iş akışlarında nasıl hata ayıklayacaklarını öğrenmek için bu dosyaları tamamen otonom olarak okuyabilirler.

## 📝 Lisans
MIT Lisansı - TubeCreate Ekibi tarafından 🤖 ile yapıldı
