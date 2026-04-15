/**
 * api.js - Centralized API calls for LankabelTV Web Interface
 */

const API = {
    async getInfo() {
        const res = await fetch('/api/info');
        return await res.json();
    },

    async getLanguagePreferences() {
        const res = await fetch('/api/settings/language-preferences');
        return await res.json();
    },

    async getProviderPreferences() {
        const res = await fetch('/api/settings/provider-preferences');
        return await res.json();
    },

    async getDownloadPath() {
        const res = await fetch('/api/download-path');
        return await res.json();
    },

    async search(query, site) {
        const res = await fetch('/api/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, site })
        });
        if (res.status === 401) {
            window.location.href = '/login';
            return null;
        }
        return await res.json();
    },

    async getEpisodes(series_url, title = null) {
        const res = await fetch('/api/episodes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ series_url, title })
        });
        return await res.json();
    },

    async getEpisodeProviders(episode_url) {
        const res = await fetch('/api/episode/providers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ episode_url })
        });
        return await res.json();
    },

    async startDownload(downloadData) {
        const res = await fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(downloadData)
        });
        return await res.json();
    },

    async getQueueStatus() {
        const res = await fetch('/api/queue-status');
        return await res.json();
    },

    async cancelDownload(queue_id) {
        const res = await fetch('/api/download/cancel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ queue_id })
        });
        return await res.json();
    },

    async deleteDownload(queueId) {
        const res = await fetch(`/api/download/${queueId}`, {
            method: 'DELETE'
        });
        return await res.json();
    },

    async getTrackers() {
        const res = await fetch('/api/trackers');
        return await res.json();
    },

    async addTracker(trackerData) {
        const res = await fetch('/api/trackers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(trackerData)
        });
        return await res.json();
    },

    async deleteTracker(trackerId) {
        const res = await fetch(`/api/trackers/${trackerId}`, {
            method: 'DELETE'
        });
        return await res.json();
    },

    async scanTrackers() {
        const res = await fetch('/api/trackers/scan', {
            method: 'POST'
        });
        return await res.json();
    },

    async getPopularNew() {
        const res = await fetch('/api/popular-new');
        return await res.json();
    },

    async getJobEpisodes(queueId) {
        const res = await fetch(`/api/download/${queueId}/episodes`);
        return await res.json();
    },

    async reorderEpisodes(queueId, episodeUrls) {
        const res = await fetch(`/api/download/${queueId}/reorder`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ episode_urls: episodeUrls })
        });
        return await res.json();
    },

    async stopEpisode(queueId, episodeUrl) {
        const res = await fetch(`/api/download/${queueId}/episode/stop`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ episode_url: episodeUrl })
        });
        return await res.json();
    },

    async skipDownloadCandidate(queueId) {
        const res = await fetch(`/api/download/${queueId}/skip`, {
            method: 'POST'
        });
        return await res.json();
    }
};

export default API;
