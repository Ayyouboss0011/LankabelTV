import os
import re

PACKAGE_NAME = "aniworld"
SOURCE_DIR = "src/aniworld"

relative_import_pattern = re.compile(r"^from\s+(\.+)([\w\.]*)\s+import\s+(.*)$")


def convert_relative_to_absolute(path):
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    modified = False
    new_lines = []

    for line in lines:
        match = relative_import_pattern.match(line)
        if match:
            _, module_path, imports = match.groups()
            abs_parts = (
                [PACKAGE_NAME] + module_path.split(".")
                if module_path
                else [PACKAGE_NAME]
            )
            abs_import = f"from {'.'.join(abs_parts)} import {imports}"
            new_lines.append(abs_import + "\n")
            modified = True
        # Handle potential yt-dlp import issues by adding exception handling
        elif "from yt_dlp" in line and "extractor" in line:
            # Skip problematic yt-dlp extractor imports
            new_lines.append(f"# {line}")
            modified = True
        else:
            new_lines.append(line)

    if modified:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print(f"Updated: {path}")


def walk_and_convert():
    for root, _, files in os.walk(SOURCE_DIR):
        for file in files:
            if file.endswith(".py"):
                full_path = os.path.join(root, file)
                convert_relative_to_absolute(full_path)


if __name__ == "__main__":
    walk_and_convert()
