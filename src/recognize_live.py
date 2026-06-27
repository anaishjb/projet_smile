import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import os
import cv2
import pickle
import time
import threading
import msvcrt
import queue
import traceback
from datetime import datetime

from src.config import EMBEDDINGS_FILE
from src.utils.facenet_utils import compare_embeddings
from src.utils.speech_utils import speak, transcribe_audio, extract_name_from_text
from src.utils.dialog_manager import ask_ollama_with_context, summarize_conversation
from src.utils.text_post import clean_llm_reply
from src.utils.profile_manager import load_recent_history, load_profile, save_profile
from src.utils.memory_manager import log_full_conversation, save_new_face
from src.utils.async_core import (
    detect_request_q, detect_result_q,
    embed_request_q, embed_result_q,
    start_workers, exit_event,
    speak_async, shutdown_executors,
    worker_ready_event, ask_ollama_async,
    embedding_ready_event
)

# ==========================================
# Configuration
# ==========================================

TRACKER_MAX_LOST = 15
EMBED_INTERVAL = 20.0
RESEEN_THRESHOLD = 30
IOU_THRESHOLD = 0.3

# ==========================================
# Fonctions utilitaires
# ==========================================

def iou(box1, box2):
    x1, y1, w1, h1 = box1
    x2, y2, w2, h2 = box2

    xi1 = max(x1, x2)
    yi1 = max(y1, y2)
    xi2 = min(x1 + w1, x2 + w2)
    yi2 = min(y1 + h1, y2 + h2)

    inter_area = max(0, xi2 - xi1) * max(0, yi2 - yi1)
    box1_area = w1 * h1
    box2_area = w2 * h2
    union_area = box1_area + box2_area - inter_area

    return inter_area / union_area if union_area > 0 else 0


def generate_face_id(display_name: str) -> str:
    """Genere un identifiant unique stable a partir du nom affiche."""
    safe = display_name.lower().replace(" ", "_")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{safe}_{stamp}"

# ==========================================
# Ecoute touche Q
# ==========================================

def key_listener():
    while not exit_event.is_set():
        if msvcrt.kbhit():
            key = msvcrt.getch()
            if key in [b'q', b'Q']:
                print("\n[SYS] Fermeture demandee (touche Q)...")
                exit_event.set()
                break

# ==========================================
# Interaction (TTS + STT + LLM)
# ==========================================
last_interaction_time = 0
conversation_lock = threading.Lock()

