"""``python -m audit`` -- the single seam of the audit tool (issue #7)."""

import sys

from audit_tool.cli import main

if __name__ == "__main__":
    sys.exit(main())
