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
import math
import os
import random
import sys
import tempfile
import threading
from pathlib import Path

# ── Vérification des dépendances ────────────────────────────────────────────
def check_deps():
    missing = []
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        missing.append("pillow")
    try:
        from colorthief import ColorThief
    except ImportError:
        missing.append("colorthief")
    try:
        import numpy as np
    except ImportError:
        missing.append("numpy")
    try:
        import moviepy
    except ImportError:
        missing.append("moviepy")
    if missing:
        print(f"❌ Dépendances manquantes : {', '.join(missing)}")
        print(f"   Installe avec : pip install {' '.join(missing)}")
        sys.exit(1)

check_deps()

from PIL import Image, ImageDraw, ImageFont
from colorthief import ColorThief
import numpy as np
from moviepy import AudioFileClip, AudioClip, ImageSequenceClip, concatenate_audioclips

# ── Configuration ────────────────────────────────────────────────────────────
W, H = 1920, 1080          # Résolution finale
FPS = 10                   # Images par seconde
INTRO_DURATION = 2.5       # Secondes pour l'intro logo
OUTRO_DURATION = 2.5       # Secondes pour l'outro logo
FADE_DURATION = 0.8        # Fondu en/out

COVER_MARGIN = 40          # Marge autour de la pochette (px)
COVER_MAX_W = int(W * 0.48)  # Largeur max pochette
COVER_MAX_H = H - COVER_MARGIN * 2

TEXT_X = int(W * 0.52)     # X de départ des textes (partie droite)
TEXT_Y_START = 180         # Y de départ du premier texte
LINE_HEIGHT = 90           # Hauteur de ligne

SQUARE_ZONE_X = TEXT_X     # Zone des carrés animés
SQUARE_ZONE_W = W - SQUARE_ZONE_X
SQUARE_ZONE_Y_START = int(H * 0.38)

NUM_SQUARES = 8            # Nombre de carrés en vol
EPISODE_LABEL_COLOR = (200, 180, 200)  # Couleur du compteur épisode

BG_COLOR = (0, 0, 0)       # Fond noir
TEXT_COLOR = (255, 255, 255)
TEXT_LABEL_COLOR = (255, 255, 255)  # Labels "artist", "track"

# ── Polices ──────────────────────────────────────────────────────────────────
# On essaie d'utiliser des polices système. Fallback sur PIL default si absent.
def load_font(size, bold=False):
    """Charge une police système. Adapte les chemins à ton OS."""
    candidates_bold = [
        "/System/Library/Fonts/Helvetica.ttc",          # macOS
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
        "C:/Windows/Fonts/arialbd.ttf",                  # Windows
    ]
    candidates_regular = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    candidates = candidates_bold if bold else candidates_regular
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    # Fallback : police PIL intégrée (moins belle mais fonctionnelle)
    return ImageFont.load_default()

# ── Extraction de couleurs ────────────────────────────────────────────────────
def extract_colors(cover_path, n=6):
    """Extrait les N couleurs dominantes de la pochette via ColorThief."""
    ct = ColorThief(cover_path)
    palette = ct.get_palette(color_count=n, quality=1)
    # Filtre les couleurs trop sombres ou trop proches du noir
    filtered = [c for c in palette if sum(c) > 150]
    if not filtered:
        filtered = palette  # garde tout si tout est sombre
    return filtered

# ── Dessin d'un carré arrondi ─────────────────────────────────────────────────
def draw_rounded_rect(draw, x, y, size, radius, color, alpha=255):
    """Dessine un carré aux coins arrondis."""
    r, g, b = color
    fill = (r, g, b, alpha)
    draw.rounded_rectangle([x, y, x+size, y+size], radius=radius, fill=fill)

