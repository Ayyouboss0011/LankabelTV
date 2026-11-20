/**
 * search.js - Search and discovery for LankabelTV Web Interface
 */

import API from './api.js';
import { UI, escapeAttr, escapeHtml, showNotification } from './ui.js';

export const Search = {
    elements: {
        searchForm: document.getElementById('searchForm'),
        searchInput: document.getElementById('search-input'),
        searchBtn: document.getElementById('search-btn'),
        resultsContainer: document.getElementById('results-container'),
        popularAnimeGrid: document.getElementById('popular-anime-grid'),
        newAnimeGrid: document.getElementById('new-anime-grid'),
        popularNewSections: document.getElementById('popular-new-sections'),
        homeLoading: document.getElementById('home-loading'),
        homeError: document.getElementById('home-error'),
        retryHome: document.getElementById('retry-home'),
        filterSection: document.getElementById('filter-section'),
        resultsCount: document.getElementById('results-count')
    },

    currentResults: [],
    currentFilter: 'all',

    init() {
        const filterBtns = document.querySelectorAll('.filter-btn');
        filterBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                filterBtns.forEach(b => {
                    b.classList.remove('active');
                    b.setAttribute('aria-pressed', 'false');
                });
                btn.classList.add('active');
                btn.setAttribute('aria-pressed', 'true');
                this.currentFilter = btn.dataset.filter;
                this.applyFilter();
            });
        });

        if (this.elements.retryHome) {
            this.elements.retryHome.addEventListener('click', () => {
                this.loadPopularAndNewAnime();
            });
        }
    },

    async performSearch() {
        const input = this.elements.searchInput;
        const button = this.elements.searchBtn;
        if (!input || !button) return;

        if (button.disabled) return;

        const query = input.value.trim();
        if (!query) {
            UI.showHomeContent();
            if (this.elements.filterSection) this.elements.filterSection.style.display = 'none';
            return;
        }

        const siteRadios = document.querySelectorAll('input[name="site"]');
        let selectedSite = 'both';
        siteRadios.forEach(radio => { if (radio.checked) selectedSite = radio.value; });

        this.currentFilter = 'all';
        document.querySelectorAll('.filter-btn').forEach(button => {
            const isAll = button.dataset.filter === 'all';
            button.classList.toggle('active', isAll);
            button.setAttribute('aria-pressed', String(isAll));
        });

        UI.showLoadingState();
        if (this.elements.filterSection) this.elements.filterSection.style.display = 'none';
        button.disabled = true;
        button.setAttribute('aria-busy', 'true');
        button.textContent = 'Searching…';

        try {
            const data = await API.search(query, selectedSite);
            if (!data) return;
            if (data.success) {
                this.currentResults = data.results || [];
                this.applyFilter();
                if (this.elements.filterSection) this.elements.filterSection.style.display = 'flex';
            } else {
                showNotification(data.error || 'Search failed', 'error');
                UI.showEmptyState();
            }
        } catch (error) {
            console.error('Search error:', error);
            showNotification('Search failed. Please try again.', 'error');
            UI.showEmptyState();
        } finally {
            button.disabled = false;
            button.removeAttribute('aria-busy');
            button.textContent = 'Search';
            UI.hideLoadingState();
        }
    },

    displaySearchResults(results) {
        if (!results || results.length === 0) {
            UI.showEmptyState();
            if (this.elements.resultsCount) this.elements.resultsCount.textContent = 'No results';
            return;
        }

        this.elements.resultsContainer.innerHTML = '';
        results.forEach(anime => {
            this.elements.resultsContainer.appendChild(this.createAnimeCard(anime));
        });

        if (this.elements.resultsCount) {
            this.elements.resultsCount.textContent = results.length === 1 ? '1 result' : `${results.length} results`;
        }
        UI.showResultsSection();
    },

    applyFilter() {
        let filtered = this.currentResults;
        if (this.currentFilter === 'series') {
            filtered = this.currentResults.filter(result => result.media_type !== 'movie');
        } else if (this.currentFilter === 'movies') {
            filtered = this.currentResults.filter(result => result.media_type === 'movie');
        }
        this.displaySearchResults(filtered);
    },

    createAnimeCard(anime) {
        const card = document.createElement('article');
        card.className = 'anime-card';

        let coverUrl = '';
        if (anime.cover) {
            coverUrl = anime.cover;
            if (!coverUrl.startsWith('http')) {
                const baseUrl = anime.base_url
                    || (anime.site === 's.to' ? 'https://serienstream.to'
                        : anime.site === 'megakino' ? 'https://megakino23.com'
                        : 'https://aniworld.to');
                if (coverUrl.startsWith('//')) coverUrl = 'https:' + coverUrl;
                else if (coverUrl.startsWith('/')) coverUrl = baseUrl + coverUrl;
                else coverUrl = baseUrl + '/' + coverUrl;
            }
            coverUrl = coverUrl.replace('150x225', '220x330');
        }

        const isMovie = anime.media_type === 'movie';
        const sourceLabel = anime.site === 's.to'
            ? 'S.to'
            : anime.site === 'megakino' ? 'MegaKino' : 'AniWorld';
        const typeLabel = isMovie ? 'Movie' : 'Series';

        card.innerHTML = `
            <div class="anime-card-poster">
                ${coverUrl
                    ? `<img src="${coverUrl}" alt="${escapeAttr(anime.title)} poster" width="220" height="330" loading="lazy">`
                    : `<div class="no-poster" aria-hidden="true"><i class="fas fa-film"></i></div>`}
            </div>
            <div class="anime-card-content">
                <div class="anime-card-meta">
                    <span class="site-badge ${escapeHtml(anime.site || 'aniworld.to').replace('.', '-')}">${sourceLabel}</span>
                    ${anime.release_date ? `<span class="release-date">${escapeHtml(anime.release_date)}</span>` : ''}
                    ${anime.rating ? `<span class="card-rating" title="Rating"><i class="fas fa-star" aria-hidden="true"></i> ${parseFloat(anime.rating).toFixed(1)}</span>` : ''}
                </div>
                <h3 class="anime-title">${escapeHtml(anime.title)}</h3>
                <p class="anime-info">${typeLabel}</p>
                <div class="anime-actions">
                    <button class="download-btn button button--secondary" type="button">
                        <span class="btn-text">Choose episodes</span>
                        <span class="spinner btn-loader" aria-hidden="true" hidden></span>
                    </button>
                </div>
            </div>
        `;

        this.attachImageFallback(card.querySelector('.anime-card-poster'), coverUrl);

        const downloadBtn = card.querySelector('.download-btn');
        if (downloadBtn) {
            downloadBtn.setAttribute('aria-label', `Choose episodes for ${anime.title}`);
            downloadBtn.addEventListener('click', (event) => {
                const button = event.currentTarget;
                if (button.classList.contains('loading')) return;

                if (window.showDownloadModal) {
                    button.classList.add('loading');
                    button.disabled = true;
                    const text = button.querySelector('.btn-text');
                    const loader = button.querySelector('.btn-loader');
                    if (text) text.hidden = true;
                    if (loader) loader.hidden = false;
                    window.showDownloadModal(anime.title, 'Series', anime.url);
                }
            });
        }

        return card;
    },

    async loadPopularAndNewAnime() {
        if (this.elements.homeLoading) this.elements.homeLoading.style.display = 'block';
        if (this.elements.homeError) this.elements.homeError.style.display = 'none';
        if (this.elements.popularNewSections) this.elements.popularNewSections.style.display = 'none';

        try {
            const data = await API.getPopularNew();
            if (data.success) {
                this.elements.popularAnimeGrid.innerHTML = '';
                this.elements.newAnimeGrid.innerHTML = '';
                (data.popular || []).slice(0, 8).forEach(anime => {
                    this.elements.popularAnimeGrid.appendChild(this.createHomeAnimeCard(anime));
                });
                (data.new || []).slice(0, 8).forEach(anime => {
                    this.elements.newAnimeGrid.appendChild(this.createHomeAnimeCard(anime));
                });
                this.elements.popularNewSections.style.display = 'block';
                UI.showHomeContent();
            } else {
                throw new Error(data.error || 'The shelves did not load');
            }
        } catch (error) {
            console.error('Failed to load popular/new anime:', error);
            if (this.elements.homeError) this.elements.homeError.style.display = 'grid';
        } finally {
            if (this.elements.homeLoading) this.elements.homeLoading.style.display = 'none';
        }
    },

    shortenTitle(title, maxLength = 38) {
        const clean = String(title || '').replace(/\s+/g, ' ').trim();
        if (clean.length <= maxLength) return clean;
        const cut = clean.slice(0, maxLength);
        const lastSpace = cut.lastIndexOf(' ');
        return `${lastSpace > maxLength * 0.6 ? cut.slice(0, lastSpace) : cut}…`;
    },

    attachImageFallback(container, coverUrl) {
        if (!container || !coverUrl) return;
        const image = container.querySelector('img');
        if (!image) return;

        const replaceImage = () => {
            if (image.dataset.fallbackApplied) return;
            image.dataset.fallbackApplied = 'true';
            image.remove();
            const fallback = document.createElement('span');
            fallback.className = 'no-poster';
            fallback.setAttribute('aria-hidden', 'true');
            fallback.innerHTML = '<i class="fas fa-film"></i>';
            container.appendChild(fallback);
        };

        image.addEventListener('error', replaceImage, {once: true});
        if (image.complete && image.naturalWidth === 0) replaceImage();
    },

    createHomeAnimeCard(anime) {
        const card = document.createElement('a');
        card.className = 'home-anime-card';
        const fullTitle = String(anime.name || anime.title || '');
        const shortTitle = this.shortenTitle(fullTitle);
        card.href = `?q=${encodeURIComponent(fullTitle)}#search`;
        card.title = fullTitle;
        const coverUrl = typeof anime.cover === 'string'
            ? anime.cover.replace('_150x225.png', '_220x330.png')
            : '';

        card.innerHTML = `
            <span class="home-anime-cover">
                ${coverUrl
                    ? `<img src="${coverUrl}" alt="${escapeAttr(fullTitle)} poster" width="220" height="330" loading="lazy">`
                    : `<span class="no-poster" aria-hidden="true"><i class="fas fa-film"></i></span>`}
            </span>
            <span class="home-anime-title">${escapeHtml(shortTitle)}</span>
        `;

        this.attachImageFallback(card.querySelector('.home-anime-cover'), coverUrl);

        card.setAttribute('aria-label', `Search for ${fullTitle}`);
        card.addEventListener('click', (event) => {
            event.preventDefault();
            if (this.elements.searchInput) this.elements.searchInput.value = fullTitle;
            this.performSearch();
        });
        return card;
    }
};

Search.init();
