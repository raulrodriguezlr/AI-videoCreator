import asyncio
import json
from videocreator.shared.config import get_settings
from videocreator.infrastructure.persistence.database import get_sessionmaker
from videocreator.infrastructure.repositories.sql_repos import SqlScriptRepository

async def main():
    sm = get_sessionmaker(get_settings())
    repo = SqlScriptRepository(sm)
    scripts = await repo.list_for_pod('pod_01KSSGCSRMGXJ8TFFNWAT2')
    script = next((s for s in scripts if 'Drag' in s.title), None)
    if script:
        with open('dragon_script.json', 'w', encoding='utf-8') as f:
            f.write(script.model_dump_json(indent=2))
        print("Script found and saved to dragon_script.json.")
    else:
        print("Script not found.")

asyncio.run(main())