# ── Calcul des positions des carrés (animation) ───────────────────────────────
class AnimatedSquare:
    """Un carré flottant avec sa trajectoire et animation."""
    def __init__(self, color, seed, zone_x, zone_w, zone_y, zone_h, total_frames):
        rng = random.Random(seed)
        self.color = color
        self.size = rng.randint(80, 160)
        self.radius = int(self.size * 0.18)
        self.start_x = rng.uniform(zone_x, zone_x + zone_w - self.size)
        self.start_y = rng.uniform(zone_y - 50, zone_y + zone_h * 0.3)
        self.vx = rng.uniform(-0.4, 0.4)   # px/frame horizontal drift
        self.vy = rng.uniform(0.15, 0.55)   # px/frame descente
        self.rotation_speed = rng.uniform(-1.5, 1.5)  # degrés/frame
        self.phase = rng.uniform(0, math.pi * 2)
        self.amp = rng.uniform(8, 25)       # amplitude oscillation horizontale
        self.freq = rng.uniform(0.01, 0.025)
        self.alpha_base = rng.randint(200, 255)
        self.total_frames = total_frames
        self.zone_h = zone_h
        self.zone_y = zone_y

    def get_state(self, frame):
        """Retourne (x, y, alpha, size) pour une frame donnée."""
        t = frame
        x = self.start_x + self.vx * t + self.amp * math.sin(self.freq * t + self.phase)
        y = self.start_y + self.vy * t
        # Reboucle quand le carré sort en bas
        range_h = self.zone_h + self.size + 100
        y_offset = (y - self.zone_y) % range_h
        y_final = self.zone_y + y_offset - self.size
        # Fade sur les bords
        fade_zone = 80
        alpha = self.alpha_base
        if y_offset < fade_zone:
            alpha = int(self.alpha_base * y_offset / fade_zone)
        elif y_offset > range_h - fade_zone:
            alpha = int(self.alpha_base * (range_h - y_offset) / fade_zone)
        return int(x), int(y_final), max(0, alpha), self.size

# ── Génération d'une frame principale ────────────────────────────────────────
def render_frame(
    frame_idx,
    cover_resized, cover_x, cover_y,
    artist, track, released, episode,
    squares,
    font_label, font_bold, font_episode,
    fade_in_frames, fade_out_frames, total_frames
):
    """Génère une image PIL pour la frame `frame_idx`."""
    img = Image.new("RGBA", (W, H), (*BG_COLOR, 255))
    draw = ImageDraw.Draw(img, "RGBA")

    # ── Pochette à gauche ─────────────────────────────────────────────────
    img.paste(cover_resized, (cover_x, cover_y))

    # ── Carrés animés (partie droite) ─────────────────────────────────────
    sq_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sq_draw = ImageDraw.Draw(sq_layer, "RGBA")
    for sq in squares:
        x, y, alpha, size = sq.get_state(frame_idx)
        # Garde dans les limites horizontales
        x = max(SQUARE_ZONE_X, min(x, W - size))
        draw_rounded_rect(sq_draw, x, y, size, sq.radius, sq.color, alpha)
    img = Image.alpha_composite(img, sq_layer)

    # ── Textes à droite ───────────────────────────────────────────────────
    draw = ImageDraw.Draw(img, "RGBA")
    # artist
    draw.text((TEXT_X, TEXT_Y_START), "artist ", font=font_label, fill=TEXT_LABEL_COLOR)
    lw = draw.textlength("artist ", font=font_label)
    draw.text((TEXT_X + lw, TEXT_Y_START), artist, font=font_bold, fill=TEXT_COLOR)
    # track
    ty = TEXT_Y_START + LINE_HEIGHT
    draw.text((TEXT_X, ty), "track ", font=font_label, fill=TEXT_LABEL_COLOR)
    lw2 = draw.textlength("track ", font=font_label)
    draw.text((TEXT_X + lw2, ty), track, font=font_bold, fill=TEXT_COLOR)
    # released
    ty2 = ty + LINE_HEIGHT + 20
    draw.text((TEXT_X, ty2), "released ", font=font_label, fill=TEXT_LABEL_COLOR)
    lw3 = draw.textlength("released ", font=font_label)
    draw.text((TEXT_X + lw3, ty2), released, font=font_bold, fill=TEXT_COLOR)

    # ── Compteur d'épisode ────────────────────────────────────────────────
    ep_str = f".{episode:04d}"
    ep_w = draw.textlength(ep_str, font=font_episode)
    draw.text((W - ep_w - 30, H - 80), ep_str, font=font_episode, fill=EPISODE_LABEL_COLOR)

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
def render_logo_frame(frame_idx, total_frames, fade_in=True):
    """Frame noire avec le logo mediatq. centré."""
    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)
    font_logo = load_font(96, bold=True)
    logo_text = "mediatq. ■"
    # Centrage
    bbox = draw.textbbox((0, 0), logo_text, font=font_logo)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    lx = (W - tw) // 2
    ly = (H - th) // 2
    # Alpha fade
    if fade_in:
        progress = frame_idx / max(total_frames - 1, 1)
    else:
        progress = 1.0 - frame_idx / max(total_frames - 1, 1)
    alpha = int(255 * min(progress * 1.5, 1.0))
    # Dessin du texte blanc avec alpha simulé sur fond noir
    r = int(255 * alpha / 255)
    draw.text((lx, ly), logo_text, font=font_logo, fill=(r, r, r))
    return img

