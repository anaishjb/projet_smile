import os
import json
import time
from datetime import datetime
from src.config import CONVERSATIONS_DIR, PROFILES_DIR

'''
# cartelle persistenti
BASE_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../data"))
CONV_DIR = os.path.join(BASE_DATA_DIR, "conversations")
PROFILE_DIR = os.path.join(BASE_DATA_DIR, "profiles")

os.makedirs(CONV_DIR, exist_ok=True)
os.makedirs(PROFILE_DIR, exist_ok=True)
'''

def _load_json_robust(path: str):
    """Charge un JSON avec fallback d'encodage (cp1252/latin-1 → re-sauvegarde en UTF-8)."""
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                data = json.load(f)
            if enc != "utf-8":
                # Fichier mal encodé : le réécrire en UTF-8 pour les prochaines fois
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                print(f"[PROFIL] Fichier réencodé en UTF-8 : {path}")
            return data
        except UnicodeDecodeError:
            continue
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _conv_path(face_id: str) -> str:
    return os.path.join(CONVERSATIONS_DIR, f"{face_id}.json")

def _profile_path(face_id: str) -> str:
    return os.path.join(PROFILES_DIR, f"{face_id}.json")

# -------------------------
# 1. Conversazione (short-term memory)
# -------------------------

def load_recent_history(face_id: str, window: int = 7) -> list[dict]:
    """
    Ritorna gli ultimi `window` turni di conversazione salvati per questo utente.
    Ogni turno è: { "timestamp": ..., "user": "...", "bot": "..." }
    Se non c'è ancora storia, ritorna [].
    """
    path = _conv_path(face_id)
    if not os.path.exists(path):
        return []

    data = _load_json_robust(path)
    if not isinstance(data, list):
        return []

    # prendi SOLO gli ultimi `window`
    return data[-window:]

def format_history_for_prompt(history: list[dict]) -> str:
    """
    Converte gli ultimi turni in un testo da dare al modello.
    """
    if not history:
        return "Aucune conversation précédente avec cette personne."
    lines = []
    for turn in history:
        user_line = turn.get("user", "").strip()
        bot_line  = turn.get("bot", "").strip()
        ts        = turn.get("timestamp", "?")
        if user_line:
            lines.append(f"[{ts}] Utilisateur: {user_line}")
        if bot_line:
            lines.append(f"[{ts}] Robot: {bot_line}")
    return "\n".join(lines)

# -------------------------
# 2. Profilo (long-term memory)
# -------------------------

def _default_profile(face_id: str) -> dict:
    return {
        "face_id": face_id,
        "name": face_id,
        "known_since": datetime.now().strftime("%Y-%m-%d"),
        "age": None,
        "gender": None,
        "occupation": None,
        "interests": [],
        "personality": None,
        "goals": [],
        "notes_summary": "",
        "recent_conversations": [],
        "last_update": None
    }


def load_profile(face_id: str) -> dict:
    """
    Charge le profil long-terme de l'utilisateur identifié par face_id.
    Retourne un profil vide si le fichier n'existe pas encore.
    """
    path = _profile_path(face_id)
    if not os.path.exists(path):
        return _default_profile(face_id)

    data = _load_json_robust(path)
    if isinstance(data, dict):
        return data
    return _default_profile(face_id)

def save_profile(face_id: str, profile: dict):
    """
    Sauvegarde le profil long-terme de l'utilisateur identifié par face_id.
    """
    path = _profile_path(face_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

def format_profile_for_prompt(profile: dict) -> str:
    """
    Serializza il profilo in forma leggibile dal modello.
    """
    return json.dumps(profile, ensure_ascii=False, indent=2)

def update_profile_notes(name: str, new_note: str):
    """
    Aggiorna campo 'notes' del profilo aggiungendo un'annotazione libera.
    Per ora semplice append testuale.
    (Lo useremo più avanti per Step 2 e Step 3)
    """
    prof = load_profile(name)
    notes = prof.get("notes", "")
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    prof["notes"] = (notes + f"\n[{timestamp}] {new_note}").strip()
    save_profile(name, prof)
