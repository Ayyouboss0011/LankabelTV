/**
 * download.js - Netflix Style Download modal and episode management for LankabelTV
 */

import API from './api.js';
import { showNotification } from './ui.js';
import { Queue } from './queue.js';
import { Trackers } from './trackers.js';

export const Download = {
    state: {
        currentDownloadData: null,
        availableEpisodes: {},
        availableMovies: [],
        selectedEpisodes: new Set(),
        episodeLanguageSelections: {},
        episodeProviderSelections: {},
        languagePreferences: { lankabeltv: [], sto: [] },
        providerPreferences: { lankabeltv: [], sto: [] },
        availableProviders: [],
        currentSessionId: 0
    },

    elements: {
        downloadModal: document.getElementById('download-modal'),
        animeTitle: document.getElementById('download-anime-title'),
        episodeTree: document.getElementById('episode-tree'),
        episodeTreeLoading: document.getElementById('episode-tree-loading'),
        confirmBtn: document.getElementById('confirm-download'),
        trackCheckbox: document.getElementById('track-series-checkbox'),
        trackerLanguageSelection: document.getElementById('tracker-language-selection'),
        trackerLanguage: document.getElementById('tracker-language'),
        trackerLanguageDropdown: document.getElementById('tracker-language-dropdown'),
        trackerLastSeenPreview: document.getElementById('tracker-last-seen-preview'),
        lastSeenStatus: document.getElementById('last-seen-status'),
        downloadPath: document.getElementById('download-path')
    },

    async init() {
        await Promise.all([
            this.loadLanguagePreferences(),
            this.loadProviderPreferences()
        ]);
        // Custom dropdowns removed in favor of badges
    },

    async loadLanguagePreferences() {
        try {
            const data = await API.getLanguagePreferences();
            if (data.success) {
                this.state.languagePreferences = {
                    lankabeltv: data.lankabeltv || [],
                    sto: data.sto || []
                };
            }
        } catch (err) { console.error('Failed to load language preferences:', err); }
    },

    async loadProviderPreferences() {
        try {
            const data = await API.getProviderPreferences();
            if (data.success) {
                this.state.providerPreferences = {
                    lankabeltv: data.lankabeltv || [],
                    sto: data.sto || []
                };
            }
        } catch (err) { console.error('Failed to load provider preferences:', err); }
    },

    async showModal(animeTitle, episodeTitle, episodeUrl) {
        this.state.currentSessionId++;
        if (this.elements.episodeTree) this.elements.episodeTree.innerHTML = '';

        let detectedSite = 'aniworld.to';
        if (episodeUrl.includes('/serie/stream/') || episodeUrl.includes('186.2.175.5')) {
            detectedSite = 's.to';
        }
        
        this.state.currentDownloadData = { anime: animeTitle, episode: episodeTitle, url: episodeUrl, site: detectedSite };
        this.state.selectedEpisodes.clear();
        this.state.availableEpisodes = {};
        this.state.episodeLanguageSelections = {};
        this.state.episodeProviderSelections = {};

        // Prepare UI for loading
        if (this.elements.animeTitle) this.elements.animeTitle.textContent = animeTitle;
        document.getElementById('detail-backdrop').style.backgroundImage = 'none';
        document.getElementById('detail-overview').textContent = 'Loading description...';
        document.getElementById('detail-year').textContent = '';
        document.getElementById('detail-rating').textContent = '';
        document.getElementById('detail-status').textContent = detectedSite;
        document.getElementById('detail-genres').innerHTML = '';

        if (this.elements.episodeTreeLoading) this.elements.episodeTreeLoading.style.display = 'block';
        if (this.elements.episodeTree) this.elements.episodeTree.style.display = 'none';
        this.updateSelectedCount();

        try {
            const pathData = await API.getDownloadPath();
            if (this.elements.downloadPath) {
                this.elements.downloadPath.textContent = pathData.series_path || pathData.path || "/Downloads";
            }
        } catch (err) { console.error('Failed to load download path:', err); }

        try {
            const data = await API.getEpisodes(episodeUrl, animeTitle);
            if (data.success) {
                this.state.availableEpisodes = data.episodes;
                this.state.availableMovies = data.movies || [];
                
                // Update Metadata from TMDB
                if (data.metadata) {
                    const m = data.metadata;
                    if (m.backdrop) document.getElementById('detail-backdrop').style.backgroundImage = `url('${m.backdrop}')`;
                    document.getElementById('detail-overview').textContent = m.overview || 'No description available.';
                    document.getElementById('detail-year').textContent = m.year || '';
                    if (m.rating) document.getElementById('detail-rating').textContent = `${Math.round(m.rating * 10)}% Match`;
                    if (m.status) document.getElementById('detail-status').textContent = m.status;
                    
                    const genreCont = document.getElementById('detail-genres');
                    m.genres?.forEach(g => {
                        const span = document.createElement('span');
                        span.className = 'genre-tag';
                        span.textContent = g;
                        genreCont.appendChild(span);
                    });
                }

                this.renderEpisodeTree();
            } else {
                showNotification(data.error || 'Failed to load episodes', 'error');
            }
        } catch (error) {
            console.error('Failed to fetch episodes:', error);
            showNotification('Failed to load episodes', 'error');
        } finally {
            if (this.elements.episodeTreeLoading) this.elements.episodeTreeLoading.style.display = 'none';
            if (this.elements.episodeTree) this.elements.episodeTree.style.display = 'block';
        }

        if (this.elements.downloadModal) {
            this.elements.downloadModal.style.display = 'block';
            document.body.classList.add('modal-open');
        }
    },

    hideModal() {
        if (this.elements.downloadModal) {
            this.elements.downloadModal.style.display = 'none';
            document.body.classList.remove('modal-open');
        }
        if (this.elements.episodeTree) this.elements.episodeTree.innerHTML = '';
        this.state.currentDownloadData = null;
        this.state.selectedEpisodes.clear();
        this.state.availableEpisodes = {};
        this.state.availableMovies = [];
        this.state.episodeLanguageSelections = {};
        this.state.episodeProviderSelections = {};
        if (this.elements.trackCheckbox) this.elements.trackCheckbox.checked = false;
        if (this.elements.trackerLanguageSelection) this.elements.trackerLanguageSelection.style.display = 'none';
        if (this.elements.trackerLastSeenPreview) this.elements.trackerLastSeenPreview.style.display = 'none';
    },

    async autoVerifyEpisodeLanguages(episodes) {
        const sessionId = this.state.currentSessionId;
        const batchSize = 3;
        for (let i = 0; i < episodes.length; i += batchSize) {
            if (this.state.currentSessionId !== sessionId) return;
            const batch = episodes.slice(i, i + batchSize);
            await Promise.all(batch.map(async (ep) => {
                try {
                    const data = await API.getEpisodeProviders(ep.url);
                    if (this.state.currentSessionId !== sessionId) return;
                    if (data.success) {
                        const langWrapper = document.querySelector(`.episode-lang-wrapper[data-episode-url="${ep.url}"]`);
                        if (langWrapper) {
                            let langBadgesContainer = langWrapper.querySelector('.episode-lang-badges') || document.createElement('div');
                            langBadgesContainer.className = 'episode-lang-badges';
                            if (!langWrapper.querySelector('.episode-lang-badges')) langWrapper.appendChild(langBadgesContainer);
                            this.createLanguageBadges(langBadgesContainer, data.languages, ep.url);

                            let providerWrapper = langWrapper.querySelector('.episode-provider-wrapper') || document.createElement('div');
                            providerWrapper.className = 'episode-provider-wrapper';
                            providerWrapper.dataset.episodeUrl = ep.url;
                            if (!langWrapper.querySelector('.episode-provider-wrapper')) langWrapper.appendChild(providerWrapper);

                            let provBadgesContainer = providerWrapper.querySelector('.episode-provider-badges') || document.createElement('div');
                            provBadgesContainer.className = 'episode-provider-badges';
                            if (!providerWrapper.querySelector('.episode-provider-badges')) providerWrapper.appendChild(provBadgesContainer);
                            this.createProviderBadges(provBadgesContainer, data.providers, ep.url);
                        }
                        const epInCache = this.state.availableEpisodes[ep.season]?.find(e => e.episode === ep.episode);
                        if (epInCache) {
                            epInCache.languages = data.languages;
                            epInCache.providers = data.providers;
                        }
                        this.updateSeasonLanguageBadges(ep.season);
                        this.updateSeasonProviderBadges(ep.season);
                        this.updateTrackerPreview();
                    }
                } catch (err) { console.error(`Auto-verify error for ${ep.season}x${ep.episode}:`, err); }
            }));
            if (i + batchSize < episodes.length) await new Promise(r => setTimeout(r, 500));
        }
    },

    updateTrackerPreview() {
        if (!this.elements.trackCheckbox || !this.elements.trackCheckbox.checked) return;
        if (!this.elements.lastSeenStatus) return;

        const targetLanguage = this.elements.trackerLanguage?.value || 'German Dub';
        const langMap = { "German Dub": 1, "German Sub": 3, "English Dub": 2, "English Sub": 2 };
        const targetLangId = langMap[targetLanguage];

        let maxS = 0, maxE = 0;
        const seasons = Object.keys(this.state.availableEpisodes).map(Number).sort((a, b) => b - a);
        let found = false;
        
        for (const sNum of seasons) {
            const episodes = this.state.availableEpisodes[sNum];
            if (episodes && episodes.length > 0) {
                const sortedEpisodes = [...episodes].sort((a, b) => b.episode - a.episode);
                for (const ep of sortedEpisodes) {
                    let hasLang = ep.languages?.some(l => (typeof l === 'number' ? l === targetLangId : l === targetLanguage));
                    if (hasLang) { maxS = sNum; maxE = Number(ep.episode) || 0; found = true; break; }
                }
            }
            if (found) break;
        }

        if (found) {
            this.elements.lastSeenStatus.innerHTML = `<strong>Season ${maxS} Episode ${maxE}</strong>`;
            this.elements.lastSeenStatus.style.color = 'var(--netflix-red)';
        } else {
            const hasUnverified = Object.values(this.state.availableEpisodes).flat().some(ep => !ep.languages || ep.languages.length === 0);
            this.elements.lastSeenStatus.innerHTML = hasUnverified ? '<i class="fas fa-spinner fa-spin"></i> Checking...' : 'None found';
            this.elements.lastSeenStatus.style.color = '#aaa';
        }
    },

    createLanguageBadges(container, languages, episodeUrl, isTracker = false) {
        container.innerHTML = '';
        if (!languages || languages.length === 0) {
            if (!isTracker) container.innerHTML = '<span style="font-size: 10px; opacity: 0.5;">Loading...</span>';
            return;
        }

        let selectedLang = isTracker ? (this.elements.trackerLanguage.value) : this.state.episodeLanguageSelections[episodeUrl];
        if (!selectedLang && !isTracker) {
            const sitePrefs = this.state.currentDownloadData.site === 's.to' ? this.state.languagePreferences.sto : this.state.languagePreferences.lankabeltv;
            selectedLang = sitePrefs?.find(pref => languages.includes(pref)) || (languages.includes('German Dub') ? 'German Dub' : (languages.includes('German Sub') ? 'German Sub' : languages[0]));
            this.state.episodeLanguageSelections[episodeUrl] = selectedLang;
        }

        languages.forEach(lang => {
            const badge = document.createElement('span');
            badge.className = 'lang-badge' + (lang === selectedLang ? ' active' : '');
            badge.textContent = lang.replace('German', 'DE').replace('English', 'EN').replace('Dub', 'D').replace('Sub', 'S');
            badge.title = lang;
            badge.addEventListener('click', (e) => {
                e.stopPropagation();
                if (isTracker) {
                    this.elements.trackerLanguage.value = lang;
                    this.updateTrackerPreview();
                } else {
                    this.state.episodeLanguageSelections[episodeUrl] = lang;
                }
                container.querySelectorAll('.lang-badge').forEach(b => b.classList.remove('active'));
                badge.classList.add('active');
            });
            container.appendChild(badge);
        });
    },

    createProviderBadges(container, providers, episodeUrl) {
        container.innerHTML = '';
        if (!providers || providers.length === 0) return;
        const sitePrefs = this.state.currentDownloadData.site === 's.to' ? this.state.providerPreferences.sto : this.state.providerPreferences.lankabeltv;

        let selectedProv = this.state.episodeProviderSelections[episodeUrl];
        if (!selectedProv) {
            selectedProv = sitePrefs?.find(pref => providers.includes(pref));
            if (!selectedProv) {
                selectedProv = providers.includes('VOE') ? 'VOE' : providers[0];
            }
            this.state.episodeProviderSelections[episodeUrl] = selectedProv;
        }

        const sortedProviders = [...providers].sort((a, b) => {
            if (a === 'VOE') return -1;
            if (b === 'VOE') return 1;
            return a.localeCompare(b);
        });

        sortedProviders.forEach(prov => {
            const badge = document.createElement('span');
            badge.className = 'provider-badge' + (prov === selectedProv ? ' active' : '');
            badge.textContent = prov.substring(0, 3).toUpperCase();
            badge.title = prov;
            badge.addEventListener('click', (e) => {
                e.stopPropagation();
                this.state.episodeProviderSelections[episodeUrl] = prov;
                container.querySelectorAll('.provider-badge').forEach(b => b.classList.remove('active'));
                badge.classList.add('active');
            });
            container.appendChild(badge);
        });
    },

    renderEpisodeTree() {
        if (this.elements.trackCheckbox && !this.elements.trackCheckbox.dataset.listenerAdded) {
            this.elements.trackCheckbox.addEventListener('change', () => {
                this.elements.trackerLanguageSelection.style.display = this.elements.trackCheckbox.checked ? 'block' : 'none';
                this.elements.trackerLastSeenPreview.style.display = this.elements.trackCheckbox.checked ? 'block' : 'none';
                if (this.elements.trackCheckbox.checked) {
                   const langs = ["German Dub", "German Sub", "English Dub", "English Sub"];
                   this.createLanguageBadges(this.elements.trackerLanguageDropdown, langs, null, true);
                }
                this.updateTrackerPreview();
                this.updateSelectedCount();
            });
            this.elements.trackCheckbox.dataset.listenerAdded = 'true';
        }
        
        this.elements.episodeTree.innerHTML = '';
        const episodesToVerify = [];
        const seasons = Object.keys(this.state.availableEpisodes).sort((a, b) => Number(a) - Number(b));

        seasons.forEach((seasonNum) => {
            const season = this.state.availableEpisodes[seasonNum];
            const seasonContainer = document.createElement('div');
            seasonContainer.className = 'season-container collapsed';
            seasonContainer.dataset.seasonContainer = seasonNum;
            seasonContainer.innerHTML = `
                <div class="season-header" data-season="${seasonNum}">
                    <input type="checkbox" class="season-checkbox" id="season-${seasonNum}" style="accent-color: var(--netflix-red);">
                    <label class="season-label" style="font-weight:700;">Season ${seasonNum}</label>
                    <div style="display: flex; gap: 15px; margin-left: auto;">
                        <div class="season-lang-badges"></div>
                        <div class="season-provider-badges"></div>
                    </div>
                </div>
                <div class="episodes-container" style="display:none;"></div>
            `;
            
            const header = seasonContainer.querySelector('.season-header');
            const epContainer = seasonContainer.querySelector('.episodes-container');

            header.addEventListener('click', (e) => {
                if (e.target.type === 'checkbox') return;
                const isCollapsed = seasonContainer.classList.toggle('collapsed');
                epContainer.style.display = isCollapsed ? 'none' : 'block';
            });

            seasonContainer.querySelector('.season-checkbox').addEventListener('change', (e) => {
                this.toggleSeason(seasonNum, e.target.checked);
            });

            season.forEach(episode => {
                const epItem = document.createElement('div');
                epItem.className = 'episode-item-tree';
                const epId = `${episode.season}-${episode.episode}`;
                epItem.innerHTML = `
                    <div style="display:flex; align-items:center; gap:10px;">
                        <input type="checkbox" class="episode-checkbox" id="episode-${epId}" style="accent-color: var(--netflix-red);">
                        <label for="episode-${epId}" class="episode-label">${episode.title}</label>
                    </div>
                    <div class="episode-lang-wrapper" data-episode-url="${episode.url}" style="display:flex; gap:15px; align-items:center;">
                        <div class="episode-lang-badges"></div>
                        <div class="episode-provider-wrapper" data-episode-url="${episode.url}">
                            <div class="episode-provider-badges"></div>
                        </div>
                    </div>
                `;
                epItem.querySelector('.episode-checkbox').addEventListener('change', (e) => this.toggleEpisode(episode, e.target.checked));
                this.createLanguageBadges(epItem.querySelector('.episode-lang-badges'), episode.languages, episode.url);
                this.createProviderBadges(epItem.querySelector('.episode-provider-badges'), episode.providers, episode.url);
                epContainer.appendChild(epItem);
                if (!episode.languages || episode.languages.length === 0) episodesToVerify.push(episode);
            });
            this.elements.episodeTree.appendChild(seasonContainer);
            this.updateSeasonLanguageBadges(seasonNum);
            this.updateSeasonProviderBadges(seasonNum);
        });
        this.updateSelectedCount();
        if (episodesToVerify.length > 0) this.autoVerifyEpisodeLanguages(episodesToVerify);
    },

    updateSeasonLanguageBadges(seasonNum) {
        const season = this.state.availableEpisodes[seasonNum];
        const header = this.elements.episodeTree.querySelector(`.season-header[data-season="${seasonNum}"]`);
        const badgesContainer = header?.querySelector('.season-lang-badges');
        if (!season || !badgesContainer) return;

        const allLangs = new Set();
        season.forEach(ep => ep.languages?.forEach(l => allLangs.add(l)));
        if (allLangs.size === 0) return;

        badgesContainer.innerHTML = '';
        Array.from(allLangs).sort().forEach(lang => {
            const badge = document.createElement('span');
            badge.className = 'season-lang-badge';
            badge.textContent = lang.replace('German', 'DE').replace('English', 'EN').replace('Dub', 'D').replace('Sub', 'S');
            badge.title = `Apply ${lang} to Season ${seasonNum}`;
            badge.addEventListener('click', (e) => {
                e.stopPropagation();
                season.forEach(ep => {
                    if (ep.languages?.includes(lang)) {
                        this.state.episodeLanguageSelections[ep.url] = lang;
                        const epLangWrapper = document.querySelector(`.episode-lang-wrapper[data-episode-url="${ep.url}"]`);
                        epLangWrapper?.querySelectorAll('.lang-badge').forEach(b => b.classList.toggle('active', b.title === lang));
                    }
                });
                badgesContainer.querySelectorAll('.season-lang-badge').forEach(b => b.classList.remove('active'));
                badge.classList.add('active');
            });
            badgesContainer.appendChild(badge);
        });
    },

    updateSeasonProviderBadges(seasonNum) {
        const season = this.state.availableEpisodes[seasonNum];
        const header = this.elements.episodeTree.querySelector(`.season-header[data-season="${seasonNum}"]`);
        const badgesContainer = header?.querySelector('.season-provider-badges');
        if (!season || !badgesContainer) return;

        const allProvs = new Set();
        season.forEach(ep => ep.providers?.forEach(p => allProvs.add(p)));
        if (allProvs.size === 0) return;

        badgesContainer.innerHTML = '';
        const sortedProvs = Array.from(allProvs).sort((a, b) => {
            if (a === 'VOE') return -1;
            if (b === 'VOE') return 1;
            return a.localeCompare(b);
        });

        sortedProvs.forEach(prov => {
            const badge = document.createElement('span');
            badge.className = 'season-provider-badge';
            badge.textContent = prov.substring(0, 3).toUpperCase();
            badge.title = `Apply ${prov} to Season ${seasonNum}`;
            badge.addEventListener('click', (e) => {
                e.stopPropagation();
                season.forEach(ep => {
                    if (ep.providers?.includes(prov)) {
                        this.state.episodeProviderSelections[ep.url] = prov;
                        const epProvWrapper = document.querySelector(`.episode-provider-wrapper[data-episode-url="${ep.url}"]`);
                        epProvWrapper?.querySelectorAll('.provider-badge').forEach(b => b.classList.toggle('active', b.title === prov));
                    }
                });
                badgesContainer.querySelectorAll('.season-provider-badge').forEach(b => b.classList.remove('active'));
                badge.classList.add('active');
            });
            badgesContainer.appendChild(badge);
        });
    },

    toggleSeason(seasonNum, isChecked) {
        this.state.availableEpisodes[seasonNum].forEach(episode => {
            const cb = document.getElementById(`episode-${episode.season}-${episode.episode}`);
            if (cb) { cb.checked = isChecked; this.toggleEpisode(episode, isChecked); }
        });
    },

    toggleEpisode(episode, isSelected) {
        const key = `${episode.season}-${episode.episode}`;
        if (isSelected) this.state.selectedEpisodes.add(key); else this.state.selectedEpisodes.delete(key);
        this.updateSeasonCheckboxState(episode.season);
        this.updateSelectedCount();
    },

    updateSeasonCheckboxState(seasonNum) {
        const season = this.state.availableEpisodes[seasonNum];
        const cb = document.getElementById(`season-${seasonNum}`);
        if (!cb || !season) return;
        const selectedInSeason = season.filter(ep => this.state.selectedEpisodes.has(`${ep.season}-${ep.episode}`));
        cb.checked = selectedInSeason.length === season.length;
        cb.indeterminate = selectedInSeason.length > 0 && selectedInSeason.length < season.length;
    },

    selectAll() {
        Object.values(this.state.availableEpisodes).flat().forEach(ep => {
            const key = `${ep.season}-${ep.episode}`;
            const cb = document.getElementById(`episode-${key}`);
            if (cb) { cb.checked = true; this.state.selectedEpisodes.add(key); }
        });
        Object.keys(this.state.availableEpisodes).forEach(s => this.updateSeasonCheckboxState(s));
        this.updateSelectedCount();
    },

    deselectAll() {
        this.state.selectedEpisodes.clear();
        this.elements.episodeTree.querySelectorAll('.episode-checkbox, .season-checkbox').forEach(cb => { cb.checked = false; cb.indeterminate = false; });
        this.updateSelectedCount();
    },

    updateSelectedCount() {
        const count = this.state.selectedEpisodes.size;
        const isTrackerEnabled = this.elements.trackCheckbox?.checked;
        if (this.elements.confirmBtn) {
            this.elements.confirmBtn.disabled = (count === 0 && !isTrackerEnabled);
            this.elements.confirmBtn.textContent = isTrackerEnabled && count === 0 ? 'Add Tracker' : (count > 0 ? `Start Download (${count})` : 'Start Download');
        }
    },

    async startDownload() {
        const isTrackerEnabled = this.elements.trackCheckbox?.checked;
        const count = this.state.selectedEpisodes.size;
        if (!this.state.currentDownloadData || (count === 0 && !isTrackerEnabled)) return;

        this.elements.confirmBtn.disabled = true;
        this.elements.confirmBtn.textContent = 'Starting...';
        const trackingLang = this.elements.trackerLanguage?.value || 'German Dub';

        if (count === 0 && isTrackerEnabled) {
            const success = await Trackers.addTrackerForSeries(this.state.currentDownloadData, this.state.availableEpisodes, trackingLang, 'VOE');
            if (success) this.hideModal();
            this.elements.confirmBtn.disabled = false;
            this.updateSelectedCount();
            return;
        }

        const selectedUrls = [];
        const episodesConfig = {};
        const sitePrefs = this.state.currentDownloadData.site === 's.to' ? this.state.languagePreferences.sto : this.state.languagePreferences.lankabeltv;
        let overallLang = sitePrefs?.[0] || 'German Dub';
        let overallProv = 'VOE';

        this.state.selectedEpisodes.forEach(key => {
            const [s, e] = key.split('-').map(Number);
            const epData = this.state.availableEpisodes[s]?.find(item => item.season === s && item.episode === e);
            if (epData) {
                selectedUrls.push(epData.url);
                const epLang = this.state.episodeLanguageSelections[epData.url] || overallLang;
                const epProv = this.state.episodeProviderSelections[epData.url] || epData.providers?.[0] || overallProv;
                episodesConfig[epData.url] = { language: epLang, provider: epProv };
                overallLang = epLang; overallProv = epProv;
            }
        });

        try {
            const data = await API.startDownload({ episode_urls: selectedUrls, language: overallLang, provider: overallProv, anime_title: this.state.currentDownloadData.anime, episodes_config: episodesConfig });
            if (data.success) {
                showNotification(`Started download for ${selectedUrls.length} eps`, 'success');
                if (isTrackerEnabled) await Trackers.addTrackerForSeries(this.state.currentDownloadData, this.state.availableEpisodes, trackingLang, overallProv);
                this.hideModal();
                Queue.startTracking();
            } else showNotification(data.error || 'Failed', 'error');
        } catch (err) { showNotification('Error starting download', 'error'); }
        finally { this.elements.confirmBtn.disabled = false; this.elements.confirmBtn.textContent = 'Start Download'; }
    }
};
