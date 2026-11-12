"""Spaces hub: one connector module per app, loaded on first use."""
import importlib

APPS = ('notion', 'github', 'gdrive', 'zotero')
TITLES = {'notion': 'Notion', 'github': 'GitHub', 'gdrive': 'Google Drive', 'zotero': 'Zotero'}


def connector(app, http, credentials, journal):
    if app not in APPS:
        raise ValueError('Unknown app.')
    module = importlib.import_module('spaces.' + app)
    return module.Connector(http=http, credentials=credentials, journal=journal)
