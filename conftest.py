"""Root conftest — adds the workflow_orchestrator directory to sys.path.

This allows tests to use bare imports like `from models import ...` and
`from server.dag_executor import ...` without requiring PYTHONPATH=. to be
set manually.
"""

import sys
from pathlib import Path

# Insert the workflow_orchestrator directory at the front of sys.path
# so that `import models` and `import server.xxx` resolve correctly.
_project_root = str(Path(__file__).resolve().parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
