@echo off
setlocal enabledelayedexpansion

set CURRENT_DIR=%cd%
cd ..\..

py -m pip install -U pip
py -m pip install -U nuitka imageio
py -m pip install -U -e .

rem Extract JSON_PATH
for /f "delims=" %%i in ('py -c "import fake_useragent, os; print(os.path.join(os.path.dirname(fake_useragent.__file__), 'data', 'browsers.jsonl'))"') do set JSON_PATH=%%i

rem Extract version
for /f "delims=" %%i in ('py -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])"') do set VERSION=%%i

rem Get the current year
for /f "delims=" %%i in ('powershell -Command "(Get-Date).Year"') do set YEAR=%%i

rem Display the extracted information
echo JSON_PATH: !JSON_PATH!
echo Version: !VERSION!
echo Year: !YEAR!

rem Create temporary build directory
set TEMP_BUILD_DIR=%TEMP%\aniworld_build_%RANDOM%
mkdir "%TEMP_BUILD_DIR%"
xcopy /E /I /Q src "%TEMP_BUILD_DIR%\src\"

rem Run preprocessing on temp directory
pushd "%TEMP_BUILD_DIR%"
py src/aniworld/nuitka/preprocess.py
popd

set TEMP_MAIN_PATH=%TEMP_BUILD_DIR%\src\aniworld\__main__.py

py -m nuitka ^
    --onefile ^
    --assume-yes-for-downloads ^
    --show-progress ^
    --remove-output ^
    --lto=no ^
    --disable-ccache ^
    --nofollow-import-to=yt_dlp.extractor.lazy_extractors ^
    --nofollow-import-to=yt_dlp.extractor.youtube_dl ^
    --nofollow-import-to=yt_dlp.extractor.wikimedia ^
    --nofollow-import-to=yt_dlp.extractor.wikipedia ^
    --nofollow-import-to=yt_dlp.extractor.wikidata ^
    --include-package=aniworld ^
    --include-data-file="!JSON_PATH!=fake_useragent/data/browsers.jsonl" ^
    --include-data-file=src/aniworld/ASCII.txt=aniworld/ASCII.txt ^
    --include-data-file=src/aniworld/aniskip/scripts/aniskip.lua=aniworld/aniskip/scripts/aniskip.lua ^
    --include-data-file=src/aniworld/aniskip/scripts/autostart.lua=aniworld/aniskip/scripts/autostart.lua ^
    --include-data-file=src/aniworld/aniskip/scripts/autoexit.lua=aniworld/aniskip/scripts/autoexit.lua ^
    --output-filename="aniworld-!VERSION!-windows_x64" ^
    --company-name="Phoenixthrush UwU" ^
    --product-name="LankabelTV" ^
    --file-version="!VERSION!" ^
    --product-version="!VERSION!" ^
    --file-description="LankabelTV is a command-line tool for downloading and streaming content from aniworld.to and s.to." ^
    --copyright="Copyright (c) 2024-!YEAR! phoenixthrush, Tmaster055" ^
    --windows-icon-from-ico=src/aniworld/nuitka/icon.webp ^
    "%TEMP_MAIN_PATH%"

rem Clean up temporary directory only (Nuitka cleans itself with --remove-output)
rmdir /S /Q "%TEMP_BUILD_DIR%"

cd /d "%CURRENT_DIR%"
