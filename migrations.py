import peewee as pw
from playhouse.migrate import *
import logging

def perform_migrations(database):
    migrator = SqliteMigrator(database)
    def get_version():
        return database.execute_sql('PRAGMA user_version').fetchone()[0]
    def set_version(ver):
        # it is a bad idea to append text into a query string, you should always use query parameters
        # however, in this case the query parameter does not work, causes syntax error
        # so we first check if the parameter is an integer, which can't be used for SQL injections
        if not isinstance(ver, int): raise TypeError
        database.execute_sql('PRAGMA user_version = ' + str(ver))

    if get_version() < 10:
        logging.warning("Upgrading schema to Version 1.0: Add fields for whitelisting channels to use command in, and optional message for alien users.")
        with database.atomic():
            migrate(
                migrator.add_column('server', 'channel_whitelist', pw.TextField(null=True)),
                migrator.add_column('server', 'message_on_alien_detected', pw.TextField(null=True)),
            )
            set_version(10)

