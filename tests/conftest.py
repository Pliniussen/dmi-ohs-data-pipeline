import os

# Integration tests truncate tables, so never let them use the app database.
os.environ["POSTGRES_DB"] = os.environ.get("TEST_POSTGRES_DB", "dmi_ohs_test")
