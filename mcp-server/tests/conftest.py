"""mcp-server 테스트 공통 설정. `import server`가 되도록 mcp-server/를 sys.path에 추가."""

import sys
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parent.parent
if str(MCP_ROOT) not in sys.path:
    sys.path.insert(0, str(MCP_ROOT))
