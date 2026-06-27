import os
import json
import pickle
from datetime import datetime

from src.config import CONVERSATIONS_DIR, EMBEDDINGS_FILE


def log_full_conversation(face_id: str, user_text: str, bot_reply: str) -> None:
    os.makedirs(CONVERSATIONS_DIR, exist_ok=True)
    path = os.path.join(CONVERSATIONS_DIR, f"{face_id}.json")

    history = []
    if os.path.exists(path):
        for enc in ("utf-8", "cp1252", "latin-1"):
            try:
                with open(path, "r", encoding=enc) as f:
                    history = json.load(f)
                if enc != "utf-8":
                    # Réécrire en UTF-8 pour les prochaines fois
                    with open(path, "w", encoding="utf-8") as fw:
                        json.dump(history, fw, ensure_ascii=False, indent=2)
                    print(f"[MEMORY] Fichier réencodé en UTF-8 : {path}")
                break
            except UnicodeDecodeError:
                continue
            except (json.JSONDecodeError, ValueError):
                history = []
                break

    history.append({
        "timestamp": datetime.now().isoformat(),
        "user": user_text,
        "bot": bot_reply,
    })

    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def save_new_face(face_id: str, embedding) -> None:
    known = {}
    if os.path.exists(EMBEDDINGS_FILE):
        try:
            with open(EMBEDDINGS_FILE, "rb") as f:
                known = pickle.load(f)
        except Exception:
            known = {}

    known[face_id] = embedding

    os.makedirs(os.path.dirname(EMBEDDINGS_FILE), exist_ok=True)
    with open(EMBEDDINGS_FILE, "wb") as f:
        pickle.dump(known, f)

    print(f"[MEMORY] Visage '{face_id}' sauvegardé.")
