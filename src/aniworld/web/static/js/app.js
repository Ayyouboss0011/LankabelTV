/**
 * app.js - Main entry point for LankabelTV Web Interface
 */

import API from './api.js';
import { UI, showNotification } from './ui.js';
import { Search } from './search.js';
import { Download } from './download.js';
import { Queue } from './queue.js';
import { Trackers } from './trackers.js';

document.addEventListener('DOMContentLoaded', async function () {
    const versionDisplay = document.getElementById('version-display');
    const tabHome = document.getElementById('tab-home');
    const tabDownloads = document.getElementById('tab-downloads');
    const mainView = document.getElementById('main-view');
    const downloadsView = document.getElementById('downloads-view');
    const themeToggle = document.getElementById('theme-toggle');
    const navTitle = document.getElementById('nav-title');
    const emptyGoSearch = document.getElementById('empty-go-search');

    let homeLoaded = false;

    UI.initializeTheme();
    await Download.init();
    Queue.init();
    loadVersionInfo();
    Queue.checkStatus();

    const initialQuery = new URLSearchParams(window.location.search).get('q');

    if (window.location.hash === '#downloads') {
        switchTab('downloads', false);
    } else if (initialQuery) {
        Search.elements.searchInput.value = initialQuery;
        Search.performSearch();
    } else {
        homeLoaded = true;
        Search.loadPopularAndNewAnime();
    }

    if (tabHome) tabHome.addEventListener('click', () => switchTab('home'));
    if (tabDownloads) tabDownloads.addEventListener('click', () => switchTab('downloads'));

    if (Search.elements.searchForm) {
        Search.elements.searchForm.addEventListener('submit', (event) => {
            event.preventDefault();
            Search.performSearch();
        });
    } else if (Search.elements.searchBtn) {
        Search.elements.searchBtn.addEventListener('click', () => Search.performSearch());
    }

    if (Trackers.elements.scanBtn) {
        Trackers.elements.scanBtn.addEventListener('click', () => Trackers.scan());
    }

    if (emptyGoSearch) {
        emptyGoSearch.addEventListener('click', () => switchTab('home'));
    }

    if (themeToggle) themeToggle.addEventListener('click', () => UI.toggleTheme());

    if (navTitle) {
        navTitle.addEventListener('click', function () {
            switchTab('home');
            if (Search.elements.searchInput) Search.elements.searchInput.value = '';
            UI.showHomeContent();
            Search.loadPopularAndNewAnime();
        });
    }

    document.getElementById('close-download-modal')?.addEventListener('click', () => Download.hideModal());
    document.getElementById('confirm-download')?.addEventListener('click', () => Download.startDownload());
    document.getElementById('select-all')?.addEventListener('click', () => Download.selectAll());
    document.getElementById('deselect-all')?.addEventListener('click', () => Download.deselectAll());

    window.addEventListener('popstate', () => {
        if (window.location.hash === '#downloads') switchTab('downloads', false);
        else switchTab('home', false);
    });

    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') return;

        const downloadModal = document.getElementById('download-modal');
        if (downloadModal && downloadModal.style.display !== 'none') {
            Download.hideModal();
            return;
        }

        ['stop-modal', 'tracker-modal'].forEach((id) => {
            const modal = document.getElementById(id);
            if (!modal || modal.style.display === 'none') return;
            modal.querySelector('.close-btn')?.click();
        });
    });

    async function loadVersionInfo() {
        try {
            const data = await API.getInfo();
            if (versionDisplay) versionDisplay.textContent = `v${data.version}`;
        } catch (error) {
            console.error('Failed to load version info:', error);
            if (versionDisplay) versionDisplay.textContent = 'v?.?.?';
        }
    }

    function switchTab(tabName, updateHistory = true) {
        const isDownloads = tabName === 'downloads';

        if (tabHome) {
            tabHome.classList.toggle('active', !isDownloads);
            tabHome.setAttribute('aria-selected', String(!isDownloads));
        }
        if (tabDownloads) {
            tabDownloads.classList.toggle('active', isDownloads);
            tabDownloads.setAttribute('aria-selected', String(isDownloads));
        }
        if (mainView) mainView.style.display = isDownloads ? 'none' : 'block';
        if (downloadsView) downloadsView.style.display = isDownloads ? 'block' : 'none';

        if (isDownloads) {
            Queue.startTracking();
            Trackers.updateDisplay();
        } else {
            UI.showHomeContent();
            if (!homeLoaded) {
                homeLoaded = true;
                Search.loadPopularAndNewAnime();
            }
        }

        if (updateHistory) {
            const nextHash = isDownloads ? '#downloads' : '#search';
            if (window.location.hash !== nextHash) {
                history.pushState(null, '', nextHash);
            }
        }
    }

    window.showDownloadModal = (title, epTitle, url) => Download.showModal(title, epTitle, url);
});

window.showNotification = showNotification;
