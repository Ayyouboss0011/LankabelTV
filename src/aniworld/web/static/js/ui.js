/**
 * ui.js - UI helpers and theme management for LankabelTV Web Interface
 */

export function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;
    notification.setAttribute('role', type === 'error' ? 'alert' : 'status');
    document.body.appendChild(notification);
    setTimeout(() => notification.remove(), 4200);
}

export function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

export function escapeAttr(text) {
    return escapeHtml(text).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

export const UI = {
    elements: {
        homeContent: document.getElementById('home-content'),
        emptyState: document.getElementById('empty-state'),
        resultsSection: document.getElementById('results-section'),
        loadingSection: document.getElementById('loading-section'),
        themeIcon: document.getElementById('theme-icon'),
        navTitle: document.getElementById('nav-title')
    },

    showLoadingState() {
        if (this.elements.homeContent) this.elements.homeContent.style.display = 'none';
        if (this.elements.emptyState) this.elements.emptyState.style.display = 'none';
        if (this.elements.resultsSection) this.elements.resultsSection.style.display = 'none';
        if (this.elements.loadingSection) this.elements.loadingSection.style.display = 'block';
    },

    hideLoadingState() {
        if (this.elements.loadingSection) this.elements.loadingSection.style.display = 'none';
    },

    showResultsSection() {
        if (this.elements.homeContent) this.elements.homeContent.style.display = 'none';
        if (this.elements.emptyState) this.elements.emptyState.style.display = 'none';
        if (this.elements.loadingSection) this.elements.loadingSection.style.display = 'none';
        if (this.elements.resultsSection) this.elements.resultsSection.style.display = 'block';
    },

    showEmptyState() {
        if (this.elements.homeContent) this.elements.homeContent.style.display = 'none';
        if (this.elements.resultsSection) this.elements.resultsSection.style.display = 'none';
        if (this.elements.loadingSection) this.elements.loadingSection.style.display = 'none';
        if (this.elements.emptyState) this.elements.emptyState.style.display = 'block';
    },

    showHomeContent() {
        if (this.elements.resultsSection) this.elements.resultsSection.style.display = 'none';
        if (this.elements.loadingSection) this.elements.loadingSection.style.display = 'none';
        if (this.elements.emptyState) this.elements.emptyState.style.display = 'none';
        if (this.elements.homeContent) this.elements.homeContent.style.display = 'block';
    },

    initializeTheme() {
        const saved = localStorage.getItem('theme') || 'dark';
        this.setTheme(saved);
    },

    currentTheme() {
        return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
    },

    toggleTheme() {
        this.setTheme(this.currentTheme() === 'dark' ? 'light' : 'dark');
    },

    setTheme(theme) {
        const next = theme === 'light' ? 'light' : 'dark';
        document.documentElement.dataset.theme = next;
        document.body.dataset.theme = next;
        if (this.elements.themeIcon) {
            this.elements.themeIcon.className = next === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
        }
        const dropdownIcon = document.getElementById('theme-icon-dropdown');
        if (dropdownIcon) dropdownIcon.className = next === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
        localStorage.setItem('theme', next);
    }
};
