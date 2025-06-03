#!/usr/bin/env python3

import os
import subprocess
import sys
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class TemplateHandler(FileSystemEventHandler):
    """Handler for template file changes."""

    def __init__(self):
        self.last_modified = {}
        self.debounce_time = 0.5  # Wait 0.5 seconds before recompiling

    def on_modified(self, event):
        """Called when a file is modified."""
        if event.is_directory:
            return

        # Check if the file should trigger recompilation
        if not self._should_watch_file(event.src_path):
            return

        # Debounce rapid file changes
        current_time = time.time()
        if event.src_path in self.last_modified:
            if current_time - self.last_modified[event.src_path] < self.debounce_time:
                return

        self.last_modified[event.src_path] = current_time

        # Get relative path for cleaner output
        rel_path = os.path.relpath(event.src_path)
        print(f"\n📝 File changed: {rel_path}")

        # Run compiler
        self.compile_templates()

    def on_created(self, event):
        """Called when a file is created."""
        if event.is_directory:
            return

        # Check if the file should trigger recompilation
        if not self._should_watch_file(event.src_path):
            return

        rel_path = os.path.relpath(event.src_path)
        print(f"\n✨ New file created: {rel_path}")
        self.compile_templates()

    def compile_templates(self):
        """Run the compiler script using the current Python interpreter (venv's python if in venv)."""
        try:
            print("🔄 Compiling templates...")
            result = subprocess.run(
                [sys.executable, "compiler.py"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                print("✅ Compilation successful!")
                if result.stdout.strip():
                    # Print compiler output but skip the preview
                    lines = result.stdout.strip().split("\n")
                    for line in lines:
                        if (
                            not line.startswith("=== Preview ===")
                            and not line.strip().isdigit()
                        ):
                            print(f"   {line}")
            else:
                print("❌ Compilation failed!")
                if result.stderr:
                    print(f"Error: {result.stderr}")

        except subprocess.TimeoutExpired:
            print("❌ Compilation timed out!")
        except Exception as e:
            print(f"❌ Error running compiler: {e}")

    def _should_watch_file(self, file_path):
        """Determine if a file should trigger recompilation."""
        file_path = Path(file_path)

        # If file is in routes/, watch all files
        if "routes" in file_path.parts:
            return True

        # If file is in root directory, only watch .py and .bib files
        if file_path.parent == Path.cwd():
            return file_path.suffix in [".py", ".bib"]

        return False


def main():
    """Main watcher function."""

    # Check if routes directory exists
    routes_dir = Path("routes")
    if not routes_dir.exists():
        print("❌ routes/ directory not found!")
        return

    # Check if compiler.py exists
    if not Path("compiler.py").exists():
        print("❌ compiler.py not found!")
        return

    print("🚀 Starting template watcher...")
    print(f"📁 Watching routes/: {routes_dir.absolute()}")
    print("📁 Watching root/: .py and .bib files")
    print("📝 Monitoring for changes")
    print("🔄 Will automatically run compiler.py on changes")
    print("\nPress Ctrl+C to stop\n")

    # Run initial compilation
    handler = TemplateHandler()
    print("🔄 Running initial compilation...")
    handler.compile_templates()

    # Set up file watchers
    observer = Observer()

    # Watch routes directory for all files
    observer.schedule(handler, str(routes_dir), recursive=True)

    # Watch root directory for .py and .bib files
    observer.schedule(handler, ".", recursive=False)

    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n👋 Stopping watcher...")
        observer.stop()

    observer.join()
    print("✅ Watcher stopped.")


if __name__ == "__main__":
    main()
