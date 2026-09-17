# Databricks notebook source
# MAGIC %md
# MAGIC # [GENIE ONE EXTENSION — ADDITIVE] Provision an extension Genie Agent
# MAGIC
# MAGIC Additive copy of `src/setup/genie_setup.py` that provisions ANY extension
# MAGIC Agent from a parameterized JSON path (the original reads a fixed path and is
# MAGIC not modified). Idempotent: find-by-title → PATCH in place, else POST create.
# MAGIC Remaps the `${catalog}`/`${schema}` placeholders in the Agent JSON to the real
# MAGIC values before pushing (per the CI/CD skill's catalog-remap step).
# MAGIC
# MAGIC Params: files_path, warehouse_id, title, description, agent_json (relative to
# MAGIC files_path), catalog, schema.

# COMMAND ----------
dbutils.widgets.text("files_path", "")
dbutils.widgets.text("warehouse_id", "")
dbutils.widgets.text("title", "")
dbutils.widgets.text("description", "")
dbutils.widgets.text("agent_json", "")   # e.g. genie_ext/genie_cx.json
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")

FILES_PATH   = dbutils.widgets.get("files_path")
WAREHOUSE_ID = dbutils.widgets.get("warehouse_id")
TITLE        = dbutils.widgets.get("title")
DESCRIPTION  = dbutils.widgets.get("description") or f"{TITLE} — Genie One extension Agent."
AGENT_JSON   = dbutils.widgets.get("agent_json")
CATALOG      = dbutils.widgets.get("catalog")
SCHEMA       = dbutils.widgets.get("schema")
assert FILES_PATH and WAREHOUSE_ID and TITLE and AGENT_JSON and CATALOG and SCHEMA, "all params required"

if not FILES_PATH:
    nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
    FILES_PATH = "/Workspace" + "/".join(nb.split("/")[:-2])

# COMMAND ----------
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()

# Read the checked-in Agent JSON (a parsed object) and remap catalog/schema placeholders.
with open(f"{FILES_PATH}/{AGENT_JSON}", "r", encoding="utf-8") as f:
    serialized_space = f.read()
serialized_space = serialized_space.replace("${catalog}", CATALOG).replace("${schema}", SCHEMA)

me = w.current_user.me().user_name
parent_path = f"/Workspace/Users/{me}/genie_spaces"
w.workspace.mkdirs(parent_path)

# COMMAND ----------
# Find an existing space with this title (paginate).
existing_id = None
page_token = None
while True:
    params = {"page_token": page_token} if page_token else {}
    resp = w.api_client.do("GET", "/api/2.0/genie/spaces", query=params) or {}
    for s in resp.get("spaces", []):
        if s.get("title") == TITLE:
            existing_id = s.get("space_id")
            break
    page_token = resp.get("next_page_token")
    if existing_id or not page_token:
        break

# COMMAND ----------
if existing_id:
    w.api_client.do(
        "PATCH", f"/api/2.0/genie/spaces/{existing_id}",
        body={"serialized_space": serialized_space, "title": TITLE,
              "description": DESCRIPTION, "warehouse_id": WAREHOUSE_ID},
    )
    space_id = existing_id
    print(f"Updated existing Genie space: {existing_id}")
else:
    created = w.api_client.do(
        "POST", "/api/2.0/genie/spaces",
        body={"warehouse_id": WAREHOUSE_ID, "title": TITLE, "description": DESCRIPTION,
              "parent_path": parent_path, "serialized_space": serialized_space},
    )
    space_id = created.get("space_id")
    print(f"Created Genie space: {space_id}")

print("GENIE_SPACE_ID:", space_id)
