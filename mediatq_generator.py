#!/usr/bin/env python3
"""
mediatq. Video Generator
========================
Génère automatiquement les vidéos YouTube mediatq. à partir d'une pochette, d'un fichier audio et des métadonnées.

Layout reproduit fidèlement depuis le template After Effects :
  - Fond noir
  - Pochette à gauche (pleine hauteur)
  - Textes à droite (artist / track / released) en mix regular + bold
  - Carrés animés aux couleurs de la pochette (partie droite)
  - Compteur d'épisode en bas à droite
  - Intro/outro avec logo mediatq.

Dépendances :
    pip install pillow colorthief numpy moviepy
    + FFmpeg installé sur le système (https://ffmpeg.org/)

Usage :
    python mediatq_generator.py \
        --cover pochette.jpg \
        --audio track.mp3 \
        --artist "Flash and the Pan" \
        --track "Walking in the Rain (Tigerskin Rework)" \
        --released "2011" \
        --episode 49 \
        --output output.mp4

    Ou en mode interactif (sans arguments) :
    python mediatq_generator.py
"""

import argparse
import os
import sys
import threading
from pathlib import Path
import numpy as np

# ── Vérification des dépendances ────────────────────────────────────────────
def check_deps():
    missing = []
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        missing.append("pillow")
    try:
        import moviepy
    except ImportError:
        missing.append("moviepy")
    if missing:
        print(f"❌ Dépendances manquantes : {', '.join(missing)}")
        print(f"   Installe avec : pip install {' '.join(missing)}")
        sys.exit(1)

check_deps()

from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy import AudioFileClip

# ── Configuration ────────────────────────────────────────────────────────────
W, H = 1920, 1080          # Résolution finale
FPS = 10                   # Images par seconde
FADE_DURATION = 0.8        # Fondu en/out

COVER_SIZE = 860           # Pochette carrée fixe (px)

TEXT_X = 1000              # X de départ des textes
TRACKING = -95             # Approche (1/1000 em, style After Effects)
Y_ARTIST   = 135
Y_TRACK    = 180
Y_EP       = 225
Y_LABEL    = 315
Y_RELEASED = 360

MAX_TEXT_X    = W - 100    # Limite droite du texte
WRAP_LINE_H   = 45         # Hauteur de ligne pour le retour à la ligne
EP_NUM_X = W - 100         # 100px depuis le bord droit
EP_NUM_Y = 980


BG_COLOR = (13, 13, 13)    # Fond #0D0D0D
TEXT_COLOR = (255, 255, 255)
TEXT_LABEL_COLOR = (255, 255, 255)  # Labels "artist", "track"

# ── Polices ──────────────────────────────────────────────────────────────────
# On essaie d'utiliser des polices système. Fallback sur PIL default si absent.
_FONT_DIR = Path(__file__).parent / "alte_haas_grotesk"
_FONT_REGULAR = _FONT_DIR / "AlteHaasGroteskRegular.ttf"
_FONT_BOLD    = _FONT_DIR / "AlteHaasGroteskBold.ttf"

def load_font(size, bold=False):
    path = _FONT_BOLD if bold else _FONT_REGULAR
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()

# ── Extraction de couleurs ────────────────────────────────────────────────────
# ── Texte avec tracking ───────────────────────────────────────────────────────
def draw_tracked_text(draw, x, y, text, font, fill, tracking=0, anchor="ls"):
    """Dessine du texte avec un tracking (approche) en unités 1/1000 em."""
    font_size = getattr(font, "size", 50)
    tracking_px = tracking / 1000 * font_size
    if anchor in ("rs",):
        total_w = sum(draw.textlength(c, font=font) + tracking_px for c in text)
        x -= total_w
    for char in text:
        draw.text((x, y), char, font=font, fill=fill, anchor="ls" if anchor != "rs" else "ls")
        x += draw.textlength(char, font=font) + tracking_px

def tracked_textlength(draw, text, font, tracking=0):
    """Calcule la largeur d'un texte avec tracking."""
    font_size = getattr(font, "size", 50)
    tracking_px = tracking / 1000 * font_size
    return sum(draw.textlength(c, font=font) + tracking_px for c in text)


