/**
 * Shared camera-selector helper for Mark Attendance / Registration pages.
 * Populates a <select> with active cameras from /api/cameras and remembers
 * the last pick per-browser in localStorage.
 *
 * A camera is either:
 *   - 'webcam': accessed locally via getUserMedia — no server involvement.
 *   - 'ip':     accessed via /api/camera/<id>/status|snapshot|stream.
 */
const CameraSelector = (() => {
    const STORAGE_KEY = 'attendance_selected_camera_id';

    async function populate(selectEl) {
        try {
            const res = await fetch('/api/cameras?active_only=1');
            const data = await res.json();
            if (!data.success || !data.cameras.length) return [];

            selectEl.innerHTML = '';
            data.cameras.forEach(cam => {
                const opt = document.createElement('option');
                opt.value = cam.id;
                opt.dataset.type = cam.camera_type;
                opt.textContent = cam.location ? `${cam.name} — ${cam.location}` : cam.name;
                selectEl.appendChild(opt);
            });

            const saved = localStorage.getItem(STORAGE_KEY);
            if (saved && data.cameras.some(c => String(c.id) === saved)) {
                selectEl.value = saved;
            }

            return data.cameras;
        } catch (e) {
            console.error('Failed to load cameras:', e);
            return [];
        }
    }

    function remember(cameraId) {
        try { localStorage.setItem(STORAGE_KEY, String(cameraId)); } catch (e) { /* ignore */ }
    }

    function selected(selectEl) {
        const opt = selectEl.selectedOptions[0];
        if (!opt) return null;
        return { id: opt.value, type: opt.dataset.type, label: opt.textContent };
    }

    return { populate, remember, selected };
})();
