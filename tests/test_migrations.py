import contextlib
import io

from alembic import command
from alembic.config import Config

ENV = """
from sqlalchemy import Column, MetaData, String, Table

from opus_core.migrations import run

metadata = MetaData()
Table("settings", metadata, Column("key", String(64), primary_key=True))
run("postgresql+psycopg://nobody@nowhere/none", metadata)
"""

REVISION = '''
from alembic import op
import sqlalchemy as sa

revision = "a1"
down_revision = None


def upgrade():
    op.create_table("settings", sa.Column("key", sa.String(64), primary_key=True))
'''


def test_offline_the_migrations_are_written_as_sql_without_a_database(tmp_path):
    (tmp_path / "versions").mkdir()
    (tmp_path / "env.py").write_text(ENV)
    (tmp_path / "script.py.mako").write_text("")
    (tmp_path / "versions" / "a1_settings.py").write_text(REVISION)
    config = Config()
    config.set_main_option("script_location", str(tmp_path))
    written = io.StringIO()
    config.output_buffer = written
    with contextlib.redirect_stdout(written):
        command.upgrade(config, "head", sql=True)
    assert "CREATE TABLE settings" in written.getvalue()
    assert "INSERT INTO alembic_version (version_num) VALUES ('a1')" in written.getvalue()
