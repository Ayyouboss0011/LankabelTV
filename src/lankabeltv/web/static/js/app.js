/**
 * app.js - Main entry point for Netflix-style LankabelTV
 */

import API from './api.js';
import { UI, showNotification } from './ui.js';
import { Search } from './search.js';
import { Download } from './download.js';
import { Queue } from './queue.js';
import { Trackers } from './trackers.js';

document.addEventListener('DOMContentLoaded', async function() {
    console.log('LankabelTV Netflix-Style loaded');

    // UI Elements
    const tabHome = document.getElementById('tab-home');
    const tabDownloads = document.getElementById('tab-downloads');
    const mainView = document.getElementById('main-view');
    const downloadsView = document.getElementById('downloads-view');
    const navLogo = document.getElementById('nav-logo');
    const searchInput = document.getElementById('search-input');

    // Initialize modules
    UI.initializeTheme();
    await Download.init();
    Queue.init();
    Queue.checkStatus();
    Search.loadPopularAndNewAnime();

    // Event Listeners
    if (tabHome) tabHome.addEventListener('click', () => switchTab('home'));
    if (tabDownloads) tabDownloads.addEventListener('click', () => switchTab('downloads'));
    if (navLogo) navLogo.addEventListener('click', () => {
        switchTab('home');
        if (searchInput) searchInput.value = '';
        Search.showHome();
    });

    if (searchInput) {
        searchInput.addEventListener('input', debounce(() => {
            Search.performSearch();
        }, 500));
        
        searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') Search.performSearch();
        });
    }

    // Download modal listeners (Reusing existing IDs)
    document.getElementById('close-download-modal')?.addEventListener('click', () => Download.hideModal());
    document.getElementById('confirm-download')?.addEventListener('click', () => Download.startDownload());
    document.getElementById('select-all')?.addEventListener('click', () => Download.selectAll());
    document.getElementById('deselect-all')?.addEventListener('click', () => Download.deselectAll());

    // Tracker listeners
    document.getElementById('scan-trackers-btn')?.addEventListener('click', () => Trackers.scan());
    document.getElementById('close-tracker-modal')?.addEventListener('click', () => {
        document.getElementById('tracker-modal').style.display = 'none';
        document.body.classList.remove('modal-open');
    });
    document.getElementById('cancel-tracker-remove')?.addEventListener('click', () => {
        document.getElementById('tracker-modal').style.display = 'none';
        document.body.classList.remove('modal-open');
    });

    function switchTab(tabName) {
        if (tabName === 'home') {
            tabHome?.classList.add('active');
            tabDownloads?.classList.remove('active');
            if (mainView) mainView.style.display = 'block';
            if (downloadsView) downloadsView.style.display = 'none';
        } else {
            tabHome?.classList.remove('active');
            tabDownloads?.classList.add('active');
            if (mainView) mainView.style.display = 'none';
            if (downloadsView) downloadsView.style.display = 'block';
            Queue.startTracking();
            Trackers.updateDisplay();
        }
    }

    function debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    // Export showDownloadModal to window so anime cards can call it
    window.showDownloadModal = (title, epTitle, url) => Download.showModal(title, epTitle, url);
});

window.showNotification = showNotification;
