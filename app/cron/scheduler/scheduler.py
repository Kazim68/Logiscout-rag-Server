"""
Cron scheduler — disabled.
Commit ingestion is driven entirely by GitHub webhooks; no periodic polling is needed.
"""
        finally:
            scheduler = None

