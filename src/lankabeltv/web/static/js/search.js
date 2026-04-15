/**
 * search.js - Netflix Style Search and Display functionality for LankabelTV
 */

import API from './api.js';
import { UI, escapeHtml, showNotification } from './ui.js';

export const Search = {
    elements: {
        searchInput: document.getElementById('search-input'),
        resultsContainer: document.getElementById('results-container'),
        popularAnimeGrid: document.getElementById('popular-anime-grid'),
        newAnimeGrid: document.getElementById('new-anime-grid'),
        popularNewSections: document.getElementById('popular-new-sections'),
        homeLoading: document.getElementById('home-loading'),
        resultsCount: document.getElementById('results-count'),
        resultsSection: document.getElementById('results-section'),
        homeContent: document.getElementById('home-content'),
        heroTitle: document.getElementById('hero-title'),
        heroDesc: document.getElementById('hero-desc'),
        heroBg: document.getElementById('hero-bg'),
        heroPlayBtn: document.getElementById('hero-play-btn')
    },

    currentResults: [],

    init() {
        // No filter buttons in the new Netflix design for now to keep it simple
    },

    async performSearch() {
        const query = this.elements.searchInput.value.trim();
        if (!query) {
            this.showHome();
            return;
        }

        UI.showLoadingState();
        try {
            const data = await API.search(query, "both");
            if (data && data.success) {
                this.currentResults = data.results;
                this.displaySearchResults(this.currentResults);
            } else {
                showNotification(data?.error || 'Search failed', 'error');
            }
        } catch (error) {
            console.error('Search error:', error);
            showNotification('Search failed. Please try again.', 'error');
        } finally {
            UI.hideLoadingState();
        }
    },

    showHome() {
        this.elements.resultsSection.style.display = 'none';
        this.elements.homeContent.style.display = 'block';
        document.getElementById('hero-section').style.display = 'block';
    },

    displaySearchResults(results) {
        this.elements.homeContent.style.display = 'none';
        document.getElementById('hero-section').style.display = 'none';
        this.elements.resultsSection.style.display = 'block';
        
        this.elements.resultsContainer.innerHTML = '';
        if (this.elements.resultsCount) {
            this.elements.resultsCount.textContent = `Found ${results.length} Titles`;
        }

        results.forEach(anime => {
            const card = this.createAnimeCard(anime);
            this.elements.resultsContainer.appendChild(card);
        });
    },

    createAnimeCard(anime, isRowItem = false) {
        const card = document.createElement('div');
        card.className = 'anime-card';
        
        let coverUrl = anime.cover || '';
        if (coverUrl) {
            if (!coverUrl.startsWith('http')) {
                const baseUrl = anime.site === 's.to' ? 'https://s.to' : 'https://aniworld.to';
                if (coverUrl.startsWith('//')) coverUrl = 'https:' + coverUrl;
                else if (coverUrl.startsWith('/')) coverUrl = baseUrl + coverUrl;
                else coverUrl = baseUrl + '/' + coverUrl;
            }
            // Use higher resolution if possible for AniWorld images
            // TMDB images (image.tmdb.org) should stay at their requested resolution
            if (coverUrl.includes('aniworld.to') || coverUrl.includes('s.to')) {
                coverUrl = coverUrl.replace("150x225", "220x330");
            }
        }

        const rating = anime.rating ? (typeof anime.rating === 'number' ? anime.rating.toFixed(1) : anime.rating) : null;

        card.innerHTML = `
            <img src="${coverUrl || 'https://via.placeholder.com/220x330?text=No+Poster'}" loading="lazy" alt="${escapeHtml(anime.title)}">
            <div class="card-overlay">
                <div class="card-title">${escapeHtml(anime.title)}</div>
                <div class="card-info">
                    ${rating ? `<span class="card-rating">${rating} Rating</span>` : ''}
                    <span class="site-badge">${escapeHtml(anime.site || 'aniworld.to')}</span>
                </div>
                <div class="card-actions">
                    <button class="card-icon-btn download-icon" title="Download">
                        <i class="fas fa-download"></i>
                    </button>
                    <button class="card-icon-btn" title="More Info">
                        <i class="fas fa-plus"></i>
                    </button>
                </div>
            </div>
        `;

        card.querySelector('.download-icon').addEventListener('click', (e) => {
            e.stopPropagation();
            if (window.showDownloadModal) {
                window.showDownloadModal(anime.title, 'Series', anime.url);
            }
        });

        // Clicking the card itself could also trigger info/download
        card.addEventListener('click', () => {
             if (window.showDownloadModal) {
                window.showDownloadModal(anime.title, 'Series', anime.url);
            }
        });

        return card;
    },

    async loadPopularAndNewAnime() {
        if (this.elements.homeLoading) this.elements.homeLoading.style.display = 'block';
        try {
            const data = await API.getPopularNew();
            if (data.success) {
                this.elements.popularAnimeGrid.innerHTML = '';
                this.elements.newAnimeGrid.innerHTML = '';
                
                // Set Hero from a random popular anime
                if (data.popular && data.popular.length > 0) {
                    const featured = data.popular[Math.floor(Math.random() * Math.min(data.popular.length, 5))];
                    this.updateHero(featured);
                }

                data.popular.forEach(a => {
                    const anime = this.mapHomeToSearchObj(a, 'popular');
                    this.elements.popularAnimeGrid.appendChild(this.createAnimeCard(anime, true));
                });

                data.new.forEach(a => {
                    const anime = this.mapHomeToSearchObj(a, 'new');
                    this.elements.newAnimeGrid.appendChild(this.createAnimeCard(anime, true));
                });

                this.elements.popularNewSections.style.display = 'block';
            }
        } catch (error) {
            console.error('Failed to load popular/new anime:', error);
        } finally {
            if (this.elements.homeLoading) this.elements.homeLoading.style.display = 'none';
        }
    },

    updateHero(anime) {
        if (!anime) return;
        this.elements.heroTitle.textContent = anime.name;
        if (anime.description) {
            this.elements.heroDesc.textContent = anime.description;
        }
        
        let coverUrl = anime.cover || '';
        if (coverUrl) {
            // For TMDB images, use original or large resolution for Hero
            if (coverUrl.includes('image.tmdb.org')) {
                coverUrl = coverUrl.replace('/w500/', '/original/');
            } else {
                coverUrl = coverUrl.replace('_150x225.png', '_220x330.png');
            }
            this.elements.heroBg.style.backgroundImage = `url('${coverUrl}')`;
        }

        this.elements.heroPlayBtn.onclick = () => {
            const searchObj = this.mapHomeToSearchObj(anime);
            if (window.showDownloadModal) {
                window.showDownloadModal(searchObj.title, 'Series', searchObj.url);
            }
        };
    },

    mapHomeToSearchObj(homeAnime) {
        // Map home object format to consistent search result format
        const site = homeAnime.link?.includes('s.to') ? 's.to' : 'aniworld.to';
        const baseUrl = site === 's.to' ? 'https://s.to' : 'https://aniworld.to';
        const streamPath = site === 's.to' ? 'serie/stream' : 'anime/stream';
        
        return {
            title: homeAnime.name,
            name: homeAnime.name,
            url: homeAnime.link?.startsWith('http') ? homeAnime.link : `${baseUrl}/${streamPath}/${homeAnime.link}`,
            cover: homeAnime.cover,
            site: site,
            rating: homeAnime.rating || null
        };
    }
};

Search.init();
