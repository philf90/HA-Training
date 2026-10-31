"""Konstanten fuer die Integration Training."""

DOMAIN = "ha_training"
TITLE = "Training"

# Geheimer Teil der Webhook-Adresse (webhook.async_generate_id()); wer ihn
# kennt, kann Trainings anlegen. Nie ins Log und nie in die Diagnose.
CONF_WEBHOOK_ID = "webhook_id"

# Wie viele Trainings ihre Details (Route, Puls- und Tempoverlauf) behalten.
# Die Zusammenfassung bleibt fuer alle Trainings erhalten, sie ist klein.
# Eine Stunde Gehen mit einem GPS-Punkt pro Sekunde braucht rund 170 KB.
CONF_KEEP_DETAILS = "keep_details"
DEFAULT_KEEP_DETAILS = 200
MIN_KEEP_DETAILS = 10
MAX_KEEP_DETAILS = 2000

# Speicher unter .storage/ (nicht ueber /local/ erreichbar, siehe README).
STORAGE_VERSION = 1
STORAGE_INDEX = f"{DOMAIN}.index"
STORAGE_DETAIL = f"{DOMAIN}.detail"

# Signal an die Entitaeten, wenn neue oder geaenderte Trainings ankamen.
SIGNAL_UPDATED = f"{DOMAIN}_updated"

# Ereignis-Typ der Ereignis-Entitaet "Neues Training".
EVENT_NEW_WORKOUT = "neues_training"

# Karte, von der Integration selbst ausgeliefert (siehe __init__.py).
CARD_PATH = f"/{DOMAIN}"
CARD = "ha-training-card.js"
LEAFLET_DIR = "leaflet"
