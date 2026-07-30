#!/usr/bin/env python3
"""Regenerate real playable footage for T12 & T13 (were 100-byte empty stubs).

T12-capcut-trim-001: one 25s 1080p clip with a burnt-in timecode so a
  00:05-00:20 trim is objectively verifiable.
T13-capcut-color-render-001: 5 distinct-colour 1080p clips (each 4s) so a
  consistent colour grade + cross-dissolve transitions are meaningful.
"""
import os
import cv2
import numpy as np

TASKS = os.path.join(os.path.dirname(__file__), "..", "tasks")
W, H, FPS = 1920, 1080, 30
FONT = cv2.FONT_HERSHEY_SIMPLEX


def writer(path, fps=FPS):
    fourcc = cv2.VideoWriter_fourcc(*"avc1")
    vw = cv2.VideoWriter(path, fourcc, fps, (W, H))
    if not vw.isOpened():  # fallback if H.264 encoder unavailable
        vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    return vw


def gen_t12(path, seconds=25):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    vw = writer(path)
    total = seconds * FPS
    for i in range(total):
        t = i / FPS
        # animated gradient background so frames genuinely differ
        base = np.zeros((H, W, 3), np.uint8)
        shift = int((t / seconds) * 255)
        base[:, :, 0] = (np.linspace(0, 255, W).astype(np.uint8) + shift) % 255
        base[:, :, 1] = (shift) % 255
        base[:, :, 2] = (255 - shift) % 255
        mm, ss = divmod(int(t), 60)
        ff = i % FPS
        tc = f"{mm:02d}:{ss:02d}.{ff:02d}"
        cv2.putText(base, tc, (620, 560), FONT, 4.0, (255, 255, 255), 8, cv2.LINE_AA)
        cv2.putText(base, "T12 clip - trim me 00:05-00:20", (430, 700),
                    FONT, 1.6, (255, 255, 255), 4, cv2.LINE_AA)
        vw.write(base)
    vw.release()


def gen_t13(dirpath, seconds=4):
    os.makedirs(dirpath, exist_ok=True)
    # 5 deliberately different, slightly off-balance colours (need grading)
    tints = [
        (40, 40, 180),   # reddish, dim
        (30, 160, 60),   # green, oversaturated feel
        (170, 120, 30),  # cold blue
        (60, 90, 200),   # warm orange
        (120, 60, 140),  # magenta
    ]
    for idx, (b, g, r) in enumerate(tints, 1):
        path = os.path.join(dirpath, f"clip-{idx:02d}.mp4")
        vw = writer(path)
        for i in range(seconds * FPS):
            t = i / FPS
            frame = np.zeros((H, W, 3), np.uint8)
            # slight brightness pulse so it's real motion, colour is the point
            k = 0.85 + 0.15 * np.sin(t * 2)
            frame[:] = (int(b * k), int(g * k), int(r * k))
            cv2.putText(frame, f"clip {idx:02d}", (760, 560),
                        FONT, 4.0, (255, 255, 255), 8, cv2.LINE_AA)
            vw.write(frame)
        vw.release()
        print("wrote", path)


if __name__ == "__main__":
    t12 = os.path.join(TASKS, "T12-capcut-trim-001", "input", "clip.mp4")
    gen_t12(t12)
    print("wrote", t12)
    t13 = os.path.join(TASKS, "T13-capcut-color-render-001", "input", "raw-footage")
    gen_t13(t13)
