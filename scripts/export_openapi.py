import sys

import yaml

sys.path.insert(0, ".")
from app.config import Settings
from app.main import create_app

app = create_app(Settings(_env_file=None, database_url="sqlite://"))
with open("openapi.yaml", "w", encoding="utf-8", newline="\n") as f:
    yaml.safe_dump(app.openapi(), f, allow_unicode=True, sort_keys=False)
print("openapi.yaml written:", len(app.openapi()["paths"]), "paths")