def soft_light(base, blend):
    low  = base - (1 - 2*blend) * base * (1 - base)
    high = np.where(base <= 0.25,
                    base + (2*blend-1) * (((16*base-12)*base+4)*base - base),
                    base + (2*blend-1) * (np.sqrt(np.maximum(base, 0)) - base))
    return np.where(blend <= 0.5, low, high)

# ── Génération d'une frame principale ────────────────────────────────────────
def render_frame(
    frame_idx,
    cover_resized, cover_x, cover_y,
    artist, track, ep, ep_type, label, released, episode,
    font_label, font_bold, font_episode,
    fade_in_frames, fade_out_frames, total_frames,
    with_cover=True
):
    """Génère une image PIL pour la frame `frame_idx`."""
    img = Image.new("RGBA", (W, H), (*BG_COLOR, 255))
    draw = ImageDraw.Draw(img, "RGBA")

    # ── Pochette à gauche ─────────────────────────────────────────────────
    if with_cover:
        img.paste(cover_resized, (cover_x, cover_y), cover_resized)

    # ── Textes à droite ───────────────────────────────────────────────────
    draw = ImageDraw.Draw(img, "RGBA")

    wrap_x = TEXT_X

    def draw_line(y, static_text, variable_text):
        """Retourne le nombre de lignes supplémentaires utilisées (0 = pas de retour)."""
        lw = tracked_textlength(draw, static_text, font_label, TRACKING)
        draw_tracked_text(draw, TEXT_X, y, static_text, font_label, TEXT_LABEL_COLOR, TRACKING)
        var_x = TEXT_X + lw
        cur_x, cur_y = var_x, y
        extra_lines = 0
        words = variable_text.split(" ")
        for i, word in enumerate(words):
            chunk = ("" if i == 0 else " ") + word
            cw = tracked_textlength(draw, chunk, font_bold, TRACKING)
            if cur_x + cw > MAX_TEXT_X and cur_x > var_x:
                cur_y += WRAP_LINE_H
                cur_x  = wrap_x
                chunk  = word
                cw     = tracked_textlength(draw, chunk, font_bold, TRACKING)
                extra_lines += 1
            draw_tracked_text(draw, cur_x, cur_y, chunk, font_bold, TEXT_COLOR, TRACKING)
            cur_x += cw
        return extra_lines

    offset = 0
    offset += draw_line(Y_ARTIST   + offset, "artist ",     artist)   * WRAP_LINE_H
    offset += draw_line(Y_TRACK    + offset, "track ",      track)    * WRAP_LINE_H
    offset += draw_line(Y_EP       + offset, ep_type + " ", ep)       * WRAP_LINE_H
    offset += draw_line(Y_LABEL    + offset, "label ",      label)    * WRAP_LINE_H
    offset += draw_line(Y_RELEASED + offset, "released ",   released) * WRAP_LINE_H

    # ── Compteur d'épisode ────────────────────────────────────────────────
    ep_str = f".{episode:04d}"
    draw_tracked_text(draw, EP_NUM_X, EP_NUM_Y, ep_str, font_episode, TEXT_COLOR, TRACKING, anchor="rs")

    # ── Fade in / out ─────────────────────────────────────────────────────
    alpha_mult = 1.0
    if frame_idx < fade_in_frames:
        alpha_mult = frame_idx / fade_in_frames
    elif frame_idx > total_frames - fade_out_frames:
        alpha_mult = (total_frames - frame_idx) / fade_out_frames
    if alpha_mult < 1.0:
        black = Image.new("RGBA", (W, H), (0, 0, 0, int(255 * (1 - alpha_mult))))
        img = Image.alpha_composite(img, black)

    return img.convert("RGB")

# ── Génération du frame intro/outro logo ────────────────────────────────────

