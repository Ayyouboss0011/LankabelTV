/**
 * download.js - Download modal and episode management for LankabelTV Web Interface
 */

import API from './api.js';
import { escapeHtml, showNotification } from './ui.js';
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
        languagePreferences: { aniworld: [], sto: [] },
        providerPreferences: { aniworld: [], sto: [] },
        availableProviders: [],
        currentSessionId: 0,
        lastFocused: null
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
        trackerLastSeenPreview: document.getElementById('tracker-last-seen-preview'),
        lastSeenStatus: document.getElementById('last-seen-status'),
        selectionHint: document.getElementById('selection-hint'),
        episodeVerification: document.getElementById('episode-verification'),
        downloadPath: document.getElementById('download-path')
    },

    async init() {
        await Promise.all([
            this.loadLanguagePreferences(),
            this.loadProviderPreferences()
        ]);
    },

    initCustomDropdowns() {
        if (!this.elements.trackerLanguageDropdown) return;

        const dropdown = this.elements.trackerLanguageDropdown;
        const selected = dropdown.querySelector('.select-selected');
        const items = dropdown.querySelector('.select-items');
        const hiddenInput = this.elements.trackerLanguage;

        selected.addEventListener('click', (e) => {
            e.stopPropagation();
            this.closeAllCustomDropdowns(dropdown);
            items.classList.toggle('select-hide');
            dropdown.classList.toggle('select-arrow-active');
        });

        items.querySelectorAll('div').forEach(item => {
            item.addEventListener('click', (e) => {
                const val = item.getAttribute('data-value');
                selected.textContent = val;
                hiddenInput.value = val;
                
                // Trigger change event manually on the hidden input if needed
                hiddenInput.dispatchEvent(new Event('change'));
                
                items.classList.add('select-hide');
                dropdown.classList.remove('select-arrow-active');
                
                items.querySelectorAll('div').forEach(d => d.classList.remove('same-as-selected'));
                item.classList.add('same-as-selected');
            });
        });

        document.addEventListener('click', () => {
            this.closeAllCustomDropdowns();
        });
    },

    closeAllCustomDropdowns(exceptDropdown = null) {
        document.querySelectorAll('.custom-select').forEach(dropdown => {
            if (dropdown !== exceptDropdown) {
                dropdown.classList.remove('select-arrow-active');
                dropdown.querySelector('.select-items').classList.add('select-hide');
            }
        });
    },

    async loadLanguagePreferences() {
        try {
            const data = await API.getLanguagePreferences();
            if (data.success) {
                this.state.languagePreferences = {
                    aniworld: data.aniworld || [],
                    sto: data.sto || []
                };
            }
        } catch (err) {
            console.error('Failed to load language preferences:', err);
        }
    },

    async loadProviderPreferences() {
        try {
            const data = await API.getProviderPreferences();
            if (data.success) {
                this.state.providerPreferences = {
                    aniworld: data.aniworld || [],
                    sto: data.sto || []
                };
            }
        } catch (err) {
            console.error('Failed to load provider preferences:', err);
        }
    },

    getSiteLanguagePrefs() {
        const site = this.state.currentDownloadData?.site;
        if (site === 's.to') return this.state.languagePreferences.sto || [];
        if (site === 'megakino') return ['German Dub'];
        return this.state.languagePreferences.aniworld || [];
    },

    getSiteProviderPrefs() {
        const site = this.state.currentDownloadData?.site;
        if (site === 's.to') return this.state.providerPreferences.sto || [];
        if (site === 'megakino') return ['VOE', 'GXPlayer'];
        return this.state.providerPreferences.aniworld || [];
    },

    async showModal(animeTitle, episodeTitle, episodeUrl) {
        // Increment session ID to invalidate pending background requests from previous sessions
        this.state.currentSessionId++;
        this.state.lastFocused = document.activeElement;
        
        // Clear episode tree content immediately to prevent stale data
        if (this.elements.episodeTree) this.elements.episodeTree.innerHTML = '';

        let detectedSite = 'aniworld.to';
        if (
            episodeUrl.includes('/serie/stream/') ||
            episodeUrl.includes('serienstream.to') ||
            episodeUrl.includes('s.to') ||
            episodeUrl.includes('186.2.175.5') ||
            episodeUrl.includes('186.2.163.190')
        ) {
            detectedSite = 's.to';
        } else if (episodeUrl.startsWith('megakino:') || episodeUrl.includes('megakino')) {
            detectedSite = 'megakino';
        }
        
        this.state.currentDownloadData = { anime: animeTitle, episode: episodeTitle, url: episodeUrl, site: detectedSite };
        this.state.selectedEpisodes.clear();
        this.state.availableEpisodes = {};
        this.state.episodeLanguageSelections = {};
        this.state.episodeProviderSelections = {};

        if (this.elements.animeTitle) this.elements.animeTitle.textContent = animeTitle;

        if (this.elements.episodeTreeLoading) this.elements.episodeTreeLoading.style.display = 'flex';
        if (this.elements.episodeTree) this.elements.episodeTree.style.display = 'none';
        if (this.elements.selectionHint) this.elements.selectionHint.textContent = 'Select at least one episode.';
        this.updateSelectedCount();

        try {
            const pathData = await API.getDownloadPath();
            const downloadPath = pathData.path || pathData.series_path || pathData.movie_path || '';
            if (this.elements.downloadPath) this.elements.downloadPath.textContent = downloadPath;
            const pathRow = this.elements.downloadPath?.closest('.download-path');
            if (pathRow) pathRow.style.display = downloadPath ? '' : 'none';
        } catch (err) { console.error('Failed to load download path:', err); }

        try {
            const data = await API.getEpisodes(episodeUrl, animeTitle);
            if (data.success) {
                this.state.availableEpisodes = data.episodes;
                this.state.availableMovies = data.movies || [];
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
            this.elements.downloadModal.style.display = 'flex';
            document.body.classList.add('modal-open');
            setTimeout(() => document.getElementById('close-download-modal')?.focus(), 0);
        }
    },

    hideModal() {
        this.state.currentSessionId++;
        if (this.elements.downloadModal) {
            this.elements.downloadModal.style.display = 'none';
            document.body.classList.remove('modal-open');
        }

        // Clear episode tree content immediately to prevent stale data on re-open
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
        if (this.elements.episodeVerification) this.elements.episodeVerification.hidden = true;

        // Reset all download button loaders
        document.querySelectorAll('.download-btn.loading').forEach(btn => {
            btn.classList.remove('loading');
            btn.disabled = false;
            const text = btn.querySelector('.btn-text');
            const loader = btn.querySelector('.btn-loader');
            if (text) text.hidden = false;
            if (loader) loader.hidden = true;
        });

        if (this.state.lastFocused && typeof this.state.lastFocused.focus === 'function') {
            this.state.lastFocused.focus();
        }
        this.state.lastFocused = null;
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
                            this.createLanguageBadges(langBadgesContainer, data.languages, ep.url, true);

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
                } catch (err) {
                    console.error(`Auto-verify error for ${ep.season}x${ep.episode}:`, err);
                    const wrapper = document.querySelector(`.episode-lang-wrapper[data-episode-url="${ep.url}"]`);
                    const container = wrapper?.querySelector('.episode-lang-badges');
                    if (container) container.innerHTML = '<span class="badge-empty">None</span>';
                }
            }));
            if (i + batchSize < episodes.length) await new Promise(r => setTimeout(r, 500));
        }

        if (this.state.currentSessionId === sessionId && this.elements.episodeVerification) {
            this.elements.episodeVerification.hidden = true;
        }
    },

    updateTrackerPreview() {
        if (!this.elements.trackCheckbox || !this.elements.trackCheckbox.checked) return;
        if (!this.elements.lastSeenStatus) return;

        const targetLanguage = this.elements.trackerLanguage?.value || 'German Dub';
        
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
        const targetLangId = langMap[targetLanguage];

        let maxS = 0, maxE = 0;
        const seasons = Object.keys(this.state.availableEpisodes).map(Number).sort((a, b) => b - a);
        let found = false;
        
        for (const sNum of seasons) {
            const episodes = this.state.availableEpisodes[sNum];
            if (episodes && episodes.length > 0) {
                // We want the HIGHEST episode number in this season that matches the language
                const sortedEpisodes = [...episodes].sort((a, b) => b.episode - a.episode);
                for (const ep of sortedEpisodes) {
                    // Normalize languages: could be [1, 2] or ["German Dub", "English Sub"]
                    let hasLang = false;
                    if (ep.languages && Array.isArray(ep.languages)) {
                        hasLang = ep.languages.some(l => {
                            if (typeof l === 'number') return l === targetLangId;
                            if (typeof l === 'string') return l === targetLanguage;
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

        if (found) {
            this.elements.lastSeenStatus.innerHTML = `<strong>Season ${maxS} Episode ${maxE}</strong>`;
            this.elements.lastSeenStatus.classList.remove('is-missing');
            this.elements.lastSeenStatus.classList.add('is-ok');
        } else {
            const hasUnverified = Object.values(this.state.availableEpisodes).flat().some(ep => !ep.languages || ep.languages.length === 0);
            this.elements.lastSeenStatus.classList.remove('is-ok');
            if (hasUnverified) {
                this.elements.lastSeenStatus.innerHTML = '<span class="spinner" aria-hidden="true"></span> Checking availability…';
                this.elements.lastSeenStatus.classList.remove('is-missing');
            } else {
                this.elements.lastSeenStatus.textContent = 'None found in this language';
                this.elements.lastSeenStatus.classList.add('is-missing');
            }
        }
    },

    createLanguageBadges(container, languages, episodeUrl, isFinal = false) {
        container.innerHTML = '';
        if (!languages || languages.length === 0) {
            container.innerHTML = isFinal
                ? '<span class="badge-empty">None</span>'
                : '<span class="badge-loading" aria-hidden="true"></span>';
            return;
        }

        let selectedLang = this.state.episodeLanguageSelections[episodeUrl];
        if (!selectedLang) {
            const sitePrefs = this.getSiteLanguagePrefs();
            selectedLang = sitePrefs?.find(pref => languages.includes(pref));
            if (!selectedLang) {
                // Default fallback if no preference matches
                if (languages.includes('German Dub')) selectedLang = 'German Dub';
                else if (languages.includes('German Sub')) selectedLang = 'German Sub';
                else if (languages.length > 0) selectedLang = languages[0];
            }
            this.state.episodeLanguageSelections[episodeUrl] = selectedLang;
        }

        languages.forEach(lang => {
            const badge = document.createElement('button');
            badge.type = 'button';
            badge.className = 'lang-badge' + (lang === selectedLang ? ' active' : '');
            badge.textContent = lang.replace('German', 'DE').replace('English', 'EN').replace('Dub', 'Dub').replace('Sub', 'Sub');
            badge.title = lang;
            badge.setAttribute('aria-pressed', String(lang === selectedLang));
            badge.addEventListener('click', (e) => {
                e.stopPropagation();
                this.state.episodeLanguageSelections[episodeUrl] = lang;
                container.querySelectorAll('.lang-badge').forEach(b => {
                    b.classList.remove('active');
                    b.setAttribute('aria-pressed', 'false');
                });
                badge.classList.add('active');
                badge.setAttribute('aria-pressed', 'true');
            });
            container.appendChild(badge);
        });
    },

    createProviderBadges(container, providers, episodeUrl) {
        container.innerHTML = '';
        if (!providers || providers.length === 0) {
            return;
        }

        const sitePrefs = this.getSiteProviderPrefs();

        // Sort providers based on preferences
        const sortedProviders = [...providers].sort((a, b) => {
            const indexA = sitePrefs ? sitePrefs.indexOf(a) : -1;
            const indexB = sitePrefs ? sitePrefs.indexOf(b) : -1;

            if (indexA === -1 && indexB === -1) return 0;
            if (indexA === -1) return 1;
            if (indexB === -1) return -1;
            return indexA - indexB;
        });

        let selectedProv = this.state.episodeProviderSelections[episodeUrl];
        if (!selectedProv) {
            selectedProv = sitePrefs?.find(pref => providers.includes(pref));
            if (!selectedProv && providers.length > 0) {
                selectedProv = providers[0];
            }
            this.state.episodeProviderSelections[episodeUrl] = selectedProv;
        }

        sortedProviders.forEach(prov => {
            const badge = document.createElement('button');
            badge.type = 'button';
            badge.className = 'provider-badge' + (prov === selectedProv ? ' active' : '');
            badge.textContent = prov.replace('streamtape', 'ST').replace('filemoon', 'FM').replace('vidmoly', 'VM').replace('vidoza', 'VZ').replace(/GXPlayer/i, 'GX');
            badge.title = prov;
            badge.setAttribute('aria-pressed', String(prov === selectedProv));
            badge.addEventListener('click', (e) => {
                e.stopPropagation();
                this.state.episodeProviderSelections[episodeUrl] = prov;
                container.querySelectorAll('.provider-badge').forEach(b => {
                    b.classList.remove('active');
                    b.setAttribute('aria-pressed', 'false');
                });
                badge.classList.add('active');
                badge.setAttribute('aria-pressed', 'true');
            });
            container.appendChild(badge);
        });
    },

    renderEpisodeTree() {
        if (this.elements.trackCheckbox && !this.elements.trackCheckbox.dataset.listenerAdded) {
            this.elements.trackCheckbox.addEventListener('change', () => {
                if (this.elements.trackerLanguageSelection) {
                    this.elements.trackerLanguageSelection.style.display = this.elements.trackCheckbox.checked ? 'block' : 'none';
                    if (this.elements.trackerLastSeenPreview) this.elements.trackerLastSeenPreview.style.display = this.elements.trackCheckbox.checked ? 'block' : 'none';
                    
                    // Set default tracking language based on preferences
                    if (this.elements.trackCheckbox.checked && this.elements.trackerLanguage) {
                        const sitePrefs = this.getSiteLanguagePrefs();
                        if (sitePrefs && sitePrefs.length > 0) {
                            const defaultLang = sitePrefs[0];
                            this.elements.trackerLanguage.value = defaultLang;
                            
                        }
                    }
                }
                this.updateTrackerPreview();
                this.updateSelectedCount();
            });

            if (this.elements.trackerLanguage) {
                this.elements.trackerLanguage.addEventListener('change', () => {
                    this.updateTrackerPreview();
                });
            }

            this.elements.trackCheckbox.dataset.listenerAdded = 'true';
        }
        this.elements.episodeTree.innerHTML = '';

        const episodesToVerify = [];
        const seasons = Object.keys(this.state.availableEpisodes).sort((a, b) => Number(a) - Number(b));

        // Tracking only makes sense for series, not for single movies
        const onlyMovies = seasons.length === 1 && seasons[0] === '0';
        const trackerOption = this.elements.downloadModal?.querySelector('.tracker-option');
        if (trackerOption) trackerOption.style.display = onlyMovies ? 'none' : '';
        if (onlyMovies && this.elements.trackCheckbox) this.elements.trackCheckbox.checked = false;

        // Add Season Navigation if more than 3 seasons
        if (seasons.length > 2) {
            const seasonNav = document.createElement('div');
            seasonNav.className = 'season-nav';
            
            seasons.forEach(sNum => {
                const navBtn = document.createElement('button');
                navBtn.type = 'button';
                navBtn.className = 'control-btn';
                navBtn.textContent = `S${sNum}`;
                navBtn.title = `Jump to Season ${sNum}`;
                navBtn.onclick = () => {
                    const el = this.elements.episodeTree.querySelector(`.season-container[data-season-container="${sNum}"]`);
                    if (el) {
                        el.classList.remove('collapsed');
                        const header = el.querySelector('.season-header');
                        if (header) header.setAttribute('aria-expanded', 'true');
                        el.scrollIntoView({ block: 'start' });
                    }
                };
                seasonNav.appendChild(navBtn);
            });
            this.elements.episodeTree.appendChild(seasonNav);
        }

        seasons.forEach((seasonNum, index) => {
            const season = this.state.availableEpisodes[seasonNum];
            const seasonContainer = document.createElement('div');
            
            // Collapse all seasons by default, unless there is only one
            const isCollapsed = seasons.length > 1;
            seasonContainer.className = 'season-container' + (isCollapsed ? ' collapsed' : '');
            seasonContainer.dataset.seasonContainer = seasonNum;
            seasonContainer.innerHTML = `
                <div class="season-header" data-season="${seasonNum}" tabindex="0" role="button" aria-expanded="${String(!isCollapsed)}">
                    <input type="checkbox" class="season-checkbox" id="season-${seasonNum}">
                    <label for="season-${seasonNum}" class="season-label">${escapeHtml(seasonNum === '0' ? 'Movie' : 'Season ' + seasonNum)} (${season.length} ${season.length === 1 ? 'episode' : 'episodes'})</label>
                </div>
                <div class="episodes-container"></div>
            `;
            const header = seasonContainer.querySelector('.season-header');
            const epContainer = seasonContainer.querySelector('.episodes-container');

            header.addEventListener('click', (e) => {
                if (e.target.closest('.season-checkbox') || e.target.closest('.season-label') || e.target.closest('.season-lang-badge') || e.target.closest('.season-provider-badge') || e.target.closest('.control-btn')) {
                    return;
                }
                seasonContainer.classList.toggle('collapsed');
                header.setAttribute('aria-expanded', String(!seasonContainer.classList.contains('collapsed')));
            });

            header.addEventListener('keydown', (e) => {
                if (e.key !== 'Enter' && e.key !== ' ') return;
                if (e.target !== header) return;
                e.preventDefault();
                seasonContainer.classList.toggle('collapsed');
                header.setAttribute('aria-expanded', String(!seasonContainer.classList.contains('collapsed')));
            });

            seasonContainer.querySelector('.season-checkbox').addEventListener('change', (e) => {
                e.stopPropagation();
                this.toggleSeason(seasonNum, e.target.checked);
            });

            seasonContainer.querySelector('.season-label').addEventListener('click', (e) => {
                e.stopPropagation();
            });

            season.forEach(episode => {
                const epItem = document.createElement('div');
                epItem.className = 'episode-item-tree';
                const epId = `${episode.season}-${episode.episode}`;
                epItem.innerHTML = `
                    <div class="episode-checkbox-wrapper">
                        <input type="checkbox" class="episode-checkbox" id="episode-${epId}">
                        <label for="episode-${epId}" class="episode-label">${escapeHtml(episode.title)}</label>
                    </div>
                    <div class="episode-lang-wrapper" data-episode-url="${episode.url}">
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
        if (episodesToVerify.length > 0) {
            if (this.elements.episodeVerification) this.elements.episodeVerification.hidden = false;
            this.autoVerifyEpisodeLanguages(episodesToVerify);
        } else if (this.elements.episodeVerification) {
            this.elements.episodeVerification.hidden = true;
        }
    },

    updateSeasonLanguageBadges(seasonNum) {
        const season = this.state.availableEpisodes[seasonNum];
        const header = this.elements.episodeTree.querySelector(`.season-header[data-season="${seasonNum}"]`);
        if (!season || !header) return;

        let badgesContainer = header.querySelector('.season-lang-badges') || document.createElement('div');
        badgesContainer.className = 'season-lang-badges';
        if (!header.querySelector('.season-lang-badges')) header.appendChild(badgesContainer);

        const allLangs = new Set();
        season.forEach(ep => ep.languages?.forEach(l => allLangs.add(l)));
        if (allLangs.size === 0) { badgesContainer.innerHTML = ''; return; }

        badgesContainer.innerHTML = '';
        Array.from(allLangs).sort().forEach(lang => {
            const badge = document.createElement('button');
            badge.type = 'button';
            badge.className = 'season-lang-badge';
            badge.textContent = lang.replace('German', 'DE').replace('English', 'EN').replace('Dub', 'Dub').replace('Sub', 'Sub');
            badge.title = `Select ${lang} for all episodes in Season ${seasonNum}`;
            badge.addEventListener('click', (e) => {
                e.stopPropagation();
                season.forEach(ep => {
                    if (ep.languages?.includes(lang)) {
                        this.state.episodeLanguageSelections[ep.url] = lang;
                        const epLangWrapper = document.querySelector(`.episode-lang-wrapper[data-episode-url="${ep.url}"]`);
                        epLangWrapper?.querySelectorAll('.lang-badge').forEach(b => {
                            b.classList.toggle('active', b.title === lang);
                            b.setAttribute('aria-pressed', String(b.title === lang));
                        });
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
        if (!season || !header) return;

        let badgesContainer = header.querySelector('.season-provider-badges') || document.createElement('div');
        badgesContainer.className = 'season-provider-badges';
        if (!header.querySelector('.season-provider-badges')) header.appendChild(badgesContainer);

        const allProvs = new Set();
        season.forEach(ep => ep.providers?.forEach(p => allProvs.add(p)));
        if (allProvs.size === 0) { badgesContainer.innerHTML = ''; return; }

        const sitePrefs = this.getSiteProviderPrefs();

        const sortedProvs = Array.from(allProvs).sort((a, b) => {
            const indexA = sitePrefs ? sitePrefs.indexOf(a) : -1;
            const indexB = sitePrefs ? sitePrefs.indexOf(b) : -1;

            if (indexA === -1 && indexB === -1) return a.localeCompare(b);
            if (indexA === -1) return 1;
            if (indexB === -1) return -1;
            return indexA - indexB;
        });

        badgesContainer.innerHTML = '';
        sortedProvs.forEach(prov => {
            const badge = document.createElement('button');
            badge.type = 'button';
            badge.className = 'season-provider-badge';
            badge.textContent = prov.replace('streamtape', 'ST').replace('filemoon', 'FM').replace('vidmoly', 'VM').replace('vidoza', 'VZ').replace(/GXPlayer/i, 'GX');
            badge.title = `Select ${prov} for all episodes in Season ${seasonNum}`;
            badge.addEventListener('click', (e) => {
                e.stopPropagation();
                season.forEach(ep => {
                    if (ep.providers?.includes(prov)) {
                        this.state.episodeProviderSelections[ep.url] = prov;
                        const epProvWrapper = document.querySelector(`.episode-provider-wrapper[data-episode-url="${ep.url}"]`);
                        epProvWrapper?.querySelectorAll('.provider-badge').forEach(b => {
                            b.classList.toggle('active', b.title === prov);
                            b.setAttribute('aria-pressed', String(b.title === prov));
                        });
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
            
            if (isTrackerEnabled && count === 0) {
                this.elements.confirmBtn.textContent = 'Add tracker';
            } else {
                this.elements.confirmBtn.textContent = count > 0 ? `Start download (${count})` : 'Start download';
            }
        }

        if (this.elements.selectionHint) {
            this.elements.selectionHint.textContent = count === 0
                ? (isTrackerEnabled ? 'No episodes selected; the tracker will be added.' : 'Select at least one episode.')
                : `${count} ${count === 1 ? 'episode' : 'episodes'} selected.`;
        }
    },

    async startDownload() {
        const isTrackerEnabled = this.elements.trackCheckbox?.checked;
        const count = this.state.selectedEpisodes.size;

        if (!this.state.currentDownloadData || (count === 0 && !isTrackerEnabled)) {
            showNotification('Please select at least one episode to download or enable tracking', 'error');
            return;
        }

        this.elements.confirmBtn.disabled = true;
        this.elements.confirmBtn.textContent = count > 0 ? 'Starting…' : 'Adding…';

        const trackingLang = this.elements.trackerLanguage?.value || 'German Dub';

        if (count === 0 && isTrackerEnabled) {
            const defaultProv = this.state.currentDownloadData.site === 's.to' ? 'VOE' : 'VOE'; // Fallback
            
            const success = await Trackers.addTrackerForSeries(this.state.currentDownloadData, this.state.availableEpisodes, trackingLang, defaultProv);
            if (success) this.hideModal();
            this.elements.confirmBtn.disabled = false;
            this.updateSelectedCount();
            return;
        }

        const selectedUrls = [];
        const episodesConfig = {};
        
        // Use first selected episode's language or preferred language for overall request (though episodesConfig overrides)
        const sitePrefs = this.getSiteLanguagePrefs();
        let overallLang = sitePrefs && sitePrefs.length > 0 ? sitePrefs[0] : 'German Dub';
        let overallProv = 'VOE';

        this.state.selectedEpisodes.forEach(key => {
            const [s, e] = key.split('-').map(Number);
            const epData = this.state.availableEpisodes[s]?.find(item => item.season === s && item.episode === e);
            if (epData) {
                selectedUrls.push(epData.url);
                const epLang = this.state.episodeLanguageSelections[epData.url] || overallLang;
                const epProv = this.state.episodeProviderSelections[epData.url] || (epData.providers && epData.providers.length > 0 ? epData.providers[0] : overallProv);
                episodesConfig[epData.url] = { language: epLang, provider: epProv };
                overallLang = epLang; // Use the last one as representative
                overallProv = epProv;
            }
        });

        try {
            const data = await API.startDownload({
                episode_urls: selectedUrls,
                language: overallLang,
                provider: overallProv,
                anime_title: this.state.currentDownloadData.anime,
                episodes_config: episodesConfig
            });
            if (data.success) {
                showNotification(`Download started for ${selectedUrls.length} episodes`, 'success');
                if (isTrackerEnabled) await Trackers.addTrackerForSeries(this.state.currentDownloadData, this.state.availableEpisodes, trackingLang, overallProv);
                this.hideModal();
                Queue.startTracking();
            } else { showNotification(data.error || 'Download failed', 'error'); }
        } catch (err) { showNotification('Failed to start download', 'error'); }
        finally {
            this.elements.confirmBtn.disabled = false;
            this.updateSelectedCount();
        }
    }
};
