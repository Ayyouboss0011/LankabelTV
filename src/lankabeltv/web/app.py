"""
Flask web application for LankabelTV
"""

import logging
import os
import time
import threading
import webbrowser
from datetime import datetime
from functools import wraps
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, render_template, jsonify, request, session, redirect, url_for

from .. import config
from ..models import Episode
from .database import UserDatabase
from .download_manager import get_download_manager


class WebApp:
    """Flask web application wrapper for LankabelTV"""

    def __init__(self, host="0.0.0.0", port=5000, debug=False, arguments=None):
        """
        Initialize the Flask web application.

        Args:
            host: Host to bind to (default: 127.0.0.1)
            port: Port to bind to (default: 5000)
            debug: Enable Flask debug mode (default: False)
            arguments: Command line arguments object
        """
        self.host = host
        self.port = port
        self.debug = debug
        self.arguments = arguments
        self.start_time = time.time()

        # Authentication settings
        self.auth_enabled = (
            getattr(arguments, "enable_web_auth", False) if arguments else False
        )
        # Always initialize DB for trackers, even if auth is disabled
        self.db = UserDatabase()

        # Download manager
        self.download_manager = get_download_manager(self.db)

        # Create Flask app
        self.app = self._create_app()

        # Setup routes
        self._setup_routes()

        # Start tracker processor
        self.download_manager.start_tracker_processor()

    def _create_app(self) -> Flask:
        """Create and configure Flask application."""
        # Get the web module directory
        web_dir = os.path.dirname(os.path.abspath(__file__))

        app = Flask(
            __name__,
            template_folder=os.path.join(web_dir, "templates"),
            static_folder=os.path.join(web_dir, "static"),
        )

        # Configure Flask
        app.config["SECRET_KEY"] = os.urandom(24)
        app.config["JSON_SORT_KEYS"] = False

        return app

    def _require_api_auth(self, f):
        """Decorator to require authentication for API routes."""

        @wraps(f)
        def decorated_function(*args, **kwargs):
            # If authentication is disabled, allow all API calls
            if not self.auth_enabled:
                return f(*args, **kwargs)

            if not self.db:
                return jsonify({"error": "Authentication database not available"}), 500

            session_token = request.cookies.get("session_token")
            if not session_token:
                # Still check if we have any users, if not, it's local mode or first setup
                if not self.db.has_users():
                    return f(*args, **kwargs)
                return jsonify({"error": "Authentication required"}), 401

            user = self.db.get_user_by_session(session_token)
            if not user:
                return jsonify({"error": "Invalid session"}), 401

            return f(*args, **kwargs)

        return decorated_function

    def _require_auth(self, f):
        """Decorator to require authentication for routes."""

        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not self.auth_enabled:
                return f(*args, **kwargs)

            if not self.db:
                # If no DB but auth enabled, something is wrong, allow login/setup
                return f(*args, **kwargs)

            # Check for session token in cookies
            session_token = request.cookies.get("session_token")
            if not session_token:
                # If no session, only redirect if we're not already on a public page
                if request.endpoint in ["login", "setup", "static"]:
                    return f(*args, **kwargs)
                return redirect(url_for("login"))

            user = self.db.get_user_by_session(session_token)
            if not user:
                if request.endpoint in ["login", "setup", "static"]:
                    return f(*args, **kwargs)
                return redirect(url_for("login"))

            # Store user info in Flask session for templates
            session["user"] = user
            return f(*args, **kwargs)

        return decorated_function

    def _require_admin(self, f):
        """Decorator to require admin privileges for routes."""

        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not self.auth_enabled:
                return f(*args, **kwargs)

            if not self.db:
                return jsonify({"error": "Authentication database not available"}), 500

            session_token = request.cookies.get("session_token")
            if not session_token:
                return redirect(url_for("login"))

            user = self.db.get_user_by_session(session_token)
            if not user or not user["is_admin"]:
                return jsonify({"error": "Admin access required"}), 403

            session["user"] = user
            return f(*args, **kwargs)

        return decorated_function

    def _setup_routes(self):
        """Setup Flask routes."""

        @self.app.route("/")
        @self._require_auth
        def index():
            """Main page route."""
            if self.auth_enabled and self.db:
                # Check if this is first-time setup
                if not self.db.has_users():
                    return redirect(url_for("setup"))

                # Get current user info for template
                session_token = request.cookies.get("session_token")
                user = self.db.get_user_by_session(session_token)
                return render_template("index.html", user=user, auth_enabled=True)
            else:
                return render_template("index.html", auth_enabled=False)

        @self.app.route("/login", methods=["GET", "POST"])
        def login():
            """Login page route."""
            if not self.auth_enabled or not self.db:
                return redirect(url_for("index"))

            # If no users exist, redirect to setup
            if not self.db.has_users():
                return redirect(url_for("setup"))

            if request.method == "POST":
                data = request.get_json()
                username = data.get("username", "").strip()
                password = data.get("password", "")

                if not username or not password:
                    return jsonify(
                        {"success": False, "error": "Username and password required"}
                    ), 400

                user = self.db.verify_user(username, password)
                if user:
                    session_token = self.db.create_session(user["id"])
                    response = jsonify({"success": True, "redirect": url_for("index")})
                    response.set_cookie(
                        "session_token",
                        session_token,
                        httponly=True,
                        secure=False,
                        max_age=30 * 24 * 60 * 60,
                    )
                    return response
                else:
                    return jsonify(
                        {"success": False, "error": "Invalid credentials"}
                    ), 401

            return render_template("login.html")

        @self.app.route("/logout", methods=["POST"])
        def logout():
            """Logout route."""
            if not self.auth_enabled or not self.db:
                return redirect(url_for("index"))

            session_token = request.cookies.get("session_token")
            if session_token:
                self.db.delete_session(session_token)

            response = jsonify({"success": True, "redirect": url_for("login")})
            response.set_cookie("session_token", "", expires=0)
            return response

        @self.app.route("/setup", methods=["GET", "POST"])
        def setup():
            """First-time setup route for creating admin user."""
            if not self.auth_enabled or not self.db:
                return redirect(url_for("index"))

            if self.db.has_users():
                return redirect(url_for("index"))

            if request.method == "POST":
                data = request.get_json()
                username = data.get("username", "").strip()
                password = data.get("password", "")

                if not username or not password:
                    return jsonify(
                        {"success": False, "error": "Username and password required"}
                    ), 400

                if len(password) < 6:
                    return jsonify(
                        {
                            "success": False,
                            "error": "Password must be at least 6 characters",
                        }
                    ), 400

                if self.db.create_user(
                    username, password, is_admin=True, is_original_admin=True
                ):
                    return jsonify(
                        {
                            "success": True,
                            "message": "Admin user created successfully",
                            "redirect": url_for("login"),
                        }
                    )
                else:
                    return jsonify(
                        {"success": False, "error": "Failed to create user"}
                    ), 500

            return render_template("setup.html")

        @self.app.route("/settings")
        @self._require_auth
        def settings():
            """Settings page route."""
            # If auth disabled, create a dummy admin user for the template
            if not self.auth_enabled:
                user = {"username": "Local User", "is_admin": True, "is_original_admin": True, "id": 0}
                users = []
                return render_template("settings.html", user=user, users=users, auth_enabled=False)

            if not self.db:
                return redirect(url_for("index"))

            session_token = request.cookies.get("session_token")
            user = self.db.get_user_by_session(session_token)
            users = self.db.get_all_users() if user and user["is_admin"] else []

            return render_template("settings.html", user=user, users=users, auth_enabled=True)

        # User management API routes
        @self.app.route("/api/users", methods=["GET"])
        @self._require_admin
        def api_get_users():
            """Get all users (admin only)."""
            if not self.db:
                return jsonify(
                    {"success": False, "error": "Authentication not available"}
                ), 500
            users = self.db.get_all_users()
            return jsonify({"success": True, "users": users})

        @self.app.route("/api/users", methods=["POST"])
        @self._require_admin
        def api_create_user():
            """Create new user (admin only)."""
            data = request.get_json()

            if not data:
                return jsonify(
                    {"success": False, "error": "No JSON data received"}
                ), 400

            # Debug logging
            logging.debug(f"Received data: {data}")

            username = data.get("username", "").strip()
            password = data.get("password", "").strip()
            is_admin = data.get("is_admin", False)

            # Debug logging
            logging.debug(
                f"Processed - username: '{username}', password: 'XXX', is_admin: {is_admin}"
            )

            if not username or not password:
                return jsonify(
                    {
                        "success": False,
                        "error": f'Username and password required. Got username: "{username}", password: "{password}"',
                    }
                ), 400

            if len(password) < 6:
                return jsonify(
                    {
                        "success": False,
                        "error": "Password must be at least 6 characters",
                    }
                ), 400

            if not self.db:
                return jsonify(
                    {"success": False, "error": "Authentication not available"}
                ), 500

            if self.db.create_user(username, password, is_admin):
                return jsonify(
                    {"success": True, "message": "User created successfully"}
                )
            else:
                return jsonify(
                    {
                        "success": False,
                        "error": "Failed to create user (username may already exist)",
                    }
                ), 400

        @self.app.route("/api/users/<int:user_id>", methods=["DELETE"])
        @self._require_admin
        def api_delete_user(user_id):
            """Delete user (admin only)."""
            if not self.db:
                return jsonify(
                    {"success": False, "error": "Authentication not available"}
                ), 500

            # Get user info to check if it's the original admin
            users = self.db.get_all_users()
            user_to_delete = next((u for u in users if u["id"] == user_id), None)

            if user_to_delete and user_to_delete.get("is_original_admin"):
                return jsonify(
                    {"success": False, "error": "Cannot delete the original admin user"}
                ), 400

            if self.db.delete_user(user_id):
                return jsonify(
                    {"success": True, "message": "User deleted successfully"}
                )
            else:
                return jsonify(
                    {"success": False, "error": "Failed to delete user"}
                ), 400

        @self.app.route("/api/users/<int:user_id>", methods=["PUT"])
        @self._require_admin
        def api_update_user(user_id):
            """Update user (admin only)."""
            data = request.get_json()
            username = (
                data.get("username", "").strip() if data.get("username") else None
            )
            password = data.get("password", "") if data.get("password") else None
            is_admin = data.get("is_admin") if "is_admin" in data else None

            if password and len(password) < 6:
                return jsonify(
                    {
                        "success": False,
                        "error": "Password must be at least 6 characters",
                    }
                ), 400

            if not self.db:
                return jsonify(
                    {"success": False, "error": "Authentication not available"}
                ), 500

            if self.db.update_user(user_id, username, password, is_admin):
                return jsonify(
                    {"success": True, "message": "User updated successfully"}
                )
            else:
                return jsonify(
                    {"success": False, "error": "Failed to update user"}
                ), 400

        @self.app.route("/api/change-password", methods=["POST"])
        @self._require_api_auth
        def api_change_password():
            """Change user password."""
            if not self.auth_enabled or not self.db:
                return jsonify(
                    {"success": False, "error": "Authentication not enabled"}
                ), 400

            session_token = request.cookies.get("session_token")
            user = self.db.get_user_by_session(session_token)
            if not user:
                return jsonify({"success": False, "error": "Invalid session"}), 401

            data = request.get_json()
            current_password = data.get("current_password", "")
            new_password = data.get("new_password", "")

            if not current_password or not new_password:
                return jsonify(
                    {
                        "success": False,
                        "error": "Current and new passwords are required",
                    }
                ), 400

            if len(new_password) < 6:
                return jsonify(
                    {
                        "success": False,
                        "error": "New password must be at least 6 characters",
                    }
                ), 400

            if self.db.change_password(user["id"], current_password, new_password):
                return jsonify(
                    {"success": True, "message": "Password changed successfully"}
                )
            else:
                return jsonify(
                    {
                        "success": False,
                        "error": "Failed to change password. Current password may be incorrect.",
                    }
                ), 400

        @self.app.route("/api/test")
        @self._require_api_auth
        def api_test():
            """API test endpoint."""
            return jsonify(
                {
                    "status": "success",
                    "message": "Connection test successful",
                    "timestamp": datetime.now().isoformat(),
                    "version": config.VERSION,
                }
            )

        @self.app.route("/api/info")
        @self._require_api_auth
        def api_info():
            """API info endpoint."""
            uptime_seconds = int(time.time() - self.start_time)
            uptime_str = self._format_uptime(uptime_seconds)

            # Convert latest_version to string if it's a Version object
            latest_version = getattr(config, "LATEST_VERSION", None)
            if latest_version is not None:
                latest_version = str(latest_version)

            return jsonify(
                {
                    "version": config.VERSION,
                    "status": "running",
                    "uptime": uptime_str,
                    "latest_version": latest_version,
                    "is_newest": getattr(config, "IS_NEWEST_VERSION", True),
                    "supported_providers": list(config.SUPPORTED_PROVIDERS),
                    "platform": config.PLATFORM_SYSTEM,
                }
            )

        @self.app.route("/health")
        def health():
            """Health check endpoint."""
            return jsonify(
                {"status": "healthy", "timestamp": datetime.now().isoformat()}
            )

        @self.app.route("/api/search", methods=["POST"])
        @self._require_api_auth
        def api_search():
            """Search for anime endpoint."""
            try:
                from flask import request

                data = request.get_json()
                if not data or "query" not in data:
                    return jsonify(
                        {"success": False, "error": "Query parameter is required"}
                    ), 400

                query = data["query"].strip()
                if not query:
                    return jsonify(
                        {"success": False, "error": "Query cannot be empty"}
                    ), 400

                # Get site parameter (default to both)
                site = data.get("site", "both")

                # Create wrapper function for search with dual-site support
                def search_anime_wrapper(keyword, site="both"):
                    """Wrapper function for anime search with multi-site support"""
                    from ..search import search_anime
                    from .. import config

                    if site == "both":
                        # Search both sites
                        lankabeltv_results = []
                        sto_results = []

                        try:
                            lankabeltv_results = search_anime(keyword=keyword, only_return=True, site="aniworld.to")
                        except Exception as e:
                            logging.warning(f"Failed to fetch from aniworld: {e}")

                        try:
                            sto_results = search_anime(keyword=keyword, only_return=True, site="s.to")
                        except Exception as e:
                            logging.warning(f"Failed to fetch from s.to: {e}")

                        # Combine and deduplicate results
                        all_results = []
                        seen_slugs = set()

                        # Add lankabeltv results
                        for anime in lankabeltv_results:
                            slug = anime.get("link", "")
                            if slug and slug not in seen_slugs:
                                anime["site"] = "aniworld.to"
                                anime["base_url"] = config.ANIWORLD_TO
                                anime["stream_path"] = "anime/stream"
                                all_results.append(anime)
                                seen_slugs.add(slug)

                        # Add s.to results, but skip duplicates
                        for anime in sto_results:
                            slug = anime.get("link", "")
                            if slug and slug not in seen_slugs:
                                anime["site"] = "s.to"
                                anime["base_url"] = config.S_TO
                                # s.to search results might already include "serie/" path
                                if slug.startswith("serie/"):
                                    anime["stream_path"] = ""
                                else:
                                    anime["stream_path"] = "serie/stream"
                                all_results.append(anime)
                                seen_slugs.add(slug)

                        return all_results

                    elif site == "s.to":
                        # Single site search - s.to
                        try:
                            results = search_anime(keyword=keyword, only_return=True, site="s.to")
                            for anime in results:
                                anime["site"] = "s.to"
                                anime["base_url"] = config.S_TO
                                anime["stream_path"] = "serie/stream"
                            return results
                        except Exception as e:
                            logging.error(f"s.to search failed: {e}")
                            return []

                    else:
                        # Single site search - aniworld.to (default)
                        try:
                            results = search_anime(keyword=keyword, only_return=True, site="aniworld.to")
                            for anime in results:
                                anime["site"] = "aniworld.to"
                                anime["base_url"] = config.ANIWORLD_TO
                                anime["stream_path"] = "anime/stream"
                            return results
                        except Exception as e:
                            logging.error(f"aniworld.to search failed: {e}")
                            return []

                # Use wrapper function
                results = search_anime_wrapper(query, site)

                # Process results - simplified without episode fetching
                processed_results = []
                for anime in results[:50]:  # Limit to 50 results
                    # Get the link and construct full URL if needed
                    link = anime.get("link", "")
                    anime_site = anime.get("site", "aniworld.to")
                    anime_base_url = anime.get("base_url", config.ANIWORLD_TO)
                    anime_stream_path = anime.get("stream_path", "anime/stream")

                    if link and not link.startswith("http"):
                        # If it's just a slug, construct the full URL using the anime's specific site info
                        if anime_site == "s.to":
                            # s.to search results might return slugs like 'serie/stream/x' or 'serie/x'
                            # we want to ensure we use /serie/x
                            clean_slug = link
                            if clean_slug.startswith("serie/stream/"): clean_slug = clean_slug[13:]
                            elif clean_slug.startswith("serie/"): clean_slug = clean_slug[6:]
                            elif clean_slug.startswith("stream/"): clean_slug = clean_slug[7:]
                            
                            full_url = f"{config.S_TO}/serie/{clean_slug}"
                        elif anime_stream_path:
                            full_url = f"{anime_base_url}/{anime_stream_path}/{link}"
                        else:
                            full_url = f"{anime_base_url}/{link}"
                    else:
                        full_url = link

                    # Use the same field names as CLI search
                    name = anime.get("name", "Unknown Name")
                    year = anime.get("productionYear", "Unknown Year")
                    cover = anime.get("cover", "")

                    # Create title like CLI does, but avoid double parentheses
                    if year and year != "Unknown Year" and str(year) not in name:
                        title = f"{name} {year}"
                    else:
                        title = name
                    
                    processed_anime = {
                        "title": title,
                        "url": full_url,
                        "description": anime.get("description", "") or anime.get("overview", ""),
                        "slug": link,
                        "name": name,
                        "year": year,
                        "site": anime_site,
                        "cover": cover,
                        "rating": anime.get("vote_average"),
                        "release_date": anime.get("release_date"),
                    }

                    processed_results.append(processed_anime)

                return jsonify(
                    {
                        "success": True,
                        "results": processed_results,
                        "count": len(processed_results),
                    }
                )

            except Exception as err:
                logging.error(f"Search error: {err}")
                return jsonify(
                    {"success": False, "error": f"Search failed: {str(err)}"}
                ), 500

        @self.app.route("/api/episode/providers", methods=["POST"])
        @self._require_api_auth
        def api_episode_providers():
            """Get available providers for an episode endpoint."""
            try:
                from flask import request

                data = request.get_json()
                if not data or "episode_url" not in data:
                    return jsonify(
                        {"success": False, "error": "Episode URL is required"}
                    ), 400

                episode_url = data["episode_url"]

                try:
                    # Initialize Episode to fetch providers
                    # This will fetch the HTML and extract providers/languages
                    episode = Episode(link=episode_url)
                    episode.auto_fill_details()

                    # Return available providers and languages
                    return jsonify({
                        "success": True,
                        "providers": episode.provider_name,
                        "languages": episode.language_name,
                        "provider_data": episode.provider,  # Full data if needed
                        "language_codes": episode.language
                    })

                except Exception as e:
                    logging.error(f"Failed to fetch episode providers: {e}")
                    return jsonify(
                        {"success": False, "error": f"Failed to fetch providers: {str(e)}"}
                    ), 500

            except Exception as err:
                logging.error(f"Provider fetch error: {err}")
                return jsonify(
                    {"success": False, "error": f"Failed to fetch providers: {str(err)}"}
                ), 500

        @self.app.route("/api/download", methods=["POST"])
        @self._require_api_auth
        def api_download():
            """Start download endpoint."""
            try:
                from flask import request

                data = request.get_json()
                logging.info(f"[DEBUG] Received download request: {data}")

                # Check for both single episode (legacy) and multiple episodes (new)
                episode_urls = data.get("episode_urls", [])
                single_episode_url = data.get("episode_url")

                if single_episode_url:
                    episode_urls = [single_episode_url]

                if not episode_urls:
                    logging.warning("[DEBUG] Download request failed: No episode URLs provided")
                    return jsonify(
                        {"success": False, "error": "Episode URL(s) required"}
                    ), 400

                language = data.get("language", "German Sub")
                provider = data.get("provider", "VOE")
                
                # Get per-episode configuration
                episodes_config = data.get("episodes_config") or {}

                # DEBUG: Log received parameters
                logging.debug(
                    f"WEB API RECEIVED - Language: '{language}', Provider: '{provider}'"
                )
                logging.debug(f"WEB API RECEIVED - Request data: {data}")

                # Get current user for queue tracking
                current_user = None
                if self.auth_enabled and self.db:
                    session_token = request.cookies.get("session_token")
                    current_user = self.db.get_user_by_session(session_token)

                # Determine anime title
                anime_title = data.get("anime_title", "Unknown Anime")

                # Calculate total episodes by checking episode URLs
                from ..entry import _group_episodes_by_series

                try:
                    anime_list = _group_episodes_by_series(episode_urls)
                    total_episodes = sum(
                        len(anime.episode_list) for anime in anime_list
                    )
                except Exception as e:
                    logging.error(f"Failed to process episode URLs: {e}")
                    return jsonify(
                        {
                            "success": False,
                            "error": "No valid anime objects could be created from provided URLs",
                        }
                    ), 400

                if total_episodes == 0:
                    return jsonify(
                        {
                            "success": False,
                            "error": "No valid anime objects could be created from provided URLs",
                        }
                    ), 400

                # Add to download queue
                queue_id = self.download_manager.add_download(
                    anime_title=anime_title,
                    episode_urls=episode_urls,
                    language=language,
                    provider=provider,
                    total_episodes=total_episodes,
                    created_by=current_user["id"] if current_user else None,
                    episodes_config=episodes_config,
                )

                if not queue_id:
                    return jsonify(
                        {"success": False, "error": "Failed to add download to queue"}
                    ), 500

                return jsonify(
                    {
                        "success": True,
                        "message": f"Download added to queue: {total_episodes} episode(s)",
                        "episode_count": total_episodes,
                        "language": language,
                        "provider": provider,
                        "queue_id": queue_id,
                    }
                )

            except Exception as err:
                logging.error(f"Download error: {err}")
                return jsonify(
                    {"success": False, "error": f"Failed to start download: {str(err)}"}
                ), 500

        @self.app.route("/api/download/cancel", methods=["POST"])
        @self._require_api_auth
        def api_cancel_download():
            """Cancel download endpoint."""
            try:
                from flask import request

                data = request.get_json()
                queue_id = data.get("queue_id")

                if not queue_id:
                    return jsonify(
                        {"success": False, "error": "Queue ID required"}
                    ), 400

                if self.download_manager.cancel_download(int(queue_id)):
                    return jsonify(
                        {"success": True, "message": f"Download {queue_id} cancelled"}
                    )
                else:
                    return jsonify(
                        {"success": False, "error": f"Failed to cancel download {queue_id}"}
                    ), 400

            except Exception as err:
                logging.error(f"Download error: {err}")
                return jsonify(
                    {"success": False, "error": f"Failed to cancel download: {str(err)}"}
                ), 500

        @self.app.route("/api/download/<int:queue_id>", methods=["DELETE"])
        @self._require_api_auth
        def api_delete_download(queue_id):
            """Delete download from history endpoint."""
            try:
                if self.download_manager.delete_download(queue_id):
                    return jsonify(
                        {"success": True, "message": f"Download {queue_id} deleted"}
                    )
                else:
                    return jsonify(
                        {"success": False, "error": f"Failed to delete download {queue_id}"}
                    ), 400

            except Exception as err:
                logging.error(f"Download error: {err}")
                return jsonify(
                    {"success": False, "error": f"Failed to start download: {str(err)}"}
                ), 500

        @self.app.route("/api/download/<int:queue_id>/episodes", methods=["GET"])
        @self._require_api_auth
        def api_get_download_episodes(queue_id):
            """Get detailed episodes for a download job."""
            try:
                episodes = self.download_manager.get_job_episodes(queue_id)
                if episodes is not None:
                    return jsonify({"success": True, "episodes": episodes})
                else:
                    return jsonify({"success": False, "error": "Download not found"}), 404
            except Exception as e:
                logging.error(f"Failed to get episodes for job {queue_id}: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route("/api/download/<int:queue_id>/reorder", methods=["POST"])
        @self._require_api_auth
        def api_reorder_download_episodes(queue_id):
            """Reorder episodes for a download job."""
            try:
                data = request.get_json()
                new_order_urls = data.get("episode_urls")
                if not new_order_urls:
                    return jsonify({"success": False, "error": "New order (URLs) required"}), 400

                if self.download_manager.reorder_episodes(queue_id, new_order_urls):
                    return jsonify({"success": True, "message": "Episodes reordered successfully"})
                else:
                    return jsonify({"success": False, "error": "Failed to reorder (check if job is queued and URLs are valid)"}), 400
            except Exception as e:
                logging.error(f"Failed to reorder episodes for job {queue_id}: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route("/api/download/<int:queue_id>/episode/stop", methods=["POST"])
        @self._require_api_auth
        def api_stop_download_episode(queue_id):
            """Stop/remove a single episode from a download job."""
            try:
                data = request.get_json()
                ep_url = data.get("episode_url")
                if not ep_url:
                    return jsonify({"success": False, "error": "Episode URL required"}), 400

                if self.download_manager.stop_episode(queue_id, ep_url):
                    return jsonify({"success": True, "message": "Episode stopped/removed successfully"})
                else:
                    return jsonify({"success": False, "error": "Failed to stop episode"}), 400
            except Exception as e:
                logging.error(f"Failed to stop episode for job {queue_id}: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route("/api/download/<int:queue_id>/skip", methods=["POST"])
        @self._require_api_auth
        def api_skip_download_candidate(queue_id):
            """Skip current download server/candidate."""
            try:
                if self.download_manager.skip_current_candidate(queue_id):
                    return jsonify({"success": True, "message": "Skipping to next server..."})
                else:
                    return jsonify({"success": False, "error": "Failed to skip (check if download is running)"}), 400
            except Exception as e:
                logging.error(f"Failed to skip candidate for job {queue_id}: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route("/api/settings/downloads", methods=["GET", "POST"])
        @self._require_api_auth
        def api_download_settings():
            """Get or set download settings (max concurrent series/episodes)."""
            try:
                if request.method == "POST":
                    data = request.get_json()
                    max_series = data.get("max_concurrent_series")
                    max_episodes = data.get("max_concurrent_episodes")
                    
                    if max_series is None or max_episodes is None:
                        # Fallback for old frontend if only max_concurrent_downloads is sent
                        max_series = max_series or data.get("max_concurrent_downloads")
                        max_episodes = max_episodes or 1
                        
                    if max_series is None:
                        return jsonify({"success": False, "error": "max_concurrent_series is required"}), 400
                        
                    self.download_manager.set_download_limits(int(max_series), int(max_episodes))
                    return jsonify({"success": True, "message": "Download settings updated"})
                
                # GET request
                return jsonify({
                    "success": True,
                    "max_concurrent_series": self.download_manager.max_concurrent_series,
                    "max_concurrent_episodes": self.download_manager.max_concurrent_episodes
                })
            except Exception as err:
                logging.error(f"Failed to get/set download settings: {err}")
                return jsonify({"success": False, "error": str(err)}), 500

        @self.app.route("/api/download-path", methods=["GET", "POST"])
        @self._require_api_auth
        def api_download_path():
            """Get or set download path endpoint."""
            try:
                if request.method == "POST":
                    data = request.get_json()
                    series_path = data.get("series_path")
                    movie_path = data.get("movie_path")
                    
                    if not series_path and not movie_path:
                        return jsonify({"success": False, "error": "Path is required"}), 400
                        
                    # Save to database
                    success = True
                    if series_path:
                        success &= self.db.set_setting("series_download_path", series_path)
                    if movie_path:
                        success &= self.db.set_setting("movie_download_path", movie_path)

                    if success:
                        return jsonify({"success": True, "message": "Download paths updated"})
                    else:
                        return jsonify({"success": False, "error": "Failed to save settings"}), 500
                
                # GET request
                # Check database first
                series_path = self.db.get_setting("series_download_path") if self.db else None
                movie_path = self.db.get_setting("movie_download_path") if self.db else None

                # Fallback to defaults or general download_path if set in DB (migration/compatibility)
                if not series_path or not movie_path:
                    general_path = self.db.get_setting("download_path") if self.db else None
                    if not general_path:
                        if (
                            self.arguments
                            and hasattr(self.arguments, "output_dir")
                            and self.arguments.output_dir is not None
                        ):
                            general_path = str(self.arguments.output_dir)
                        else:
                            general_path = str(config.DEFAULT_DOWNLOAD_PATH)
                    
                    if not series_path: series_path = general_path or str(config.DEFAULT_SERIES_PATH)
                    if not movie_path: movie_path = general_path or str(config.DEFAULT_MOVIE_PATH)

                return jsonify({
                    "series_path": series_path,
                    "movie_path": movie_path
                })
            except Exception as err:
                logging.error(f"Failed to get/set download path: {err}")
                return jsonify({
                    "path": str(config.DEFAULT_DOWNLOAD_PATH),
                    "series_path": str(config.DEFAULT_SERIES_PATH),
                    "movie_path": str(config.DEFAULT_MOVIE_PATH),
                    "error": str(err)
                }), 500

        @self.app.route("/api/settings/language-preferences", methods=["GET", "POST"])
        @self._require_api_auth
        def api_language_preferences():
            """Get or set language preferences endpoint."""
            try:
                import json
                if request.method == "POST":
                    data = request.get_json()
                    lankabeltv_prefs = data.get("lankabeltv", [])
                    sto_prefs = data.get("sto", [])
                    
                    if self.db:
                        self.db.set_setting("lang_pref_lankabeltv", json.dumps(lankabeltv_prefs))
                        self.db.set_setting("lang_pref_sto", json.dumps(sto_prefs))
                        return jsonify({"success": True, "message": "Language preferences updated"})
                    else:
                        return jsonify({"success": False, "error": "Database not available"}), 500
                
                # GET request
                lankabeltv_prefs = []
                sto_prefs = []
                if self.db:
                    lankabeltv_raw = self.db.get_setting("lang_pref_lankabeltv")
                    sto_raw = self.db.get_setting("lang_pref_sto")
                    if lankabeltv_raw:
                        lankabeltv_prefs = json.loads(lankabeltv_raw)
                    if sto_raw:
                        sto_prefs = json.loads(sto_raw)
                
                return jsonify({
                    "success": True, 
                    "lankabeltv": lankabeltv_prefs, 
                    "sto": sto_prefs
                })
            except Exception as err:
                logging.error(f"Failed to get/set language preferences: {err}")
                return jsonify({"success": False, "error": str(err)}), 500

        @self.app.route("/api/settings/provider-preferences", methods=["GET", "POST"])
        @self._require_api_auth
        def api_provider_preferences():
            """Get or set provider preferences endpoint."""
            try:
                import json
                if request.method == "POST":
                    data = request.get_json()
                    lankabeltv_prefs = data.get("lankabeltv", [])
                    sto_prefs = data.get("sto", [])
                    
                    if self.db:
                        self.db.set_setting("prov_pref_lankabeltv", json.dumps(lankabeltv_prefs))
                        self.db.set_setting("prov_pref_sto", json.dumps(sto_prefs))
                        return jsonify({"success": True, "message": "Provider preferences updated"})
                    else:
                        return jsonify({"success": False, "error": "Database not available"}), 500
                
                # GET request
                lankabeltv_prefs = []
                sto_prefs = []
                if self.db:
                    lankabeltv_raw = self.db.get_setting("prov_pref_lankabeltv")
                    sto_raw = self.db.get_setting("prov_pref_sto")
                    if lankabeltv_raw:
                        lankabeltv_prefs = json.loads(lankabeltv_raw)
                    if sto_raw:
                        sto_prefs = json.loads(sto_raw)
                
                return jsonify({
                    "success": True, 
                    "lankabeltv": lankabeltv_prefs, 
                    "sto": sto_prefs
                })
            except Exception as err:
                logging.error(f"Failed to get/set language preferences: {err}")
                return jsonify({"success": False, "error": str(err)}), 500

        @self.app.route("/api/episodes", methods=["POST"])
        @self._require_api_auth
        def api_episodes():
            """Get episodes and TMDB metadata for a series endpoint."""
            try:
                from flask import request
                import requests

                data = request.get_json()
                if not data or "series_url" not in data:
                    return jsonify(
                        {"success": False, "error": "Series URL is required"}
                    ), 400

                series_url = data["series_url"]
                title = data.get("title")

                # Fetch TMDB Metadata
                tmdb_meta = {
                    "backdrop": None,
                    "overview": "No description available.",
                    "rating": None,
                    "year": None,
                    "genres": [],
                    "status": None
                }
                
                if title:
                    try:
                        search_title = title.split(' (')[0].split('  ')[0].strip()
                        tmdb_url = f"https://api.themoviedb.org/3/search/multi?query={requests.utils.quote(search_title)}&api_key={config.TMDB_API_KEY}"
                        resp = requests.get(tmdb_url, timeout=5)
                        if resp.status_code == 200:
                            results = resp.json().get("results", [])
                            if results:
                                best = results[0]
                                tmdb_id = best.get("id")
                                media_type = best.get("media_type", "tv")
                                
                                detail_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={config.TMDB_API_KEY}"
                                detail_resp = requests.get(detail_url, timeout=5)
                                if detail_resp.status_code == 200:
                                    d = detail_resp.json()
                                    tmdb_meta["backdrop"] = f"https://image.tmdb.org/t/p/original{d.get('backdrop_path')}" if d.get('backdrop_path') else None
                                    tmdb_meta["overview"] = d.get("overview") or tmdb_meta["overview"]
                                    tmdb_meta["rating"] = d.get("vote_average")
                                    tmdb_meta["year"] = (d.get("first_air_date") or d.get("release_date") or "")[:4]
                                    tmdb_meta["genres"] = [g.get("name") for g in d.get("genres", [])]
                                    tmdb_meta["status"] = d.get("status")
                    except Exception as e:
                        logging.warning(f"TMDB metadata fetch failed: {e}")

                # Create wrapper function to handle all logic
                def get_episodes_for_series(series_url, title=None):
                    """Wrapper function using existing functions to get episodes and movies"""
                    from ..common import (
                        get_season_episode_count,
                        get_movie_episode_count,
                        get_season_episodes_details,
                    )
                    from ..entry import _detect_site_from_url
                    from .. import config

                    # Special handling for HDFilme URLs - Removed/Deprecated
                    if "hdfilme.press" in series_url:
                        # return {}, [], "hdfilme"
                        pass

                    # Extract slug and site using existing functions
                    _site = _detect_site_from_url(series_url)

                    if "/anime/stream/" in series_url:
                        slug = series_url.split("/anime/stream/")[-1].rstrip("/")
                        stream_path = "anime/stream"
                        base_url = config.ANIWORLD_TO
                    elif "/serie/stream/" in series_url:
                        slug = series_url.split("/serie/stream/")[-1].rstrip("/")
                        # Use /serie/ as base for s.to now
                        stream_path = "serie"
                        base_url = config.S_TO
                    elif config.S_TO in series_url and "/serie/" in series_url:
                        slug = series_url.split("/serie/")[-1].rstrip("/")
                        stream_path = "serie"
                        base_url = config.S_TO
                    else:
                        raise ValueError("Invalid series URL format")

                    # Use new function to get season/episode details
                    try:
                        episodes_details = get_season_episodes_details(slug, base_url)
                        
                        # Fallback to counts if details failed (empty)
                        if not episodes_details:
                            season_counts = get_season_episode_count(slug, base_url)
                            episodes_details = {}
                            for s, c in season_counts.items():
                                episodes_details[s] = [{"season": s, "episode": e, "languages": []} for e in range(1, c + 1)]
                    except Exception as e:
                        logging.error(f"Failed to get episode details: {e}")
                        # Fallback
                        season_counts = get_season_episode_count(slug, base_url)
                        episodes_details = {}
                        for s, c in season_counts.items():
                            episodes_details[s] = [{"season": s, "episode": e, "languages": []} for e in range(1, c + 1)]

                    # Build episodes structure
                    episodes_by_season = {}
                    
                    # Convert site-specific language codes to names for frontend
                    site_lang_names = config.SITE_LANGUAGE_NAMES.get(_site, {})
                    
                    for season_num, ep_list in episodes_details.items():
                        if ep_list:
                            episodes_by_season[season_num] = []
                            for ep_data in ep_list:
                                ep_num = ep_data["episode"]
                                lang_codes = ep_data.get("languages", [])
                                lang_names = [site_lang_names.get(code, f"Unknown({code})") for code in lang_codes]
                                
                                episodes_by_season[season_num].append(
                                    {
                                        "season": season_num,
                                        "episode": ep_num,
                                        "title": f"Episode {ep_num}",
                                        "url": f"{base_url}/{stream_path}/{slug}/staffel-{season_num}/episode-{ep_num}",
                                        "languages": lang_names,
                                        "language_codes": lang_codes,
                                        "providers": ep_data.get("providers", [])
                                    }
                                )

                    # Get movies if this is from aniworld.to (movies only available there)
                    movies = []
                    if base_url == config.ANIWORLD_TO:
                        try:
                            movie_count = get_movie_episode_count(slug)
                            for movie_num in range(1, movie_count + 1):
                                movies.append(
                                    {
                                        "movie": movie_num,
                                        "title": f"Movie {movie_num}",
                                        "url": f"{base_url}/{stream_path}/{slug}/filme/film-{movie_num}",
                                    }
                                )
                        except Exception as e:
                            logging.warning(
                                f"Failed to get movie count for {slug}: {e}"
                            )

                    # Fallback if no seasons found
                    if not episodes_by_season:
                        episodes_by_season[1] = [
                            {
                                "season": 1,
                                "episode": 1,
                                "title": "Episode 1",
                                "url": f"{base_url}/{stream_path}/{slug}/staffel-1/episode-1",
                            }
                        ]

                    return episodes_by_season, movies, slug

                # Use the wrapper function
                try:
                    episodes_by_season, movies, slug = get_episodes_for_series(
                        series_url, title
                    )
                except ValueError as e:
                    return jsonify({"success": False, "error": str(e)}), 400
                except Exception as e:
                    logging.error(f"Failed to get episodes: {e}")
                    return jsonify(
                        {"success": False, "error": "Failed to fetch episodes"}
                    ), 500

                return jsonify(
                    {
                        "success": True,
                        "episodes": episodes_by_season,
                        "movies": movies,
                        "slug": slug,
                        "metadata": tmdb_meta
                    }
                )

            except Exception as err:
                logging.error(f"Episodes fetch error: {err}")
                return jsonify(
                    {"success": False, "error": f"Failed to fetch episodes: {str(err)}"}
                ), 500

        @self.app.route("/api/queue-status")
        @self._require_api_auth
        def api_queue_status():
            """Get download queue status endpoint."""
            try:
                queue_status = self.download_manager.get_queue_status()

                return jsonify({"success": True, "queue": queue_status})
            except Exception as e:
                logging.error(f"Failed to get queue status: {e}")
                return jsonify(
                    {"success": False, "error": "Failed to get queue status"}
                ), 500

        @self.app.route("/api/popular-new")
        @self._require_api_auth
        def api_popular_new():
            """Get popular and new anime endpoint."""
            try:
                from ..search import fetch_popular_and_new_anime

                anime_data = fetch_popular_and_new_anime()
                return jsonify(
                    {
                        "success": True,
                        "popular": anime_data.get("popular", []),
                        "new": anime_data.get("new", []),
                    }
                )
            except Exception as e:
                logging.error(f"Failed to fetch popular/new anime: {e}")
                return jsonify(
                    {
                        "success": False,
                        "error": f"Failed to fetch popular/new anime: {str(e)}",
                    }
                ), 500

        @self.app.route("/api/trackers", methods=["GET"])
        @self._require_api_auth
        def api_get_trackers():
            """Get all trackers for the current user."""
            try:
                # If authentication is disabled, return all trackers
                if not self.auth_enabled:
                    trackers = self.db.get_trackers() if self.db else []
                    for t in trackers:
                        t_id = t["id"]
                        t["is_scanning"] = self.download_manager._tracker_scan_status.get(t_id, False)
                        t["debug_messages"] = self.download_manager._tracker_debug_messages.get(t_id, [])
                        if t_id in self.download_manager._tracker_debug_messages:
                            # Clear messages after sending to avoid duplicates
                            self.download_manager._tracker_debug_messages[t_id] = []
                    return jsonify({"success": True, "trackers": trackers})

                if not self.db:
                    return jsonify({"success": False, "error": "Database not available"}), 500

                session_token = request.cookies.get("session_token")
                if not session_token:
                    # If no session but no users exist yet, allow access (local mode/first setup)
                    if not self.db.has_users():
                        trackers = self.db.get_trackers()
                        for t in trackers:
                            t_id = t["id"]
                            t["is_scanning"] = self.download_manager._tracker_scan_status.get(t_id, False)
                            t["debug_messages"] = self.download_manager._tracker_debug_messages.get(t_id, [])
                            if t_id in self.download_manager._tracker_debug_messages:
                                self.download_manager._tracker_debug_messages[t_id] = []
                        return jsonify({"success": True, "trackers": trackers})
                    return jsonify({"success": False, "error": "Unauthorized"}), 401

                user = self.db.get_user_by_session(session_token)
                if not user:
                    return jsonify({"success": False, "error": "Invalid session"}), 401

                trackers = self.db.get_trackers(user_id=user["id"])
                for t in trackers:
                    t_id = t["id"]
                    t["is_scanning"] = self.download_manager._tracker_scan_status.get(t_id, False)
                    t["debug_messages"] = self.download_manager._tracker_debug_messages.get(t_id, [])
                    if t_id in self.download_manager._tracker_debug_messages:
                        self.download_manager._tracker_debug_messages[t_id] = []
                return jsonify({"success": True, "trackers": trackers})
            except Exception as e:
                logging.error(f"Failed to get trackers: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route("/api/trackers/scan", methods=["POST"])
        @self._require_api_auth
        def api_scan_trackers():
            """Manually trigger a scan of all trackers."""
            try:
                self.download_manager.trigger_tracker_scan()
                return jsonify({"success": True, "message": "Tracker scan started"})
            except Exception as e:
                logging.error(f"Failed to scan trackers: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route("/api/trackers", methods=["POST"])
        @self._require_api_auth
        def api_add_tracker():
            """Add a new tracker."""
            try:
                data = request.get_json()
                anime_title = data.get("anime_title")
                series_url = data.get("series_url")
                language = data.get("language")
                provider = data.get("provider")
                last_season = data.get("last_season", 0)
                last_episode = data.get("last_episode", 0)

                if not anime_title or not series_url:
                    return jsonify({"success": False, "error": "Missing required fields"}), 400

                user_id = None
                if self.auth_enabled and self.db:
                    session_token = request.cookies.get("session_token")
                    user = self.db.get_user_by_session(session_token)
                    if user:
                        user_id = user["id"]

                tracker_id = self.db.add_tracker(
                    user_id=user_id,
                    anime_title=anime_title,
                    series_url=series_url,
                    language=language,
                    provider=provider,
                    last_season=last_season,
                    last_episode=last_episode
                )

                if tracker_id:
                    return jsonify({"success": True, "tracker_id": tracker_id})
                else:
                    return jsonify({"success": False, "error": "Failed to add tracker"}), 500
            except Exception as e:
                logging.error(f"Failed to add tracker: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route("/api/trackers/<int:tracker_id>", methods=["DELETE"])
        @self._require_api_auth
        def api_delete_tracker(tracker_id):
            """Delete a tracker."""
            try:
                user_id = None
                if self.auth_enabled and self.db:
                    session_token = request.cookies.get("session_token")
                    user = self.db.get_user_by_session(session_token)
                    if user:
                        user_id = user["id"]

                if self.db.delete_tracker(tracker_id, user_id=user_id):
                    return jsonify({"success": True, "message": "Tracker deleted"})
                else:
                    return jsonify({"success": False, "error": "Failed to delete tracker"}), 400
            except Exception as e:
                logging.error(f"Failed to delete tracker: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

    def _format_uptime(self, seconds: int) -> str:
        """Format uptime in human readable format."""
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            minutes = seconds // 60
            seconds = seconds % 60
            return f"{minutes}m {seconds}s"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            seconds = seconds % 60
            return f"{hours}h {minutes}m {seconds}s"

    def run(self):
        """Run the Flask web application."""
        logging.info("Starting LankabelTV Web Interface...")
        logging.info(f"Server running at http://{self.host}:{self.port}")

        try:
            self.app.run(
                host=self.host,
                port=self.port,
                debug=self.debug,
                use_reloader=False,  # Disable reloader to avoid conflicts
            )
        except KeyboardInterrupt:
            logging.info("Web interface stopped by user")
        except Exception as err:
            logging.error(f"Error running web interface: {err}")
            raise


def create_app(host="127.0.0.1", port=5000, debug=False, arguments=None) -> WebApp:
    """
    Factory function to create web application.

    Args:
        host: Host to bind to
        port: Port to bind to
        debug: Enable debug mode
        arguments: Command line arguments object

    Returns:
        WebApp instance
    """
    return WebApp(host=host, port=port, debug=debug, arguments=arguments)


def start_web_interface(arguments=None, port=5000, debug=False):
    """Start the web interface with configurable settings."""
    # Bind to 0.0.0.0 by default for better accessibility
    host = "0.0.0.0"
    web_app = create_app(host=host, port=port, debug=debug, arguments=arguments)

    # Print startup status
    auth_status = (
        "Authentication ENABLED"
        if getattr(arguments, "enable_web_auth", False)
        else "No Authentication (Local Mode)"
    )
    browser_status = (
        "Browser will open automatically"
        if not getattr(arguments, "no_browser", False)
        else "Browser auto-open disabled"
    )
    # Status showing that the web interface is exposed
    expose_status = "ENABLED (0.0.0.0)"

    # Get download paths from config (which respect env variables)
    series_path = str(config.DEFAULT_SERIES_PATH)
    movie_path = str(config.DEFAULT_MOVIE_PATH)

    # Show appropriate server address based on host
    # For user convenience, still show localhost if possible
    server_address = f"http://localhost:{port}"

    print("\n" + "=" * 69)
    print("🌐 LankabelTV Web Interface")
    print("=" * 69)
    print(f"📍 Server Address:   {server_address}")
    print(f"🔐 Security Mode:    {auth_status}")
    print(f"🌐 External Access:  {expose_status}")
    print(f"📁 Series Path:      {series_path}")
    print(f"📁 Movie Path:       {movie_path}")
    print(f"🐞 Debug Mode:       {'ENABLED' if debug else 'DISABLED'}")
    print(f"📦 Version:          {config.VERSION}")
    print(f"🌏 Browser:          {browser_status}")
    print("=" * 69)
    print("💡 Access the web interface by opening the URL above in your browser")
    if getattr(arguments, "enable_web_auth", False):
        print("💡 First visit will prompt you to create an admin account")
    print("💡 Press Ctrl+C to stop the server")
    print("=" * 69 + "\n")

    # Open browser automatically unless disabled
    if not getattr(arguments, "no_browser", False):

        def open_browser():
            # Wait a moment for the server to start
            time.sleep(1.5)
            url = f"http://127.0.0.1:{port}"
            logging.info(f"Opening browser at {url}")
            try:
                webbrowser.open(url)
            except Exception as e:
                logging.warning(f"Could not open browser automatically: {e}")

        # Start browser opening in a separate thread
        browser_thread = threading.Thread(target=open_browser)
        browser_thread.daemon = True
        browser_thread.start()

    web_app.run()


if __name__ == "__main__":
    start_web_interface()