# ── Aperçu (frame unique) ─────────────────────────────────────────────────────
def generate_preview(args):
    cover_img = Image.open(args.cover).convert("RGBA")
    cw, ch = cover_img.size
    scale = max(COVER_SIZE / cw, COVER_SIZE / ch)
    tmp = cover_img.resize((int(cw * scale), int(ch * scale)), Image.LANCZOS)
    left = (tmp.width - COVER_SIZE) // 2
    top  = (tmp.height - COVER_SIZE) // 2
    cover_resized = tmp.crop((left, top, left + COVER_SIZE, top + COVER_SIZE))
    font_label   = load_font(50, bold=False)
    font_bold    = load_font(50, bold=True)
    font_episode = load_font(50, bold=True)
    cover_x = 100
    cover_y = (H - COVER_SIZE) // 2
    img = render_frame(
        frame_idx=150,
        cover_resized=cover_resized, cover_x=cover_x, cover_y=cover_y,
        artist=args.artist, track=args.track,
        ep=str(args.episode), ep_type=getattr(args, "ep_type", "ep"), label=args.label, released=args.released,
        episode=args.episode,
        font_label=font_label, font_bold=font_bold, font_episode=font_episode,
        fade_in_frames=0, fade_out_frames=0, total_frames=300,
    )
    # Motif sur l'aperçu
    motif_path = r"C:\Users\adrie\Desktop\mediatq_\mdtq_youtube_motif.mp4"
    try:
        from moviepy import VideoFileClip
        mc = VideoFileClip(motif_path)
        motif_frame = Image.fromarray(mc.get_frame(0)).filter(ImageFilter.GaussianBlur(radius=5))
        mc.close()
        mh, mw = motif_frame.height, motif_frame.width
        y2, x2 = min(186 + mh, H), min(1100 + mw, W)
        ch, cw = y2 - 186, x2 - 1100
        # Cache luma : cover recadrée fill pour remplir les dims du motif
        _c = cover_resized.convert("RGB")
        _scale = max(mw / _c.width, mh / _c.height)
        _tmp = _c.resize((int(_c.width * _scale), int(_c.height * _scale)), Image.LANCZOS)
        _l = (_tmp.width - mw) // 2
        _t = (_tmp.height - mh) // 2
        _cover_m = _tmp.crop((_l, _t, _l + mw, _t + mh)).filter(ImageFilter.GaussianBlur(radius=100))
        luma = np.array(_cover_m, dtype=np.float32)[:ch, :cw] / 255.0  # (h, w, 3)
        base_np = np.array(img).astype(np.float32) / 255.0
        mf_np   = np.array(motif_frame).astype(np.float32)[:ch, :cw] / 255.0
        base_np[186:y2, 1100:x2] = np.clip(base_np[186:y2, 1100:x2] + mf_np * luma, 0, 1)
        img = Image.fromarray((base_np * 255).astype(np.uint8))
    except Exception:
        pass
    # Noise soft light 25%
    noise_path = r"C:\Users\adrie\Desktop\mediatq_\mdtq_youtube_noise.mp4"
    try:
        from moviepy import VideoFileClip as _VFC
        nc = _VFC(noise_path)
        noise_np = nc.get_frame(0).astype(np.float32) / 255.0
        nc.close()
        base_np = np.array(img, dtype=np.float32) / 255.0
        sl = soft_light(base_np, noise_np)
        base_np = base_np * 0.60 + sl * 0.40
        img = Image.fromarray((np.clip(base_np, 0, 1) * 255).astype(np.uint8))
    except Exception:
        pass
    return img

