/**
 * trackers.js - Series tracker management for LankabelTV Web Interface
 */

import API from './api.js';
import { escapeHtml, showNotification } from './ui.js';

export const Trackers = {
    elements: {
        trackersSection: document.getElementById('trackers-section'),
        trackersList: document.getElementById('trackers-list'),
        scanBtn: document.getElementById('scan-trackers-btn')
    },

    async scan() {
        if (!this.elements.scanBtn) return;
        this.elements.scanBtn.disabled = true;
        const originalText = this.elements.scanBtn.innerHTML;
        this.elements.scanBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Scanning...';
        
        try {
            const data = await API.scanTrackers();
            if (data.success) {
                showNotification('Tracker scan started', 'success');
                // Increase update frequency during scan
                if (this.scanInterval) clearInterval(this.scanInterval);
                this.scanInterval = setInterval(() => this.updateDisplay(), 2000);
                setTimeout(() => {
                    clearInterval(this.scanInterval);
                    this.scanInterval = null;
                }, 30000); // 30 seconds of high-freq updates
            } else {
                showNotification(data.error || 'Failed to start scan', 'error');
            }
        } catch (err) {
            console.error('Scan error:', err);
            showNotification('Failed to start scan', 'error');
        } finally {
            setTimeout(() => {
                this.elements.scanBtn.disabled = false;
                this.elements.scanBtn.innerHTML = originalText;
            }, 2000);
        }
    },

    async updateDisplay() {
        if (!this.elements.trackersSection) return;
        try {
            const data = await API.getTrackers();
            if (data.success && data.trackers && data.trackers.length > 0) {
                this.elements.trackersSection.style.display = 'block';
                
                // Handle debug messages
                data.trackers.forEach(t => {
                    if (t.debug_messages && t.debug_messages.length > 0) {
                        t.debug_messages.forEach(msg => {
                            if (msg.includes('ERROR:')) console.error(msg);
                            else console.log(msg);
                        });
                    }
                });

                this.render(data.trackers);
            } else {
                this.elements.trackersSection.style.display = 'block';
                if (this.elements.trackersList) {
                    this.elements.trackersList.innerHTML = '<div class="empty-state-small" style="grid-column: 1/-1; text-align: center; padding: 20px; opacity: 0.6;"><p>No active trackers</p></div>';
                }
            }
        } catch (error) {
            console.error('Error loading trackers:', error);
            this.elements.trackersSection.style.display = 'none';
        }
    },

    render(trackers) {
        if (!this.elements.trackersList) return;
        
        // Use a more persistent approach to avoid flickering but allow animations
        const currentItems = Array.from(this.elements.trackersList.querySelectorAll('.queue-item'));
        const newTrackerIds = trackers.map(t => String(t.id));

        // Remove items that are no longer present
        currentItems.forEach(item => {
            if (!newTrackerIds.includes(item.dataset.id)) item.remove();
        });

        trackers.forEach(t => {
            let item = currentItems.find(el => el.dataset.id === String(t.id));
            const isNew = !item;
            if (isNew) {
                item = document.createElement('div');
                item.className = 'queue-item';
                item.dataset.id = t.id;
                this.elements.trackersList.appendChild(item);
            }

            const oldS = item.dataset.lastSeason || t.last_season;
            const oldE = item.dataset.lastEpisode || t.last_episode;
            const isScanning = t.is_scanning;

            item.innerHTML = `
                <div class="queue-item-header">
                    <div class="queue-item-title">
                        ${isScanning ? '<i class="fas fa-spinner fa-spin" style="margin-right: 8px; color: var(--accent-color);"></i>' : ''}
                        ${escapeHtml(t.anime_title)}
                    </div>
                    <button class="delete-tracker-btn" data-id="${t.id}" title="Remove Tracker" style="background: none; border: none; color: #f56565; cursor: pointer;">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
                <div class="queue-item-details">
                    Tracking: ${escapeHtml(t.language)} via ${escapeHtml(t.provider)}<br>
                    Last seen: <span class="last-seen-text">S${t.last_season} E${t.last_episode}</span>
                </div>
            `;

            // Animate episode counting if increased
            if (!isNew && (t.last_season > oldS || (t.last_season == oldS && t.last_episode > oldE))) {
                const textEl = item.querySelector('.last-seen-text');
                textEl.style.color = '#48bb78';
                textEl.style.fontWeight = 'bold';
                textEl.classList.add('pulse-animation');
            }

            item.dataset.lastSeason = t.last_season;
            item.dataset.lastEpisode = t.last_episode;

            item.querySelector('.delete-tracker-btn').addEventListener('click', () => {
                this.showDeleteConfirmation(t);
            });
            this.elements.trackersList.appendChild(item);
        });
    },

    showDeleteConfirmation(tracker) {
        const modal = document.getElementById('tracker-modal');
        const titleEl = document.getElementById('tracker-modal-title');
        const confirmBtn = document.getElementById('confirm-tracker-remove');
        const cancelBtn = document.getElementById('cancel-tracker-remove');
        const closeBtn = document.getElementById('close-tracker-modal');

        if (!modal || !titleEl || !confirmBtn) return;

        titleEl.textContent = tracker.anime_title;
        modal.style.display = 'flex';
        document.body.classList.add('modal-open');

        const closeModal = () => {
            modal.style.display = 'none';
            document.body.classList.remove('modal-open');
            // Cleanup event listeners
            confirmBtn.replaceWith(confirmBtn.cloneNode(true));
            cancelBtn.replaceWith(cancelBtn.cloneNode(true));
            closeBtn.replaceWith(closeBtn.cloneNode(true));
        };

        const onConfirm = async () => {
            try {
                const data = await API.deleteTracker(tracker.id);
                if (data.success) {
                    this.updateDisplay();
                    showNotification('Tracker removed', 'success');
                } else {
                    showNotification(data.error || 'Failed to remove tracker', 'error');
                }
            } catch (err) {
                console.error('Delete tracker error:', err);
                showNotification('Failed to remove tracker', 'error');
            }
            closeModal();
        };

        // We need to re-select after clone if we want to add listeners again, 
        // but easier to just use the clones or not clone and use once: true
        const newConfirmBtn = document.getElementById('confirm-tracker-remove');
        const newCancelBtn = document.getElementById('cancel-tracker-remove');
        const newCloseBtn = document.getElementById('close-tracker-modal');

        newConfirmBtn.addEventListener('click', onConfirm);
        newCancelBtn.addEventListener('click', closeModal);
        newCloseBtn.addEventListener('click', closeModal);
        
        // Close on clicking overlay
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeModal();
        }, { once: true });
    },

    async addTrackerForSeries(currentDownloadData, availableEpisodes, language, provider) {
        if (!currentDownloadData) return false;
        
        // Find the last episode specifically for the selected language
        let maxS = 0, maxE = 0;
        
        // Map language string to ID (same as in backend)
        const langMap = {
            "German Dub": 1,
            "German Sub": 3,
            "English Dub": 2,
            "English Sub": 2,
            "Language ID 1": 1,
            "Language ID 2": 2,
            "Language ID 3": 3,
        };
        const targetLangId = langMap[language];

        const seasonNums = Object.keys(availableEpisodes).map(Number).sort((a, b) => b - a);
        let found = false;
        
        // First try to find the latest episode WITH language info
        for (const sNum of seasonNums) {
            const episodes = availableEpisodes[sNum];
            if (episodes && episodes.length > 0) {
                const sortedEpisodes = [...episodes].sort((a, b) => b.episode - a.episode);
                for (const ep of sortedEpisodes) {
                    let hasLang = false;
                    if (ep.languages && Array.isArray(ep.languages)) {
                        hasLang = ep.languages.some(l => {
                            if (typeof l === 'number') return l === targetLangId;
                            if (typeof l === 'string') return l === language;
                            return false;
                        });
                    }
                    
                    if (hasLang) {
                        maxS = sNum;
                        maxE = Number(ep.episode) || 0;
                        found = true;
                        break;
                    }
                }
            }
            if (found) break;
        }

        // If specific language wasn't found, we DON'T fallback to the global last episode
        // because that causes the problem of downloading everything.
        // Instead, we use 0,0 or let the user decide.
        // But for safety during debugging, we'll keep the current "found" values.

        try {
            const data = await API.addTracker({
                anime_title: currentDownloadData.anime,
                series_url: currentDownloadData.url,
                language: language,
                provider: provider,
                last_season: maxS,
                last_episode: maxE
            });
            if (data.success) {
                showNotification('Tracker added successfully', 'success');
                this.updateDisplay();
                return true;
            } else {
                showNotification(data.error || 'Failed to add tracker', 'error');
                return false;
            }
        } catch (err) {
            console.error('Tracker error:', err);
            showNotification('Failed to add tracker', 'error');
            return false;
        }
    }
};
