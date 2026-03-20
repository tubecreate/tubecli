/**
 * TubeCLI Dashboard — Internationalization (i18n)
 * Loads language from API and provides T() for translations.
 */
let _lang = 'en';
const _translations = {
    vi: {
        // Sidebar
        'nav.dashboard': 'Dashboard',
        'nav.extensions': 'Extensions',
        'nav.api_manager': 'API Manager',
        'nav.settings': 'Cài đặt',
        'sidebar.connected': 'API Đã kết nối',
        'sidebar.offline': 'API Ngoại tuyến',

        // Dashboard
        'dash.title': '📊 Dashboard',
        'stat.agents': 'Agents',
        'stat.profiles': 'Hồ sơ trình duyệt',
        'stat.skills': 'Kỹ năng',
        'stat.workflows': 'Workflows',
        'stat.extensions': 'Extensions',
        'stat.api_keys': 'API Keys',
        'dash.system_status': '🟢 Trạng thái hệ thống',
        'dash.quick_actions': '📌 Thao tác nhanh',
        'dash.manage_agents': '🤖 Quản lý Agents',
        'dash.browser_profiles': '🌐 Hồ sơ trình duyệt',
        'dash.workflow_builder': '🔄 Trình tạo Workflow',
        'dash.cloud_api_keys': '☁️ Cloud API Keys',
        'status.online': 'Trực tuyến',
        'status.offline': 'Ngoại tuyến',
        'status.checking': 'Đang kiểm tra...',
        'status.idle': 'Chờ',
        'status.running': 'đang chạy',
        'status.models': 'mô hình',

        // Extensions
        'ext.title': '🧩 Extensions',
        'ext.install_git': '+ Cài từ Git',
        'ext.click_hint': 'Nhấp vào extension để mở giao diện quản lý.',
        'ext.agents_desc': 'Tạo, chỉnh sửa và trò chuyện với AI agents',
        'ext.browser_desc': 'Quản lý hồ sơ trình duyệt ẩn danh',
        'ext.workflows_desc': 'Trình tạo workflow với node editor',
        'ext.skills_desc': 'Quản lý và chạy kỹ năng của agent',
        'ext.market_desc': 'Duyệt và cài đặt extension cộng đồng',
        'ext.cloud_api_desc': 'Quản lý API keys cho Gemini, OpenAI, Claude, DeepSeek, Grok',
        'ext.ollama_desc': 'Quản lý mô hình AI cục bộ qua Ollama',
        'ext.multi_agents_desc': 'Điều phối đội agent và phân công công việc',
        'ext.back': '← Quay lại Extensions',

        // Agents
        'agents.generate_ai': '⚡ Tạo bằng AI',
        'agents.create': '+ Tạo Agent',
        'agents.no_agents': 'Chưa có agent nào.',
        'agents.skills_count': 'kỹ năng',
        'agents.chat': '💬 Chat',
        'agents.edit': 'Sửa',
        'agents.delete': 'Xóa',
        'agents.delete_confirm': 'Xóa agent này?',

        // Agent Modal
        'agent_modal.create_title': 'Tạo Agent',
        'agent_modal.edit_title': 'Sửa:',
        'agent_modal.identity': '👤 Danh tính',
        'agent_modal.behavior': '🧠 Hành vi',
        'agent_modal.browser': '🌐 Trình duyệt',
        'agent_modal.schedule': '⏰ Lên lịch',
        'agent_modal.history': '📜 Lịch sử',
        'agent_modal.skills': '⚡ Kỹ năng',
        'agent_modal.telegram': '✈️ Telegram',
        'agent_modal.messenger': '💬 Messenger',
        'agent_modal.identity_title': 'Danh tính & Tùy chọn',
        'agent_modal.save': 'Lưu Agent',
        'agent_modal.cancel': 'Hủy',
        'agent_modal.name_required': 'Tên không được để trống',

        // Browser
        'browser.new_profile': '+ Hồ sơ mới',
        'browser.no_profiles': 'Chưa có hồ sơ nào.',
        'browser.create_profile': 'Tạo hồ sơ',
        'browser.create_fetch': 'Tạo & Lấy Fingerprint',
        'browser.creating': 'Đang tạo...',
        'browser.delete_confirm': 'Xóa',
        'browser.no_proxy': 'Không proxy',

        // Skills
        'skills.no_skills': 'Không tìm thấy kỹ năng.',
        'skills.run': '▶ Chạy',
        'skills.executed': 'Kỹ năng đã được thực thi. Kiểm tra CLI.',

        // Cloud API
        'cloud_api.add_key': '+ Thêm Key',
        'cloud_api.stored_keys': '🔐 Keys đã lưu',
        'cloud_api.no_keys': 'Chưa có keys nào.',
        'cloud_api.active': '✅ Hoạt động',
        'cloud_api.no_key': '❌ Chưa có Key',
        'cloud_api.add': '+ Thêm',
        'cloud_api.test': '🧪 Kiểm tra',
        'cloud_api.remove_confirm': 'Xóa "{label}" từ {provider}?',
        'cloud_api.provider': 'Provider',
        'cloud_api.label': 'Nhãn',
        'cloud_api.key': 'Key',
        'cloud_api.status': 'Trạng thái',
        'cloud_api.actions': 'Thao tác',

        // Ollama
        'ollama.models': '📦 Mô hình',
        'ollama.loaded': '🔥 Đã tải',
        'ollama.not_running': 'Ollama chưa chạy.',
        'ollama.no_models': 'Chưa có mô hình. Tải một mô hình bên dưới.',
        'ollama.pull': '📥 Tải',
        'ollama.enter_model': 'Nhập tên mô hình.',
        'ollama.pulling': 'Đang tải "{name}"...',
        'ollama.done': 'Xong!',
        'ollama.failed': 'Thất bại: ',
        'ollama.remove_confirm': 'Xóa "{name}"?',
        'ollama.model_col': 'Mô hình',
        'ollama.size_col': 'Dung lượng',
        'ollama.modified_col': 'Cập nhật',
        'ollama.status_col': 'Trạng thái',
        'ollama.actions_col': 'Thao tác',

        // Multi-Agents
        'multi.create_team': '+ Tạo nhóm',
        'multi.teams': '👥 Nhóm',
        'multi.no_teams': 'Chưa có nhóm.',
        'multi.delegation_log': '📋 Nhật ký phân công',
        'multi.no_history': 'Chưa có lịch sử.',
        'multi.delete_confirm': 'Xóa nhóm?',
        'multi.team_name': 'Tên nhóm:',
        'multi.agent_ids': 'ID Agents (phân cách bằng dấu phẩy):',
        'multi.strategy': 'Chiến lược (sequential/parallel/lead-delegate):',
        'multi.created': 'Đã tạo!',
        'multi.team_col': 'Nhóm',
        'multi.strategy_col': 'Chiến lược',
        'multi.agents_col': 'Agents',
        'multi.time_col': 'Thời gian',
        'multi.task_col': 'Nhiệm vụ',

        // Settings
        'settings.title': '⚙️ Cài đặt',
        'settings.version': '🔄 Phiên bản & Cập nhật',
        'settings.general': '⚙️ Tổng quan',
        'settings.language': '🌐 Ngôn ngữ',
        'settings.api_port': 'Cổng API',
        'settings.ai_model': 'Mô hình AI',
        'settings.api_base': 'API Base URL',
        'settings.save': 'Lưu cài đặt',
        'settings.check_update': '🔍 Kiểm tra cập nhật',
        'settings.update_now': '⬆️ Cập nhật ngay',
        'settings.checking': '🔍 Đang kiểm tra...',
        'settings.fetching': 'Đang lấy từ GitHub...',
        'settings.update_available': '🔔 Có bản cập nhật! {count} commit mới',
        'settings.up_to_date': '✅ Bạn đang dùng phiên bản mới nhất!',
        'settings.update_confirm': 'Cập nhật TubeCLI lên phiên bản mới nhất? API server cần khởi động lại.',
        'settings.updating': '⏳ Đang cập nhật...',
        'settings.pulling': 'Đang tải mã nguồn mới từ GitHub...',
        'settings.updated': '✅ Đã cập nhật lên v{version}!',
        'settings.restart_needed': 'Vui lòng khởi động lại API server.',
        'settings.restart_banner': '⚠️ Khởi động lại API server để áp dụng bản cập nhật. Chạy: ',
        'settings.update_failed': '❌ Cập nhật thất bại: ',
        'settings.changelog': '📋 Nhật ký thay đổi',
        'settings.lang_label': 'Ngôn ngữ giao diện',
        'settings.lang_saved': '✅ Đã lưu! Đang tải lại...',

        // Install Extension Modal
        'install_ext.title': '📦 Cài đặt Extension từ Git',
        'install_ext.url_label': 'Git Repository URL',
        'install_ext.cancel': 'Hủy',
        'install_ext.install': '🚀 Cài đặt',
        'install_ext.installing': '⏳ Đang cài đặt...',
        'install_ext.url_required': 'URL không được để trống.',
        'install_ext.installed': 'Đã cài đặt!',
        'install_ext.failed': 'Thất bại: ',

        // Chat
        'chat.title': '💬 Trò chuyện với',
        'chat.placeholder': 'Nhập tin nhắn...',
        'chat.send': 'Gửi',
        'chat.say_hello': 'Hãy nói xin chào!',
        'chat.typing': 'Đang gõ...',
        'chat.loading': 'Đang tải...',

        // Generate Agent
        'gen.title': '⚡ Tạo Agent bằng AI',
        'gen.name': 'Tên Agent',
        'gen.prefix': 'Tag Prefix',
        'gen.desc': 'Mô tả',
        'gen.provider': 'AI Provider',
        'gen.model': 'Mô hình',
        'gen.api_key': 'API Key',
        'gen.accounts': '🔑 Tài khoản Google (phân cách bằng tab)',
        'gen.preview': '📄 Xem trước',
        'gen.close': 'Đóng',
        'gen.generate': '⚡ Tạo',
        'gen.apply': '🚀 Áp dụng',
        'gen.name_desc_required': 'Cần có Tên & Mô tả!',
        'gen.calling': '🤖 Đang gọi {provider}/{model}...',
        'gen.done': '✅ Xong!',
        'gen.failed': '❌ Thất bại',
        'gen.error': '❌ Lỗi',
        'gen.generating': 'Đang tạo...',

        // Add API Key Modal
        'add_key.title': '🔑 Thêm API Key',
        'add_key.provider': 'Provider',
        'add_key.key': 'API Key',
        'add_key.label': 'Nhãn',
        'add_key.cancel': 'Hủy',
        'add_key.save': 'Lưu Key',
        'add_key.required': 'Key không được để trống.',
        'add_key.added': 'Đã thêm!',
        'add_key.failed': 'Thất bại.',

        // API Manager
        'api.title': '🔌 API Manager',
        'api.desc': 'System CLI REST API — TubeCLI API Server Endpoints',
        'api.status': 'Trạng thái Server:',
        'api.running': 'Đang chạy',
        'api.base_url': 'Base URL:',
        'api.swagger': 'Mở Swagger Docs',
        'api.redoc': 'Mở ReDoc',
        'api.endpoints': '📡 Endpoints có sẵn',
        'api.method': 'Phương thức',
        'api.path': 'Đường dẫn',
        'api.description': 'Mô tả',
        'api.tags': 'Tags',
        'api.load_fail': 'Không thể tải API spec. Kiểm tra server đang chạy.',

        // Form labels
        'form.name': 'Tên',
        'form.proxy': 'Proxy',
        'form.os': 'Hệ điều hành',
        'form.browser': 'Trình duyệt',
    },
    en: {
        // Sidebar
        'nav.dashboard': 'Dashboard',
        'nav.extensions': 'Extensions',
        'nav.api_manager': 'API Manager',
        'nav.settings': 'Settings',
        'sidebar.connected': 'API Connected',
        'sidebar.offline': 'API Offline',

        // Dashboard
        'dash.title': '📊 Dashboard',
        'stat.agents': 'Agents',
        'stat.profiles': 'Browser Profiles',
        'stat.skills': 'Skills',
        'stat.workflows': 'Workflows',
        'stat.extensions': 'Extensions',
        'stat.api_keys': 'API Keys',
        'dash.system_status': '🟢 System Status',
        'dash.quick_actions': '📌 Quick Actions',
        'dash.manage_agents': '🤖 Manage Agents',
        'dash.browser_profiles': '🌐 Browser Profiles',
        'dash.workflow_builder': '🔄 Workflow Builder',
        'dash.cloud_api_keys': '☁️ Cloud API Keys',
        'status.online': 'Online',
        'status.offline': 'Offline',
        'status.checking': 'Checking...',
        'status.idle': 'Idle',
        'status.running': 'running',
        'status.models': 'models',

        // Extensions
        'ext.title': '🧩 Extensions',
        'ext.install_git': '+ Install from Git',
        'ext.click_hint': 'Click on an extension to open its management interface.',
        'ext.agents_desc': 'Create, edit and chat with AI agents',
        'ext.browser_desc': 'Manage anti-detect browser profiles',
        'ext.workflows_desc': 'Visual workflow builder with node editor',
        'ext.skills_desc': 'Manage and run agent skills',
        'ext.market_desc': 'Browse and install community extensions',
        'ext.cloud_api_desc': 'Manage API keys for Gemini, OpenAI, Claude, DeepSeek, Grok',
        'ext.ollama_desc': 'Manage local AI models via Ollama',
        'ext.multi_agents_desc': 'Orchestrate agent teams and task delegation',
        'ext.back': '← Back to Extensions',

        // Agents
        'agents.generate_ai': '⚡ Generate with AI',
        'agents.create': '+ Create Agent',
        'agents.no_agents': 'No agents yet.',
        'agents.skills_count': 'skills',
        'agents.chat': '💬 Chat',
        'agents.edit': 'Edit',
        'agents.delete': 'Del',
        'agents.delete_confirm': 'Delete agent?',

        // Agent Modal
        'agent_modal.create_title': 'Create Agent',
        'agent_modal.edit_title': 'Edit:',
        'agent_modal.identity': '👤 Identity',
        'agent_modal.behavior': '🧠 Behavior',
        'agent_modal.browser': '🌐 Browser',
        'agent_modal.schedule': '⏰ Schedule',
        'agent_modal.history': '📜 History',
        'agent_modal.skills': '⚡ Skills',
        'agent_modal.telegram': '✈️ Telegram',
        'agent_modal.messenger': '💬 Messenger',
        'agent_modal.identity_title': 'Identity & Options',
        'agent_modal.save': 'Save Agent',
        'agent_modal.cancel': 'Cancel',
        'agent_modal.name_required': 'Name required',

        // Browser
        'browser.new_profile': '+ New Profile',
        'browser.no_profiles': 'No profiles yet.',
        'browser.create_profile': 'Create Profile',
        'browser.create_fetch': 'Create & Fetch Fingerprint',
        'browser.creating': 'Creating...',
        'browser.delete_confirm': 'Delete',
        'browser.no_proxy': 'No proxy',

        // Skills
        'skills.no_skills': 'No skills found.',
        'skills.run': '▶ Run',
        'skills.executed': 'Skill executed. Check CLI.',

        // Cloud API
        'cloud_api.add_key': '+ Add Key',
        'cloud_api.stored_keys': '🔐 Stored Keys',
        'cloud_api.no_keys': 'No keys stored.',
        'cloud_api.active': '✅ Active',
        'cloud_api.no_key': '❌ No Key',
        'cloud_api.add': '+ Add',
        'cloud_api.test': '🧪 Test',
        'cloud_api.remove_confirm': 'Remove "{label}" from {provider}?',
        'cloud_api.provider': 'Provider',
        'cloud_api.label': 'Label',
        'cloud_api.key': 'Key',
        'cloud_api.status': 'Status',
        'cloud_api.actions': 'Actions',

        // Ollama
        'ollama.models': '📦 Models',
        'ollama.loaded': '🔥 Loaded',
        'ollama.not_running': 'Ollama not running.',
        'ollama.no_models': 'No models. Pull one below.',
        'ollama.pull': '📥 Pull',
        'ollama.enter_model': 'Enter model name.',
        'ollama.pulling': 'Pulling "{name}"...',
        'ollama.done': 'Done!',
        'ollama.failed': 'Failed: ',
        'ollama.remove_confirm': 'Remove "{name}"?',
        'ollama.model_col': 'Model',
        'ollama.size_col': 'Size',
        'ollama.modified_col': 'Modified',
        'ollama.status_col': 'Status',
        'ollama.actions_col': 'Actions',

        // Multi-Agents
        'multi.create_team': '+ Create Team',
        'multi.teams': '👥 Teams',
        'multi.no_teams': 'No teams.',
        'multi.delegation_log': '📋 Delegation Log',
        'multi.no_history': 'No history.',
        'multi.delete_confirm': 'Delete team?',
        'multi.team_name': 'Team name:',
        'multi.agent_ids': 'Agent IDs (comma-separated):',
        'multi.strategy': 'Strategy (sequential/parallel/lead-delegate):',
        'multi.created': 'Created!',
        'multi.team_col': 'Team',
        'multi.strategy_col': 'Strategy',
        'multi.agents_col': 'Agents',
        'multi.time_col': 'Time',
        'multi.task_col': 'Task',

        // Settings
        'settings.title': '⚙️ Settings',
        'settings.version': '🔄 Version & Update',
        'settings.general': '⚙️ General',
        'settings.language': '🌐 Language',
        'settings.api_port': 'API Port',
        'settings.ai_model': 'AI Model',
        'settings.api_base': 'API Base URL',
        'settings.save': 'Save Settings',
        'settings.check_update': '🔍 Check for Update',
        'settings.update_now': '⬆️ Update Now',
        'settings.checking': '🔍 Checking...',
        'settings.fetching': 'Fetching from GitHub...',
        'settings.update_available': '🔔 Update available! {count} new commit(s)',
        'settings.up_to_date': '✅ You are up to date!',
        'settings.update_confirm': 'Update TubeCLI to latest version? The API server will need to restart after update.',
        'settings.updating': '⏳ Updating...',
        'settings.pulling': 'Pulling latest code from GitHub...',
        'settings.updated': '✅ Updated to v{version}!',
        'settings.restart_needed': 'Please restart the API server.',
        'settings.restart_banner': '⚠️ Restart the API server to apply the update. Run: ',
        'settings.update_failed': '❌ Update failed: ',
        'settings.changelog': '📋 Changelog',
        'settings.lang_label': 'UI Language',
        'settings.lang_saved': '✅ Saved! Reloading...',

        // Install Extension Modal
        'install_ext.title': '📦 Install Extension from Git',
        'install_ext.url_label': 'Git Repository URL',
        'install_ext.cancel': 'Cancel',
        'install_ext.install': '🚀 Install',
        'install_ext.installing': '⏳ Installing...',
        'install_ext.url_required': 'URL required.',
        'install_ext.installed': 'Installed!',
        'install_ext.failed': 'Failed: ',

        // Chat
        'chat.title': '💬 Chat with',
        'chat.placeholder': 'Type a message...',
        'chat.send': 'Send',
        'chat.say_hello': 'Say hello!',
        'chat.typing': 'Typing...',
        'chat.loading': 'Loading...',

        // Generate Agent
        'gen.title': '⚡ Generate Agent with AI',
        'gen.name': 'Agent Name',
        'gen.prefix': 'Tag Prefix',
        'gen.desc': 'Description',
        'gen.provider': 'AI Provider',
        'gen.model': 'Model',
        'gen.api_key': 'API Key',
        'gen.accounts': '🔑 Google Accounts (tab-separated)',
        'gen.preview': '📄 Preview',
        'gen.close': 'Close',
        'gen.generate': '⚡ Generate',
        'gen.apply': '🚀 Apply',
        'gen.name_desc_required': 'Name & Description required!',
        'gen.calling': '🤖 Calling {provider}/{model}...',
        'gen.done': '✅ Done!',
        'gen.failed': '❌ Failed',
        'gen.error': '❌ Error',
        'gen.generating': 'Generating...',

        // Add API Key Modal
        'add_key.title': '🔑 Add API Key',
        'add_key.provider': 'Provider',
        'add_key.key': 'API Key',
        'add_key.label': 'Label',
        'add_key.cancel': 'Cancel',
        'add_key.save': 'Save Key',
        'add_key.required': 'Key required.',
        'add_key.added': 'Added!',
        'add_key.failed': 'Failed.',

        // API Manager
        'api.title': '🔌 API Manager',
        'api.desc': 'System CLI REST API — TubeCLI API Server Endpoints',
        'api.status': 'Server Status:',
        'api.running': 'Running',
        'api.base_url': 'Base URL:',
        'api.swagger': 'Open Swagger Docs',
        'api.redoc': 'Open ReDoc',
        'api.endpoints': '📡 Available Endpoints',
        'api.method': 'Method',
        'api.path': 'Path',
        'api.description': 'Description',
        'api.tags': 'Tags',
        'api.load_fail': 'Cannot load API spec. Check if server is running.',

        // Form labels
        'form.name': 'Name',
        'form.proxy': 'Proxy',
        'form.os': 'OS',
        'form.browser': 'Browser',
    }
};