def handle_interaction(face_id, display_name: str, known_faces: dict, seen_faces: dict, embedding=None):
    """
    face_id      : identifiant unique de la personne (None si inconnu)
    display_name : prenom affiche et utilise pour la synthese vocale
    known_faces  : dict partage {face_id: embedding}
    seen_faces   : dict partage {face_id|tid: timestamp}
    """
    try:
        # === 1. Salutation initiale ===
        if face_id is None and embedding is not None:
            speak_async(speak, "Bonjour ! Je ne crois pas t'avoir déjà rencontré. Comment tu t'appelles ?").result()
            time.sleep(1.2)

            user_name_raw = transcribe_audio(
                duration=12,
                stop_on_silence=True,
                silence_limit=3.5
            ).strip()

            display_name = extract_name_from_text(user_name_raw)
            face_id = generate_face_id(display_name)

            speak_async(speak, f"Enchanté {display_name} ! Je me souviendrai de toi. Comment tu vas aujourd'hui ?").result()

            save_new_face(face_id, embedding)
            known_faces[face_id] = embedding

            profile = load_profile(face_id)
            profile["name"] = display_name
            save_profile(face_id, profile)

            seen_faces[face_id] = time.time()
            time.sleep(1.2)

        else:
            speak_async(speak, f"Bonjour {display_name} !").result()
            time.sleep(1.2)

        # === 2. Machine d'etats conversationnelle ===
        state = "GREETING"
        print("[CONV] Etat initial : GREETING")

        silence_counter = 0
        max_silence_rounds = 5

        greeting_keywords = ["bonjour", "salut", "bonsoir", "coucou", "hey", "allo"]
        farewell_keywords = [
            "au revoir", "a bientot", "a plus", "bonne journee", "bonne soiree",
            "je dois y aller", "je m'en vais", "ciao"
        ]

        print("\n[CONV] Conversation active — tu peux parler maintenant !\n")

        first_turn = True

        while not exit_event.is_set():
            user_text = transcribe_audio(
                duration=20,
                stop_on_silence=True,
                silence_limit=3.2
            ).strip()

            if not user_text:
                silence_counter += 1
                print(f"[CONV] Silence detecte ({silence_counter}/{max_silence_rounds})")
                if silence_counter >= max_silence_rounds:
                    print("[CONV] Aucune reponse depuis trop longtemps, fin de la conversation.")
                    break
                continue

            silence_counter = 0
            print(f"[STT] Tu as dit : \"{user_text}\"")

            lower_text = user_text.lower()

            # === 3a. Etat GREETING ===
            if state == "GREETING":
                if (
                    len(lower_text.split()) > 1
                    or "come" in lower_text
                    or "sto" in lower_text
                    or "bene" in lower_text
                    or "male" in lower_text
                ):
                    state = "FREE_TALK"
                else:
                    reply_future = ask_ollama_async(
                        lambda prompt: ask_ollama_with_context(
                            face_id,
                            prompt,
                            is_first_turn=first_turn,
                            state=state
                        ),
                        user_text
                    )
                    reply_raw = reply_future.result(timeout=120)
                    reply = clean_llm_reply(reply_raw, state=state, is_first_turn=first_turn)
                    first_turn = False
                    speak_async(speak, reply).result()
                    log_full_conversation(face_id, user_text, reply)
                    print("[CONV] Pret a ecouter !")
                    time.sleep(1.0)
                    continue

            # === 3b. Detection d'au revoir ===
            goodbye_phrases = [
                "je dois y aller", "je m'en vais", "a tout a l'heure",
                "a bientot", "au revoir", "bonne journee", "bonne soiree",
                "c'est tout pour moi", "on se revoit", "a plus tard", "a plus",
            ]

            is_goodbye = (
                any(kw in lower_text for kw in goodbye_phrases)
                or any(kw in lower_text for kw in ["au revoir", "a bientot", "a plus"])
            )
            is_pure_greeting = (
                len(lower_text.split()) <= 2
                and any(kw in lower_text for kw in greeting_keywords)
                and not any(kw in lower_text for kw in goodbye_phrases)
            )

            if is_goodbye and not is_pure_greeting:
                print("[CONV] Au revoir detecte.")

                farewell_prompt = (
                    f"L'utilisateur {display_name} a dit : '{user_text}'. "
                    "Réponds avec un au revoir chaleureux et amical. "
                    "Maximum deux phrases. Ne pose pas de questions."
                )

                reply_future = ask_ollama_async(
                    lambda prompt: ask_ollama_with_context(
                        face_id,
                        prompt,
                        is_first_turn=False,
                        state="FAREWELL"
                    ),
                    farewell_prompt
                )
                farewell_raw = reply_future.result(timeout=120)
                farewell_reply = clean_llm_reply(farewell_raw, state="FAREWELL", is_first_turn=False)

                speak_async(speak, farewell_reply).result()
                log_full_conversation(face_id, user_text, farewell_reply)
                print(f"[TTS] Robot : \"{farewell_reply}\"")
                break

            # === 3c. Conversation normale (FREE_TALK) ===
            state = "FREE_TALK"

            reply_future = ask_ollama_async(
                lambda prompt: ask_ollama_with_context(
                    face_id,
                    prompt,
                    is_first_turn=first_turn,
                    state=state
                ),
                user_text
            )

            reply_raw = reply_future.result(timeout=120)
            reply = (
                clean_llm_reply(reply_raw, state=state, is_first_turn=first_turn)
                or "Je n'ai pas bien compris, peux-tu répéter ?"
            )
            first_turn = False

            speak_async(speak, reply).result()
            log_full_conversation(face_id, user_text, reply)
            print(f"[TTS] Robot : \"{reply}\"\n")
            time.sleep(1.0)
            print("[CONV] Pret a ecouter !")

        # === 4. Fin de conversation ===
        print(f"[CONV] Conversation avec {display_name} terminee.\n")

        try:
            recent = load_recent_history(face_id, window=10)
            summarize_conversation(face_id, recent)
            print(f"[MEMORY] Profil de {display_name} mis a jour.")
        except Exception as e:
            print(f"[MEMORY] Erreur lors de la mise a jour du profil : {e}")

    except Exception as e:
        print("[INTERACT] Erreur :", repr(e))
        traceback.print_exc()