# ── Construction de la vidéo complète ────────────────────────────────────────
def generate_video(args):
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
    scale = min(COVER_MAX_W / cw, COVER_MAX_H / ch)
    cover_resized = cover_img.resize((int(cw * scale), int(ch * scale)), Image.LANCZOS)
    cover_x = COVER_MARGIN
    cover_y = (H - cover_resized.height) // 2

    # ── Extraction des couleurs ───────────────────────────────────────────
    print("🎨 Extraction des couleurs dominantes...")
    colors = extract_colors(args.cover, n=6)
    print(f"   Couleurs extraites : {colors}")

    # ── Chargement de l'audio ─────────────────────────────────────────────
    print("🎵 Analyse de l'audio...")
    audio_clip = AudioFileClip(args.audio)
    audio_duration = audio_clip.duration
    print(f"   Durée : {audio_duration:.1f}s")

    # ── Calcul des durées ─────────────────────────────────────────────────
    main_duration = audio_duration
    total_main_frames = int(main_duration * FPS)
    intro_frames = int(INTRO_DURATION * FPS)
    outro_frames = int(OUTRO_DURATION * FPS)
    fade_frames = int(FADE_DURATION * FPS)

    # ── Polices ───────────────────────────────────────────────────────────
    print("🔤 Chargement des polices...")
    font_label = load_font(52, bold=False)
    font_bold = load_font(52, bold=True)
    font_episode = load_font(36, bold=False)

    # ── Création des carrés animés ─────────────────────────────────────────
    sq_zone_y = int(H * 0.35)
    sq_zone_h = H - sq_zone_y
    squares = []
    for i in range(NUM_SQUARES):
        color = colors[i % len(colors)]
        sq = AnimatedSquare(
            color=color,
            seed=i * 137 + 42,
            zone_x=SQUARE_ZONE_X,
            zone_w=SQUARE_ZONE_W,
            zone_y=sq_zone_y,
            zone_h=sq_zone_h,
            total_frames=total_main_frames,
        )
        squares.append(sq)

    # ── Dossier temporaire pour les frames ────────────────────────────────
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # ── Frames intro ──────────────────────────────────────────────────
        print(f"🎞  Rendu intro ({intro_frames} frames)...")
        intro_paths = []
        for i in range(intro_frames):
            frame = render_logo_frame(i, intro_frames, fade_in=True)
            p = tmpdir / f"intro_{i:05d}.png"
            frame.save(p)
            intro_paths.append(str(p))

        # ── Frames principales ────────────────────────────────────────────
        print(f"🎞  Rendu vidéo principale ({total_main_frames} frames)...")
        main_paths = []
        for i in range(total_main_frames):
            if i % (FPS * 5) == 0:
                secs = i // FPS
                print(f"   {secs}s / {int(main_duration)}s...", end="\r")
            frame = render_frame(
                frame_idx=i,
                cover_resized=cover_resized,
                cover_x=cover_x,
                cover_y=cover_y,
                artist=args.artist,
                track=args.track,
                released=args.released,
                episode=args.episode,
                squares=squares,
                font_label=font_label,
                font_bold=font_bold,
                font_episode=font_episode,
                fade_in_frames=fade_frames,
                fade_out_frames=fade_frames,
                total_frames=total_main_frames,
            )
            p = tmpdir / f"main_{i:05d}.png"
            frame.save(p)
            main_paths.append(str(p))
        print()

        # ── Frames outro ──────────────────────────────────────────────────
        print(f"🎞  Rendu outro ({outro_frames} frames)...")
        outro_paths = []
        for i in range(outro_frames):
            frame = render_logo_frame(i, outro_frames, fade_in=False)
            p = tmpdir / f"outro_{i:05d}.png"
            frame.save(p)
            outro_paths.append(str(p))

        # ── Assemblage avec moviepy ───────────────────────────────────────
        print("🔧 Assemblage de la vidéo...")
        all_paths = intro_paths + main_paths + outro_paths
        clip = ImageSequenceClip(all_paths, fps=FPS)

        # Audio : silence pendant intro/outro, musique au milieu
        silence_intro = AudioClip(lambda t: np.array([0, 0]), duration=INTRO_DURATION, fps=44100)
        silence_outro = AudioClip(lambda t: np.array([0, 0]), duration=OUTRO_DURATION, fps=44100)
        full_audio = concatenate_audioclips([silence_intro, audio_clip, silence_outro])
        clip = clip.with_audio(full_audio)

        # ── Export final ──────────────────────────────────────────────────
        output = args.output
        print(f"💾 Export vers {output}...")
        clip.write_videofile(
            output,
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            ffmpeg_params=["-crf", "18", "-preset", "fast"],
            logger=None,
        )
        print(f"\n✅ Vidéo générée : {output}")

