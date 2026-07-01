# utils/dialog_manager.py
import requests
import json
from datetime import datetime

from src.config import OLLAMA_URL, MODEL_NAME

# IMPORT CORRECTS
# prends le profil et l'historique UNIQUEMENT depuis profile_manager
from src.utils.profile_manager import (
    load_profile, save_profile,
    load_recent_history,
    format_profile_for_prompt,
    format_history_for_prompt,
)


def build_llm_prompt(
    face_id: str,
    user_text: str,
    is_first_turn: bool = False,
    state: str = "FREE_TALK",
) -> str:
    profile = load_profile(face_id)
    history = load_recent_history(face_id, window=7)
    display_name = profile.get("name", face_id)

    profile_txt = format_profile_for_prompt(profile)
    history_txt = format_history_for_prompt(history)
    notes_summary = profile.get("notes_summary", "").strip() or "(aucune mémoire épisodique disponible)"

    if state == "GREETING":
        stage = "C'est le début de la conversation. Tu peux saluer brièvement et te présenter naturellement."
    elif state == "FAREWELL":
        stage = "La conversation se termine. Réponds avec un au revoir chaleureux, ne relance pas."
    else:
        stage = "La conversation est déjà en cours. NE salue PAS à nouveau."

    prompt = f"""
Tu es "Robot", un assistant robotique qui parle en français, avec un ton chaleureux et naturel.
Tu parles avec {display_name}, que tu connais.
Ton interlocuteur peut être une personne âgée ou une personne ayant des troubles cognitifs.

ÉTAT ACTUEL : {state.upper()}
{stage}

RÈGLES DE COMMUNICATION
RÈGLES :
- Ne commence pas par "Bonjour" ou le prénom, sauf au premier tour.
- FAREWELL : au revoir uniquement, sans question.
- 2 phrases maximum.
- Pas d'emojis.

RÈGLES IMPORTANTES — PUBLIC VULNÉRABLE
- Sois patient, même si l'utilisateur se répète.
- Utilise des phrases courtes, un vocabulaire simple et concret. Évite les métaphores, le langage abstrait ou les expressions idiomatiques.
- Ne corrige jamais l'utilisateur, même s'il dit quelque chose d'inexact.
- Ne fais jamais d'hypothèses sur l'état émotionnel de l'utilisateur s'il ne l'a pas exprimé clairement.

MÉMOIRE LONG TERME :
{profile_txt}

MÉMOIRE ÉPISODIQUE (résumés précédents) :
{notes_summary}

MÉMOIRE COURT TERME (7 derniers échanges) :
{history_txt}

L'UTILISATEUR DIT :
{user_text}

Réponds en tant que "Robot" :
Robot:
""".strip()

    return prompt


def ask_ollama(prompt: str, model: str = MODEL_NAME) -> str:
    data = {"model": model, "prompt": prompt, "stream": False}
    resp = requests.post(OLLAMA_URL, json=data)
    resp.raise_for_status()
    return resp.json().get("response") or ""


def ask_ollama_with_context(
    face_id: str,
    user_text: str,
    is_first_turn: bool = False,
    state: str = "FREE_TALK",
) -> str:
    prompt = build_llm_prompt(face_id, user_text, is_first_turn=is_first_turn, state=state)
    return ask_ollama(prompt)

def summarize_conversation(face_id: str, conversation):
    """
    Résume la conversation, déduit des informations sur l'utilisateur et met à jour le profil.
    Le profil est toujours sauvegardé, même si l'appel LLM échoue.
    """
    profile = load_profile(face_id)
    display_name = profile.get("name", face_id)

    try:
        # --- 1. Prépare le texte de la conversation ---
        dialogue_text = "\n".join(
            [f"Utilisateur: {x['user']}\nAssistant: {x['bot']}" for x in conversation]
        )

        # --- 2. Prépare le prompt ---
        prompt = f"""
Tu es un système de mémoire conversationnelle. Tu vas recevoir :
1. Le profil actuel de l'utilisateur (potentiellement incomplet)
2. La transcription de la dernière conversation

Ton rôle est de mettre à jour le profil de façon cohérente,
en ne déduisant que ce qui ressort clairement.

=== PROFIL ACTUEL ===
{json.dumps(profile, ensure_ascii=False, indent=2)}

=== CONVERSATION ===
{dialogue_text}

Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ni après, sans balises markdown.
Le JSON doit contenir exactement ces clés :
- summary: bref résumé de l'interaction (3-4 phrases)
- gender: "homme", "femme" ou null si non déductible
- age: tranche d'âge estimée (ex. "20-30") ou null
- occupation: profession ou domaine si mentionné
- interests: liste de sujets ou loisirs cités
- personality: traits comportementaux (ex. curieux, empathique, analytique)
- goals: objectifs personnels ou professionnels si mentionnés
        """

        response = ask_ollama(prompt, model=MODEL_NAME)

        # --- 3. Parse output LLM ---
        try:
            data = json.loads(response)
        except Exception:
            start = response.find("{")
            end = response.rfind("}") + 1
            data = json.loads(response[start:end]) if start != -1 and end != -1 else {}

        # --- 4. Merge intelligent ---
        profile["notes_summary"] = data.get("summary", profile.get("notes_summary", ""))

        for key in ["gender", "age", "occupation", "personality"]:
            val = data.get(key)
            if val and (profile.get(key) in [None, ""]):
                profile[key] = val

        def merge_list(a, b):
            return list(set((a or []) + (b or [])))

        profile["interests"] = merge_list(profile.get("interests", []), data.get("interests", []))
        profile["goals"] = merge_list(profile.get("goals", []), data.get("goals", []))

    except Exception as e:
        print(f"[MEMORY] Erreur lors du résumé LLM (profil de base conservé) : {e}")

    # --- 5. Toujours sauvegarder, même si le LLM a échoué ---
    profile["recent_conversations"] = conversation[-5:]
    profile["last_update"] = datetime.now().isoformat()
    save_profile(face_id, profile)
    print(f"[MEMORY] Profil de {display_name} mis à jour.")
    return profile


