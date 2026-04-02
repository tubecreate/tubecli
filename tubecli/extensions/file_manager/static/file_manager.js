/**
 * File Manager — Frontend Logic
 * Handles file browsing, CRUD operations, keyboard shortcuts, drag & drop
 */
const FM = {
    currentPath: '',
    selectedItem: null,
    clipboard: null,  // {action: 'copy'|'cut', path: ''}
    viewMode: 'grid', // 'grid' | 'list'
    items: [],

    // ── API ──────────────────────────────────────────────────

    async api(method, endpoint, body = null) {
        const opts = { method, headers: { 'Content-Type': 'application/json' } };
        if (body) opts.body = JSON.stringify(body);
        try {
            const res = await fetch(`/api/v1/files${endpoint}`, opts);
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
            return data;
        } catch (e) {
            this.toast(e.message, 'error');
            throw e;
        }
    },

    // ── Init ─────────────────────────────────────────────────

    async init() {
        // Load roots
        try {
            const data = await this.api('GET', '/roots');
            this.renderSidebar(data.roots || []);
            // Navigate to first existing root
            const first = (data.roots || []).find(r => r.exists);
            if (first) {
                this.navigate(first.path);
            }
        } catch (e) {
            console.error('Init failed:', e);
        }

        // Event listeners
        document.addEventListener('keydown', (e) => this.handleKeyboard(e));
        document.addEventListener('click', () => this.hideContextMenu());
        document.getElementById('searchInput').addEventListener('input',
            this.debounce(() => this.handleSearch(), 300)
        );
        document.getElementById('showHidden').addEventListener('change', () => this.refresh());
    },

    // ── Navigation ───────────────────────────────────────────

    async navigate(path) {
        this.currentPath = path;
        this.selectedItem = null;
        this.updateToolbarButtons();

        document.getElementById('fileGrid').innerHTML = '';
        document.getElementById('emptyState').style.display = 'none';
        document.getElementById('loading').style.display = 'flex';

        try {
            const showHidden = document.getElementById('showHidden').checked;
            const data = await this.api('GET', `/list?path=${encodeURIComponent(path)}&show_hidden=${showHidden}`);
            this.items = data.items || [];
            this.renderFiles(this.items);
            this.renderBreadcrumb(data.path);
            this.updateStatus(data);

            // Highlight sidebar
            document.querySelectorAll('.fm-sidebar-item').forEach(el => {
                el.classList.toggle('active', el.dataset.path === path);
            });

        } catch (e) {
            document.getElementById('loading').style.display = 'none';
            document.getElementById('emptyState').style.display = 'flex';
        }
    },

    // ── Render ────────────────────────────────────────────────

    renderSidebar(roots) {
        const container = document.getElementById('quickAccess');
        const icons = {
            'Desktop': 'desktop_windows',
            'Documents': 'description',
            'Downloads': 'download',
            'data': 'storage',
        };

        container.innerHTML = roots.map(r => {
            const icon = icons[r.name] || 'folder';
            const disabled = !r.exists ? 'style="opacity:0.4;pointer-events:none;"' : '';
            return `<div class="fm-sidebar-item" data-path="${r.path}" onclick="FM.navigate('${r.path.replace(/\\/g, '\\\\')}')" ${disabled}>
                <span class="material-icons-round">${icon}</span>
                <span>${r.name}</span>
            </div>`;
        }).join('');
    },

    renderBreadcrumb(path) {
        const parts = path.replace(/\\/g, '/').split('/').filter(Boolean);
        const bc = document.getElementById('breadcrumb');
        let accumulated = '';

        bc.innerHTML = parts.map((part, i) => {
            accumulated += (i === 0 && path.includes(':') ? '' : '/') + part;
            if (i === 0 && path.includes(':')) accumulated = part;
            const isLast = i === parts.length - 1;
            const sep = i < parts.length - 1 ? '<span class="fm-crumb-sep">›</span>' : '';
            const cls = isLast ? 'fm-crumb active' : 'fm-crumb';
            const clickPath = accumulated.replace(/\\/g, '\\\\');
            return `<span class="${cls}" onclick="FM.navigate('${clickPath}')">${part}</span>${sep}`;
        }).join('');
    },

    renderFiles(items) {
        const grid = document.getElementById('fileGrid');
        const loading = document.getElementById('loading');
        const empty = document.getElementById('emptyState');

        loading.style.display = 'none';
        grid.className = `fm-file-grid ${this.viewMode === 'list' ? 'list-view' : ''}`;

        if (items.length === 0) {
            grid.innerHTML = '';
            empty.style.display = 'flex';
            return;
        }
        empty.style.display = 'none';

        // Sort: folders first, then files
        const sorted = [...items].sort((a, b) => {
            if (a.is_dir && !b.is_dir) return -1;
            if (!a.is_dir && b.is_dir) return 1;
            return a.name.localeCompare(b.name);
        });

        grid.innerHTML = sorted.map(item => {
            const iconInfo = this.getFileIcon(item);
            const safePath = (item.path || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");

            if (this.viewMode === 'list') {
                return `<div class="fm-file-card" data-path="${item.path}"
                    onclick="FM.selectItem(this, '${safePath}')"
                    ondblclick="FM.openItem('${safePath}', ${item.is_dir})"
                    oncontextmenu="FM.showContextMenu(event, '${safePath}', ${item.is_dir})">
                    <span class="fm-file-icon ${iconInfo.cls}" style="font-size:20px">${iconInfo.icon}</span>
                    <span class="fm-file-name">${this.escHtml(item.name)}</span>
                    <span class="fm-file-size">${item.is_dir ? '' : (item.size_human || '')}</span>
                    <span class="fm-file-modified">${item.modified || ''}</span>
                </div>`;
            }

            return `<div class="fm-file-card" data-path="${item.path}"
                onclick="FM.selectItem(this, '${safePath}')"
                ondblclick="FM.openItem('${safePath}', ${item.is_dir})"
                oncontextmenu="FM.showContextMenu(event, '${safePath}', ${item.is_dir})">
                <span class="fm-file-icon ${iconInfo.cls}">${iconInfo.icon}</span>
                <span class="fm-file-name">${this.escHtml(item.name)}</span>
                ${!item.is_dir ? `<span class="fm-file-size">${item.size_human || ''}</span>` : ''}
            </div>`;
        }).join('');
    },

    getFileIcon(item) {
        if (item.is_dir) return { icon: '📁', cls: 'folder' };
        const ext = (item.extension || '').toLowerCase();
        const map = {
            '.txt': { icon: '📄', cls: 'file-txt' },
            '.md': { icon: '📝', cls: 'file-txt' },
            '.log': { icon: '📋', cls: 'file-txt' },
            '.json': { icon: '{ }', cls: 'file-code' },
            '.js': { icon: 'JS', cls: 'file-code' },
            '.py': { icon: '🐍', cls: 'file-code' },
            '.html': { icon: '🌐', cls: 'file-code' },
            '.css': { icon: '🎨', cls: 'file-code' },
            '.jpg': { icon: '🖼', cls: 'file-img' },
            '.jpeg': { icon: '🖼', cls: 'file-img' },
            '.png': { icon: '🖼', cls: 'file-img' },
            '.gif': { icon: '🖼', cls: 'file-img' },
            '.svg': { icon: '🖼', cls: 'file-img' },
            '.mp4': { icon: '🎬', cls: 'file-media' },
            '.mp3': { icon: '🎵', cls: 'file-media' },
            '.wav': { icon: '🎵', cls: 'file-media' },
            '.pdf': { icon: '📕', cls: 'file-txt' },
            '.zip': { icon: '📦', cls: 'file-other' },
            '.rar': { icon: '📦', cls: 'file-other' },
            '.exe': { icon: '⚙️', cls: 'file-other' },
        };
        return map[ext] || { icon: '📄', cls: 'file-other' };
    },

    // ── Selection ────────────────────────────────────────────

    selectItem(el, path) {
        document.querySelectorAll('.fm-file-card.selected').forEach(c => c.classList.remove('selected'));
        el.classList.add('selected');
        this.selectedItem = path;
        this.updateToolbarButtons();
    },

    updateToolbarButtons() {
        const has = !!this.selectedItem;
        document.getElementById('btnRename').disabled = !has;
        document.getElementById('btnDelete').disabled = !has;
        document.getElementById('btnCopy').disabled = !has;
        document.getElementById('btnPaste').disabled = !this.clipboard;
    },

    // ── File Operations ──────────────────────────────────────

    async createFolder() {
        const name = prompt('Enter folder name:');
        if (!name) return;
        const sep = this.currentPath.includes('/') ? '/' : '\\';
        const path = this.currentPath + sep + name;
        try {
            await this.api('POST', '/create-folder', { path });
            this.toast(`Created folder: ${name}`, 'success');
            this.refresh();
        } catch (e) { /* toast already shown */ }
    },

    async createFile() {
        const name = prompt('Enter file name:');
        if (!name) return;
        const sep = this.currentPath.includes('/') ? '/' : '\\';
        const path = this.currentPath + sep + name;
        try {
            await this.api('POST', '/create-file', { path, content: '' });
            this.toast(`Created file: ${name}`, 'success');
            this.refresh();
        } catch (e) { /* toast already shown */ }
    },

    async deleteSelected() {
        if (!this.selectedItem) return;
        const name = this.selectedItem.split(/[/\\]/).pop();
        if (!confirm(`Delete "${name}"?`)) return;
        try {
            await this.api('DELETE', `/delete?path=${encodeURIComponent(this.selectedItem)}`);
            this.toast(`Deleted: ${name}`, 'success');
            this.selectedItem = null;
            this.refresh();
        } catch (e) { /* toast already shown */ }
    },

    async renameSelected() {
        if (!this.selectedItem) return;
        const oldName = this.selectedItem.split(/[/\\]/).pop();
        const newName = prompt('Enter new name:', oldName);
        if (!newName || newName === oldName) return;
        const parent = this.selectedItem.substring(0, this.selectedItem.lastIndexOf(oldName));
        try {
            await this.api('POST', '/move', { src: this.selectedItem, dst: parent + newName });
            this.toast(`Renamed to: ${newName}`, 'success');
            this.refresh();
        } catch (e) { /* toast already shown */ }
    },

    copySelected() {
        if (!this.selectedItem) return;
        this.clipboard = { action: 'copy', path: this.selectedItem };
        this.updateToolbarButtons();
        const name = this.selectedItem.split(/[/\\]/).pop();
        this.toast(`Copied: ${name}`, 'info');
    },

    moveSelected() {
        if (!this.selectedItem) return;
        this.clipboard = { action: 'cut', path: this.selectedItem };
        this.updateToolbarButtons();
        const name = this.selectedItem.split(/[/\\]/).pop();
        this.toast(`Ready to move: ${name}`, 'info');
    },

    async pasteClipboard() {
        if (!this.clipboard) return;
        const name = this.clipboard.path.split(/[/\\]/).pop();
        const sep = this.currentPath.includes('/') ? '/' : '\\';
        const dst = this.currentPath + sep + name;
        try {
            if (this.clipboard.action === 'copy') {
                await this.api('POST', '/copy', { src: this.clipboard.path, dst });
                this.toast(`Pasted: ${name}`, 'success');
            } else {
                await this.api('POST', '/move', { src: this.clipboard.path, dst });
                this.toast(`Moved: ${name}`, 'success');
                this.clipboard = null;
            }
            this.refresh();
        } catch (e) { /* toast already shown */ }
    },

    openItem(path, isDir) {
        path = path || this.selectedItem;
        if (!path) return;
        const item = this.items.find(i => i.path.replace(/\\/g, '\\\\') === path || i.path === path);
        const realIsDir = isDir !== undefined ? isDir : (item && item.is_dir);
        if (realIsDir) {
            this.navigate(path.replace(/\\\\/g, '\\'));
        } else {
            this.previewFile(path.replace(/\\\\/g, '\\'));
        }
    },

    async previewFile(path) {
        try {
            const data = await this.api('GET', `/read?path=${encodeURIComponent(path)}&max_lines=500`);
            if (data.is_binary) {
                this.toast('Binary file — cannot preview', 'info');
                return;
            }
            const name = path.split(/[/\\]/).pop();
            document.getElementById('previewTitle').textContent = name;
            document.getElementById('previewContent').textContent = data.content || '(empty)';
            document.getElementById('previewModal').style.display = 'flex';
        } catch (e) { /* toast already shown */ }
    },

    closePreview() {
        document.getElementById('previewModal').style.display = 'none';
    },

    // ── Properties ───────────────────────────────────────────

    async showProperties() {
        if (!this.selectedItem) return;
        try {
            const data = await this.api('GET', `/info?path=${encodeURIComponent(this.selectedItem)}`);
            const body = document.getElementById('propertiesBody');
            body.innerHTML = `
                <div class="fm-prop-row"><div class="fm-prop-label">Name</div><div class="fm-prop-value">${this.escHtml(data.name)}</div></div>
                <div class="fm-prop-row"><div class="fm-prop-label">Path</div><div class="fm-prop-value">${this.escHtml(data.path)}</div></div>
                <div class="fm-prop-row"><div class="fm-prop-label">Type</div><div class="fm-prop-value">${data.is_dir ? 'Folder' : 'File'}</div></div>
                ${!data.is_dir ? `<div class="fm-prop-row"><div class="fm-prop-label">Size</div><div class="fm-prop-value">${data.size_human}</div></div>` : ''}
                ${data.is_dir && data.total_files !== undefined ? `<div class="fm-prop-row"><div class="fm-prop-label">Total Files</div><div class="fm-prop-value">${data.total_files}</div></div>
                <div class="fm-prop-row"><div class="fm-prop-label">Total Size</div><div class="fm-prop-value">${data.total_size_human}</div></div>` : ''}
                <div class="fm-prop-row"><div class="fm-prop-label">Modified</div><div class="fm-prop-value">${data.modified}</div></div>
                <div class="fm-prop-row"><div class="fm-prop-label">Created</div><div class="fm-prop-value">${data.created}</div></div>
                ${data.extension ? `<div class="fm-prop-row"><div class="fm-prop-label">Extension</div><div class="fm-prop-value">${data.extension}</div></div>` : ''}
            `;
            document.getElementById('propertiesPanel').style.display = 'block';
        } catch (e) { /* toast */ }
    },

    closeProperties() {
        document.getElementById('propertiesPanel').style.display = 'none';
    },

    // ── Context Menu ─────────────────────────────────────────

    showContextMenu(e, path, isDir) {
        e.preventDefault();
        e.stopPropagation();
        this.selectedItem = path;

        // Highlight card
        document.querySelectorAll('.fm-file-card.selected').forEach(c => c.classList.remove('selected'));
        const card = document.querySelector(`[data-path="${CSS.escape(path)}"]`) ||
                     e.target.closest('.fm-file-card');
        if (card) card.classList.add('selected');
        this.updateToolbarButtons();

        const menu = document.getElementById('contextMenu');
        menu.style.display = 'block';
        menu.style.left = Math.min(e.clientX, window.innerWidth - 200) + 'px';
        menu.style.top = Math.min(e.clientY, window.innerHeight - 250) + 'px';
    },

    hideContextMenu() {
        document.getElementById('contextMenu').style.display = 'none';
    },

    // ── Search ───────────────────────────────────────────────

    async handleSearch() {
        const query = document.getElementById('searchInput').value.trim().toLowerCase();
        if (!query) {
            this.renderFiles(this.items);
            return;
        }
        const filtered = this.items.filter(i => i.name.toLowerCase().includes(query));
        this.renderFiles(filtered);
    },

    // ── View ─────────────────────────────────────────────────

    setView(mode) {
        this.viewMode = mode;
        document.getElementById('viewGrid').classList.toggle('active', mode === 'grid');
        document.getElementById('viewList').classList.toggle('active', mode === 'list');
        this.renderFiles(this.items);
    },

    refresh() {
        if (this.currentPath) this.navigate(this.currentPath);
    },

    // ── Keyboard ─────────────────────────────────────────────

    handleKeyboard(e) {
        if (e.target.tagName === 'INPUT') return;

        if (e.key === 'Delete' && this.selectedItem) {
            e.preventDefault();
            this.deleteSelected();
        } else if (e.key === 'F2' && this.selectedItem) {
            e.preventDefault();
            this.renameSelected();
        } else if (e.ctrlKey && e.key === 'c' && this.selectedItem) {
            e.preventDefault();
            this.copySelected();
        } else if (e.ctrlKey && e.key === 'v' && this.clipboard) {
            e.preventDefault();
            this.pasteClipboard();
        } else if (e.key === 'Backspace') {
            e.preventDefault();
            this.goUp();
        } else if (e.key === 'F5') {
            e.preventDefault();
            this.refresh();
        } else if (e.key === 'Escape') {
            this.closePreview();
            this.closeProperties();
            this.hideContextMenu();
        }
    },

    goUp() {
        if (!this.currentPath) return;
        const sep = this.currentPath.includes('/') ? '/' : '\\';
        const parts = this.currentPath.split(sep);
        if (parts.length > 1) {
            parts.pop();
            const parent = parts.join(sep);
            if (parent) this.navigate(parent);
        }
    },

    // ── Helpers ───────────────────────────────────────────────

    updateStatus(data) {
        document.getElementById('statusInfo').textContent = data.path || '';
        document.getElementById('statusCount').textContent =
            `${data.dirs || 0} folders, ${data.files || 0} files`;
    },

    toast(msg, type = 'info') {
        const container = document.getElementById('toastContainer');
        const icons = { success: 'check_circle', error: 'error', info: 'info' };
        const el = document.createElement('div');
        el.className = `fm-toast ${type}`;
        el.innerHTML = `<span class="material-icons-round">${icons[type]}</span>${this.escHtml(msg)}`;
        container.appendChild(el);
        setTimeout(() => { el.style.opacity = 0; setTimeout(() => el.remove(), 300); }, 3000);
    },

    escHtml(s) {
        const d = document.createElement('div');
        d.textContent = s || '';
        return d.innerHTML;
    },

    debounce(fn, ms) {
        let timer;
        return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
    },
};

// ── Boot ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => FM.init());