# ── Construction de la vidéo complète ────────────────────────────────────────
def generate_video(args, progress_logger=None):
    print("🎬 mediatq. Video Generator")
    print(f"   Artist  : {args.artist}")
    print(f"   Track   : {args.track}")
    print(f"   Released: {args.released}")
    print(f"   Episode : {args.episode:04d}")
    print(f"   Cover   : {args.cover}")
    print(f"   Audio   : {args.audio}")
    print()

    # ── Chargement de la pochette ─────────────────────────────────────────
    print("📸 Chargement de la pochette...")
    cover_img = Image.open(args.cover).convert("RGBA")
    cw, ch = cover_img.size
    scale = max(COVER_SIZE / cw, COVER_SIZE / ch)
    tmp = cover_img.resize((int(cw * scale), int(ch * scale)), Image.LANCZOS)
    left = (tmp.width - COVER_SIZE) // 2
    top  = (tmp.height - COVER_SIZE) // 2
    cover_resized = tmp.crop((left, top, left + COVER_SIZE, top + COVER_SIZE))
    cover_x = 100
    cover_y = (H - COVER_SIZE) // 2

    # ── Chargement de l'audio ─────────────────────────────────────────────
    print("🎵 Analyse de l'audio...")
    audio_clip = AudioFileClip(args.audio)
    audio_duration = audio_clip.duration
    print(f"   Durée : {audio_duration:.1f}s")

    # ── Calcul des durées ─────────────────────────────────────────────────

    # ── Polices ───────────────────────────────────────────────────────────
    print("🔤 Chargement des polices...")
    font_label = load_font(50, bold=False)
    font_bold = load_font(50, bold=True)
    font_episode = load_font(50, bold=True)

    # ── Rendu fond + texte (sans cover) ──────────────────────────────────
    print("🖼  Rendu de la frame...")
    bg_img = render_frame(
        frame_idx=0,
        cover_resized=cover_resized, cover_x=cover_x, cover_y=cover_y,
        artist=args.artist, track=args.track,
        ep=str(args.episode), ep_type=getattr(args, "ep_type", "ep"),
        label=args.label, released=args.released, episode=args.episode,
        font_label=font_label, font_bold=font_bold, font_episode=font_episode,
        fade_in_frames=0, fade_out_frames=0, total_frames=1,
        with_cover=False,
    )
    bg_np = np.array(bg_img, dtype=np.float32) / 255.0

    # ── Cover en numpy plein cadre ────────────────────────────────────────
    cover_rgb = np.array(cover_resized.convert("RGB"), dtype=np.float32) / 255.0
    cover_full = np.zeros((H, W, 3), dtype=np.float32)
    cover_full[cover_y:cover_y+COVER_SIZE, cover_x:cover_x+COVER_SIZE] = cover_rgb
    cover_mask = np.zeros((H, W, 1), dtype=np.float32)
    cover_mask[cover_y:cover_y+COVER_SIZE, cover_x:cover_x+COVER_SIZE] = 1.0

    # ── Chargement du noise ───────────────────────────────────────────────
    print("🎲 Chargement du noise...")
    from moviepy import VideoClip, VideoFileClip
    noise_path = r"C:\Users\adrie\Desktop\mediatq_\mdtq_youtube_noise.mp4"
    noise_clip  = VideoFileClip(noise_path)
    noise_dur   = noise_clip.duration

    # Pré-chargement noise (60 frames = 6s, ~350 Mo) — évite la lecture disque par frame
    MAX_NOISE_FRAMES = 60
    _noise_n = min(max(1, int(round(noise_dur * FPS))), MAX_NOISE_FRAMES)
    print(f"⚡ Pré-calcul noise ({_noise_n} frames)...")
    noise_ready = np.empty((_noise_n, H, W, 3), dtype=np.uint8)
    for _i in range(_noise_n):
        noise_ready[_i] = noise_clip.get_frame(_i / FPS)

    # ── Chargement du motif ───────────────────────────────────────────────
    print("🎨 Chargement du motif...")
    motif_path = r"C:\Users\adrie\Desktop\mediatq_\mdtq_youtube_motif.mp4"
    motif_clip = VideoFileClip(motif_path)

    MOTIF_X, MOTIF_Y = 1100, 186
    motif_h, motif_w = motif_clip.get_frame(0).shape[:2]
    paste_x2 = min(MOTIF_X + motif_w, W)
    paste_y2 = min(MOTIF_Y + motif_h, H)
    crop_h, crop_w = paste_y2 - MOTIF_Y, paste_x2 - MOTIF_X

    # Cache luma : cover recadrée fill pour remplir exactement les dims du motif
    _c = cover_resized.convert("RGB")
    _scale = max(motif_w / _c.width, motif_h / _c.height)
    _tmp = _c.resize((int(_c.width * _scale), int(_c.height * _scale)), Image.LANCZOS)
    _l = (_tmp.width - motif_w) // 2
    _t = (_tmp.height - motif_h) // 2
    cover_for_motif = _tmp.crop((_l, _t, _l + motif_w, _t + motif_h))
    cover_for_motif = cover_for_motif.filter(ImageFilter.GaussianBlur(radius=100))
    cover_luma = np.array(cover_for_motif, dtype=np.float32)[:crop_h, :crop_w] / 255.0  # (h, w, 3)

    # ── Pré-calcul frames motif au FPS natif (fluidité) ──────────────────
    print("⚡ Pré-calcul frames motif...")
    MOTIF_DELAY  = 2.0           # le motif apparaît 2s après le début de la vidéo
    _motif_fps   = motif_clip.fps
    MAX_MOTIF_FRAMES = 300       # limite mémoire (~300 frames natives)
    _motif_n = min(max(1, int(round(motif_clip.duration * _motif_fps))), MAX_MOTIF_FRAMES)
    motif_ready = np.empty((_motif_n, crop_h, crop_w, 3), dtype=np.float32)
    for _i in range(_motif_n):
        _raw = Image.fromarray(motif_clip.get_frame(_i / _motif_fps)).filter(ImageFilter.GaussianBlur(radius=5))
        motif_ready[_i] = np.clip(
            np.array(_raw, dtype=np.float32)[:crop_h, :crop_w] / 255.0 * cover_luma, 0, 1)

    # ── Constantes pré-calculées pour make_main ───────────────────────────
    inv_cover_mask  = 1.0 - cover_mask          # évite le calcul par frame
    cover_composite = cover_full * cover_mask   # région cover dans le canvas
    _buf = np.empty_like(bg_np)                 # buffer réutilisable

    # ── Chargement des logos ──────────────────────────────────────────────
    print("🎬 Chargement des logos...")
    logo_start_clip = VideoFileClip(r"C:\Users\adrie\Desktop\mediatq_\mdtq_youtube_logo_start.mp4")
    logo_end_clip   = VideoFileClip(r"C:\Users\adrie\Desktop\mediatq_\mdtq_youtube_logo_end.mp4")
    logo_start_dur  = logo_start_clip.duration
    logo_end_dur    = logo_end_clip.duration
    logo_start_last = logo_start_clip.get_frame(logo_start_dur - 1e-4).astype(np.float32) / 255.0

    # ── Timeline ──────────────────────────────────────────────────────────
    t_fi_start  = logo_start_dur
    t_fi_end    = logo_start_dur + FADE_DURATION
    t_fo_start  = audio_duration - logo_end_dur - FADE_DURATION
    t_fo_end    = audio_duration - logo_end_dur

    # ── Rendu fond+noise+cover sans motif ────────────────────────────────
    def make_bg(t_main):
        np.copyto(_buf, bg_np)
        noise_f = noise_ready[int(t_main * FPS) % _noise_n].astype(np.float32) / 255.0
        sl = soft_light(_buf, noise_f)
        comp = _buf * 0.60 + sl * 0.40
        return comp * inv_cover_mask + cover_composite  # float32

    # ── Applique le motif à 100% sur une frame float32 ────────────────────
    MOTIF_FADE_DURATION = 2.0   # durée du fade out du motif (plus long que le contenu)
    _motif_fo_start = t_fo_start
    _motif_fo_end   = t_fo_start + MOTIF_FADE_DURATION

    def apply_motif(frame_f32, t_vid):
        if t_vid < MOTIF_DELAY:
            return
        if t_vid >= _motif_fo_end:
            return
        if t_vid >= _motif_fo_start:
            opacity = 1.0 - (t_vid - _motif_fo_start) / MOTIF_FADE_DURATION
        else:
            opacity = 1.0
        idx = int((t_vid - MOTIF_DELAY) * _motif_fps) % _motif_n
        region = frame_f32[MOTIF_Y:paste_y2, MOTIF_X:paste_x2]
        np.add(region, motif_ready[idx] * opacity, out=region)
        np.clip(region, 0, 1, out=region)

    # ── Génération vidéo via VideoClip ────────────────────────────────────
    print("🎞  Génération de la vidéo...")
    def make_frame(t):
        if t <= t_fi_start:
            # Étape 01 : logo_start + motif
            comp = logo_start_clip.get_frame(min(t, logo_start_dur - 1e-4)).astype(np.float32) / 255.0
            apply_motif(comp, t)
            return (np.clip(comp, 0, 1) * 255).astype(np.uint8)

        elif t <= t_fi_end:
            # Étape 02a : fondu logo_start → contenu + motif
            alpha = (t - t_fi_start) / FADE_DURATION
            comp  = np.clip(logo_start_last * (1 - alpha) + make_bg(t - t_fi_start) * alpha, 0, 1)
            apply_motif(comp, t)
            return (comp * 255).astype(np.uint8)

        elif t <= t_fo_start:
            # Étape 02b : contenu plein + motif
            comp = make_bg(t - t_fi_start)
            apply_motif(comp, t)
            return (np.clip(comp, 0, 1) * 255).astype(np.uint8)

        elif t <= t_fo_end:
            # Étape 03a : fondu contenu → logo_end + motif
            alpha  = (t - t_fo_start) / FADE_DURATION
            logo_f = logo_end_clip.get_frame(min(t - t_fo_start, logo_end_dur - 1e-4)).astype(np.float32) / 255.0
            comp   = np.clip(make_bg(t - t_fi_start) * (1 - alpha) + logo_f * alpha, 0, 1)
            apply_motif(comp, t)
            return (comp * 255).astype(np.uint8)

        else:
            # Étape 03b : logo_end + motif
            comp = logo_end_clip.get_frame(min(t - t_fo_start, logo_end_dur - 1e-4)).astype(np.float32) / 255.0
            apply_motif(comp, t)
            return (np.clip(comp, 0, 1) * 255).astype(np.uint8)

    clip = VideoClip(make_frame, duration=audio_duration)
    clip = clip.with_audio(audio_clip)

    # ── Export final ──────────────────────────────────────────────────────
    print(f"💾 Export vers {args.output}...")
    clip.write_videofile(
        args.output,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        threads=os.cpu_count() or 4,
        ffmpeg_params=["-crf", "18", "-preset", "ultrafast"],
        logger=progress_logger,
    )
    print(f"\n✅ Vidéo générée : {args.output}")

