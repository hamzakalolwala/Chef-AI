import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("SOUSCHEF_CLASSIFIER", "mock")
os.environ.setdefault("SOUSCHEF_DATA_DIR", tempfile.mkdtemp(prefix="souschef-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
