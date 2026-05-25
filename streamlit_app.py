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
.stApp { background-color: #f4f4f4; color: #111111; }
h1, h2, h3 { color: #111111; }
.stButton > button {
    background-color: #111111;
    color: #ffffff;
    border: none;
    border-radius: 4px;
}
.stButton > button:hover { background-color: #333333; color: #ffffff; }
</style>
""", unsafe_allow_html=True)

st.title("mediatq.  ■  Video Generator")
st.markdown("---")

cover_file = st.file_uploader("cover", type=["jpg", "jpeg", "png"])
audio_file = st.file_uploader("audio", type=["mp3", "wav", "aiff", "flac"])

col1, col2 = st.columns(2)
with col1:
    artist   = st.text_input("artist")
    label    = st.text_input("label")
    released = st.text_input("released")
with col2:
    track   = st.text_input("track")
    ep_type = st.radio("type", ["ep", "lp"], horizontal=True)
    episode = st.number_input("number", min_value=1, value=1, step=1)

st.markdown("---")

col_prev, col_gen = st.columns(2)

if col_prev.button("Aperçu", use_container_width=True):
    if not cover_file:
        st.error("Veuillez uploader une pochette.")
    else:
        from mediatq_generator import generate_preview
        with tempfile.TemporaryDirectory() as tmpdir:
            cover_path = os.path.join(tmpdir, "cover.jpg")
            with open(cover_path, "wb") as f:
                f.write(cover_file.getbuffer())
            class Args: pass
            args = Args()
            args.cover    = cover_path
            args.artist   = artist
            args.track    = track
            args.label    = label
            args.released = released
            args.ep_type  = ep_type
            args.episode  = int(episode)
            with st.spinner("Génération de l'aperçu..."):
                try:
                    img = generate_preview(args)
                    st.image(img, caption="Aperçu (frame fixe)", use_container_width=True)
                except Exception as e:
                    st.error(f"Erreur : {e}")

if col_gen.button("Générer la vidéo", use_container_width=True):
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
            audio_path  = os.path.join(tmpdir, "audio" + Path(audio_file.name).suffix)
            output_path = os.path.join(tmpdir, "output.mp4")

            with open(cover_path, "wb") as f:
                f.write(cover_file.getbuffer())
            with open(audio_path, "wb") as f:
                f.write(audio_file.getbuffer())

            class Args: pass
            args = Args()
            args.cover    = cover_path
            args.audio    = audio_path
            args.artist   = artist
            args.track    = track
            args.label    = label
            args.released = released
            args.ep_type  = ep_type
            args.episode  = int(episode)
            args.output   = output_path

            with st.spinner("Génération en cours... (peut prendre plusieurs minutes)"):
                try:
                    generate_video(args)
                    st.success("Vidéo générée !")
                    with open(output_path, "rb") as f:
                        st.download_button(
                            label="Télécharger la vidéo",
                            data=f,
                            file_name=f"{int(episode):04d}_{artist}_{track}.mp4",
                            mime="video/mp4",
                            use_container_width=True,
                        )
                except Exception as e:
                    st.error(f"Erreur lors de la génération : {e}")
