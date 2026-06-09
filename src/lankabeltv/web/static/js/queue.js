/**
 * queue.js - Netflix Style Download queue management for LankabelTV
 */

import API from './api.js';
import { UI, escapeHtml, showNotification } from './ui.js';

export const Queue = {
    state: {
        progressInterval: null,
        currentQueueIdToCancel: null,
        expandedJobs: new Set()
    },

    elements: {
        downloadBadge: document.getElementById('download-badge'),
        downloadsView: document.getElementById('downloads-view'),
        downloadsEmptyState: document.getElementById('downloads-empty-state'),
        activeDownloads: document.getElementById('active-downloads'),
        completedDownloads: document.getElementById('completed-downloads'),
        activeQueueList: document.getElementById('active-queue-list'),
        completedQueueList: document.getElementById('completed-queue-list')
    },

    async checkStatus() {
        console.log(`[Q-FRONTEND] ${new Date().toISOString()} checkStatus() called`);
        try {
            const data = await API.getQueueStatus();
            console.log(`[Q-FRONTEND] checkStatus() response:`, data);
            if (data.success && data.queue && (data.queue.active.length > 0 || data.queue.completed.length > 0)) {
                console.log(`[Q-FRONTEND] checkStatus() found ${data.queue.active.length} active, ${data.queue.completed.length} completed - starting tracking`);
                this.startTracking();
            } else {
                console.log(`[Q-FRONTEND] checkStatus() no active or completed downloads - skipping tracking`);
            }
        } catch (err) { console.error('[Q-FRONTEND] Failed to check queue status:', err); }
    },

    startTracking() {
        if (this.state.progressInterval) {
            console.log(`[Q-FRONTEND] startTracking() - already tracking, skipping`);
            return;
        }
        console.log(`[Q-FRONTEND] ${new Date().toISOString()} startTracking() - starting 2s polling interval`);
        this.updateDisplay();
        this.state.progressInterval = setInterval(() => this.updateDisplay(), 2000);
    },

    init() {
        // Initial setup if needed
    },

    async updateDisplay() {
        const updateId = `upd-${Date.now()}-${Math.random().toString(36).substr(2, 5)}`;
        const updateStartTime = performance.now();
        try {
            const data = await API.getQueueStatus();
            const apiTime = performance.now() - updateStartTime;
            if (!data.success) {
                console.warn(`[Q-FRONTEND] [${updateId}] ${apiTime.toFixed(2)}ms updateDisplay() API returned success=false:`, data);
                return;
            }
            const active = data.queue.active || [];
            const completed = data.queue.completed || [];
            const totalTime = performance.now() - updateStartTime;
            console.log(`[Q-FRONTEND] [${updateId}] ${apiTime.toFixed(2)}ms API / ${totalTime.toFixed(2)}ms total - ${active.length} active, ${completed.length} completed`);

            if (this.elements.downloadBadge) {
                if (active.length > 0) {
                    this.elements.downloadBadge.textContent = active.length;
                    this.elements.downloadBadge.style.display = 'inline-block';
                } else {
                    this.elements.downloadBadge.style.display = 'none';
                }
            }
            
            if (active.length === 0 && completed.length === 0) {
                if (this.elements.downloadsEmptyState) this.elements.downloadsEmptyState.style.display = 'block';
                if (this.elements.activeDownloads) this.elements.activeDownloads.style.display = 'none';
                if (this.elements.completedDownloads) this.elements.completedDownloads.style.display = 'none';
            } else {
                if (this.elements.downloadsEmptyState) this.elements.downloadsEmptyState.style.display = 'none';
                
                if (active.length > 0) {
                    if (this.elements.activeDownloads) this.elements.activeDownloads.style.display = 'block';
                    this.updateQueueList(this.elements.activeQueueList, active, 'active');
                } else if (this.elements.activeDownloads) {
                    this.elements.activeDownloads.style.display = 'none';
                }
                
                if (completed.length > 0) {
                    if (this.elements.completedDownloads) this.elements.completedDownloads.style.display = 'block';
                    this.updateQueueList(this.elements.completedQueueList, completed, 'completed');
                } else if (this.elements.completedDownloads) {
                    this.elements.completedDownloads.style.display = 'none';
                }
            }
        } catch (err) { console.error('Failed to update queue display:', err); }
    },

    updateQueueList(container, items) {
        if (!container) return;

        const currentIds = items.map(item => item.id.toString());

        // Remove items that are no longer in the list
        const existingItems = Array.from(container.querySelectorAll('.queue-item'));
        existingItems.forEach(el => {
            if (!currentIds.includes(el.dataset.id)) {
                console.log(`[Q-FRONTEND] Removing item ${el.dataset.id} from UI (no longer in server response)`);
                el.remove();
            }
        });

        items.forEach(item => {
            let qItem = container.querySelector(`.queue-item[data-id="${item.id}"]`);
            const prog = Math.max(0, Math.min(100, parseFloat(item.progress_percentage || 0)));
            const isCompleted = item.status === 'completed' || item.status === 'failed';
            const isExpanded = this.state.expandedJobs.has(item.id);

            if (!qItem) {
                console.log(`[Q-FRONTEND] Creating new queue item UI for job ${item.id}:`, {
                    status: item.status,
                    progress: prog,
                    current_episode: item.current_episode,
                    completed: item.completed_episodes,
                    total: item.total_episodes
                });
                qItem = document.createElement('div');
                qItem.className = 'queue-item';
                qItem.dataset.id = item.id;
                container.appendChild(qItem);
                
                // Static content
                qItem.innerHTML = `
                    <div class="queue-item-header">
                        <div style="display:flex; align-items:center; gap:12px;">
                            <button class="expand-job-btn" title="Show details">
                                <i class="fas fa-chevron-right"></i>
                            </button>
                            <div class="queue-item-title"></div>
                        </div>
                        <div class="header-actions" style="display:flex; align-items:center; gap:15px;">
                            <span class="queue-item-status"></span>
                            <div class="action-buttons"></div>
                        </div>
                    </div>
                    <div class="queue-progress-bar">
                        <div class="queue-progress-fill"></div>
                    </div>
                    <div class="queue-progress-text"></div>
                    <div class="queue-episode-list" style="display: none;"></div>
                `;

                qItem.querySelector('.expand-job-btn').addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.toggleJobExpansion(item.id, qItem);
                });
            }

            // Update dynamic parts
            const titleEl = qItem.querySelector('.queue-item-title');
            if (titleEl.textContent !== item.anime_title) titleEl.textContent = item.anime_title;
            const statusEl = qItem.querySelector('.queue-item-status');
            statusEl.textContent = item.status;
            statusEl.className = `queue-item-status ${item.status}`;
            
            const actionBtns = qItem.querySelector('.action-buttons');
            const btnHtml = !isCompleted ? 
                `<button class="card-icon-btn stop-btn" title="Stop"><i class="fas fa-stop"></i></button>` : 
                `<button class="card-icon-btn delete-btn" title="Remove"><i class="fas fa-trash"></i></button>`;
            
            if (actionBtns.innerHTML !== btnHtml) {
                actionBtns.innerHTML = btnHtml;
                actionBtns.querySelector('.stop-btn')?.addEventListener('click', (e) => {
                    e.stopPropagation();
                    console.log(`[DEBUG] STOP button clicked for Job ID: ${item.id}`);
                    this.executeCancel(item.id);
                });
                actionBtns.querySelector('.delete-btn')?.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.executeDelete(item.id);
                });
            }

            qItem.querySelector('.queue-progress-fill').style.width = `${prog}%`;
            const epMsg = item.current_episode ? escapeHtml(item.current_episode) : '';
            const isPostProcessing = epMsg.toLowerCase().includes('post-processing') || epMsg.toLowerCase().includes('finalizing');
            const epStatusBadge = isPostProcessing
                ? ` • <span style="color:#4fc3f7; font-weight:600;">${epMsg}</span>`
                : (epMsg ? ` • <span style="color:#eee;">${epMsg}</span>` : '');
            qItem.querySelector('.queue-progress-text').innerHTML = `
                ${prog.toFixed(1)}% • ${item.completed_episodes}/${item.total_episodes} Episodes${epStatusBadge}
            `;

            const list = qItem.querySelector('.queue-episode-list');
            const expandBtn = qItem.querySelector('.expand-job-btn');
            
            if (isExpanded) {
                list.style.display = 'block';
                expandBtn.classList.add('active');
                // Always refresh if expanded to show latest episode statuses (downloading, completed etc)
                this.loadEpisodes(item.id, qItem);
            } else {
                list.style.display = 'none';
                expandBtn.classList.remove('active');
            }
        });
    },

    async toggleJobExpansion(queueId, qItem) {
        const btn = qItem.querySelector('.expand-job-btn');
        const list = qItem.querySelector('.queue-episode-list');
        
        if (this.state.expandedJobs.has(queueId)) {
            this.state.expandedJobs.delete(queueId);
            btn.classList.remove('active');
            list.style.display = 'none';
        } else {
            this.state.expandedJobs.add(queueId);
            btn.classList.add('active');
            list.style.display = 'block';
            if (!list.innerHTML.trim()) {
                await this.loadEpisodes(queueId, qItem);
            }
        }
    },

    async loadEpisodes(queueId, qItem) {
        const list = qItem.querySelector('.queue-episode-list');
        list.innerHTML = '<div style="padding:10px; text-align:center; color:#777;"><i class="fas fa-spinner fa-spin"></i> Loading episodes...</div>';
        
        try {
            const data = await API.getJobEpisodes(queueId);
            if (data.success) {
                this.renderEpisodes(queueId, list, data.episodes);
            } else {
                list.innerHTML = `<div style="padding:10px; color:var(--netflix-red);">${escapeHtml(data.error || 'Failed to load episodes')}</div>`;
            }
        } catch (err) {
            console.error('Failed to load episodes:', err);
            list.innerHTML = '<div style="padding:10px; color:var(--netflix-red);">Error loading episodes</div>';
        }
    },

    renderEpisodes(queueId, container, episodes) {
        console.log(`[DEBUG] renderEpisodes called for Job ${queueId} with ${episodes?.length} eps`);
        if (!episodes || episodes.length === 0) {
            container.innerHTML = '<div style="padding:10px; color:#777;">No episodes found</div>';
            return;
        }

        container.innerHTML = '';
        episodes.forEach((ep, index) => {
            const epEl = document.createElement('div');
            epEl.className = 'queue-episode-item';
            const isCompleted = ep.status === 'completed' || ep.status === 'failed' || ep.status === 'cancelled';
            // Map internal status to user-friendly label.
            let statusLabel = ep.status;
            let statusClass = ep.status;
            if (ep.status === 'downloading' && parseFloat(ep.progress) >= 99) {
                statusLabel = 'post-processing';
                statusClass = 'post-processing';
            }
            epEl.innerHTML = `
                <div class="ep-info">
                    <span class="ep-title">${escapeHtml(ep.title || ep.name || 'Episode ' + (index + 1))}</span>
                    <span class="ep-status-text ${statusClass}">${statusLabel}</span>
                </div>
                <div class="ep-actions">
                    ${!isCompleted ? `<button class="ep-stop-btn" title="Cancel Episode"><i class="fas fa-times"></i></button>` : ''}
                </div>
            `;
            
            const stopBtn = epEl.querySelector('.ep-stop-btn');
            if (stopBtn) {
                stopBtn.onclick = async (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    UI.showConfirmModal(
                        'Cancel Episode',
                        `Are you sure you want to cancel the download for <strong>${escapeHtml(ep.title || ep.name)}</strong>?`,
                        async () => {
                            try {
                                const res = await API.stopEpisode(queueId, ep.url);
                                if (res.success) {
                                    showNotification('Episode cancelled', 'info');
                                    ep.status = 'cancelled';
                                    this.renderEpisodes(queueId, container, episodes);
                                } else {
                                    showNotification(res.error || 'Failed to cancel episode', 'error');
                                }
                            } catch (err) { console.error(err); }
                        }
                    );
                };
            }
            
            container.appendChild(epEl);
        });
    },

    async executeDelete(queueId) {
        try {
            const data = await API.deleteDownload(queueId);
            if (data.success) this.updateDisplay();
            else showNotification(data.error || 'Failed to delete', 'error');
        } catch (err) { console.error('Delete error:', err); }
    },

    async executeCancel(queueId) {
        UI.showConfirmModal(
            'Cancel Download',
            'Are you sure you want to stop and cancel this entire download job?',
            async () => {
                try {
                    const data = await API.cancelDownload(queueId);
                    if (data.success) {
                        showNotification('Download stopped', 'info');
                        this.updateDisplay();
                    } else {
                        showNotification(data.error || 'Failed to cancel', 'error');
                    }
                } catch (err) { console.error('Cancel error:', err); }
            }
        );
    }
};
