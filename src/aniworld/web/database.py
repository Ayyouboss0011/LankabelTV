"""
Database models and utilities for LankabelTV web authentication
"""

import hashlib
import os
import secrets
import sqlite3
from typing import Optional, Dict, List
from pathlib import Path


def get_database_path() -> str:
    """Get the persistent database path based on OS"""
    if os.path.exists("/.dockerenv"):  # 2. Docker environment
        db_dir = "/app/data"
    elif os.name == "nt":  # 2. Windows
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        db_dir = os.path.join(appdata, "aniworld")
    else:  # 3. Linux and others
        db_dir = os.path.expanduser("~/.local/share/aniworld")

    # Ensure directory exists
    Path(db_dir).mkdir(parents=True, exist_ok=True)
    return os.path.join(db_dir, "aniworld.db")


class UserDatabase:
    """SQLite database manager for user authentication"""

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the user database.

        Args:
            db_path: Path to the SQLite database file (if None, uses system location)
        """
        self.db_path = db_path or get_database_path()
        self._init_database()

    def _init_database(self) -> None:
        """Initialize the database tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Create users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    is_admin BOOLEAN NOT NULL DEFAULT 0,
                    is_original_admin BOOLEAN NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP
                )
            """)

            # Create sessions table for session management
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_token TEXT UNIQUE NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            """)

            # Create trackers table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trackers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    anime_title TEXT NOT NULL,
                    series_url TEXT NOT NULL,
                    language TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    last_season INTEGER DEFAULT 0,
                    last_episode INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
                )
            """)

            # Create settings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            # Note: download_queue table removed - download status now handled in memory

            conn.commit()

    def _hash_password(self, password: str, salt: str) -> str:
        """
        Hash a password with salt using SHA-256.

        Args:
            password: Plain text password
            salt: Salt string

        Returns:
            Hashed password
        """
        return hashlib.sha256((password + salt).encode()).hexdigest()

    def create_user(
        self,
        username: str,
        password: str,
        is_admin: bool = False,
        is_original_admin: bool = False,
    ) -> bool:
        """
        Create a new user.

        Args:
            username: Username
            password: Plain text password
            is_admin: Whether user should have admin privileges
            is_original_admin: Whether this is the original admin user

        Returns:
            True if user was created successfully, False otherwise
        """
        try:
            salt = secrets.token_hex(16)
            password_hash = self._hash_password(password, salt)

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO users (username, password_hash, salt, is_admin, is_original_admin)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (username, password_hash, salt, is_admin, is_original_admin),
                )
                conn.commit()
                return True

        except sqlite3.IntegrityError:
            # Username already exists
            return False
        except Exception:
            return False

    def verify_user(self, username: str, password: str) -> Optional[Dict]:
        """
        Verify user credentials.

        Args:
            username: Username
            password: Plain text password

        Returns:
            User dictionary if credentials are valid, None otherwise
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, username, password_hash, salt, is_admin, is_original_admin
                    FROM users WHERE username = ?
                """,
                    (username,),
                )

                row = cursor.fetchone()
                if not row:
                    return None

                user_id, username, stored_hash, salt, is_admin, is_original_admin = row

                # Verify password
                if self._hash_password(password, salt) == stored_hash:
                    # Update last login
                    cursor.execute(
                        """
                        UPDATE users SET last_login = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """,
                        (user_id,),
                    )
                    conn.commit()

                    return {
                        "id": user_id,
                        "username": username,
                        "is_admin": bool(is_admin),
                        "is_original_admin": bool(is_original_admin),
                    }

                return None

        except Exception:
            return None

    def create_session(self, user_id: int) -> str:
        """
        Create a new session for a user.

        Args:
            user_id: User ID

        Returns:
            Session token
        """
        session_token = secrets.token_urlsafe(32)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Clean up expired sessions first
            cursor.execute("""
                DELETE FROM sessions WHERE expires_at < CURRENT_TIMESTAMP
            """)

            # Create new session (expires in 30 days)
            cursor.execute(
                """
                INSERT INTO sessions (session_token, user_id, expires_at)
                VALUES (?, ?, datetime('now', '+30 days'))
            """,
                (session_token, user_id),
            )

            conn.commit()

        return session_token

    def get_user_by_session(self, session_token: str) -> Optional[Dict]:
        """
        Get user information by session token.

        Args:
            session_token: Session token

        Returns:
            User dictionary if session is valid, None otherwise
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT u.id, u.username, u.is_admin, u.is_original_admin
                    FROM users u
                    JOIN sessions s ON u.id = s.user_id
                    WHERE s.session_token = ? AND s.expires_at > CURRENT_TIMESTAMP
                """,
                    (session_token,),
                )

                row = cursor.fetchone()
                if row:
                    return {
                        "id": row[0],
                        "username": row[1],
                        "is_admin": bool(row[2]),
                        "is_original_admin": bool(row[3]),
                    }

                return None

        except Exception:
            return None

    def delete_session(self, session_token: str) -> bool:
        """
        Delete a session (logout).

        Args:
            session_token: Session token to delete

        Returns:
            True if session was deleted, False otherwise
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    DELETE FROM sessions WHERE session_token = ?
                """,
                    (session_token,),
                )
                conn.commit()
                return cursor.rowcount > 0

        except Exception:
            return False

    def get_all_users(self) -> List[Dict]:
        """
        Get all users (admin only).

        Returns:
            List of user dictionaries
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, username, is_admin, is_original_admin, created_at, last_login
                    FROM users ORDER BY username
                """)

                users = []
                for row in cursor.fetchall():
                    users.append(
                        {
                            "id": row[0],
                            "username": row[1],
                            "is_admin": bool(row[2]),
                            "is_original_admin": bool(row[3]),
                            "created_at": row[4],
                            "last_login": row[5],
                        }
                    )

                return users

        except Exception:
            return []

    def delete_user(self, user_id: int) -> bool:
        """
        Delete a user.

        Args:
            user_id: User ID to delete

        Returns:
            True if user was deleted, False otherwise
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
                conn.commit()
                return cursor.rowcount > 0

        except Exception:
            return False

    def update_user(
        self,
        user_id: int,
        username: str = None,
        password: str = None,
        is_admin: bool = None,
    ) -> bool:
        """
        Update user information.

        Args:
            user_id: User ID to update
            username: New username (optional)
            password: New password (optional)
            is_admin: New admin status (optional)

        Returns:
            True if user was updated, False otherwise
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                updates = []
                params = []

                if username is not None:
                    updates.append("username = ?")
                    params.append(username)

                if password is not None:
                    salt = secrets.token_hex(16)
                    password_hash = self._hash_password(password, salt)
                    updates.append("password_hash = ?")
                    updates.append("salt = ?")
                    params.extend([password_hash, salt])

                if is_admin is not None:
                    updates.append("is_admin = ?")
                    params.append(is_admin)

                if not updates:
                    return True  # Nothing to update

                params.append(user_id)

                cursor.execute(
                    f"""
                    UPDATE users SET {", ".join(updates)}
                    WHERE id = ?
                """,
                    params,
                )

                conn.commit()
                return cursor.rowcount > 0

        except sqlite3.IntegrityError:
            # Username already exists
            return False
        except Exception:
            return False

    def has_users(self) -> bool:
        """
        Check if any users exist in the database.

        Returns:
            True if at least one user exists, False otherwise
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM users")
                count = cursor.fetchone()[0]
                return count > 0

        except Exception:
            return False

    def change_password(
        self, user_id: int, current_password: str, new_password: str
    ) -> bool:
        """
        Change a user's password.

        Args:
            user_id: User ID
            current_password: Current password for verification
            new_password: New password

        Returns:
            True if password was changed successfully, False otherwise
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Get current password hash and salt
                cursor.execute(
                    """
                    SELECT password_hash, salt FROM users WHERE id = ?
                """,
                    (user_id,),
                )

                row = cursor.fetchone()
                if not row:
                    return False

                stored_hash, salt = row

                # Verify current password
                if self._hash_password(current_password, salt) != stored_hash:
                    return False

                # Generate new salt and hash for new password
                new_salt = secrets.token_hex(16)
                new_hash = self._hash_password(new_password, new_salt)

                # Update password
                cursor.execute(
                    """
                    UPDATE users SET password_hash = ?, salt = ?
                    WHERE id = ?
                """,
                    (new_hash, new_salt, user_id),
                )

                conn.commit()
                return cursor.rowcount > 0

        except Exception:
            return False

    def cleanup_expired_sessions(self) -> None:
        """Clean up expired sessions."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM sessions WHERE expires_at < CURRENT_TIMESTAMP
                """)
                conn.commit()

        except Exception:
            pass

    def add_tracker(
        self,
        user_id: Optional[int],
        anime_title: str,
        series_url: str,
        language: str,
        provider: str,
        last_season: int = 0,
        last_episode: int = 0,
    ) -> Optional[int]:
        """Add a series to trackers."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO trackers (user_id, anime_title, series_url, language, provider, last_season, last_episode)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        user_id,
                        anime_title,
                        series_url,
                        language,
                        provider,
                        last_season,
                        last_episode,
                    ),
                )
                conn.commit()
                return cursor.lastrowid
        except Exception:
            return None

    def get_trackers(self, user_id: Optional[int] = None) -> List[Dict]:
        """Get all trackers, optionally filtered by user_id."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                if user_id is not None:
                    cursor.execute(
                        "SELECT * FROM trackers WHERE user_id = ?", (user_id,)
                    )
                else:
                    cursor.execute("SELECT * FROM trackers")

                columns = [column[0] for column in cursor.description]
                results = []
                for row in cursor.fetchall():
                    results.append(dict(zip(columns, row)))
                return results
        except Exception:
            return []

    def update_tracker_last_episode(
        self, tracker_id: int, season: int, episode: int
    ) -> bool:
        """Update the last seen episode for a tracker."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE trackers SET last_season = ?, last_episode = ? WHERE id = ?",
                    (season, episode, tracker_id),
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception:
            return False

    def delete_tracker(self, tracker_id: int, user_id: Optional[int] = None) -> bool:
        """Delete a tracker."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                if user_id is not None:
                    cursor.execute(
                        "DELETE FROM trackers WHERE id = ? AND user_id = ?",
                        (tracker_id, user_id),
                    )
                else:
                    cursor.execute("DELETE FROM trackers WHERE id = ?", (tracker_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception:
            return False

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a setting value by key."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
                row = cursor.fetchone()
                return row[0] if row else default
        except Exception:
            return default

    def set_setting(self, key: str, value: str) -> bool:
        """Set a setting value."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (key, value),
                )
                conn.commit()
                return True
        except Exception:
            return False

    # Download Queue Management Methods - Removed
    # Download status is now handled in memory by DownloadQueueManager
