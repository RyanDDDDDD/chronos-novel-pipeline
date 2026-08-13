"""Root directory entry point: uv run python run.py [--port 8775] [--no-browser] [--dev]"""
import os

os.environ["PYTHONPYCACHEPREFIX"] = os.path.join(os.path.dirname(__file__), ".pycache_global")

from main import main
    
if __name__ == "__main__":
    main()
