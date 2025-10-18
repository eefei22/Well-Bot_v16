# script: list_chirp3_hd_voices.py

from google.cloud import texttospeech

def list_chirp3_hd_voices():
    client = texttospeech.TextToSpeechClient()
    voices = client.list_voices().voices  # list of Voice objects
    chirp3 = []
    for v in voices:
        # voice name is in format like “en-US-Chirp3-HD-Charon” etc.
        name = v.name  # e.g. “en-US-Chirp3-HD-Charon”
        if "Chirp3-HD" in name or "Chirp3" in name:
            # optionally check also language or channels etc
            chirp3.append({
                "name": name,
                "language_codes": v.language_codes,
                "ssml_gender": texttospeech.SsmlVoiceGender(v.ssml_gender).name if hasattr(v, "ssml_gender") else None,
                "natural_sample_rate_hertz": v.natural_sample_rate_hertz
            })
    return chirp3

if __name__ == "__main__":
    voices = list_chirp3_hd_voices()
    print(f"Found {len(voices)} Chirp3-HD voices (or candidates):")
    for v in voices:
        print(f"  • {v['name']}, langs={v['language_codes']}, gender={v['ssml_gender']}, rate={v['natural_sample_rate_hertz']} Hz")
