import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("TADKA_CLASSIFIER", "mock")
os.environ.setdefault("TADKA_DATA_DIR", tempfile.mkdtemp(prefix="tadka-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
