import os
import sys
import tempfile
from pathlib import Path

import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))
from mediatq_generator import generate_video

st.set_page_config(page_title="mediatq. Video Generator", layout="centered")

st.markdown("""
<style>
body { background-color: #111; }
.stApp { background-color: #111111; }
h1 { color: #7DDE3A; }
</style>
""", unsafe_allow_html=True)

st.title("mediatq.  ■  Video Generator")
st.markdown("---")

cover_file = st.file_uploader("Pochette (JPG / PNG)", type=["jpg", "jpeg", "png"])
audio_file = st.file_uploader("Audio (MP3 / WAV)", type=["mp3", "wav", "aiff", "flac"])

col1, col2 = st.columns(2)
with col1:
    artist   = st.text_input("Artiste")
    released = st.text_input("Date de sortie (ex : 2024)")
with col2:
    track   = st.text_input("Titre du track")
    episode = st.number_input("Numéro d'épisode", min_value=1, value=1, step=1)

st.markdown("---")

if st.button("🎬 Générer la vidéo", use_container_width=True):
    if not cover_file:
        st.error("Veuillez uploader une pochette.")
    elif not audio_file:
        st.error("Veuillez uploader un fichier audio.")
    elif not artist:
        st.error("Veuillez entrer le nom de l'artiste.")
    elif not track:
        st.error("Veuillez entrer le titre du track.")
    else:
        with tempfile.TemporaryDirectory() as tmpdir:
            cover_path  = os.path.join(tmpdir, "cover" + Path(cover_file.name).suffix)
            audio_ext   = Path(audio_file.name).suffix
            audio_path  = os.path.join(tmpdir, "audio" + audio_ext)
            output_path = os.path.join(tmpdir, "output.mp4")

            with open(cover_path, "wb") as f:
                f.write(cover_file.getbuffer())
            with open(audio_path, "wb") as f:
                f.write(audio_file.getbuffer())

            class Args:
                pass
            args = Args()
            args.cover    = cover_path
            args.audio    = audio_path
            args.artist   = artist
            args.track    = track
            args.released = released
            args.episode  = int(episode)
            args.output   = output_path

            with st.spinner("Génération en cours... (peut prendre plusieurs minutes)"):
                try:
                    generate_video(args)
                    st.success("✅ Vidéo générée !")
                    with open(output_path, "rb") as f:
                        st.download_button(
                            label="⬇️ Télécharger la vidéo",
                            data=f,
                            file_name=f"{episode:04d}. {artist} - {track}.mp4",
                            mime="video/mp4",
                            use_container_width=True,
                        )
                except Exception as e:
                    st.error(f"Erreur lors de la génération : {e}")
