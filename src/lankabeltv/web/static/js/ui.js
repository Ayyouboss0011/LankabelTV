/**
 * ui.js - UI helpers and theme management for Netflix-style LankabelTV
 */

export function showNotification(msg, type = 'info') {
    const n = document.createElement('div');
    n.className = `notification ${type}`;
    n.textContent = msg;
    n.style.cssText = `position: fixed; top: 80px; right: 20px; padding: 12px 20px; border-radius: 4px; color: white; z-index: 2000; background: ${type === 'success' ? '#46d369' : (type === 'error' ? '#e50914' : '#2f2f2f')}; box-shadow: 0 4px 12px rgba(0,0,0,0.5); font-weight: bold;`;
    document.body.appendChild(n);
    setTimeout(() => {
        n.style.opacity = '0';
        n.style.transition = 'opacity 0.5s ease';
        setTimeout(() => n.remove(), 500);
    }, 3000);
}

export function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

export const UI = {
    elements: {
        homeContent: document.getElementById('home-content'),
        resultsSection: document.getElementById('results-section'),
        loadingSection: document.getElementById('loading-section'),
        heroSection: document.getElementById('hero-section'),
        homeLoading: document.getElementById('home-loading')
    },

    showLoadingState() {
        if (this.elements.homeContent) this.elements.homeContent.style.display = 'none';
        if (this.elements.resultsSection) this.elements.resultsSection.style.display = 'none';
        if (this.elements.heroSection) this.elements.heroSection.style.display = 'none';
        if (this.elements.loadingSection) this.elements.loadingSection.style.display = 'block';
    },

    hideLoadingState() {
        if (this.elements.loadingSection) this.elements.loadingSection.style.display = 'none';
    },

    showResultsSection() {
        if (this.elements.homeContent) this.elements.homeContent.style.display = 'none';
        if (this.elements.loadingSection) this.elements.loadingSection.style.display = 'none';
        if (this.elements.heroSection) this.elements.heroSection.style.display = 'none';
        if (this.elements.resultsSection) this.elements.resultsSection.style.display = 'block';
    },

    showHomeContent() {
        if (this.elements.resultsSection) this.elements.resultsSection.style.display = 'none';
        if (this.elements.loadingSection) this.elements.loadingSection.style.display = 'none';
        if (this.elements.homeContent) this.elements.homeContent.style.display = 'block';
        if (this.elements.heroSection) this.elements.heroSection.style.display = 'block';
    },

    initializeTheme() {
        // Netflix design is always dark
        document.body.setAttribute('data-theme', 'dark');
    },

    toggleTheme() {
        // Disabled for Netflix style
        showNotification("Netflix style is optimized for dark mode.", "info");
    },

    showConfirmModal(title, message, onConfirm) {
        const modal = document.createElement('div');
        modal.className = 'modal-overlay';
        modal.style.display = 'flex';
        modal.style.zIndex = '3000';
        modal.style.alignItems = 'center';
        modal.style.justifyContent = 'center';
        
        modal.innerHTML = `
            <div class="modal-content" style="max-width: 450px !important; min-height: auto !important; height: auto !important; padding: 30px; position: relative; display: block;">
                <h3 style="margin-bottom: 20px; font-size: 1.5rem; font-weight: 700;">${title}</h3>
                <p style="margin-bottom: 30px; color: #b3b3b3; font-size: 1.1rem; line-height: 1.5;">${message}</p>
                <div style="display: flex; justify-content: flex-end; gap: 15px;">
                    <button class="lang-badge cancel-btn" style="padding: 10px 20px; background: #333; border: none; color: white; border-radius: 4px; cursor: pointer;">Cancel</button>
                    <button class="hero-btn primary confirm-btn" style="padding: 10px 20px; font-size: 0.9rem; min-width: 100px; justify-content: center;">Confirm</button>
                </div>
                <button class="close-modal-x" style="position: absolute; right: 20px; top: 20px; background: none; border: none; color: white; font-size: 24px; cursor: pointer;">&times;</button>
            </div>
        `;
        
        const close = () => {
            modal.style.opacity = '0';
            modal.style.transition = 'opacity 0.2s ease';
            setTimeout(() => modal.remove(), 200);
        };
        
        modal.querySelector('.cancel-btn').onclick = close;
        modal.querySelector('.close-modal-x').onclick = close;
        modal.querySelector('.confirm-btn').onclick = () => {
            onConfirm();
            close();
        };
        
        // Close on backdrop click
        modal.onclick = (e) => {
            if (e.target === modal) close();
        };
        
        document.body.appendChild(modal);
    }
};
