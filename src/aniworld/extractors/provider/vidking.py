import re
import logging
import json
import base64
import time
import hashlib
import requests
from typing import Optional, Dict, Any
from ... import config

# Regex patterns for API tokens and encrypted data
JWT_PATTERN = re.compile(r'x-app-token["\']\s*:\s*["\']([^"\']+)["\']')
AES_DATA_PATTERN = re.compile(r'^(U2FsdGVkX1[A-Za-z0-9+/=]+)')
SCRIPT_TOKEN_PATTERN = re.compile(r'token\s*=\s*["\']([^"\']+)["\']')

def decrypt_cryptojs_aes(encrypted_data: str, password: str) -> Optional[str]:
    """
    Decrypt CryptoJS style AES (OpenSSL compatible) data.
    """
    try:
        from Cryptodome.Cipher import AES
        from Cryptodome.Util.Padding import unpad

        data = base64.b64decode(encrypted_data)
        if data[:8] != b'Salted__':
            return None
        
        salt = data[8:16]
        ciphertext = data[16:]

        # CryptoJS uses PBKDF1 (MD5) to derive key and IV
        # Key: 32 bytes, IV: 16 bytes
        def derive_key_iv(password_bytes, salt_bytes, key_len, iv_len):
            d = d_i = b''
            while len(d) < key_len + iv_len:
                d_i = hashlib.md5(d_i + password_bytes + salt_bytes).digest()
                d += d_i
            return d[:key_len], d[key_len:key_len + iv_len]

        key, iv = derive_key_iv(password.encode(), salt, 32, 16)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted = unpad(cipher.decrypt(ciphertext), AES.block_size)
        return decrypted.decode('utf-8')
    except ImportError:
        logging.error("Missing 'pycryptodome' package. Please install with 'pip install pycryptodome'")
        return None
    except Exception as e:
        logging.debug(f"AES Decryption failed with password '{password}': {e}")
        return None

def get_direct_link_from_vidking(embeded_vidking_link: str) -> str:
    """
    Extract direct m3u8 video link from VidKing using their API and AES decryption.
    """
    try:
        # Normalize the link (ensure it's a vidking.net link)
        if "vidking.net" not in embeded_vidking_link:
            tmdb_id = embeded_vidking_link.split("/")[-1].replace("vidking:", "")
            embeded_vidking_link = f"https://www.vidking.net/embed/movie/{tmdb_id}"
        else:
            tmdb_id = embeded_vidking_link.rstrip("/").split("/")[-1]

        headers = {
            "User-Agent": config.RANDOM_USER_AGENT,
            "Referer": "https://www.vidking.net/",
            "Origin": "https://www.vidking.net"
        }

        # Step 1: Get the player page to find the x-app-token
        session = requests.Session()
        response = session.get(embeded_vidking_link, headers=headers, timeout=config.DEFAULT_REQUEST_TIMEOUT)
        response.raise_for_status()

        # Step 2: Extract x-app-token (JWT)
        token = ""
        # Search in HTML
        token_match = JWT_PATTERN.search(response.text)
        if token_match:
            token = token_match.group(1)
        
        # If not in HTML, try to find linked scripts and check them
        if not token:
            script_urls = re.findall(r'src=["\'](https?://[^"\']+\.js[^"\']*)["\']', response.text)
            for script_url in script_urls[:3]: # Only check first 3 scripts for performance
                try:
                    s_resp = session.get(script_url, headers=headers, timeout=5)
                    t_match = JWT_PATTERN.search(s_resp.text) or SCRIPT_TOKEN_PATTERN.search(s_resp.text)
                    if t_match:
                        token = t_match.group(1)
                        break
                except:
                    continue

        # Step 3: Call the sources API
        # The structure is often: https://api.videasy.net/{provider}/sources-with-title
        providers = ["myflixerzupcloud", "upcloud", "vidking", "videasy"]
        api_base = "https://api.videasy.net"
        
        sources = []
        
        # We need the x-app-token for this to work
        if not token:
            # Fallback dummy token if extraction fails
            token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0bSI6MTc3MDM0MTY4MTgzNiwiaXAiOiIifQ.dummy"

        api_headers = headers.copy()
        api_headers["x-app-token"] = token
        
        for prov in providers:
            api_url = f"{api_base}/{prov}/sources-with-title"
            params = {
                "mediaType": "movie",
                "tmdbId": tmdb_id,
                "_t": int(time.time() * 1000)
            }
            
            try:
                api_response = session.get(api_url, params=params, headers=api_headers, timeout=10)
                if api_response.status_code == 200:
                    encrypted_data = api_response.text.strip()
                    
                    # Step 4: Decrypt the response
                    # Known VidKing/Videasy passwords
                    passwords = [
                        "v_player_secret_key", 
                        "videasy", 
                        "vidking", 
                        "flixer", 
                        "upcloud",
                        "v_player",
                        "secret_key",
                        "4f5g6h7j8k9l"
                    ]
                    
                    for pw in passwords:
                        decrypted = decrypt_cryptojs_aes(encrypted_data, pw)
                        if decrypted:
                            try:
                                data = json.loads(decrypted)
                                if isinstance(data, dict) and "sources" in data:
                                    for source in data["sources"]:
                                        if source.get("type") == "hls" or ".m3u8" in source.get("file", ""):
                                            return source["file"]
                            except json.JSONDecodeError:
                                continue
            except:
                continue

        # Final Fallback: Search the original HTML for any m3u8 URL patterns
        # Some versions of the player put it in a global variable
        m3u8_match = re.search(r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', response.text)
        if m3u8_match:
            return m3u8_match.group(1)

        raise ValueError("Failed to extract m3u8 source from VidKing API after multiple attempts.")

    except Exception as err:
        raise ValueError(f"VidKing API Error: {err}") from err

def get_preview_image_link_from_vidking(embeded_vidking_link: str) -> str:
    """
    Try to extract the preview image.
    """
    try:
        tmdb_id = embeded_vidking_link.split("/")[-1].replace("vidking:", "")
        return f"https://image.tmdb.org/t/p/w1280/{tmdb_id}.jpg"
    except Exception:
        return ""

if __name__ == "__main__":
    link = "https://www.vidking.net/embed/movie/383498"
    try:
        print(f"Direct Link: {get_direct_link_from_vidking(link)}")
    except Exception as e:
        print(f"Error: {e}")