# ── Interface graphique ───────────────────────────────────────────────────────
def gui_mode():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    FONT = ("Alte Haas Grotesk", 11)
    BG = "#f4f4f4"
    FG = "#111111"
    ENTRY_BG = "#ffffff"
    ENTRY_BORDER = "#cccccc"
    BTN_BG = "#111111"
    BTN_FG = "#ffffff"
    BTN_ACTIVE = "#333333"

    root = tk.Tk()
    root.title("mediatq. Video Generator")
    root.configure(bg=BG)
    root.resizable(False, False)

    def label(parent, text, col, row, colspan=1):
        tk.Label(parent, text=text, font=FONT, bg=BG, fg=FG).grid(
            row=row, column=col, sticky="w", padx=10, pady=6, columnspan=colspan)

    def entry(parent, var, col, row, width=50, bold=False):
        f = ("Alte Haas Grotesk", 11, "bold") if bold else FONT
        tk.Entry(parent, textvariable=var, font=f, bg=ENTRY_BG, fg=FG,
                 insertbackground=FG, relief="flat", width=width,
                 highlightbackground=ENTRY_BORDER, highlightthickness=1).grid(
            row=row, column=col, padx=10, pady=6, sticky="ew")

    def browse_btn(parent, var, col, row, filetypes):
        def pick():
            path = filedialog.askopenfilename(filetypes=filetypes)
            if path:
                var.set(path)
        tk.Button(parent, text="Parcourir", font=FONT, bg=BTN_BG, fg=BTN_FG,
                  activebackground=BTN_ACTIVE, activeforeground=BTN_FG, relief="flat",
                  command=pick).grid(row=row, column=col, padx=(0, 10), pady=6)


    # ── Titre ─────────────────────────────────────────────────────────────────
    tk.Label(root, text="mediatq.  ■  Video Generator", font=("Alte Haas Grotesk", 16, "bold"),
             bg=BG, fg=FG).grid(row=0, column=0, columnspan=2, pady=(18, 10))

    frame = tk.Frame(root, bg=BG)
    frame.grid(row=1, column=0, padx=20, pady=5, sticky="n")

    # ── Aperçu intégré ────────────────────────────────────────────────────────
    PREV_W, PREV_H = 480, 270
    preview_frame = tk.Frame(root, bg=ENTRY_BORDER, width=PREV_W, height=PREV_H)
    preview_frame.grid(row=1, column=1, padx=(0, 20), pady=5, sticky="n")
    preview_frame.grid_propagate(False)
    preview_label = tk.Label(preview_frame, bg=ENTRY_BORDER)
    preview_label.place(x=0, y=0, width=PREV_W, height=PREV_H)

    import json
    _SESSION_FILE = Path(__file__).parent / "last_session.json"
    def load_session():
        if _SESSION_FILE.exists():
            try:
                return json.loads(_SESSION_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}
    def save_session(data):
        try:
            _SESSION_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    _s = load_session()
    v_cover    = tk.StringVar(value=_s.get("cover", "C:/Users/adrie/Desktop/mediatq_/137. Blurry Apple - Apple.jpeg"))
    v_audio    = tk.StringVar(value=_s.get("audio", ""))
    v_artist   = tk.StringVar(value=_s.get("artist", "Artist Name"))
    v_track    = tk.StringVar(value=_s.get("track", "Track Title"))
    v_label    = tk.StringVar(value=_s.get("label", "Label Name"))
    v_released = tk.StringVar(value=_s.get("released", "2024"))
    v_episode  = tk.StringVar(value=str(_s.get("episode", "124")))
    v_ep_type  = tk.StringVar(value=_s.get("ep_type", "ep"))

    # ── Auto-preview ─────────────────────────────────────────────────────────
    _preview_job = [None]

    def _do_preview():
        cover = v_cover.get().strip()
        if not cover or not os.path.exists(cover):
            return
        try:
            from PIL import ImageTk
            class _A: pass
            a = _A()
            a.cover    = cover
            a.artist   = v_artist.get().strip()
            a.track    = v_track.get().strip()
            a.label    = v_label.get().strip()
            a.ep_type  = v_ep_type.get()
            a.released = v_released.get().strip()
            a.episode  = int(v_episode.get().strip() or "1")
            img = generate_preview(a)
            photo = ImageTk.PhotoImage(img.resize((480, 270), Image.LANCZOS))
            root.after(0, lambda p=photo: _set_preview(p))
        except Exception:
            pass

    def _set_preview(photo):
        preview_label.configure(image=photo)
        preview_label.image = photo

    def _schedule_preview(*_):
        if _preview_job[0]:
            root.after_cancel(_preview_job[0])
        _preview_job[0] = root.after(800, lambda: threading.Thread(target=_do_preview, daemon=True).start())

    for _v in (v_cover, v_artist, v_track, v_label, v_released, v_episode, v_ep_type):
        _v.trace_add("write", _schedule_preview)

    label(frame, "cover", 0, 0)
    entry(frame, v_cover, 1, 0, bold=True)
    browse_btn(frame, v_cover, 2, 0, [("Images", "*.jpg *.jpeg *.png")])

    label(frame, "audio", 0, 1)
    entry(frame, v_audio, 1, 1)
    browse_btn(frame, v_audio, 2, 1, [("Audio", "*.mp3 *.wav *.aiff *.flac")])

    label(frame, "artist", 0, 2)
    entry(frame, v_artist, 1, 2)

    label(frame, "track", 0, 3)
    entry(frame, v_track, 1, 3)

    label(frame, "label", 0, 4)
    entry(frame, v_label, 1, 4)

    label(frame, "released", 0, 5)
    entry(frame, v_released, 1, 5, width=20)

    label(frame, "type", 0, 6)
    ep_frame = tk.Frame(frame, bg=BG)
    ep_frame.grid(row=6, column=1, sticky="w", padx=10, pady=6)
    for val in ("ep", "lp"):
        tk.Radiobutton(ep_frame, text=val, variable=v_ep_type, value=val,
                       font=FONT, bg=BG, fg=FG, selectcolor=BG,
                       activebackground=BG, activeforeground=FG).pack(side="left", padx=8)

    label(frame, "number", 0, 7)
    entry(frame, v_episode, 1, 7, width=10, bold=True)


    # ── Barre de progression ──────────────────────────────────────────────────
    progress_var = tk.DoubleVar(value=0)
    progress_bar = ttk.Progressbar(root, variable=progress_var,
                                   mode='determinate', maximum=100)
    progress_bar.grid(row=2, column=0, columnspan=2, padx=20, pady=(10, 5), sticky="ew")

    # ── Génération ────────────────────────────────────────────────────────────
    btn_frame = tk.Frame(root, bg=BG)
    btn_frame.grid(row=3, column=0, columnspan=2, pady=(0, 20))

    btn_generate = tk.Button(btn_frame, text="  Générer la vidéo  ", font=("Alte Haas Grotesk", 12, "bold"),
                             bg=BTN_BG, fg=BTN_FG, activebackground=BTN_ACTIVE,
                             activeforeground=BTN_FG, relief="flat", pady=8)
    btn_generate.pack(side="left", padx=10)

    def run():
        cover = v_cover.get().strip()
        audio = v_audio.get().strip()
        artist = v_artist.get().strip()
        track = v_track.get().strip()
        lbl = v_label.get().strip()
        ep_type = v_ep_type.get()
        released = v_released.get().strip()
        try:
            episode = int(v_episode.get().strip())
        except ValueError:
            messagebox.showerror("Erreur", "Le numéro d'épisode doit être un nombre.")
            return
        def _sanitize(s):
            return "".join(c if c not in r'\/:*?"<>|' else "_" for c in s)
        output = str(Path(__file__).parent / f"{episode:04d}_{_sanitize(artist)}_{_sanitize(track)}.mp4")

        if not cover or not os.path.exists(cover):
            messagebox.showerror("Erreur", f"Pochette introuvable :\n{cover}")
            return
        if not audio or not os.path.exists(audio):
            messagebox.showerror("Erreur", f"Fichier audio introuvable :\n{audio}")
            return

        class Args:
            pass
        args = Args()
        args.cover = cover
        args.audio = audio
        args.artist = artist
        args.track = track
        args.label = lbl
        args.ep_type = ep_type
        args.released = released
        args.episode = episode
        args.output = output
        save_session({"cover": cover, "audio": audio, "artist": artist,
                      "track": track, "label": lbl, "ep_type": ep_type,
                      "released": released, "episode": episode})
        btn_generate.configure(state="disabled", text="  Génération en cours...  ")

        def task():
            try:
                import proglog
                class TkLogger(proglog.ProgressBarLogger):
                    def bars_callback(self, bar, attr, value, old_value=None):
                        if attr == 'index':
                            total = self.bars[bar].get('total', 1) or 1
                            pct = int(100 * value / total)
                            progress_var.set(pct)
                            root.update_idletasks()
                progress_var.set(0)
                generate_video(args, progress_logger=TkLogger())
                progress_var.set(100)
                messagebox.showinfo("Terminé", f"Vidéo générée :\n{output}")
            except Exception as e:
                messagebox.showerror("Erreur", str(e))
            finally:
                btn_generate.configure(state="normal", text="  Générer la vidéo  ")

        threading.Thread(target=task, daemon=True).start()

    btn_generate.configure(command=run)
    root.mainloop()