/**
 * Translate key, with optional replacements.
 * T('ollama.pulling', {name:'qwen'})  →  'Đang tải "qwen"...'
 */
function T(key, vars) {
    let s = (_translations[_lang] && _translations[_lang][key]) || (_translations['en'] && _translations['en'][key]) || key;
    if (vars) {
        Object.keys(vars).forEach(k => {
            s = s.replace(new RegExp('\\{' + k + '\\}', 'g'), vars[k]);
        });
    }
    return s;
}

/**
 * Apply translations to all elements with data-i18n attribute.
 */
function applyI18n() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        el.textContent = T(key);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        el.placeholder = T(el.getAttribute('data-i18n-placeholder'));
    });
    // Update html lang attribute
    document.documentElement.lang = _lang;
}

/**
 * Fetch current language from API and apply.
 */
async function loadI18nFromApi() {
    try {
        const r = await fetch((localStorage.getItem('tubecli_api') || 'http://localhost:5295') + '/api/v1/settings/language');
        const d = await r.json();
        if (d && d.language) {
            _lang = d.language;
        }
    } catch (e) {
        // Default to en on failure
        _lang = localStorage.getItem('tubecli_lang') || 'en';
    }
    applyI18n();
}

/**
 * Save language to API and reload page.
 */
async function changeLanguage(lang) {
    _lang = lang;
    localStorage.setItem('tubecli_lang', lang);
    try {
        await fetch((localStorage.getItem('tubecli_api') || 'http://localhost:5295') + '/api/v1/settings/language', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ language: lang })
        });
    } catch (e) { /* ignore */ }
    applyI18n();
    // Reload current tab content
    location.reload();
}
