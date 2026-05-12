import asyncio
import json

from app.models.mcp_config import MCPServerConfig
from app.services.mcp_service import check_mcp_health

async def run_tests():
    configs = [
        MCPServerConfig(name='test-sqlcl', server_type='sqlcl', command='sql'),
        MCPServerConfig(name='test-pg', server_type='postgresql', oracle_host='127.0.0.1', oracle_user='postgres', oracle_password='pwd'),
    ]
    for c in configs:
        print('---')
        print('Config:', c.name, 'type=', c.server_type)
        try:
            res = await check_mcp_health(c)
        except Exception as e:
            res = {'status': 'error', 'error': str(e)}
        print(json.dumps(res, indent=2))

if __name__ == '__main__':
    asyncio.run(run_tests())
