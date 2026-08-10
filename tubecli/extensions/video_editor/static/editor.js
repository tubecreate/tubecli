/**
 * Video Editor — Main Application Logic
 * Timeline interactions, API calls, file management, preview sync.
 */
;(function () {
    'use strict';

    // ── Configuration ──────────────────────────────────────
    const API = '/api/v1/video';
    const PIXELS_PER_SECOND = 100; // Timeline zoom base
    let zoomLevel = 1.0;
    let currentProject = null;
    let selectedMedia = null;
    let selectedClipId = null;
    let isPlaying = false;

    // ── DOM References ─────────────────────────────────────
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const els = {
        statusBadge: $('#statusBadge'),
        statusText: $('.status-text'),
        projectName: $('#projectNameInput'),
        videoPreview: $('#videoPreview'),
        previewPlaceholder: $('#previewPlaceholder'),
        timeDisplay: $('#timeDisplay'),
        mediaList: $('#mediaList'),
        mediaDropZone: $('#mediaDropZone'),
        fileInput: $('#fileInput'),
        effectsGrid: $('#effectsGrid'),
        tracksContainer: $('#tracksContainer'),
        timeRuler: $('#timeRuler'),
        playhead: $('#playhead'),
        zoomLevel: $('#zoomLevel'),
        volumeSlider: $('#volumeSlider'),
        exportSource: $('#exportSource'),
        toastContainer: $('#toastContainer'),
    };

    // ── Effects Catalog ────────────────────────────────────
    const EFFECTS = [
        { id: 'grayscale', icon: '🔲', label: 'Grayscale' },
        { id: 'sepia', icon: '🟤', label: 'Sepia' },
        { id: 'blur', icon: '🌫️', label: 'Blur' },
        { id: 'sharpen', icon: '🔍', label: 'Sharpen' },
        { id: 'vintage', icon: '📷', label: 'Vintage' },
        { id: 'negative', icon: '🎞️', label: 'Negative' },
        { id: 'vignette', icon: '🔘', label: 'Vignette' },
        { id: 'noise', icon: '📺', label: 'Noise' },
        { id: 'speed_2x', icon: '⏩', label: 'Speed 2x' },
        { id: 'speed_0.5x', icon: '🐌', label: 'Slow 0.5x' },
        { id: 'rotate_90', icon: '↻', label: 'Rotate 90°' },
        { id: 'rotate_180', icon: '🔄', label: 'Rotate 180°' },
        { id: 'flip_h', icon: '↔️', label: 'Flip H' },
        { id: 'flip_v', icon: '↕️', label: 'Flip V' },
        { id: 'brightness_up', icon: '☀️', label: 'Bright +' },
        { id: 'brightness_down', icon: '🌙', label: 'Bright -' },
        { id: 'contrast_up', icon: '◑', label: 'Contrast +' },
        { id: 'contrast_down', icon: '◐', label: 'Contrast -' },
        { id: 'saturate', icon: '🎨', label: 'Saturate' },
        { id: 'desaturate', icon: '⚪', label: 'Desaturate' },
        { id: 'fade_in', icon: '▶️', label: 'Fade In' },
        { id: 'fade_out', icon: '⏹️', label: 'Fade Out' },
        { id: 'reverse', icon: '⏪', label: 'Reverse' },
        { id: 'stabilize', icon: '📐', label: 'Stabilize' },
    ];

    // ── Initialization ─────────────────────────────────────
    async function init() {
        if (typeof loadI18nFromApi === 'function') await loadI18nFromApi();
        checkFFmpegStatus();
        setupSidebarTabs();
        setupMediaUpload();
        setupEffectsGrid();
        setupPlaybackControls();
        setupTimelineControls();
        setupModals();
        setupKeyboardShortcuts();
        renderTimeline();
        setupTimelineDrag();
    }

    // ── Timeline Dragging ──────────────────────────────────
    function setupTimelineDrag() {
        let isDragging = false;
        const scrollArea = els.timelineScroll;
        const video = els.videoPreview;
        
        function updateFromEvent(e) {
            if (!video || !video.duration) return;
            const rect = scrollArea.getBoundingClientRect();
            // X relative to the timeline content (including scroll) minus track header
            const x = e.clientX - rect.left + scrollArea.scrollLeft - 80;
            if (x < 0) return;
            
            const pps = PIXELS_PER_SECOND * zoomLevel;
            let time = x / pps;
            time = Math.max(0, Math.min(time, video.duration || 100)); // Cap at duration if known
            
            video.currentTime = time;
            updatePlayheadPosition(time);
            
            // Re-render to show timeline effects maybe?
            renderTimeline();
        }

        els.playhead.addEventListener('mousedown', (e) => {
            isDragging = true;
            if(!isPlaying) updateFromEvent(e);
        });

        scrollArea.addEventListener('mousedown', (e) => {
            // Also scrub if clicking on the time ruler
            if(e.target.classList.contains('time-ruler') || e.target.classList.contains('ruler-mark')) {
                isDragging = true;
                if(!isPlaying) updateFromEvent(e);
            }
        });

        document.addEventListener('mousemove', (e) => {
            if (isDragging) {
                updateFromEvent(e);
            }
        });

        document.addEventListener('mouseup', () => {
             isDragging = false;
        });
    }

    // ── FFmpeg Status Check ────────────────────────────────
    async function checkFFmpegStatus() {
        try {
            const res = await fetch(`${API}/status`);
            if (res.status === 404) {
                els.statusBadge.classList.add('error');
                els.statusText.textContent = 'API offline (Please restart server)';
                return;
            }
            const data = await res.json();
            if (data.ffmpeg_installed) {
                els.statusBadge.classList.add('ready');
                els.statusBadge.classList.remove('error');
                els.statusText.textContent = `FFmpeg ✓ ${data.gpu_encoder || 'CPU'}`;
            } else {
                els.statusBadge.classList.add('error');
                els.statusText.textContent = 'FFmpeg not found (Install system FFmpeg)';
            }
        } catch {
            els.statusBadge.classList.add('error');
            els.statusText.textContent = 'API network error';
        }
    }

    // ── Sidebar Tabs ───────────────────────────────────────
    function setupSidebarTabs() {
        $$('.sidebar-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                $$('.sidebar-tab').forEach(t => t.classList.remove('active'));
                $$('.sidebar-panel').forEach(p => p.classList.remove('active'));
                tab.classList.add('active');
                const panel = $(`.sidebar-panel[data-panel="${tab.dataset.tab}"]`);
                if (panel) panel.classList.add('active');
            });
        });
    }

    // ── Media Upload ───────────────────────────────────────
    function setupMediaUpload() {
        const dropZone = els.mediaDropZone;
        const fileInput = els.fileInput;

        dropZone.addEventListener('click', () => fileInput.click());

        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });
        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('dragover');
        });
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            handleFiles(e.dataTransfer.files);
        });

        fileInput.addEventListener('change', () => {
            handleFiles(fileInput.files);
            fileInput.value = '';
        });

        $('#btnUploadMedia').addEventListener('click', () => fileInput.click());
    }

    async function handleFiles(files) {
        for (const file of files) {
            const formData = new FormData();
            formData.append('file', file);
            if (currentProject) {
                formData.append('project_id', currentProject.id);
            }

            toast(`Uploading ${file.name}...`, 'info');
            try {
                const res = await fetch(`${API}/upload`, { method: 'POST', body: formData });
                if (res.status === 404) {
                    toast(`✗ Upload failed: Backend API not found! (Try restarting TubeCLI)`, 'error');
                    continue;
                }
                const data = await res.json();
                if (data.status === 'success') {
                    toast(`✓ ${file.name} uploaded`, 'success');
                    addMediaToList(data);
                } else {
                    toast(`✗ Upload failed: ${data.detail || 'unknown'}`, 'error');
                }
            } catch (err) {
                toast(`✗ Upload error: ${err.message}`, 'error');
            }
        }
    }

    function addMediaToList(data) {
        const info = data.info || {};
        const duration = info.duration ? formatTime(info.duration) : '';
        const resolution = info.width && info.height ? `${info.width}×${info.height}` : '';
        const meta = [duration, resolution, formatBytes(data.size)].filter(Boolean).join(' · ');
        const mediaId = data.media?.id || `m_${Date.now()}`;
        const mediaDuration = info.duration || 5;

        const item = document.createElement('div');
        item.className = 'media-item';
        item.dataset.mediaId = mediaId;
        item.dataset.path = data.path;
        item.dataset.filename = data.filename;
        item.dataset.duration = mediaDuration;

        const thumbDiv = document.createElement('div');
        thumbDiv.className = 'media-thumb';
        thumbDiv.style.cssText = 'background:linear-gradient(135deg,#6c5ce7 0%,#2d1b69 100%);display:flex;align-items:center;justify-content:center;font-size:14px;';
        thumbDiv.textContent = '🎬';

        const infoDiv = document.createElement('div');
        infoDiv.className = 'media-info';
        const nameDiv = document.createElement('div');
        nameDiv.className = 'media-name';
        nameDiv.title = data.filename;
        nameDiv.textContent = data.filename;
        const metaDiv = document.createElement('div');
        metaDiv.className = 'media-meta';
        metaDiv.textContent = meta;
        infoDiv.appendChild(nameDiv);
        infoDiv.appendChild(metaDiv);

        const actionsDiv = document.createElement('div');
        actionsDiv.className = 'media-actions';

        const addBtn = document.createElement('button');
        addBtn.className = 'btn-icon';
        addBtn.title = 'Add to timeline';
        addBtn.textContent = '+';
        addBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            // Automatically select the media so it loads in the preview player
            $$('.media-item').forEach(m => m.classList.remove('active'));
            item.classList.add('active');
            selectedMedia = { id: mediaId, path: data.path, filename: data.filename, duration: mediaDuration };
            loadPreview(data.path);
            
            window._editor.addToTimeline(mediaId, data.path, data.filename, mediaDuration);
        });

        const delBtn = document.createElement('button');
        delBtn.className = 'btn-icon';
        delBtn.title = 'Delete';
        delBtn.textContent = '🗑';
        delBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            item.remove();
        });

        actionsDiv.appendChild(addBtn);
        actionsDiv.appendChild(delBtn);

        item.appendChild(thumbDiv);
        item.appendChild(infoDiv);
        item.appendChild(actionsDiv);

        item.addEventListener('click', () => {
            $$('.media-item').forEach(m => m.classList.remove('active'));
            item.classList.add('active');
            selectedMedia = { id: mediaId, path: data.path, filename: data.filename, duration: mediaDuration };
            loadPreview(data.path);
        });

        els.mediaList.appendChild(item);
    }

    function loadPreview(path) {
        // Serve via API — extract filename from path
        const filename = path.replace(/\\/g, '/').split('/').pop();
        els.videoPreview.src = `${API}/files/${encodeURIComponent(filename)}`;
        els.videoPreview.load();
        els.previewPlaceholder.classList.add('hidden');
        els.exportSource.value = path;
    }

    // ── Effects Grid ───────────────────────────────────────
    function setupEffectsGrid() {
        els.effectsGrid.innerHTML = '';
        EFFECTS.forEach(effect => {
            const card = document.createElement('div');
            card.className = 'effect-card';
            card.dataset.id = effect.id;
            card.innerHTML = `
                <span class="effect-icon">${effect.icon}</span>
                <span class="effect-label">${effect.label}</span>
            `;
            card.addEventListener('click', () => applyEffect(effect.id));
            els.effectsGrid.appendChild(card);
        });
    }

    function updateActiveEffectsUI(effects = []) {
        $$('.effect-card').forEach(card => {
            if (effects.includes(card.dataset.id)) {
                card.classList.add('active');
            } else {
                card.classList.remove('active');
            }
        });
    }

    function updateVideoFilters(clip) {
        if (!els.videoPreview || !clip) return;
        let filterStr = '';
        let speed = 1.0;
        let rotateStr = '';

        (clip.effects || []).forEach(eff => {
            if (eff === 'grayscale') filterStr += 'grayscale(100%) ';
            else if (eff === 'sepia') filterStr += 'sepia(100%) ';
            else if (eff === 'blur') filterStr += 'blur(5px) ';
            else if (eff === 'sharpen') filterStr += 'contrast(150%) brightness(110%) ';
            else if (eff === 'vintage') filterStr += 'sepia(40%) contrast(120%) brightness(90%) hue-rotate(-10deg) ';
            else if (eff === 'negative') filterStr += 'invert(100%) ';
            else if (eff === 'noise') filterStr += 'contrast(120%) saturate(150%) ';
            else if (eff === 'speed_2x') speed = 2.0;
            else if (eff === 'speed_0.5x' || eff === 'speed_05x') speed = 0.5;
            else if (eff === 'rotate_90') rotateStr += 'rotate(90deg) ';
            else if (eff === 'rotate_180') rotateStr += 'rotate(180deg) ';
            else if (eff === 'flip_h') rotateStr += 'scaleX(-1) ';
            else if (eff === 'flip_v') rotateStr += 'scaleY(-1) ';
            else if (eff === 'brightness_up') filterStr += 'brightness(150%) ';
            else if (eff === 'brightness_down') filterStr += 'brightness(50%) ';
            else if (eff === 'contrast_up') filterStr += 'contrast(160%) ';
            else if (eff === 'contrast_down') filterStr += 'contrast(60%) ';
            else if (eff === 'saturate') filterStr += 'saturate(200%) ';
            else if (eff === 'desaturate') filterStr += 'saturate(0%) ';
        });

        els.videoPreview.style.filter = filterStr.trim();
        els.videoPreview.playbackRate = speed;

        // Apply Spatial Crop Simulation
        let scale = 1.0;
        let tx = 0, ty = 0;
        
        if (clip.crop && els.videoPreview.videoWidth) {
            scale = els.videoPreview.videoWidth / clip.crop.w;
            tx = -clip.crop.x;
            ty = -clip.crop.y;
            els.videoPreview.style.transformOrigin = '0 0';
        } else {
            els.videoPreview.style.transformOrigin = 'center center';
        }

        let transformStr = '';
        if (clip.crop) transformStr += `scale(${scale}) translate(${tx}px, ${ty}px) `;
        transformStr += rotateStr;
        
        els.videoPreview.style.transform = transformStr.trim();
    }

    async function applyEffect(effectId) {
        if (!selectedClipId) {
            toast('Lựa chọn một clip dưới timeline trước tiên!', 'error');
            return;
        }

        let targetClip = null;
        for (const track of timelineTracks) {
            targetClip = track.clips.find(c => c.id === selectedClipId);
            if(targetClip) break;
        }

        if(!targetClip) return;
        if (!targetClip.effects) targetClip.effects = [];

        if (targetClip.effects.includes(effectId)) {
            targetClip.effects = targetClip.effects.filter(e => e !== effectId);
            toast(`Đã gỡ bỏ hiệu ứng: ${effectId}`, 'info');
        } else {
            targetClip.effects.push(effectId);
            toast(`Áp dụng hiệu ứng: ${effectId}`, 'success');
        }

        renderTimeline();
        updateVideoFilters(targetClip);
        updateActiveEffectsUI(targetClip.effects);
    }

    // ── Text Overlay ───────────────────────────────────────
    function setupTextOverlay() {
        $('#btnAddText')?.addEventListener('click', async () => {
            if (!selectedMedia) {
                toast('Select a media file first', 'error');
                return;
            }
            const text = $('#overlayText').value.trim();
            if (!text) {
                toast('Enter text content', 'error');
                return;
            }
            toast('Adding text overlay...', 'info');
            try {
                const position = $('#overlayPosition').value;
                const res = await fetch(`${API}/overlay`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        input_file: selectedMedia.path,
                        overlay_type: 'text',
                        text: text,
                        fontsize: parseInt($('#overlayFontSize').value) || 36,
                        fontcolor: $('#overlayColor').value.replace('#', '0x'),
                        x: '10', y: '10',
                    }),
                });
                const data = await res.json();
                if (data.status === 'success') {
                    pollTask(data.task_id, 'Text overlay');
                }
            } catch (err) {
                toast(`Overlay error: ${err.message}`, 'error');
            }
        });
    }

    // ── Playback Controls ──────────────────────────────────
    function setupPlaybackControls() {
        const video = els.videoPreview;

        $('#btnPlayPause').addEventListener('click', () => {
            if (video.paused) {
                video.play();
                isPlaying = true;
                updatePlayPauseIcon(true);
            } else {
                video.pause();
                isPlaying = false;
                updatePlayPauseIcon(false);
            }
        });

        $('#btnStop').addEventListener('click', () => {
            video.pause();
            video.currentTime = 0;
            isPlaying = false;
            updatePlayPauseIcon(false);
        });

        // Toggle play/pause when clicking the video preview
        video.addEventListener('click', () => {
            $('#btnPlayPause').click();
        });

        // Make the empty state placeholder clickable to open upload dialog
        els.previewPlaceholder.addEventListener('click', () => {
            $('#fileInput').click();
        });

        video.addEventListener('timeupdate', () => {
            const current = formatTime(video.currentTime);
            const total = formatTime(video.duration || 0);
            els.timeDisplay.textContent = `${current} / ${total}`;
            updatePlayheadPosition(video.currentTime);
        });

        video.addEventListener('ended', () => {
            isPlaying = false;
            updatePlayPauseIcon(false);
        });

        // Volume
        els.volumeSlider.addEventListener('input', (e) => {
            video.volume = e.target.value / 100;
        });
        $('#btnVolumeToggle').addEventListener('click', () => {
            video.muted = !video.muted;
        });

        // Fullscreen
        $('#btnFullscreen').addEventListener('click', () => {
            const player = $('#previewPlayer');
            if (document.fullscreenElement) {
                document.exitFullscreen();
            } else {
                player.requestFullscreen?.();
            }
        });

        setupTextOverlay();
    }

    function updatePlayPauseIcon(playing) {
        const btn = $('#btnPlayPause');
        if (playing) {
            btn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>';
        } else {
            btn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>';
        }
    }

    // ── Timeline ───────────────────────────────────────────
    let timelineTracks = [
        { id: 'video-1', type: 'video', label: 'V1', clips: [] },
        { id: 'audio-1', type: 'audio', label: 'A1', clips: [] },
        { id: 'text-1',  type: 'text',  label: 'T1', clips: [] },
    ];

    function setupTimelineControls() {
        $('#btnZoomIn').addEventListener('click', () => {
            zoomLevel = Math.min(zoomLevel * 1.2, 5);
            els.zoomLevel.textContent = `${Math.round(zoomLevel * 100)}%`;
            renderTimeline();
        });
        $('#btnZoomOut').addEventListener('click', () => {
            zoomLevel = Math.max(zoomLevel / 1.2, 0.2);
            els.zoomLevel.textContent = `${Math.round(zoomLevel * 100)}%`;
            renderTimeline();
        });

        $('#btnAddTrack').addEventListener('click', () => {
            const idx = timelineTracks.filter(t => t.type === 'video').length + 1;
            timelineTracks.push({
                id: `video-${idx}`,
                type: 'video',
                label: `V${idx}`,
                clips: [],
            });
            renderTimeline();
        });

        $('#btnDeleteClip').addEventListener('click', deleteSelectedClip);
        $('#btnSplitClip').addEventListener('click', splitClip);
    }

    function splitClip() {
        if (!selectedClipId || !els.videoPreview) {
            toast('Lựa chọn một clip dưới timeline để cắt!', 'warning');
            return;
        }

        const splitTime = els.videoPreview.currentTime;
        let targetTrack = null;
        let targetClipIndex = -1;

        // Find track and clip
        for (const track of timelineTracks) {
            targetClipIndex = track.clips.findIndex(c => c.id === selectedClipId);
            if (targetClipIndex !== -1) {
                targetTrack = track;
                break;
            }
        }

        if (!targetTrack) return;
        const clip = targetTrack.clips[targetClipIndex];

        // Check if split point is within the current clip bounds
        if (splitTime <= clip.start + 0.1 || splitTime >= clip.end - 0.1) {
            toast('Vị trí cắt quá sát viền clip!', 'warning');
            return;
        }

        // Create the second half of the clip
        const clip2 = JSON.parse(JSON.stringify(clip));
        clip2.id = `clip-${Date.now()}`;
        clip2.start = splitTime;
        clip2.offset = clip.offset + (splitTime - clip.start);
        
        // Truncate the first half
        clip.end = splitTime;

        // Insert exactly after the original clip
        targetTrack.clips.splice(targetClipIndex + 1, 0, clip2);
        
        toast('Đã tách clip thành công!', 'success');
        renderTimeline();
    }

    function renderTimeline() {
        renderTimeRuler();
        renderTracks();
    }

    function renderTimeRuler() {
        const ruler = els.timeRuler;
        ruler.innerHTML = '';
        const totalSeconds = getTimelineDuration();
        const pps = PIXELS_PER_SECOND * zoomLevel;
        const headerWidth = 80;

        ruler.style.width = `${headerWidth + totalSeconds * pps + 200}px`;

        for (let s = 0; s <= totalSeconds + 5; s++) {
            const mark = document.createElement('div');
            mark.className = 'ruler-mark' + (s % 5 === 0 ? ' major' : '');
            mark.style.left = `${headerWidth + s * pps}px`;
            if (s % 5 === 0) {
                mark.textContent = formatTimeShort(s);
            }
            ruler.appendChild(mark);
        }
    }

    function renderTracks() {
        const container = els.tracksContainer;
        container.innerHTML = '';
        const pps = PIXELS_PER_SECOND * zoomLevel;

        timelineTracks.forEach(track => {
            const row = document.createElement('div');
            row.className = 'track-row';

            row.innerHTML = `
                <div class="track-header">
                    <span class="track-type-dot ${track.type}"></span>
                    <span>${track.label}</span>
                </div>
                <div class="track-content" data-track-id="${track.id}"></div>
            `;

            const content = row.querySelector('.track-content');

            // Render clips
            track.clips.forEach(clip => {
                const clipEl = document.createElement('div');
                clipEl.className = `clip ${track.type}` + (clip.id === selectedClipId ? ' selected' : '');
                clipEl.dataset.clipId = clip.id;
                clipEl.style.left = `${clip.offset * pps}px`;
                clipEl.style.width = `${(clip.end - clip.start) * pps}px`;
                clipEl.textContent = clip.label;

                clipEl.innerHTML += `
                    <div class="clip-handle left"></div>
                    <div class="clip-handle right"></div>
                `;

                clipEl.addEventListener('click', (e) => {
                    e.stopPropagation();
                    selectClip(clip.id);
                });

                clipEl.draggable = true;
                
                clipEl.addEventListener('dragstart', (e) => {
                    if (e.target.classList.contains('clip-handle')) {
                        e.preventDefault();
                        return;
                    }
                    e.dataTransfer.setData('text/plain', clip.id);
                    e.dataTransfer.effectAllowed = 'move';
                    
                    // Keep track of the mouse click offset relative to the clip start
                    const rect = clipEl.getBoundingClientRect();
                    e.dataTransfer.setData('offsetX', (e.clientX - rect.left).toString());
                    
                    // Adding a ghost helps visual feedback
                    requestAnimationFrame(() => clipEl.style.opacity = '0.5');
                });

                clipEl.addEventListener('dragend', () => {
                    clipEl.style.opacity = '1';
                    renderTracks();
                });

                content.appendChild(clipEl);
            });

            // Allow dropping media onto track
            content.addEventListener('dragover', (e) => {
                e.preventDefault();
                content.style.background = 'rgba(108, 92, 231, 0.1)';
            });
            content.addEventListener('dragleave', () => {
                content.style.background = '';
            });
            content.addEventListener('drop', (e) => {
                e.preventDefault();
                content.style.background = '';
                const clipId = e.dataTransfer.getData('text/plain');
                if (!clipId) return;
                
                let sourceClip = null;
                let sourceTrack = null;
                for (const t of timelineTracks) {
                    const c = t.clips.find(cl => cl.id === clipId);
                    if (c) {
                        sourceClip = c;
                        sourceTrack = t;
                        break;
                    }
                }
                
                if (sourceClip && sourceTrack && track.type === sourceTrack.type) {
                    sourceTrack.clips = sourceTrack.clips.filter(c => c.id !== clipId);
                    
                    const offsetXText = e.dataTransfer.getData('offsetX') || '0';
                    const mouseInClipOffset = parseFloat(offsetXText);
                    
                    const rect = content.getBoundingClientRect();
                    const dropX = e.clientX - rect.left - mouseInClipOffset + els.timelineScroll.scrollLeft;
                    
                    sourceClip.offset = Math.max(0, dropX / pps);
                    sourceClip.track_id = track.id;
                    track.clips.push(sourceClip);
                    renderTracks();
                }
            });

            container.appendChild(row);
        });
    }

    function getTimelineDuration() {
        let maxEnd = 10;
        timelineTracks.forEach(track => {
            track.clips.forEach(clip => {
                const end = clip.offset + (clip.end - clip.start);
                if (end > maxEnd) maxEnd = end;
            });
        });
        return Math.ceil(maxEnd) + 5;
    }

    function updatePlayheadPosition(currentTime) {
        const pps = PIXELS_PER_SECOND * zoomLevel;
        const headerWidth = 80;
        els.playhead.style.left = `${headerWidth + currentTime * pps}px`;
    }

    // ── Add/Remove Clips ───────────────────────────────────
    window._editor = window._editor || {};

    window._editor.addToTimeline = function (mediaId, path, filename, duration) {
        duration = parseFloat(duration) || 5;
        // Find first video track
        const track = timelineTracks.find(t => t.type === 'video') || timelineTracks[0];

        // Calculate offset (end of last clip)
        const maxOffset = track.clips.reduce((max, c) => Math.max(max, c.offset + (c.end - c.start)), 0);

        const clip = {
            id: `clip_${Date.now().toString(36)}`,
            media_id: mediaId,
            path: path,
            track_id: track.id,
            start: 0,
            end: duration,
            offset: maxOffset,
            label: filename,
            effects: [],
        };
        track.clips.push(clip);
        renderTimeline();
        toast(`Added "${filename}" to timeline`, 'success');
    };

    window._editor.removeMedia = function (btn) {
        const item = btn.closest('.media-item');
        if (item) item.remove();
    };

    function selectClip(clipId) {
        selectedClipId = clipId;
        $$('.clip').forEach(c => c.classList.toggle('selected', c.dataset.clipId === clipId));
        
        // Find the clip by ID and load its path
        for (const track of timelineTracks) {
            const clip = track.clips.find(c => c.id === clipId);
            if (clip && clip.path) {
                loadPreview(clip.path);
                updateVideoFilters(clip);
                updateActiveEffectsUI(clip.effects);
                
                // Also update the properties panel
                const propsContent = $('#propsContent');
                $('#propsTitle').textContent = clip.label;
                if (propsContent) {
                    propsContent.innerHTML = `
                        <div class="form-group">
                            <label>File Name</label>
                            <input type="text" class="input" value="${clip.label}" readonly>
                        </div>
                        <div class="form-row">
                            <div class="form-group">
                                <label>Start</label>
                                <input type="number" class="input" id="propStart" value="${clip.start}" step="0.1">
                            </div>
                            <div class="form-group">
                                <label>End</label>
                                <input type="number" class="input" id="propEnd" value="${clip.end}" step="0.1">
                            </div>
                        </div>
                        <div class="form-group" style="margin-top: 10px; border-top: 1px solid var(--border-subtle); padding-top: 10px;">
                            <label>Crop / Zoom (X, Y, W, H)</label>
                            <div class="form-row">
                                <input type="number" class="input" id="propCropX" placeholder="X" value="${clip.crop ? clip.crop.x : ''}">
                                <input type="number" class="input" id="propCropY" placeholder="Y" value="${clip.crop ? clip.crop.y : ''}">
                            </div>
                            <div class="form-row" style="margin-top: 4px;">
                                <input type="number" class="input" id="propCropW" placeholder="W" value="${clip.crop ? clip.crop.w : ''}">
                                <input type="number" class="input" id="propCropH" placeholder="H" value="${clip.crop ? clip.crop.h : ''}">
                            </div>
                        </div>
                        <button class="btn btn-primary" id="btnApplyProps" style="width: 100%; margin-top: 10px;">Apply</button>
                    `;

                    setTimeout(() => {
                        const btnApplyProps = $('#btnApplyProps');
                        if(btnApplyProps) {
                            btnApplyProps.addEventListener('click', () => {
                                const propStart = $('#propStart');
                                const propEnd = $('#propEnd');
                                const propCropX = $('#propCropX');
                                const propCropY = $('#propCropY');
                                const propCropW = $('#propCropW');
                                const propCropH = $('#propCropH');

                                clip.start = parseFloat(propStart.value) || 0;
                                clip.end = parseFloat(propEnd.value) || 5;
                                
                                const cx = propCropX.value;
                                const cy = propCropY.value;
                                const cw = propCropW.value;
                                const ch = propCropH.value;
                                if (cx && cy && cw && ch) {
                                    clip.crop = { x: parseInt(cx), y: parseInt(cy), w: parseInt(cw), h: parseInt(ch) };
                                } else {
                                    clip.crop = null;
                                }

                                renderTimeline();
                                updateVideoFilters(clip);
                                toast('Đã cập nhật thuộc tính clip', 'success');
                            });
                        }
                    }, 50);
                }
                break;
            }
        }
    }

    function deleteSelectedClip() {
        if (!selectedClipId) return;
        timelineTracks.forEach(track => {
            track.clips = track.clips.filter(c => c.id !== selectedClipId);
        });
        selectedClipId = null;
        renderTimeline();
        toast('Clip deleted', 'info');
    }

    // ── Task Polling ───────────────────────────────────────
    async function pollTask(taskId, label) {
        const poll = async () => {
            try {
                const res = await fetch(`${API}/task/${taskId}`);
                const data = await res.json();
                const task = data.task;

                if (task.status === 'done') {
                    toast(`✓ ${label} completed`, 'success');
                    // Add result to media list if it has an output file
                    if (task.result?.output) {
                        addMediaToList({
                            filename: task.result.output.split(/[\\/]/).pop(),
                            path: task.result.output,
                            size: task.result.file_size || 0,
                            info: {},
                        });
                    }
                    return;
                }
                if (task.status === 'error') {
                    toast(`✗ ${label} failed: ${task.error}`, 'error');
                    return;
                }
                // Still running, poll again
                setTimeout(poll, 1000);
            } catch {
                toast(`✗ Status check failed for ${label}`, 'error');
            }
        };
        setTimeout(poll, 500);
    }

    // ── Modals ─────────────────────────────────────────────
    function setupModals() {
        // Open modals
        $('#btnExport').addEventListener('click', () => openModal('exportModal'));
        $('#btnOpenProject').addEventListener('click', () => {
            openModal('projectsModal');
            loadProjects();
        });
        $('#btnNewProject').addEventListener('click', createNewProject);
        $('#btnStartExport').addEventListener('click', startExport);

        // Close modals
        $$('.modal-close').forEach(btn => {
            btn.addEventListener('click', () => {
                const modalId = btn.dataset.modal || btn.closest('.modal-overlay')?.id;
                if (modalId) closeModal(modalId);
            });
        });

        // Close on backdrop click
        $$('.modal-overlay').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) closeModal(modal.id);
            });
        });
    }

    function openModal(id) { $(`#${id}`).classList.add('open'); }
    function closeModal(id) { $(`#${id}`).classList.remove('open'); }

    // ── Projects ───────────────────────────────────────────
    async function createNewProject() {
        const name = prompt('Project name:', 'New Project');
        if (!name) return;
        try {
            const res = await fetch(`${API}/projects`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name }),
            });
            const data = await res.json();
            if (data.status === 'success') {
                currentProject = data.project;
                els.projectName.value = name;
                toast(`Project "${name}" created`, 'success');
            }
        } catch (err) {
            toast(`Error: ${err.message}`, 'error');
        }
    }

    async function loadProjects() {
        const list = $('#projectsList');
        list.innerHTML = '<p class="empty-state">Loading...</p>';
        try {
            const res = await fetch(`${API}/projects`);
            const data = await res.json();
            if (!data.projects?.length) {
                list.innerHTML = '<p class="empty-state">No projects yet</p>';
                return;
            }
            list.innerHTML = '';
            data.projects.forEach(p => {
                const card = document.createElement('div');
                card.className = 'project-card';
                card.innerHTML = `
                    <div class="project-info">
                        <div class="project-title">${p.name}</div>
                        <div class="project-meta">${p.media_count || 0} files · ${new Date(p.created_at).toLocaleDateString()}</div>
                    </div>
                    <div class="project-actions">
                        <button class="btn btn-ghost" style="font-size:11px;">Open</button>
                        <button class="btn-icon" title="Delete" style="color: var(--error);">🗑</button>
                    </div>
                `;
                card.querySelector('.btn-ghost').addEventListener('click', () => {
                    loadProject(p.id);
                    closeModal('projectsModal');
                });
                card.querySelector('.btn-icon').addEventListener('click', async (e) => {
                    e.stopPropagation();
                    if (confirm(`Delete project "${p.name}"?`)) {
                        await fetch(`${API}/projects/${p.id}`, { method: 'DELETE' });
                        loadProjects();
                        toast(`Project "${p.name}" deleted`, 'info');
                    }
                });
                list.appendChild(card);
            });
        } catch {
            list.innerHTML = '<p class="empty-state">Failed to load projects</p>';
        }
    }

    async function loadProject(projectId) {
        try {
            const res = await fetch(`${API}/projects/${projectId}`);
            const data = await res.json();
            if (data.status === 'success') {
                currentProject = data.project;
                els.projectName.value = data.project.name;

                // Load media into sidebar
                els.mediaList.innerHTML = '';
                (data.project.media || []).forEach(m => {
                    addMediaToList({
                        filename: m.filename,
                        path: m.path,
                        size: 0,
                        info: { duration: m.duration, width: m.width, height: m.height },
                        media: m,
                    });
                });

                // Load timeline
                if (data.project.timeline?.tracks) {
                    timelineTracks = data.project.timeline.tracks;
                    renderTimeline();
                }

                toast(`Project "${data.project.name}" loaded`, 'success');
            }
        } catch (err) {
            toast(`Error Loading: ${err.message}`, 'error');
        }
    }

    // ── Export ──────────────────────────────────────────────
    async function startExport() {
        const source = els.exportSource.value;
        if (!source) {
            toast('Select a source file first', 'error');
            return;
        }

        const format = $('#exportFormat').value;
        const quality = $('#exportQuality').value;
        const resolution = $('#exportResolution').value;
        const fps = $('#exportFps').value;

        const progress = $('#exportProgress');
        progress.style.display = 'block';
        $('#exportProgressText').textContent = 'Starting export...';
        $('#exportProgressFill').style.width = '10%';

        try {
            const res = await fetch(`${API}/export`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    input_file: source,
                    format,
                    quality,
                    resolution: resolution || undefined,
                    fps: fps ? parseInt(fps) : undefined,
                    timeline: timelineTracks,
                }),
            });
            const data = await res.json();
            if (data.status === 'success') {
                $('#exportProgressFill').style.width = '30%';
                $('#exportProgressText').textContent = 'Processing...';
                pollExportTask(data.task_id);
            }
        } catch (err) {
            toast(`Export error: ${err.message}`, 'error');
            progress.style.display = 'none';
        }
    }

    async function pollExportTask(taskId) {
        const poll = async () => {
            try {
                const res = await fetch(`${API}/task/${taskId}`);
                const data = await res.json();
                const task = data.task;

                if (task.status === 'done') {
                    $('#exportProgressFill').style.width = '100%';
                    $('#exportProgressText').textContent = '✓ Export complete!';
                    toast('✓ Video exported successfully', 'success');
                    setTimeout(() => {
                        $('#exportProgress').style.display = 'none';
                        closeModal('exportModal');
                    }, 1500);
                    return;
                }
                if (task.status === 'error') {
                    $('#exportProgressText').textContent = `✗ Error: ${task.error}`;
                    toast(`Export failed: ${task.error}`, 'error');
                    return;
                }
                const p = Math.min(90, 30 + (task.progress || 0) * 0.6);
                $('#exportProgressFill').style.width = `${p}%`;
                setTimeout(poll, 1000);
            } catch {
                toast('Lost connection to export task', 'error');
            }
        };
        setTimeout(poll, 500);
    }

    // ── Keyboard Shortcuts ─────────────────────────────────
    function setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Don't handle shortcuts when typing in inputs
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;

            switch (e.key) {
                case ' ':
                    e.preventDefault();
                    $('#btnPlayPause').click();
                    break;
                case 'Delete':
                case 'Backspace':
                    deleteSelectedClip();
                    break;
                case '=':
                case '+':
                    if (e.ctrlKey) { e.preventDefault(); $('#btnZoomIn').click(); }
                    break;
                case '-':
                    if (e.ctrlKey) { e.preventDefault(); $('#btnZoomOut').click(); }
                    break;
            }
        });
    }

    // ── Utilities ──────────────────────────────────────────
    function formatTime(seconds) {
        if (!seconds || isNaN(seconds)) return '00:00:00';
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        return [h, m, s].map(v => String(v).padStart(2, '0')).join(':');
    }

    function formatTimeShort(seconds) {
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return `${m}:${String(s).padStart(2, '0')}`;
    }

    function formatBytes(bytes) {
        if (!bytes) return '';
        const units = ['B', 'KB', 'MB', 'GB'];
        let i = 0;
        let val = bytes;
        while (val >= 1024 && i < units.length - 1) { val /= 1024; i++; }
        return `${val.toFixed(1)} ${units[i]}`;
    }

    function toast(message, type = 'info') {
        const container = els.toastContainer;
        const t = document.createElement('div');
        t.className = `toast ${type}`;
        const icons = { success: '✓', error: '✗', info: 'ℹ', warning: '⚠' };
        t.innerHTML = `<span>${icons[type] || 'ℹ'}</span><span>${message}</span>`;
        container.appendChild(t);
        setTimeout(() => {
            t.style.opacity = '0';
            t.style.transform = 'translateX(100%)';
            t.style.transition = '0.3s ease';
            setTimeout(() => t.remove(), 300);
        }, 4000);
    }

    // ── Boot ───────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', init);
})();