def handle_interaction_threadsafe(face_id, display_name, known_faces, seen_faces, embedding=None):
    global last_interaction_time
    with conversation_lock:
        last_interaction_time = time.time()
        handle_interaction(face_id, display_name, known_faces, seen_faces, embedding)
        last_interaction_time = time.time()

# ==========================================
# Base de donnees de visages
# ==========================================

def load_known_faces():
    """Charge la base d'embeddings. Les cles sont des face_id uniques."""
    if os.path.exists(EMBEDDINGS_FILE):
        with open(EMBEDDINGS_FILE, "rb") as f:
            known = pickle.load(f)
        print(f"[SYS] {len(known)} visage(s) connu(s) charge(s).")
        return known
    else:
        print("[SYS] Aucun visage enregistre. Demarrage en mode detection.")
        return {}

# ==========================================
# Boucle principale
# ==========================================

def main():
    start_workers(speak_func=speak)

    print("[SYS] Prechauffage TTS...")
    speak_async(speak, " ").result()
    print("[SYS] TTS pret.")

    print("[SYS] Attente des workers...")
    worker_ready_event.wait()
    embedding_ready_event.wait()
    print("[SYS] Tous les workers prets. Demarrage webcam.")

    global _cap, _active_interactions

    known_faces = load_known_faces()

    _cap = cv2.VideoCapture(0)
    cap = _cap
    if not cap.isOpened():
        print("[SYS] Erreur : impossible d'ouvrir la webcam.")
        return

    print("\n[SYS] Demarrage reconnaissance en direct...")
    print("Appuie sur 'q' pour quitter.\n")

    seen_faces = {}
    _active_interactions = {}
    active_interactions = _active_interactions

    trackers = {}
    track_lost = {}
    tracker_boxes = {}
    last_embed_time = {}
    next_tracker_id = 0
    frame_id = 0

    threading.Thread(target=key_listener, daemon=True).start()
    print("\n[SYS] Systeme pret. Demarrage du flux video...\n")

    while not exit_event.is_set():
        ret, frame = cap.read()
        if not ret:
            print("[SYS] Frame non lu correctement.")
            break

        frame = cv2.resize(frame, (640, 480))
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame_id += 1
        current_time = time.time()

        if detect_request_q.qsize() < 1:
            try:
                detect_request_q.put_nowait((frame_id, rgb.copy()))
            except queue.Full:
                pass

        boxes = None
        try:
            while not detect_result_q.empty():
                det_fid, result = detect_result_q.get_nowait()
                detect_result_q.task_done()
                boxes = result
        except queue.Empty:
            pass

        if boxes is None and trackers:
            boxes = []
            for tid, tr in list(trackers.items()):
                ok, box = tr.update(frame)
                if ok:
                    x, y, w, h = map(int, box)
                    boxes.append([x, y, x + w, y + h])
                    track_lost[tid] = 0
                    tracker_boxes[tid] = (x, y, w, h)
                else:
                    track_lost[tid] += 1
                    if track_lost[tid] > TRACKER_MAX_LOST:
                        print(f"[TRACK] Tracker {tid} perdu definitivement")
                        del trackers[tid]
                        del track_lost[tid]
                        tracker_boxes.pop(tid, None)
                        last_embed_time.pop(tid, None)

        if boxes is not None:
            boxes = [b for b in boxes if b is not None]
            updated_trackers = {}
            matched_ids = set()

            for b in boxes:
                x1, y1, x2, y2 = map(int, b)
                w, h = x2 - x1, y2 - y1
                new_box = (x1, y1, w, h)

                best_iou = IOU_THRESHOLD
                matched_id = None

                for tid in list(trackers.keys()):
                    if tid in matched_ids:
                        continue
                    if tid in tracker_boxes:
                        current_iou = iou(new_box, tracker_boxes[tid])
                        if current_iou > best_iou:
                            best_iou = current_iou
                            matched_id = tid

                if matched_id is not None:
                    trackers[matched_id].init(frame, new_box)
                    updated_trackers[matched_id] = trackers[matched_id]
                    tracker_boxes[matched_id] = new_box
                    track_lost[matched_id] = 0
                    matched_ids.add(matched_id)
                else:
                    tracker = (
                        cv2.legacy.TrackerCSRT_create()
                        if hasattr(cv2.legacy, "TrackerCSRT_create")
                        else cv2.TrackerCSRT_create()
                    )
                    tid = f"t{next_tracker_id}"
                    tracker.init(frame, new_box)
                    updated_trackers[tid] = tracker
                    tracker_boxes[tid] = new_box
                    track_lost[tid] = 0
                    print(f"[TRACK] Nouveau tracker {tid} cree {new_box}")
                    next_tracker_id += 1
                    matched_ids.add(tid)

            trackers = updated_trackers

        for tid, tr in list(trackers.items()):
            try:
                ok, box = tr.update(frame)
            except Exception:
                ok, box = False, None

            if not ok or box is None:
                track_lost[tid] += 1
                if track_lost[tid] > TRACKER_MAX_LOST:
                    print(f"[TRACK] Tracker {tid} perdu, supprime")
                    trackers.pop(tid, None)
                    track_lost.pop(tid, None)
                    tracker_boxes.pop(tid, None)
                    last_embed_time.pop(tid, None)
                continue

            x, y, w, h = map(int, box)
            if w <= 0 or h <= 0:
                track_lost[tid] += 1
                continue

            track_lost[tid] = 0
            tracker_boxes[tid] = (x, y, w, h)
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

            if tid not in last_embed_time or current_time - last_embed_time[tid] > EMBED_INTERVAL:
                if not embed_request_q.full():
                    try:
                        embed_request_q.put_nowait((tid, rgb.copy(), (x, y, x + w, y + h)))
                        last_embed_time[tid] = current_time
                    except queue.Full:
                        pass

        try:
            while not embed_result_q.empty():
                emb_tid, embedding = embed_result_q.get_nowait()
                embed_result_q.task_done()

                face_id = None
                display_name = "Visage detecte"
                for fid, emb_db in known_faces.items():
                    match, dist = compare_embeddings(embedding, emb_db)
                    if match:
                        face_id = fid
                        display_name = load_profile(fid).get("name", fid)
                        break

                current_time = time.time()
                display_key = face_id if face_id is not None else emb_tid

                existing = active_interactions.get(display_key)
                if existing and getattr(existing, "is_alive", lambda: False)():
                    seen_faces[display_key] = current_time
                    continue

                if display_key not in seen_faces or current_time - seen_faces[display_key] > RESEEN_THRESHOLD:
                    if not conversation_lock.locked():
                        seen_faces[display_key] = current_time
                        print(f"[SYS] Nouveau visage detecte : {display_name}")

                        th = threading.Thread(
                            target=handle_interaction_threadsafe,
                            args=(face_id, display_name, known_faces, seen_faces, embedding),
                            daemon=False
                        )
                        active_interactions[display_key] = th
                        th.start()

                        def _cleanup_thread(t, key):
                            t.join()
                            active_interactions.pop(key, None)
                        threading.Thread(target=_cleanup_thread, args=(th, display_key), daemon=True).start()
                    else:
                        print(f"[SYS] En attente de fin de conversation avant d'interagir avec {display_name}.")

        except queue.Empty:
            pass

        cv2.imshow("Face Recognition Live", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            exit_event.set()
            break

    _cleanup()


_cap = None
_active_interactions = {}


def _cleanup():
    exit_event.set()
    if _cap is not None:
        _cap.release()
    cv2.destroyAllWindows()

    active_threads = [t for t in _active_interactions.values() if isinstance(t, threading.Thread) and t.is_alive()]
    if active_threads:
        print(f"[SYS] Sauvegarde en cours ({len(active_threads)} conversation(s))...")
        for t in active_threads:
            t.join(timeout=30)

    shutdown_executors()
    print("\n[SYS] Fermeture terminee.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[SYS] Fermeture demandee (Ctrl+C).")
    finally:
        _cleanup()
