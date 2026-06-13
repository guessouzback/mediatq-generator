mediatq. Video Generator
========================

INSTALLATION
------------

1. Installer Python 3.10 ou plus recent
   → https://www.python.org/downloads/
   Cocher "Add Python to PATH" pendant l'installation.

2. Ouvrir un terminal dans ce dossier
   Windows : clic droit dans le dossier → "Ouvrir dans le terminal"
   Mac     : clic droit → "Nouveau terminal au dossier"

3. Installer les dependances
   pip install -r requirements.txt

4. Lancer l'application
   python mediatq_generator.py


STRUCTURE DU DOSSIER
--------------------

mediatq-generator/
├── mediatq_generator.py       ← script principal
├── requirements.txt           ← dependances Python
├── README.txt                 ← ce fichier
├── alte_haas_grotesk/         ← polices
│   ├── AlteHaasGroteskRegular.ttf
│   └── AlteHaasGroteskBold.ttf
└── assets/                    ← fichiers media
    ├── mdtq_youtube_motif.mp4
    ├── mdtq_youtube_noise.mp4
    ├── mdtq_youtube_logo_start.mp4
    ├── mdtq_youtube_logo_end.mp4
    └── mdtq_youtube_template.jpg


UTILISATION
-----------

1. Remplir les champs : artist, track, label, released, type (ep/lp), number
2. Cliquer "upload cover"  → selectionner la pochette (JPG ou PNG)
3. Cliquer "upload audio"  → selectionner le fichier audio (MP3, WAV, AIFF, FLAC)
4. L'apercu se met a jour automatiquement
5. Cliquer "export video"  → la video est generee dans le meme dossier que le script

Le fichier de sortie est nomme automatiquement :
[numero]_[artiste]_[titre].mp4


PROBLEMES COURANTS
------------------

"pip n'est pas reconnu"
→ Reinstaller Python en cochant "Add Python to PATH"

"Module not found"
→ Relancer : pip install -r requirements.txt

L'apercu ne s'affiche pas
→ Verifier que la pochette est bien selectionnee


CONTACT
-------
mediatq.