# ── Interface graphique ───────────────────────────────────────────────────────
def gui_mode():
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext
    root = tk.Tk()
    root.title("mediatq. Video Generator")
    root.configure(bg="#111111")
    root.resizable(False, False)

    FONT = ("Arial", 11)
    BG = "#111111"
    FG = "#ffffff"
    ENTRY_BG = "#222222"
    BTN_BG = "#333333"
    BTN_ACTIVE = "#444444"
    ACCENT = "#7DDE3A"

    def label(parent, text, col, row, colspan=1):
        tk.Label(parent, text=text, font=FONT, bg=BG, fg=FG).grid(
            row=row, column=col, sticky="w", padx=10, pady=6, columnspan=colspan)

    def entry(parent, var, col, row, width=50):
        tk.Entry(parent, textvariable=var, font=FONT, bg=ENTRY_BG, fg=FG,
                 insertbackground=FG, relief="flat", width=width).grid(
            row=row, column=col, padx=10, pady=6, sticky="ew")

    def browse_btn(parent, var, col, row, filetypes):
        def pick():
            path = filedialog.askopenfilename(filetypes=filetypes)
            if path:
                var.set(path)
        tk.Button(parent, text="Parcourir", font=FONT, bg=BTN_BG, fg=FG,
                  activebackground=BTN_ACTIVE, activeforeground=FG, relief="flat",
                  command=pick).grid(row=row, column=col, padx=(0, 10), pady=6)

    def browse_save_btn(parent, var, col, row):
        def pick():
            path = filedialog.asksaveasfilename(defaultextension=".mp4",
                                                filetypes=[("MP4", "*.mp4")])
            if path:
                var.set(path)
        tk.Button(parent, text="Parcourir", font=FONT, bg=BTN_BG, fg=FG,
                  activebackground=BTN_ACTIVE, activeforeground=FG, relief="flat",
                  command=pick).grid(row=row, column=col, padx=(0, 10), pady=6)

    # ── Titre ─────────────────────────────────────────────────────────────────
    tk.Label(root, text="mediatq.  ■  Video Generator", font=("Arial", 16, "bold"),
             bg=BG, fg=ACCENT).grid(row=0, column=0, columnspan=3, pady=(18, 10))

    frame = tk.Frame(root, bg=BG)
    frame.grid(row=1, column=0, padx=20, pady=5)

    v_cover    = tk.StringVar()
    v_audio    = tk.StringVar()
    v_artist   = tk.StringVar()
    v_track    = tk.StringVar()
    v_released = tk.StringVar()
    v_episode  = tk.StringVar(value="1")
    v_output   = tk.StringVar(value="output.mp4")

    label(frame, "Pochette (JPG/PNG)", 0, 0)
    entry(frame, v_cover, 1, 0)
    browse_btn(frame, v_cover, 2, 0, [("Images", "*.jpg *.jpeg *.png")])

    label(frame, "Audio (MP3/WAV)", 0, 1)
    entry(frame, v_audio, 1, 1)
    browse_btn(frame, v_audio, 2, 1, [("Audio", "*.mp3 *.wav *.aiff *.flac")])

    label(frame, "Artiste", 0, 2)
    entry(frame, v_artist, 1, 2)

    label(frame, "Titre du track", 0, 3)
    entry(frame, v_track, 1, 3)

    label(frame, "Date de sortie", 0, 4)
    entry(frame, v_released, 1, 4, width=20)

    label(frame, "Numéro d'épisode", 0, 5)
    entry(frame, v_episode, 1, 5, width=10)

    label(frame, "Fichier de sortie", 0, 6)
    entry(frame, v_output, 1, 6)
    browse_save_btn(frame, v_output, 2, 6)

    # ── Log ───────────────────────────────────────────────────────────────────
    log = scrolledtext.ScrolledText(root, height=12, font=("Courier", 10),
                                    bg="#1a1a1a", fg="#cccccc", relief="flat",
                                    state="disabled")
    log.grid(row=2, column=0, padx=20, pady=10, sticky="ew")

    def log_write(text):
        log.configure(state="normal")
        log.insert(tk.END, text)
        log.see(tk.END)
        log.configure(state="disabled")
        root.update_idletasks()

    class StdoutRedirect:
        def write(self, text):
            log_write(text)
        def flush(self):
            pass

    # ── Génération ────────────────────────────────────────────────────────────
    btn_generate = tk.Button(root, text="  Générer la vidéo  ", font=("Arial", 12, "bold"),
                             bg=ACCENT, fg="#000000", activebackground="#6bc932",
                             relief="flat", pady=8)
    btn_generate.grid(row=3, column=0, pady=(0, 20))

    def run():
        cover = v_cover.get().strip()
        audio = v_audio.get().strip()
        artist = v_artist.get().strip()
        track = v_track.get().strip()
        released = v_released.get().strip()
        output = v_output.get().strip()

        try:
            episode = int(v_episode.get().strip())
        except ValueError:
            messagebox.showerror("Erreur", "Le numéro d'épisode doit être un nombre.")
            return

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
        args.released = released
        args.episode = episode
        args.output = output

        btn_generate.configure(state="disabled", text="  Génération en cours...  ")
        old_stdout = sys.stdout
        sys.stdout = StdoutRedirect()

        def task():
            try:
                generate_video(args)
                log_write("\n✅ Terminé ! La vidéo est prête.\n")
                messagebox.showinfo("Terminé", f"Vidéo générée :\n{output}")
            except Exception as e:
                log_write(f"\n❌ Erreur : {e}\n")
                messagebox.showerror("Erreur", str(e))
            finally:
                sys.stdout = old_stdout
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
