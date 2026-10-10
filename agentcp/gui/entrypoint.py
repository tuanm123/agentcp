from __future__ import annotations

import sys
import os
# Add the project root to sys.path so absolute imports work when run as script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from agentcp.gui.app import App

def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