# ── Mode interactif ───────────────────────────────────────────────────────────
def interactive_mode():
    print("=" * 50)
    print("  mediatq. Video Generator — Mode interactif")
    print("=" * 50)
    cover = input("Chemin de la pochette (JPG/PNG) : ").strip()
    audio = input("Chemin du fichier audio (MP3/WAV/AIFF) : ").strip()
    artist = input("Artiste : ").strip()
    track = input("Nom du track : ").strip()
    lbl = input("Label : ").strip()
    released = input("Date de sortie : ").strip()
    episode = int(input("Numéro d'épisode : ").strip() or "1")
    output = input("Nom du fichier de sortie [output.mp4] : ").strip() or "output.mp4"

    class Args:
        pass
    args = Args()
    args.cover = cover
    args.audio = audio
    args.artist = artist
    args.track = track
    args.label = lbl
    args.released = released
    args.episode = episode
    args.output = output
    return args

# ── Point d'entrée ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Génère une vidéo YouTube mediatq.")
    parser.add_argument("--cover", help="Chemin de la pochette")
    parser.add_argument("--audio", help="Chemin du fichier audio")
    parser.add_argument("--artist", help="Nom de l'artiste")
    parser.add_argument("--track", help="Nom du track")
    parser.add_argument("--label", help="Label", default="")
    parser.add_argument("--released", help="Date de sortie", default="")
    parser.add_argument("--episode", type=int, help="Numéro d'épisode", default=1)
    parser.add_argument("--output", help="Fichier de sortie", default="output.mp4")

    args = parser.parse_args()

    # Si aucun argument, lance l'interface graphique
    if not args.cover or not args.audio:
        gui_mode()
        sys.exit(0)

    # Vérifications
    if not os.path.exists(args.cover):
        print(f"❌ Pochette introuvable : {args.cover}")
        sys.exit(1)
    if not os.path.exists(args.audio):
        print(f"❌ Audio introuvable : {args.audio}")
        sys.exit(1)

    generate_video(args)
