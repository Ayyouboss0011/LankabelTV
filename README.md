<div align="center">
  <img src="Photos/LankabelTV_Logo.png" alt="LankabelTV Logo" width="300" style="margin-bottom: 20px;">
  <br>
  <br>
  <a href="https://www.buymeacoffee.com/ayyouboss" target="_blank">
    <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" >
  </a>
</div>

<br>
<hr>
<br>

<div align="center">
  <img src="Photos/Photo1.png" width="80%" alt="Screenshot 1" style="margin-bottom: 30px; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
  <br>
  <br>
  <img src="Photos/Photo2.png" width="80%" alt="Screenshot 2" style="margin-bottom: 30px; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
  <br>
  <br>
  <img src="Photos/Photo3.png" width="80%" alt="Screenshot 3" style="margin-bottom: 10px; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
</div>

<br>
<hr>
<br>

LankabelTV is a modern, fast, and resource-efficient command-line tool and web interface for downloading and streaming anime and series.

Unlike other tools, LankabelTV does not rely on heavy browser automation, but uses direct HTTP requests and powerful libraries like `yt-dlp` and `BeautifulSoup`. This ensures maximum performance and an easy setup.

## ✨ Features

- **Modern Web UI:** An elegant, "Netflix-style" web interface with dynamic catalogs.
- **TMDB Integration:** Automatic enrichment of series and animes with posters, descriptions, and ratings directly from The Movie Database.
- **Resource Efficient:** No virtual displays (Xvfb) or Chromium instances required. Runs natively and lightweight.
- **Multi-Source Support:** Seamlessly supports content from various providers.
- **Interactive CLI:** A fast, curses-based command-line interface for terminal lovers.
- **Smart Search:** Integrated content filter and optimized search logic.

## 🚀 Quick Start

### Prerequisites
- Python 3.9 or higher
- `ffmpeg` (for video processing)

### Installation

```bash
# Clone the repository
git clone https://github.com/Ayyouboss0011/LankabelTV.git
cd LankabelTV

# Install dependencies
pip install -r requirements.txt
pip install -e .
```

### Usage

```bash
# Start Web UI (Default)
lankabeltv -w -p 8080

# Start CLI mode
lankabeltv
```

## 🐳 Docker Deployment

LankabelTV is fully optimized for Docker. Since there are no browser dependencies, the image is extremely small and efficient.

```bash
docker-compose up -d --build
```
*By default, your downloads will be saved in the mounted `./downloads` directory.*

## 🛠️ Technologies

LankabelTV is built on a robust Python stack:
- **Scraping & Downloads:** `requests`, `BeautifulSoup4`, `yt-dlp`
- **Web Frontend:** `Flask`, Modern Vanilla JS, CSS Variables
- **CLI:** `npyscreen`, `curses`

## ⚠️ Legal Disclaimer

LankabelTV is purely a client-side tool. It does not host, store, or distribute any copyrighted media itself. Use of this tool is at your own risk. Ensure that you respect the terms of service of the websites you access, as well as the applicable laws in your country.

## 📄 License

This project is released under the MIT License. See the `LICENSE` file for more details.
