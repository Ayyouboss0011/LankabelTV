/**
 * queue.js - Download queue management for LankabelTV Web Interface
 */

import API from './api.js';
import { escapeAttr, escapeHtml, showNotification } from './ui.js';
import { Trackers } from './trackers.js';

const STATUS_LABELS = {
    queued: 'Queued',
    downloading: 'Downloading',
    completed: 'Completed',
    failed: 'Failed',
    cancelled: 'Cancelled'
};

const statusLabel = (status) => STATUS_LABELS[status] || status;

export const Queue = {
    state: {
        progressInterval: null,
        currentQueueIdToCancel: null,
        isPolling: false
    },

    elements: {
        downloadBadge: document.getElementById('download-badge'),
        downloadsView: document.getElementById('downloads-view'),
        downloadsEmptyState: document.getElementById('downloads-empty-state'),
        activeDownloads: document.getElementById('active-downloads'),
        completedDownloads: document.getElementById('completed-downloads'),
        activeQueueList: document.getElementById('active-queue-list'),
        completedQueueList: document.getElementById('completed-queue-list'),
        activeCount: document.getElementById('active-count'),
        completedCount: document.getElementById('completed-count'),
        queueError: document.getElementById('queue-error'),
        stopModal: document.getElementById('stop-modal')
    },

    async checkStatus() {
        try {
            const data = await API.getQueueStatus();
            if (data.success && data.queue && (data.queue.active.length > 0 || data.queue.completed.length > 0)) {
                this.startTracking();
            }
        } catch (error) {
            console.error('Failed to check queue status:', error);
        }
    },

    startTracking() {
        if (this.state.progressInterval) return;
        this.updateDisplay();
        this.state.progressInterval = setInterval(() => this.updateDisplay(), 1000);
    },

    init() {
        if (!this.elements.stopModal) return;

        const cancelBtn = document.getElementById('cancel-stop');
        const closeBtn = document.getElementById('close-stop-modal');
        const confirmBtn = document.getElementById('confirm-stop');

        const closeModal = () => {
            this.elements.stopModal.style.display = 'none';
            document.body.classList.remove('modal-open');
        };

        cancelBtn?.addEventListener('click', closeModal);
        closeBtn?.addEventListener('click', closeModal);
        confirmBtn?.addEventListener('click', () => {
            this.executeCancel();
            closeModal();
        });
    },

    async updateDisplay() {
        if (this.state.isPolling) return;
        this.state.isPolling = true;

        try {
            const data = await API.getQueueStatus();
            if (!data.success) throw new Error(data.error || 'The queue did not load');

            if (this.elements.queueError) this.elements.queueError.style.display = 'none';

            const active = data.queue.active || [];
            const completed = data.queue.completed || [];
            Trackers.updateDisplay();

            if (this.elements.downloadBadge) {
                this.elements.downloadBadge.textContent = active.length;
                this.elements.downloadBadge.hidden = active.length === 0;
            }

            const isDownloadsVisible = this.elements.downloadsView?.style.display === 'block';

            if (active.length === 0 && completed.length === 0) {
                if (this.elements.downloadsEmptyState) this.elements.downloadsEmptyState.style.display = 'grid';
                if (this.elements.activeDownloads) this.elements.activeDownloads.style.display = 'none';
                if (this.elements.completedDownloads) this.elements.completedDownloads.style.display = 'none';
                if (this.elements.activeCount) this.elements.activeCount.textContent = '';
                if (this.elements.completedCount) this.elements.completedCount.textContent = '';

                if (!isDownloadsVisible && this.state.progressInterval) {
                    clearInterval(this.state.progressInterval);
                    this.state.progressInterval = null;
                }
                return;
            }

            if (this.elements.downloadsEmptyState) this.elements.downloadsEmptyState.style.display = 'none';

            if (active.length > 0) {
                if (this.elements.activeDownloads) this.elements.activeDownloads.style.display = 'grid';
                if (this.elements.activeCount) this.elements.activeCount.textContent = `${active.length} ${active.length === 1 ? 'job' : 'jobs'}`;
                this.updateQueueList(this.elements.activeQueueList, active);
            } else if (this.elements.activeDownloads) {
                this.elements.activeDownloads.style.display = 'none';
                if (this.elements.activeCount) this.elements.activeCount.textContent = '';
            }

            if (completed.length > 0) {
                if (this.elements.completedDownloads) this.elements.completedDownloads.style.display = 'grid';
                if (this.elements.completedCount) this.elements.completedCount.textContent = `${completed.length} ${completed.length === 1 ? 'job' : 'jobs'}`;
                this.updateQueueList(this.elements.completedQueueList, completed);
            } else if (this.elements.completedDownloads) {
                this.elements.completedDownloads.style.display = 'none';
                if (this.elements.completedCount) this.elements.completedCount.textContent = '';
            }
        } catch (error) {
            console.error('Failed to update queue display:', error);
            if (this.elements.downloadsEmptyState) this.elements.downloadsEmptyState.style.display = 'none';
            if (this.elements.activeDownloads) this.elements.activeDownloads.style.display = 'none';
            if (this.elements.completedDownloads) this.elements.completedDownloads.style.display = 'none';
            if (this.elements.queueError) this.elements.queueError.style.display = 'block';
        } finally {
            this.state.isPolling = false;
        }
    },

    updateQueueList(container, items) {
        if (!container) return;

        const currentIds = items.map(item => item.id.toString());
        Array.from(container.querySelectorAll('.queue-item')).forEach(element => {
            if (!currentIds.includes(element.dataset.id)) element.remove();
        });

        items.forEach(item => {
            let queueItem = container.querySelector(`.queue-item[data-id="${item.id}"]`);
            const isNew = !queueItem;
            const statusChanged = queueItem?.dataset.status !== item.status;

            if (isNew) {
                queueItem = document.createElement('div');
                queueItem.className = 'queue-item';
                queueItem.dataset.id = item.id;
                container.appendChild(queueItem);
            }

            const progress = Math.max(0, Math.min(100, parseFloat(item.progress_percentage || 0)));
            const isCompleted = item.status === 'completed' || item.status === 'failed';
            const isMovie = item.is_movie === true;
            const title = escapeHtml(item.anime_title);
            const titleAttr = escapeAttr(item.anime_title);
            const currentEpisode = escapeHtml(item.current_episode || '');

            if (isNew || statusChanged) {
                queueItem.dataset.status = item.status;
                queueItem.classList.remove('open');
                queueItem.setAttribute('aria-label', item.anime_title);
                queueItem.innerHTML = `
                    <div class="queue-item-header">
                        <button class="queue-item-title-wrapper" type="button" aria-expanded="false">
                            <i class="fas fa-chevron-right toggle-icon" aria-hidden="true"></i>
                            <span class="queue-item-title">${title}</span>
                        </button>
                        <div class="queue-actions-wrapper">
                            <span class="queue-item-status ${item.status}">${statusLabel(item.status)}</span>
                            ${!isCompleted && isMovie ? `<button class="change-server-btn" type="button" data-id="${item.id}" title="Switch to the next server" aria-label="Switch server for ${titleAttr}"><i class="fas fa-arrow-right-arrow-left" aria-hidden="true"></i></button>` : ''}
                            ${!isCompleted ? `<button class="stop-download-btn" type="button" data-id="${item.id}" title="Stop download" aria-label="Stop download for ${titleAttr}"><i class="fas fa-stop" aria-hidden="true"></i></button>` : ''}
                            ${isCompleted && item.status === 'failed' ? `<button class="retry-download-btn" type="button" data-id="${item.id}" title="Retry failed episodes">Retry</button>` : ''}
                            ${isCompleted ? `<button class="delete-download-btn" type="button" data-id="${item.id}" title="Remove from history" aria-label="Remove ${titleAttr} from history"><i class="fas fa-trash" aria-hidden="true"></i></button>` : ''}
                        </div>
                    </div>
                    <div class="queue-progress">
                        <div class="queue-progress-bar" role="progressbar" aria-label="Download progress for ${titleAttr}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${progress.toFixed(1)}">
                            <span class="queue-progress-fill ${item.status}" style="--progress: ${progress / 100}"></span>
                        </div>
                        <span class="queue-progress-text"><span>${progress.toFixed(1)}%</span><span class="episode-total">${item.completed_episodes}/${item.total_episodes} episodes</span></span>
                    </div>
                    <div class="queue-item-details">${currentEpisode}</div>
                    <div class="queue-item-episodes" style="display: none;">
                        <div class="loading-inline"><span class="spinner" aria-hidden="true"></span> Loading episodes…</div>
                    </div>
                `;

                const titleButton = queueItem.querySelector('.queue-item-title-wrapper');
                titleButton.addEventListener('click', () => {
                    const episodePanel = queueItem.querySelector('.queue-item-episodes');
                    const isNowOpen = queueItem.classList.toggle('open');
                    episodePanel.style.display = isNowOpen ? 'block' : 'none';
                    titleButton.setAttribute('aria-expanded', String(isNowOpen));
                    if (isNowOpen) this.loadJobEpisodes(item.id, episodePanel);
                });

                if (!isCompleted) {
                    queueItem.querySelector('.change-server-btn')?.addEventListener('click', (event) => {
                        event.stopPropagation();
                        this.executeChangeServer(item.id);
                    });
                    queueItem.querySelector('.stop-download-btn')?.addEventListener('click', (event) => {
                        event.stopPropagation();
                        this.state.currentQueueIdToCancel = item.id;
                        if (this.elements.stopModal) {
                            this.elements.stopModal.style.display = 'flex';
                            document.body.classList.add('modal-open');
                            document.getElementById('cancel-stop')?.focus();
                        }
                    });
                } else {
                    queueItem.querySelector('.retry-download-btn')?.addEventListener('click', (event) => {
                        event.stopPropagation();
                        this.executeRetry(item.id);
                    });
                    queueItem.querySelector('.delete-download-btn')?.addEventListener('click', () => {
                        this.executeDelete(item.id);
                    });
                }
            } else {
                const fill = queueItem.querySelector('.queue-progress-fill');
                if (fill) {
                    fill.className = `queue-progress-fill ${item.status}`;
                    fill.style.setProperty('--progress', String(progress / 100));
                }
                const track = queueItem.querySelector('.queue-progress-bar');
                if (track) track.setAttribute('aria-valuenow', progress.toFixed(1));

                const progressText = queueItem.querySelector('.queue-progress-text');
                if (progressText) {
                    progressText.innerHTML = `<span>${progress.toFixed(1)}%</span><span class="episode-total">${item.completed_episodes}/${item.total_episodes} episodes</span>`;
                }

                const details = queueItem.querySelector('.queue-item-details');
                if (details) details.textContent = item.current_episode || '';

                if (queueItem.classList.contains('open')) {
                    this.loadJobEpisodes(item.id, queueItem.querySelector('.queue-item-episodes'));
                }
            }
        });
    },

    async loadJobEpisodes(queueId, container) {
        if (!container) return;

        try {
            const data = await API.getJobEpisodes(queueId);
            if (!data.success) {
                container.innerHTML = '<div class="error-text">Failed to load episodes.</div>';
                return;
            }

            let episodeList = container.querySelector('.job-episodes-list');
            if (!episodeList) {
                container.innerHTML = '';
                episodeList = document.createElement('div');
                episodeList.className = 'job-episodes-list';
                container.appendChild(episodeList);
            }

            const currentUrls = data.episodes.map(episode => episode.url);
            const existingUrls = Array.from(episodeList.querySelectorAll('.job-episode-item')).map(element => element.dataset.url);

            if (JSON.stringify(currentUrls) !== JSON.stringify(existingUrls)) {
                episodeList.innerHTML = '';
                data.episodes.forEach((episode, index) => {
                    episodeList.appendChild(this.createEpisodeItem(queueId, episode, index, data.episodes.length, container));
                });
            } else {
                data.episodes.forEach(episode => {
                    const episodeItem = episodeList.querySelector(`.job-episode-item[data-url="${episode.url}"]`);
                    if (!episodeItem) return;

                    const isDownloading = episode.status === 'downloading';
                    const stats = episodeItem.querySelector('.ep-stats');
                    if (isDownloading) {
                        if (stats) stats.textContent = `${episode.speed || ''} ${episode.eta || ''}`.trim();
                    } else if (stats) {
                        stats.remove();
                    }

                    const statusText = episodeItem.querySelector('.ep-status-text');
                    if (statusText) {
                        statusText.className = `ep-status-text ${episode.status}`;
                        statusText.textContent = statusLabel(episode.status);
                    }

                    const progressValue = Math.max(0, Math.min(100, parseFloat(episode.progress || 0)));
                    const fill = episodeItem.querySelector('.ep-progress-fill');
                    if (fill) {
                        fill.className = `ep-progress-fill ${episode.status}`;
                        fill.style.setProperty('--progress', String(progressValue / 100));
                    }
                    const track = episodeItem.querySelector('.ep-progress-bar');
                    if (track) track.setAttribute('aria-valuenow', progressValue.toFixed(1));

                    const text = episodeItem.querySelector('.ep-progress-text');
                    if (text) text.textContent = `${progressValue.toFixed(1)}%`;
                });
            }
        } catch (error) {
            console.error('Failed to load job episodes:', error);
            container.innerHTML = '<div class="error-text">Failed to load episodes.</div>';
        }
    },

    createEpisodeItem(queueId, episode, index, totalCount, container) {
        const episodeItem = document.createElement('div');
        episodeItem.className = 'job-episode-item';
        episodeItem.dataset.url = episode.url;

        const canReorder = episode.status === 'queued';
        const isDownloading = episode.status === 'downloading';
        const isFinished = episode.status === 'completed' || episode.status === 'failed' || episode.status === 'cancelled';
        const progress = Math.max(0, Math.min(100, parseFloat(episode.progress || 0)));

        episodeItem.innerHTML = `
            <div class="ep-info-row">
                <div class="ep-info">
                    <span class="ep-name">${escapeHtml(episode.name)}</span>
                    ${isDownloading ? `<span class="ep-stats">${escapeHtml(episode.speed || '')} ${escapeHtml(episode.eta || '')}</span>` : ''}
                </div>
                <div class="ep-actions">
                    ${canReorder ? `
                        <button class="reorder-btn move-up" type="button" title="Move up" aria-label="Move ${escapeAttr(episode.name)} up" ${index === 0 ? 'disabled' : ''}><i class="fas fa-arrow-up" aria-hidden="true"></i></button>
                        <button class="reorder-btn move-down" type="button" title="Move down" aria-label="Move ${escapeAttr(episode.name)} down" ${index === totalCount - 1 ? 'disabled' : ''}><i class="fas fa-arrow-down" aria-hidden="true"></i></button>
                    ` : ''}
                    <span class="ep-status-text ${episode.status}">${statusLabel(episode.status)}</span>
                    ${!isFinished ? `<button class="ep-stop-btn" type="button" title="Stop episode" aria-label="Stop ${escapeAttr(episode.name)}"><i class="fas fa-xmark" aria-hidden="true"></i></button>` : ''}
                </div>
            </div>
            <div class="ep-progress-container">
                <div class="ep-progress-bar" role="progressbar" aria-label="Progress for ${escapeAttr(episode.name)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${progress.toFixed(1)}">
                    <span class="ep-progress-fill ${episode.status}" style="--progress: ${progress / 100}"></span>
                </div>
                <span class="ep-progress-text">${progress.toFixed(1)}%</span>
            </div>
        `;

        if (canReorder) {
            episodeItem.querySelector('.move-up')?.addEventListener('click', (event) => {
                event.stopPropagation();
                this.moveEpisode(queueId, index, -1, container);
            });
            episodeItem.querySelector('.move-down')?.addEventListener('click', (event) => {
                event.stopPropagation();
                this.moveEpisode(queueId, index, 1, container);
            });
        }

        episodeItem.querySelector('.ep-stop-btn')?.addEventListener('click', (event) => {
            event.stopPropagation();
            this.executeStopEpisode(queueId, episode.url, container);
        });

        return episodeItem;
    },

    async moveEpisode(queueId, index, direction, container) {
        try {
            const data = await API.getJobEpisodes(queueId);
            if (!data.success) return;
            const urls = data.episodes.map(episode => episode.url);
            const newIndex = index + direction;
            if (newIndex < 0 || newIndex >= urls.length) return;
            [urls[index], urls[newIndex]] = [urls[newIndex], urls[index]];
            const response = await API.reorderEpisodes(queueId, urls);
            if (response.success) this.loadJobEpisodes(queueId, container);
            else showNotification(response.error || 'Failed to reorder episodes', 'error');
        } catch (error) {
            console.error('Move error:', error);
        }
    },

    async executeStopEpisode(queueId, episodeUrl, container) {
        try {
            const response = await API.stopEpisode(queueId, episodeUrl);
            if (response.success) this.loadJobEpisodes(queueId, container);
            else showNotification(response.error || 'Failed to stop episode', 'error');
        } catch (error) {
            console.error('Stop episode error:', error);
        }
    },

    async executeDelete(queueId) {
        try {
            const data = await API.deleteDownload(queueId);
            if (data.success) this.updateDisplay();
            else showNotification(data.error || 'Failed to delete download', 'error');
        } catch (error) {
            console.error('Delete error:', error);
        }
    },

    async executeRetry(queueId) {
        try {
            const data = await API.retryDownload(queueId);
            if (data.success) {
                this.startTracking();
                this.updateDisplay();
            } else {
                showNotification(data.error || 'Failed to retry download', 'error');
            }
        } catch (error) {
            console.error('Retry error:', error);
        }
    },

    async executeCancel() {
        if (!this.state.currentQueueIdToCancel) return;
        try {
            const data = await API.cancelDownload(this.state.currentQueueIdToCancel);
            if (data.success) this.updateDisplay();
            else showNotification(data.error || 'Failed to stop download', 'error');
        } catch (error) {
            console.error('Cancel error:', error);
        }
    },

    async executeChangeServer(queueId) {
        try {
            const data = await API.skipDownloadCandidate(queueId);
            if (data.success) {
                this.updateDisplay();
            } else {
                showNotification(data.error || 'Failed to switch server', 'error');
            }
        } catch (error) {
            console.error('Change server error:', error);
        }
    }
};
