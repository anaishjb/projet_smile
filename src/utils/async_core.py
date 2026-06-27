# src/utils/async_core.py
import sys
import threading
import queue
import torch
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from facenet_pytorch import MTCNN, InceptionResnetV1

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
torch.set_num_threads(2)
print(f"[CORE] Device: {DEVICE}")

# Modeles globaux (instance unique partagee entre tous les workers)
resnet = InceptionResnetV1(pretrained='vggface2').eval().to(DEVICE)
mtcnn_global = None

print("[CORE] Chargement des modeles...")

# Executors TTS et Ollama
_tts_executor = None
_ollama_executor = None

# Queues
detect_request_q = queue.Queue(maxsize=2)
detect_result_q  = queue.Queue(maxsize=4)
embed_request_q  = queue.Queue(maxsize=4)
embed_result_q   = queue.Queue(maxsize=8)
tts_q            = queue.Queue(maxsize=8)
exit_event       = threading.Event()
embed_semaphore  = threading.Semaphore(1)

# Prechauffage GPU
print("[CORE] Prechauffage GPU...")
with torch.no_grad():
    dummy_tensor = torch.randn((1, 3, 160, 160), device=DEVICE)
    _ = resnet(dummy_tensor)
print(f"[CORE] ResNet pret sur {DEVICE}")

# Evenements de synchronisation
worker_ready_event = threading.Event()
embedding_ready_event = threading.Event()


def detection_worker():
    global mtcnn_global

    print("[DETECT] Worker demarre...")

    mtcnn_global = MTCNN(
        keep_all=True,
        device=DEVICE,
        min_face_size=60,
        thresholds=[0.6, 0.7, 0.8],
        post_process=True
    )

    print("[DETECT] Prechauffage MTCNN (3 passes)...")
    dummy_frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    for i in range(3):
        _ = mtcnn_global.detect(dummy_frame)

    print("[DETECT] MTCNN pret.")
    worker_ready_event.set()

    while not exit_event.is_set():
        try:
            fid, frame_rgb = detect_request_q.get(timeout=0.1)
        except queue.Empty:
            continue

        frame_rgb = np.ascontiguousarray(frame_rgb.copy())

        try:
            boxes, probs = mtcnn_global.detect(frame_rgb)

            if boxes is not None and probs is not None:
                filtered_boxes = []
                for box, prob in zip(boxes, probs):
                    x1, y1, x2, y2 = box
                    w, h = x2 - x1, y2 - y1
                    if w >= 80 and h >= 80 and prob > 0.9:
                        filtered_boxes.append(box)
                boxes = filtered_boxes if filtered_boxes else None

        except Exception as e:
            print(f"[DETECT] Erreur frame {fid} : {e}")
            boxes = None

        detect_result_q.put((fid, boxes))
        detect_request_q.task_done()


def embedding_worker():
    print("[EMBED] Worker demarre...")

    print("[EMBED] Prechauffage...")
    dummy_face = np.random.randint(0, 255, (160, 160, 3), dtype=np.uint8)
    dummy_tensor = torch.tensor(dummy_face).permute(2, 0, 1).unsqueeze(0).float() / 255.0
    dummy_tensor = dummy_tensor.to(DEVICE)
    with torch.no_grad():
        _ = resnet(dummy_tensor)

    print("[EMBED] Worker pret.")
    embedding_ready_event.set()

    while not exit_event.is_set():
        try:
            face_id, frame_rgb, box = embed_request_q.get(timeout=0.5)
        except queue.Empty:
            continue

        with embed_semaphore:
            try:
                x1, y1, x2, y2 = [int(v) for v in box]

                h, w, _ = frame_rgb.shape
                margin = 10
                x1 = max(0, x1 - margin)
                y1 = max(0, y1 - margin)
                x2 = min(w, x2 + margin)
                y2 = min(h, y2 + margin)

                face = frame_rgb[y1:y2, x1:x2]

                if face.size == 0:
                    continue

                face_tensor = torch.tensor(face).permute(2, 0, 1).unsqueeze(0).float() / 255.0
                face_tensor = torch.nn.functional.interpolate(
                    face_tensor,
                    size=(160, 160),
                    mode='bilinear',
                    align_corners=False
                ).to(DEVICE)

                mean = torch.tensor([0.5, 0.5, 0.5]).view(1, 3, 1, 1).to(DEVICE)
                std  = torch.tensor([0.5, 0.5, 0.5]).view(1, 3, 1, 1).to(DEVICE)
                face_tensor = (face_tensor - mean) / std

                with torch.no_grad():
                    emb = resnet(face_tensor).cpu().numpy()

                embed_result_q.put((face_id, emb))

            except Exception as e:
                print(f"[EMBED] Erreur : {e}")
            finally:
                embed_request_q.task_done()


def tts_worker(speak_func):
    while not exit_event.is_set():
        try:
            text = tts_q.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            speak_func(text)
        except Exception as e:
            print(f"[TTS] Erreur : {e}")
        finally:
            tts_q.task_done()


def start_executors():
    global _tts_executor, _ollama_executor
    if _tts_executor is None:
        _tts_executor = ThreadPoolExecutor(max_workers=1)
        print("[CORE] Executor TTS demarre")
    if _ollama_executor is None:
        _ollama_executor = ThreadPoolExecutor(max_workers=1)
        print("[CORE] Executor Ollama demarre")


def shutdown_executors():
    global _tts_executor, _ollama_executor
    if _tts_executor:
        _tts_executor.shutdown(wait=True)
        print("[CORE] Executor TTS arrete")
        _tts_executor = None
    if _ollama_executor:
        _ollama_executor.shutdown(wait=True)
        print("[CORE] Executor Ollama arrete")
        _ollama_executor = None


def _noop_future():
    import concurrent.futures
    f = concurrent.futures.Future()
    f.set_result(None)
    return f


def speak_async(func, *args, **kwargs):
    if exit_event.is_set() or _tts_executor is None:
        return _noop_future()
    try:
        return _tts_executor.submit(func, *args, **kwargs)
    except RuntimeError:
        return _noop_future()


def ask_ollama_async(func, *args, **kwargs):
    if exit_event.is_set() or _ollama_executor is None:
        return _noop_future()
    try:
        return _ollama_executor.submit(func, *args, **kwargs)
    except RuntimeError:
        return _noop_future()


def start_workers(speak_func=None):
    threading.Thread(target=detection_worker, daemon=True).start()
    threading.Thread(target=embedding_worker, daemon=True).start()
    start_executors()
    print("[CORE] Tous les workers demarres")
